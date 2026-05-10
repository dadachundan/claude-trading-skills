---
name: earnings-calendar
description: This skill retrieves upcoming earnings announcements for US stocks using the Finnhub API (free tier). Use this when the user requests earnings calendar data, wants to know which companies are reporting earnings in the upcoming week, or needs a weekly earnings review. The skill focuses on mid-cap and above companies (over $2B market cap) that have significant market impact, organizing the data by date and timing in a clean markdown table format. Supports multiple environments (CLI, Desktop, Web) with flexible API key management.
---

# Earnings Calendar

## Overview

This skill retrieves upcoming earnings announcements for US stocks using the Finnhub API. It focuses on companies with significant market capitalization (mid-cap and above, over $2B) that are likely to impact market movements. The skill generates organized markdown reports showing which companies are reporting earnings over the next week, grouped by date and timing (before market open, after market close, or time not announced).

**Key Features**:
- Uses Finnhub API (free tier, no daily cap)
- Filters by market cap (>$2B) to focus on market-moving companies
- Includes EPS and revenue estimates
- Multi-environment support (CLI, Desktop, Web)
- Flexible API key management
- Organized by date, timing, and market cap

## Prerequisites

### Finnhub API Key

This skill requires a Finnhub API key (free tier is sufficient).

**Get Free API Key**:
1. Visit: https://finnhub.io/register
2. Sign up for a free account
3. Copy the API key from the dashboard
4. Free tier: 60 API calls/minute, no daily cap

**API Key Setup by Environment**:

**Claude Code (CLI)**:
```bash
export FINNHUB_API_KEY="your-api-key-here"
```

**Claude Desktop**:
Set the environment variable in your system or shell profile.

**Claude Web**:
API key will be requested during skill execution (stored only for current session).

## Core Workflow

### Step 1: Get Current Date and Calculate Target Week

**CRITICAL**: Always start by obtaining the accurate current date.

Retrieve the current date and time:
- Use system date/time to get today's date
- Note: "Today's date" is provided in the environment (<env> tag)
- Calculate the target week: Next 7 days from current date

**Date Range Calculation**:
```
Current Date: [e.g., November 2, 2025]
Target Week Start: [Current Date + 1 day, e.g., November 3, 2025]
Target Week End: [Current Date + 7 days, e.g., November 9, 2025]
```

**Format dates in YYYY-MM-DD** for API compatibility.

### Step 2: Load Finnhub API Guide

Before retrieving data, load the API guide:

```
Read: references/finnhub_api_guide.md
```

This guide contains:
- Finnhub API endpoint structure and parameters
- Authentication requirements
- Market cap filtering strategy (profile2 endpoint, values in millions)
- Earnings timing conventions (bmo/amc/dmh → BMO/AMC/TAS)
- Response format and field descriptions
- Rate limits (60 calls/minute free tier)
- Error handling strategies

### Step 3: API Key Detection and Configuration

Detect API key availability based on environment.

#### 3.1 Check Environment Variable (CLI/Desktop)

```bash
if [ ! -z "$FINNHUB_API_KEY" ]; then
  echo "✓ API key found in environment"
fi
```

If set, proceed to Step 4.

#### 3.2 Prompt User for API Key (Desktop/Web)

If not found, use AskUserQuestion tool:

**Question Configuration**:
```
Question: "This skill requires a Finnhub API key to retrieve earnings data. Do you have one?"
Header: "API Key"
Options:
  1. "Yes, I'll provide it now" → Proceed to 3.3
  2. "No, get free key" → Show instructions (3.2.1)
  3. "Skip API, use manual entry" → Jump to Step 8 (fallback mode)
```

**3.2.1 If user chooses "No, get free key"**:

```
To get a free Finnhub API key:

1. Visit: https://finnhub.io/register
2. Create account (email + password)
3. Copy the API key from the dashboard
4. Free tier: 60 calls/minute, no daily limit

Once you have your API key, select "Yes, I'll provide it now" to continue.
```

#### 3.3 Request API Key Input

Prompt:
```
Please paste your Finnhub API key below:

(Your API key will only be stored for this conversation session and forgotten when the session ends.
For regular use, set the FINNHUB_API_KEY environment variable.)
```

### Step 4: Retrieve Earnings Data via Finnhub API

Use the Python script to fetch earnings data.

**Script Location**:
```
scripts/fetch_earnings_finnhub.py
```

**Execution**:

**Option A: With Environment Variable (defaults to next 7 days)**:
```bash
python scripts/fetch_earnings_finnhub.py
```

