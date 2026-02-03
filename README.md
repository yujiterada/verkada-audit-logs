# Verkada Audit Logs

A Python script for retrieving audit logs and notifications from the Verkada API.

## Overview

This tool fetches audit logs and camera notifications from Verkada's API, focusing on specific events of interest. It runs in 15-minute intervals by default and interval can be changed with CRON_INTERVAL_MINUTES.

## Features

- **Automated Token Management**: Handles API token refresh and expiration
- **Paginated Data Retrieval**: Fetches all pages of audit logs and notifications
- **Error Handling**: Comprehensive retry logic for network issues and rate limiting
- **Filtered Events**: Focuses on specific event types (Archive Action Taken, Video History Streamed, Live Stream Started)
- **Scheduled Execution**: Designed to run every 15 minutes via cron
- **Custom Time Range**: Supports `--start` and `--end` arguments for fetching logs from specific time periods

## Requirements

- Python 3.10+
- `requests` library
- `python-dotenv` library

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Set your Verkada API key as an environment variable:

```bash
export VERKADA_API_KEY="your_api_key_here"
```

Or create a `.env` file at the root:

```
VERKADA_API_KEY=your_api_key_here
```

## Usage

### Command Line

Run with automatic 15-minute interval (default behavior for cron):

```bash
python get_audit_logs.py
```

Run with custom time range using Unix timestamps:

```bash
python get_audit_logs.py --start 1706900000 --end 1706901000
```

#### Command-Line Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `--start` | int | Start time as Unix timestamp (required if `--end` is specified) |
| `--end` | int | End time as Unix timestamp (required if `--start` is specified) |

**Note**: Both `--start` and `--end` must be specified together, or neither. If not provided, the script automatically calculates the most recent 15-minute interval.

### Programmatic Usage

```python
from get_audit_logs import VerkadaAPI

# Initialize client
client = VerkadaAPI()

# Get audit logs for a time range
response = client.getAuditLogsViewV1(start_time=1234567890, end_time=1234567900)
audit_logs = response.json()['audit_logs']

# Get notifications
response = client.getNotificationsViewV1(start_time=1234567890, end_time=1234567900)
notifications = response.json()['notifications']
```

## Configuration Constants

- `DEFAULT_PAGE_SIZE`: 100 items per page
- `DEFAULT_TOKEN_EXPIRATION_TIME`: 25 minutes
- `MAX_RETRIES`: 3 retry attempts
- `CRON_INTERVAL_MINUTES`: 15-minute execution intervals
- `INTERESTED_EVENTS`: List of filtered event types

## Error Handling

The script includes custom exceptions:

- `VerkadaAuthenticationError`: Invalid API key or token
- `VerkadaTokenExpiredError`: Token needs refresh
- `VerkadaConnectionError`: Network connectivity issues

## Token Management

- Tokens are automatically cached to `token.json`
- Automatic refresh when tokens expire (25-minute lifetime)
- Handles authentication errors gracefully

## Output

The script outputs JSON-formatted logs for:
- Audit logs matching interested events
- All camera notifications within the time window

## Scheduling

Designed to run via cron every 15 minutes:

```bash
*/15 * * * * /usr/bin/python3 /path/to/get_audit_logs.py
```