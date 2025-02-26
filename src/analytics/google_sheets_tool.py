import pathlib
from typing import List, Any
from datetime import datetime

import gspread
from pydantic_ai import RunContext

from src.analytics.agent import categorization_agent, CategorizationResult

@categorization_agent.tool
async def write_to_sheets(ctx: RunContext) -> bool:
    """Write the analysis results to Google Sheets, creating both a main data sheet and a summary sheet."""
    if not ctx.deps.results:
        return False
        
    results = ctx.deps.results
    
    # Prepare data for the main sheet
    headers = [
        "Thread ID", "Primary Topic", "Secondary Topic", "Users Involved",
        "Start Time", "Thread Length", "Last Active Time", "Representative Quote",
        "Sentiment", "Resolution Status", "Reasoning"
    ]
    
    data = [headers]
    for result in results:
        data.append([
            result.thread_id,
            result.primary_topic,
            result.secondary_topic,
            ", ".join(result.users_involved),
            result.start_time.isoformat(),
            result.thread_length,
            result.last_active_time.isoformat(),
            result.representative_quote,
            result.sentiment,
            result.resolution_status,
            result.reasoning
        ])
    
    # Create summary data
    topic_counts = {}
    sentiment_by_topic = {}
    
    for result in results:
        topic_counts[result.primary_topic] = topic_counts.get(result.primary_topic, 0) + 1
        if result.primary_topic not in sentiment_by_topic:
            sentiment_by_topic[result.primary_topic] = {"Positive": 0, "Neutral": 0, "Negative": 0}
        sentiment_by_topic[result.primary_topic][result.sentiment] += 1
    
    summary_headers = ["Topic", "Count", "Positive", "Neutral", "Negative"]
    summary_data = [summary_headers]
    
    for topic, count in topic_counts.items():
        sentiments = sentiment_by_topic[topic]
        summary_data.append([
            topic,
            count,
            sentiments["Positive"],
            sentiments["Neutral"],
            sentiments["Negative"]
        ])
    
    # Write both sheets
    ROOT_DIR = pathlib.Path(__file__).parent.parent.parent
    gc = gspread.service_account(filename=ROOT_DIR / 'service_account.json')
    
    try:
        sheet = gc.open("demo_bot_tool")
    except gspread.exceptions.SpreadsheetNotFound:
        sheet = gc.create("demo_bot_tool")
    
    # Write main data
    try:
        worksheet = sheet.worksheet("Slack Categorization")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title="Slack Categorization", rows=1000, cols=20)
    worksheet.clear()
    worksheet.append_rows(data)
    
    # Write summary data
    try:
        summary_worksheet = sheet.worksheet("Topic Summary")
    except gspread.exceptions.WorksheetNotFound:
        summary_worksheet = sheet.add_worksheet(title="Topic Summary", rows=1000, cols=20)
    summary_worksheet.clear()
    summary_worksheet.append_rows(summary_data)
    
    return True

if __name__ == "__main__":
    ROOT_DIR = pathlib.Path(__file__).parent.parent.parent
    gc = gspread.service_account(filename=ROOT_DIR / 'service_account.json')

    sh = gc.open("demo_bot_tool")

    print(sh.sheet1.get('A1'))