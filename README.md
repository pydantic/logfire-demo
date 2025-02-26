# Slack Categorization with Google Sheets Integration

This project uses Pydantic AI to analyze Slack messages, categorize them, and save the results to Google Sheets.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Google Sheets Authentication

To use the Google Sheets integration, you need to set up a service account:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable the Google Sheets API and Google Drive API:
   - Search for "Google Sheets API" and enable it
   - Search for "Google Drive API" and enable it
4. Create a service account:
   - Go to "IAM & Admin" > "Service Accounts"
   - Click "Create Service Account"
   - Enter a name and description for the service account
   - Click "Create and Continue"
   - For the role, select "Project" > "Editor" (or a more restrictive role if needed)
   - Click "Continue" and then "Done"
5. Create and download the service account key:
   - Find your service account in the list
   - Click on the three dots menu (⋮) and select "Manage keys"
   - Click "Add Key" > "Create new key"
   - Choose "JSON" as the key type
   - Click "Create" to download the key file

6. Save the downloaded JSON key file to your project directory as `service_account.json` or set the path in the environment variable:

```bash
export GOOGLE_SHEETS_CREDENTIALS_PATH=/path/to/your/service_account.json
```

7. (Optional) If you want to automatically share the created spreadsheet, set the recipient's email:

```bash
export SHARE_EMAIL=your.email@example.com
```

### 3. Configure Database Connection

Set your PostgreSQL connection string in the environment:

```bash
export PG_DSN=postgres://username:password@localhost:5432/database
```

## Usage

Run the Slack categorization script:

```bash
python -m src.analytics.categorize_slack
```

The script will:
1. Fetch Slack messages from the database
2. Analyze and categorize them using Pydantic AI
3. Create a Google Sheet with the results
4. Save a local JSON backup in the `output` directory

## Google Sheets Output

The script creates a Google Sheet with two worksheets:

1. **Categorization Results**: Contains detailed information about each Slack thread
   - Thread ID
   - Primary Topic
   - Secondary Topic
   - Users Involved
   - Start Time
   - Thread Length
   - Last Active Time
   - Representative Quote
   - Sentiment
   - Resolution Status
   - Reasoning

2. **Topic Summary**: Contains a summary of topics and sentiment
   - Topic
   - Count
   - Positive
   - Neutral
   - Negative

## Pydantic AI Tools

This project demonstrates how to use Pydantic AI tools for Google Sheets integration. The tools are defined in `src/analytics/google_sheets_tool.py` and include:

- `create_google_sheet`: Creates a new Google Sheet
- `write_to_google_sheet`: Writes data to a worksheet
- `share_google_sheet`: Shares the spreadsheet with a user

These tools are registered with the Pydantic AI agent and can be used in your own projects.