**Option B: Explicit Date Range**:
```bash
python scripts/fetch_earnings_finnhub.py --from 2025-11-03 --to 2025-11-09
```

**Option C: With Session API Key**:
```bash
python scripts/fetch_earnings_finnhub.py --from 2025-11-03 --to 2025-11-09 --api-key "${API_KEY}"
```

**Script Workflow** (automatic):
1. Validates API key and date parameters
2. Calls Finnhub `/calendar/earnings` API for date range
3. Fetches `/stock/profile2` for each symbol (rate-limited, ~1.1s between calls)
4. Filters companies with market cap >$2B and country == "US"
5. Normalizes timing (bmo/amc/dmh → BMO/AMC/TAS)
6. Sorts by date → timing → market cap (descending)
7. Outputs JSON to stdout

**Note**: Profile fetching takes ~1.1 seconds per symbol to respect Finnhub's 60 calls/minute free-tier limit. For 100 symbols, expect ~2 minutes.

**Expected Output Format** (JSON):
```json
[
  {
    "symbol": "AAPL",
    "companyName": "Apple Inc",
    "date": "2025-11-04",
    "timing": "AMC",
    "marketCap": 2950000000000,
    "marketCapFormatted": "$2.9T",
    "sector": "Technology",
    "industry": "Technology",
    "epsEstimated": 1.55,
    "revenueEstimated": 89500000000,
    "fiscalDateEnding": null,
    "exchange": "NASDAQ/NMS (GLOBAL MARKET)"
  }
]
```

**Save to file** (recommended for use with report generator):
```bash
python scripts/fetch_earnings_finnhub.py --from 2025-11-03 --to 2025-11-09 > earnings_data.json
```

**Error Handling**:

- **401 Unauthorized**: Invalid API key → Verify or re-enter
- **429 Rate Limit**: >60 calls/minute → Wait 1 minute and retry
- **Empty Result**: No earnings in date range → Expand date range or note in report
- **Connection Error**: Network issue → Retry

### Step 5: Process and Organize Data

Once earnings data is retrieved (JSON format):

#### 5.1 Parse JSON Data

```python
import json
earnings_data = json.loads(earnings_json_string)
```

Or if saved to file:
```python
with open('earnings_data.json') as f:
    earnings_data = json.load(f)
```

#### 5.2 Verify Data Structure

Confirm data includes required fields:
- ✓ symbol
- ✓ companyName
- ✓ date
- ✓ timing (BMO/AMC/TAS)
- ✓ marketCap
- ✓ sector

#### 5.3 Group by Date

Group all earnings announcements by date:
- Monday, [Full Date]
- Tuesday, [Full Date]
- Wednesday, [Full Date]
- Thursday, [Full Date]
- Friday, [Full Date]

#### 5.4 Sub-Group by Timing

Within each date, create three sub-sections:
1. **Before Market Open (BMO)**
2. **After Market Close (AMC)**
3. **Time Not Announced (TAS)**

#### 5.5 Within Each Timing Group

Companies are sorted by market cap descending:
- Mega-cap (>$200B) first
- Large-cap ($10B-$200B) second
- Mid-cap ($2B-$10B) third

#### 5.6 Calculate Summary Statistics

Compute:
- **Total Companies**: Count of all companies
- **Mega/Large Cap Count**: Count where marketCap >= $10B
- **Mid Cap Count**: Count where marketCap between $2B and $10B
- **Peak Day**: Day of week with most earnings announcements
- **Sector Distribution**: Count by sector

### Step 6: Generate Markdown Report

Use the report generation script to create a formatted markdown report.

**Script Location**:
```
scripts/generate_report.py
```

**Execution**:

```bash
# Output to stdout
python scripts/generate_report.py earnings_data.json

# Save to file
python scripts/generate_report.py earnings_data.json earnings_calendar_2025-11-02.md
```

**Complete One-Liner**:
```bash
python scripts/fetch_earnings_finnhub.py --from 2025-11-03 --to 2025-11-09 > earnings_data.json && \
python scripts/generate_report.py earnings_data.json earnings_calendar_2025-11-02.md
```

**Report Structure**:

```markdown
# Upcoming Earnings Calendar - Week of [START_DATE] to [END_DATE]

## Executive Summary
- Total Companies Reporting: [N]
- Mega/Large Cap (>$10B): [N]
- Mid Cap ($2B-$10B): [N]
- Peak Day: [DAY] ([N] companies)

## [Day Name], [Full Date]

### Before Market Open (BMO)
| Ticker | Company | Market Cap | Sector | EPS Est. | Revenue Est. |

### After Market Close (AMC)
| Ticker | Company | Market Cap | Sector | EPS Est. | Revenue Est. |

### Time Not Announced (TAS)
| Ticker | Company | Market Cap | Sector | EPS Est. | Revenue Est. |

## Key Observations
...
```

