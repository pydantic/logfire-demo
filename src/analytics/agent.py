from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from pydantic_ai import Agent
from pydantic_ai.models import ModelSettings
from pydantic import BaseModel

SYSTEM_PROMPT = """
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

If you receive a request to write results to Google Sheets, use the write_to_sheets tool with the provided results.
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
    credentials_path: str
    results: Optional[List[CategorizationResult]] = None

# Create the centralized agent
categorization_agent = Agent(
    'openai:gpt-4o',
    deps_type=SlackCategorizationDeps,
    result_type=CategorizationResult,
    model_settings=ModelSettings(temprature=0.1),
    system_prompt=SYSTEM_PROMPT,
) 