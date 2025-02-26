from datetime import datetime
import asyncio
import json
import os
import pathlib
from collections import defaultdict
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models import ModelSettings
from pydantic_ai import RunContext
from pydantic import BaseModel

from dotenv import load_dotenv

# Import the get_sample_slack_messages function from our sample_slack_messages module
from src.analytics.sample_slack_messages import get_sample_slack_messages
from src.analytics.google_sheets_tool import write_to_sheets
from src.analytics.agent import categorization_agent, SlackCategorizationDeps

load_dotenv()

SYSTEM_PROMPT = f"""
TASK: Analyze the slack thread from AI platform's public community and classify it into meaningful topic categories.
CONTEXT: Users in this Slack community are posting to:
- Get technical help from the developer team
- Express confusion or challenges with the platform
- Share positive feedback about features they appreciate
- Discuss use cases and implementation questions
DATA PROCESSING INSTRUCTIONS:
1. For each Slack thread, extract and record:
   - User IDs/names of all participants
   - Thread start timestamp
   - Thread length (number of messages)
   - Last activity timestamp
   - A representative quote that best captures the user's central question/concern/feedback
2. Assign each thread to the most appropriate topic category, creating new categories as needed.
3. Review your category list after every 50 threads to:
   - Identify similar or overlapping categories that should be merged
   - Split overly broad categories that contain distinct subtopics
   - Rename categories to better represent the content they contain
TOPIC CLASSIFICATION GUIDELINES:
- Prioritize technical problem areas over general sentiment (e.g., "API Authentication Issues" rather than "User Frustration")
- Create hierarchical categories when appropriate (e.g., "Data Visualization > Custom Dashboards")
- Pay attention to recurring technical terms or platform features mentioned
- Distinguish between implementation questions, bug reports, and feature requests
- Note emerging themes that might indicate product friction points
OUTPUT FORMAT:
Create a structured Google Sheet with the following columns:
1. Thread ID
2. Primary Topic
3. Secondary Topic (if applicable)
4. Users Involved
5. Start Time
6. Thread Length
7. Last Active Time
8. Representative Quote
9. Sentiment (Positive/Neutral/Negative)
10.Resolution Status (if determinable)
11. Reasoning for Categorization
ORGANIZATION STRATEGY:
- Create a separate tab summarizing topic frequency and trends
- Flag high-engagement threads (many users or messages)
- Highlight common co-occurring topics
- Note topics with consistently negative sentiment
- Identify topics with longest time-to-resolution
"""

class CategorizationResult(BaseModel):
    thread_id: str
    primary_topic: str
    secondary_topic: str
    users_involved: list[str]
    start_time: datetime
    thread_length: int
    last_active_time: datetime
    representative_quote: str
    sentiment: str
    resolution_status: str
    reasoning: str

@dataclass
class SlackCategorizationDeps:
    """Dependencies for Slack categorization."""
    credentials_path: str = None
    results: list[CategorizationResult] = None


# use root dir
root_dir = pathlib.Path(__file__).parent.parent.parent
# Get Google Sheets credentials path from environment variable or use default
credentials_path = root_dir / 'service_account.json'

# Check if credentials file exists
if not os.path.exists(credentials_path):
    print(f"Error: Google Sheets credentials file not found at {credentials_path}")
    print("Please follow the setup instructions to create a service account and download the JSON key file.")


async def main():
    # Get sample messages from the database
    print("Fetching sample messages from the database...")
    messages = await get_sample_slack_messages(limit=20)

    # Group messages by thread ID using a simple defaultdict
    threads = defaultdict(list)
    for msg in messages:
        thread_id = msg['parent_event_ts'] or msg['message_id']
        threads[thread_id].append(msg)

    print(f"Found {len(threads)} threads")

    # Process all threads, including single-message ones
    results = []
    for thread_id, thread_messages in threads.items():
        print(f"\nAnalyzing thread: {thread_id} with {len(thread_messages)} messages")

        # Format thread for AI analysis
        thread_text = "\n".join([
            f"Message {i+1} - User {msg['author']} at {msg['timestamp']}:\n{msg['text']}"
            for i, msg in enumerate(thread_messages)
        ])

        # Use the pre-created agent
        result = await categorization_agent.run(
            user_prompt=thread_text,
            deps=SlackCategorizationDeps(
                credentials_path=credentials_path
            )
        )
        results.append(result.data)

        # Print summary
        print(f"Thread ID: {result.data.thread_id}")
        print(f"Topic: {result.data.primary_topic} / {result.data.secondary_topic}")
        print(f"Users: {', '.join(result.data.users_involved)}")
        print(f"Sentiment: {result.data.sentiment}")
        print(f"Quote: \"{result.data.representative_quote}\"")
        print("-" * 50)

    # Save results to Google Sheets and JSON
    if results:
        # Save results locally as JSON for backup
        os.makedirs("output", exist_ok=True)
        with open("output/slack_categorization_results.json", "w") as f:
            json.dump([r.dict() for r in results], f, indent=2, default=str)

        print(f"Results saved locally to output/slack_categorization_results.json")


async def save_to_google():
    # read results from slack_categorization_results.json
    with open("output/slack_categorization_results.json", "r") as f:
        results_data = json.load(f)
    
    # Convert the JSON data back to CategorizationResult objects
    results = [CategorizationResult(**r) for r in results_data]
    
    # Write results to Google Sheets through the agent
    try:
        print("Writing results to Google Sheets...")
        await categorization_agent.run(
            user_prompt="Write these analysis results to Google Sheets",
            deps=SlackCategorizationDeps(
                credentials_path=str(credentials_path),
                results=results
            )
        )
        print("Successfully wrote data to Google Sheets")
    except Exception as e:
        print(f"Error writing to Google Sheets: {e}")



if __name__ == '__main__':
    asyncio.run(save_to_google())