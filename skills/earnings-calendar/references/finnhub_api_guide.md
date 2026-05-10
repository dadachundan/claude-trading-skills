# Finnhub Earnings Calendar API Guide

This reference describes how to use the Finnhub API to fetch upcoming earnings announcements for US stocks.

## Overview

Finnhub provides a free-tier financial data API with an earnings calendar endpoint returning structured JSON including EPS/revenue estimates, announcement timing, and historical actuals.

**Official documentation**: https://finnhub.io/docs/api/earnings-calendar

## Authentication

All requests require a `token` query parameter:

```
https://finnhub.io/api/v1/calendar/earnings?from=2025-11-03&to=2025-11-09&token=YOUR_KEY
```

**Getting a free API key**:
1. Register at https://finnhub.io/register
2. Copy the API key from the dashboard
3. Free tier: 60 API calls/minute, no daily cap

**Environment variable** (recommended):
```bash
export FINNHUB_API_KEY="your-key-here"
```

## Earnings Calendar Endpoint

```
GET https://finnhub.io/api/v1/calendar/earnings
```

### Parameters

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `from`    | string | Yes      | Start date (YYYY-MM-DD)  |
| `to`      | string | Yes      | End date (YYYY-MM-DD)    |
| `token`   | string | Yes      | API key                  |
| `symbol`  | string | No       | Filter by single ticker  |

### Response

```json
{
  "earningsCalendar": [
    {
      "date": "2025-11-05",
      "epsActual": null,
      "epsEstimate": 1.55,
      "hour": "amc",
      "quarter": 4,
      "revenueActual": null,
      "revenueEstimate": 89500000000,
      "symbol": "AAPL",
      "year": 2025
    }
  ]
}
```

### Field Reference

| Field             | Type    | Description                                      |
|-------------------|---------|--------------------------------------------------|
| `date`            | string  | Earnings announcement date (YYYY-MM-DD)          |
| `symbol`          | string  | Ticker symbol                                    |
| `hour`            | string  | Announcement timing: `bmo`, `amc`, or `dmh`      |
| `epsEstimate`     | float   | Analyst EPS consensus estimate                   |
| `epsActual`       | float   | Actual EPS (null if not yet reported)            |
| `revenueEstimate` | float   | Analyst revenue consensus (in dollars)           |
| `revenueActual`   | float   | Actual revenue (null if not yet reported)        |
| `quarter`         | integer | Fiscal quarter (1–4)                             |
| `year`            | integer | Fiscal year                                      |

### Timing Values (`hour` field)

| Value | Meaning                  | Mapped to |
|-------|--------------------------|-----------|
| `bmo` | Before market open       | BMO       |
| `amc` | After market close       | AMC       |
| `dmh` | During market hours      | TAS       |
| `""`  | Not yet announced        | TAS       |

## Stock Profile Endpoint

Used to enrich earnings data with company name, market cap, and industry.

```
GET https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token=YOUR_KEY
```

### Response

```json
{
  "country": "US",
  "currency": "USD",
  "exchange": "NASDAQ/NMS (GLOBAL MARKET)",
  "finnhubIndustry": "Technology",
  "ipo": "1980-12-12",
  "logo": "https://...",
  "marketCapitalization": 2950000,
  "name": "Apple Inc",
  "phone": "14089961010",
  "shareOutstanding": 15204.1,
  "ticker": "AAPL",
  "weburl": "https://www.apple.com/"
}
```

### Key Fields

| Field                  | Notes                                          |
|------------------------|------------------------------------------------|
| `name`                 | Company display name                           |
| `country`              | Two-letter country code (`US` for US listings) |
| `marketCapitalization` | **In millions USD** — multiply by 1,000,000    |
| `finnhubIndustry`      | Industry/sector label                          |
| `exchange`             | Exchange name string                           |

**Important**: `marketCapitalization` is in **millions**. To convert to dollars: `market_cap_usd = marketCapitalization * 1_000_000`.

## Rate Limits

| Plan  | Calls/minute | Calls/second |
|-------|-------------|--------------|
| Free  | 60          | 30           |

The fetcher script (`fetch_earnings_finnhub.py`) sleeps 1.1 seconds between profile calls to stay within the free-tier limit.

## Error Handling

| HTTP Status | Meaning                    | Action                             |
|-------------|----------------------------|------------------------------------|
| 401         | Invalid or missing token   | Check `FINNHUB_API_KEY` value      |
| 429         | Rate limit exceeded        | Wait 60 seconds and retry          |
| 200 + `{}`  | Unknown symbol (profile2)  | Skip — no profile data available   |

## US Stock Filtering

The script filters using `country == "US"` from the stock profile, which is more reliable than exchange-name matching and correctly excludes Canadian cross-listings and foreign ADRs.

## Market Cap Categories

| Category  | Range         |
|-----------|---------------|
| Mega Cap  | > $200B       |
| Large Cap | $10B – $200B  |
| Mid Cap   | $2B – $10B    |

The script applies a **$2B minimum** (`MIN_MARKET_CAP`) to exclude small-cap noise.
