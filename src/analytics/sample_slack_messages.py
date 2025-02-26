import asyncio
import os
from datetime import datetime

import asyncpg
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get database connection string from environment or use default for local development
PG_DSN = os.getenv('PG_DSN', 'postgres://postgres:postgres@localhost:54320/logfire_demo')

async def get_sample_slack_messages(limit: int = 10):
    """Fetch sample slack messages from the database."""
    # Connect to the database
    conn = await asyncpg.connect(PG_DSN)
    try:
        # Query to get sample messages
        # We're selecting only text-based fields to avoid issues with complex vector data
        messages = await conn.fetch(
            """
            SELECT 
                id, 
                channel, 
                author, 
                message_id, 
                text, 
                ts::text as timestamp,
                parent_event_ts
            FROM slack_messages
            ORDER BY ts DESC
            LIMIT $1
            """,
            limit
        )
        
        # Print the results
        print(f"Found {len(messages)} slack messages:")
        print("-" * 80)
        
        for msg in messages:
            print(f"ID: {msg['id']}")
            print(f"Channel: {msg['channel']}")
            print(f"Author: {msg['author']}")
            print(f"Message ID: {msg['message_id']}")
            print(f"Timestamp: {msg['timestamp']}")
            print(f"Parent Event TS: {msg['parent_event_ts'] or 'None'}")
            print(f"Text: {msg['text']}")
            print("-" * 80)
            
        return messages
    finally:
        # Close the connection
        await conn.close()

async def main():
    """Main function to run the script."""
    try:
        await get_sample_slack_messages()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 