### Step 7: Quality Assurance

**Data Quality Checks**:
1. ✓ All dates fall within the target week
2. ✓ Market cap values are present for all companies
3. ✓ Each company has timing specified (BMO/AMC/TAS)
4. ✓ Companies are sorted by market cap within each section
5. ✓ Summary statistics are accurate

**Format Checks**:
1. ✓ Markdown tables are properly formatted
2. ✓ Market caps use consistent units (B for billions, T for trillions)
3. ✓ No placeholder text remains

### Step 8: Save and Deliver Report

**Filename Convention**:
```
earnings_calendar_[YYYY-MM-DD].md
```

The filename date represents the report generation date.

**Example Summary**:
```
✓ Earnings calendar report generated: earnings_calendar_2025-11-02.md

Summary for week of November 3-9, 2025:
- 45 companies reporting earnings
- 28 large/mega-cap, 17 mid-cap
- Peak day: Thursday (15 companies)
- Notable: Apple (Mon AMC), Microsoft (Tue AMC)
```

## Fallback Mode: Manual Data Entry

If API access is unavailable:

```
Since Finnhub API is not available, you can manually gather earnings data:

1. Visit Yahoo Finance: https://finance.yahoo.com/calendar/earnings
2. Or Seeking Alpha: https://seekingalpha.com/earnings/earnings-calendar
3. Note companies reporting next week

Please provide for each company:
- Ticker symbol
- Company name
- Earnings date
- Timing (BMO/AMC/TAS)
- Market cap (approximate)
- Sector
```

## Troubleshooting

### Problem: API key not working
- Verify key is correct (copy from Finnhub dashboard)
- Check for extra spaces before/after key
- Generate a new key if needed

### Problem: Script returns empty results
- Verify date range is in the future
- Check date format is YYYY-MM-DD
- Try a wider date range (e.g., 14 days)

### Problem: Missing major companies
- Company may not have announced earnings date yet
- Market cap may have dropped below $2B threshold
- Cross-reference with company investor relations website

### Problem: Rate limit hit (429 error)
- The script rate-limits to 1.1s between profile calls
- If still hitting limits, wait 60 seconds and retry
- Free tier: 60 calls/minute

### Problem: Script runs slowly
- Profile fetching takes ~1.1s per symbol (rate limit compliance)
- For 50 companies: ~1 minute; for 150: ~3 minutes
- This is expected behavior for the free tier

### Problem: Script execution error
- Verify Python 3 is installed: `python3 --version`
- Install requests: `pip install requests`
- Run explicitly: `python3 fetch_earnings_finnhub.py --help`

## Security Notes

1. ✓ Store API key as environment variable: `export FINNHUB_API_KEY="your-key"`
2. ✓ Keys provided in chat are session-only (forgotten when session ends)
3. ✗ Never commit API keys to version control
4. ✗ Don't share conversations containing your API key

## Resources

**Finnhub API**:
- Earnings Calendar: https://finnhub.io/docs/api/earnings-calendar
- Stock Profile: https://finnhub.io/docs/api/company-profile2
- Register: https://finnhub.io/register

**Supplementary Sources** (for verification):
- Seeking Alpha: https://seekingalpha.com/earnings/earnings-calendar
- Yahoo Finance: https://finance.yahoo.com/calendar/earnings
- MarketWatch: https://www.marketwatch.com/tools/earnings-calendar

**Skill Resources**:
- Finnhub API Guide: `references/finnhub_api_guide.md`
- Fetcher Script: `scripts/fetch_earnings_finnhub.py`
- Report Script: `scripts/generate_report.py`
- Report Template: `assets/earnings_report_template.md`

---

## Summary

This skill provides a reliable, API-driven approach to generating weekly earnings calendars for US stocks using the Finnhub free-tier API (60 calls/minute, no daily cap). The multi-environment support makes it flexible for CLI, Desktop, and Web usage, with a manual fallback when API access is unavailable.

**Key Workflow**: Date Calculation → API Key Setup → Finnhub Data Retrieval → Profile Enrichment → Report Generation → QA → Delivery

**Output**: Clean, organized markdown report with earnings grouped by date/timing/market cap, including EPS/revenue estimates and summary statistics.
