---
name: earnings-trade-analyzer
description: Analyze recent post-earnings stocks using a 5-factor scoring system (Gap Size, Pre-Earnings Trend, Volume Trend, MA200 Position, MA50 Position). Scores each stock 0-100 and assigns A/B/C/D grades. Use when user asks about earnings trade analysis, post-earnings momentum screening, earnings gap scoring, or finding best recent earnings reactions.
---

# Earnings Trade Analyzer - Post-Earnings 5-Factor Scoring

Analyze recent post-earnings stocks using a 5-factor weighted scoring system to identify the strongest earnings reactions for potential momentum trades.

## When to Use

- User asks for post-earnings trade analysis or earnings gap screening
- User wants to find the best recent earnings reactions
- User requests earnings momentum scoring or grading
- User asks about post-earnings accumulation day (PEAD) candidates

## Prerequisites

- `yfinance` Python library: `pip install yfinance` (free, no API key required)
- Internet access to SEC EDGAR (earnings calendar) and Yahoo Finance (price/profile data)

**No API key needed.** Data sources:
- **Earnings calendar:** SEC EDGAR 8-K Item 2.02 filings (companies must file within 4 business days of reporting)
- **Historical prices & company profiles:** Yahoo Finance via yfinance

## Workflow

### Step 1: Run the Earnings Trade Analyzer

Execute the analyzer script:

```bash
# Default: last 2 days of earnings, top 20 results (no API key needed)
# Limits: 500 EDGAR results → 200 scored candidates (by market cap)
python3 skills/earnings-trade-analyzer/scripts/analyze_earnings_trades.py --output-dir reports/

# Custom lookback and market cap filter
python3 skills/earnings-trade-analyzer/scripts/analyze_earnings_trades.py \
  --lookback-days 5 \
  --min-market-cap 1000000000 \
  --top 30 \
  --output-dir reports/

# With entry quality filter and explicit candidate cap
python3 skills/earnings-trade-analyzer/scripts/analyze_earnings_trades.py \
  --apply-entry-filter \
  --max-candidates 100 \
  --output-dir reports/

# Unlimited (for thorough scans — slower, may hit rate limits)
python3 skills/earnings-trade-analyzer/scripts/analyze_earnings_trades.py \
  --max-edgar-results 0 --max-candidates 0 \
  --output-dir reports/
```

### Step 2: Review Results

1. Read the generated JSON and Markdown reports
2. Load `references/scoring_methodology.md` for scoring interpretation context
3. Focus on Grade A and B stocks for actionable setups

### Step 3: Present Analysis

For each top candidate, present:
- Composite score and letter grade (A/B/C/D)
- Earnings gap size and direction
- Pre-earnings 20-day trend
- Volume ratio (20-day vs 60-day average)
- Position relative to 200-day and 50-day moving averages
- Weakest and strongest scoring components

### Step 4: Provide Actionable Guidance

Based on grades:
- **Grade A (85+):** Strong earnings reaction with institutional accumulation - consider entry
- **Grade B (70-84):** Good earnings reaction worth monitoring - wait for pullback or confirmation
- **Grade C (55-69):** Mixed signals - use caution, additional analysis needed
- **Grade D (<55):** Weak setup - avoid or wait for better conditions

## Output

- `earnings_trade_analyzer_YYYY-MM-DD_HHMMSS.json` - Structured results with schema_version "1.0"
- `earnings_trade_analyzer_YYYY-MM-DD_HHMMSS.md` - Human-readable report with tables

## Resources

- `references/scoring_methodology.md` - 5-factor scoring system, grade thresholds, and entry quality filter rules
