#!/usr/bin/env python3
"""
Earnings Trade Analyzer - Main Orchestrator

Analyzes recent post-earnings stocks using a 5-factor scoring system:
  1. Gap Size (25%)
  2. Pre-Earnings Trend (30%)
  3. Volume Trend (20%)
  4. MA200 Position (15%)
  5. MA50 Position (10%)

Scores each stock 0-100 and assigns A/B/C/D grades.

Data source: Yahoo Finance via yfinance (free, no API key required).

3-Phase Pipeline:
  Phase 1:   Fetch earnings calendar + profiles, filter by market cap + US exchange
  Phase 2:   Fetch historical daily prices (250 days) for each candidate
  Phase 3:   Score all 5 factors, composite score, grade, optional entry filter
  Phase 4:   Generate JSON + Markdown reports

Usage:
    python3 analyze_earnings_trades.py --output-dir reports/
    python3 analyze_earnings_trades.py --lookback-days 5 --min-market-cap 1000000000
    python3 analyze_earnings_trades.py --apply-entry-filter --top 30
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

# Add scripts directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from calculators.gap_size_calculator import calculate_gap
from calculators.ma50_calculator import calculate_ma50_position
from calculators.ma200_calculator import calculate_ma200_position
from calculators.pre_earnings_trend_calculator import calculate_pre_earnings_trend
from calculators.volume_trend_calculator import calculate_volume_trend
from finnhub_client import FinnhubClient
from yahoo_finance_client import YahooFinanceClient
from report_generator import generate_json_report, generate_markdown_report
from scorer import calculate_composite_score


def normalize_timing(time_value):
    """Normalize Finnhub hour field to bmo/amc/unknown."""
    if not time_value:
        return "unknown"
    t = time_value.lower().strip()
    if t == "bmo":
        return "bmo"
    elif t == "amc":
        return "amc"
    else:
        return "unknown"  # "dmh" (during market hours) and empty string


def analyze_stock(daily_prices, earnings_date, timing):
    """Score a single stock across all 5 factors.

    Args:
        daily_prices: List of price dicts (most-recent-first)
        earnings_date: YYYY-MM-DD string
        timing: 'bmo', 'amc', or 'unknown'

    Returns:
        dict with component results and composite score
    """
    gap_result = calculate_gap(daily_prices, earnings_date, timing)
    trend_result = calculate_pre_earnings_trend(daily_prices, earnings_date)
    volume_result = calculate_volume_trend(daily_prices, earnings_date)
    ma200_result = calculate_ma200_position(daily_prices)
    ma50_result = calculate_ma50_position(daily_prices)

    composite = calculate_composite_score(
        gap_score=gap_result["score"],
        trend_score=trend_result["score"],
        volume_score=volume_result["score"],
        ma200_score=ma200_result["score"],
        ma50_score=ma50_result["score"],
    )

    return {
        "gap": gap_result,
        "pre_earnings_trend": trend_result,
        "volume_trend": volume_result,
        "ma200_position": ma200_result,
        "ma50_position": ma50_result,
        "composite": composite,
    }


def apply_entry_filter(results):
    """Apply entry quality filter to exclude poor setups.

    Based on 517-trade backtest analysis (entry_filter.py):
      1. Exclude price < $30: Win Rate 40.6% for $10-$30 range (vs 54.5% baseline)
      2. Exclude gap >= 10% AND score >= 85: Win Rate 33.3% (paradox pattern)
    """
    filtered = []
    for r in results:
        price = r.get("current_price", 0)
        gap_pct = abs(r.get("gap_pct", 0))
        score = r.get("composite_score", 0)

        # Rule 1: Low price band exclusion (< $30)
        if price < 30:
            continue

        # Rule 2: High gap + high score paradox exclusion
        if gap_pct >= 10 and score >= 85:
            continue

        filtered.append(r)
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Earnings Trade Analyzer - 5-Factor Post-Earnings Scoring"
    )
    parser.add_argument(
        "--lookback-days", type=int, default=2, help="Days back for earnings (default: 2)"
    )
    parser.add_argument(
        "--min-market-cap",
        type=float,
        default=5_000_000_000,
        help="Minimum market cap in dollars (default: 5000000000)",
    )
    parser.add_argument("--min-gap", type=float, default=0, help="Minimum gap %% (default: 0)")
    parser.add_argument(
        "--min-revenue",
        type=float,
        default=1_000_000_000,
        help="Minimum revenue estimate in dollars (default: 1000000000, 0 = no filter)",
    )
    parser.add_argument(
        "--max-earnings-results",
        type=int,
        default=500,
        help="Cap earnings entries before profile fetching (default: 500, 0 = unlimited)",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=200,
        help="Max candidates to score, sorted by market cap (default: 200, 0 = unlimited)",
    )
    parser.add_argument(
        "--apply-entry-filter",
        action="store_true",
        help="Apply entry quality filter (exclude price < $30, exclude gap>=10%% AND score>=85)",
    )
    parser.add_argument("--top", type=int, default=20, help="Top results to include (default: 20)")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/",
        help="Output directory (default: reports/)",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="Finnhub API key (default: $FINNHUB_API_KEY env var)",
    )

    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        print(
            "ERROR: Finnhub API key required. Set FINNHUB_API_KEY env var or pass --api-key.",
            file=sys.stderr,
        )
        sys.exit(1)

    finnhub = FinnhubClient(api_key)
    yahoo = YahooFinanceClient()

    print("=" * 60, file=sys.stderr)
    print("Earnings Trade Analyzer - 5-Factor Scoring", file=sys.stderr)
    print("Data source: Finnhub (calendar/profiles) + Yahoo Finance (prices)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Phase 1: Fetch earnings calendar and profiles
    print("\n--- Phase 1: Fetch Earnings Calendar ---", file=sys.stderr)

    today = datetime.now()
    from_date = (today - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    print(f"Date range: {from_date} to {to_date}", file=sys.stderr)

    earnings = finnhub.get_earnings_calendar(from_date, to_date)

    if not earnings:
        print("ERROR: No earnings data returned.", file=sys.stderr)
        sys.exit(1)

    print(f"Raw earnings announcements: {len(earnings)}", file=sys.stderr)

    # Cap before expensive profile fetching to avoid rate limits
    if args.max_earnings_results and args.max_earnings_results > 0 and len(earnings) > args.max_earnings_results:
        earnings = earnings[: args.max_earnings_results]
        print(f"Capped to {len(earnings)} earnings entries (use --max-earnings-results 0 for unlimited).", file=sys.stderr)

    # Pre-filter by revenue estimate to reduce profile API calls
    if args.min_revenue and args.min_revenue > 0:
        before = len(earnings)
        earnings = [e for e in earnings if e.get("revenueEstimate", 0) >= args.min_revenue]
        print(f"Revenue filter (>=${args.min_revenue/1e9:.1f}B): {before} → {len(earnings)} symbols", file=sys.stderr)

    print("Fetching company profiles (Yahoo Finance batch)...", file=sys.stderr)
    profiles = yahoo.get_company_profiles_batch(earnings)
    print(f"Profiles retrieved: {len(profiles)}", file=sys.stderr)

    # Filter by market cap and US exchange
    candidates = []
    seen = set()
    for earning in earnings:
        symbol = earning.get("symbol")
        if not symbol or symbol in seen:
            continue

        profile = profiles.get(symbol)
        if not profile:
            continue

        market_cap = profile.get("mktCap", 0)

        if market_cap < args.min_market_cap:
            continue
        if profile.get("country", "") != "US":
            continue

        seen.add(symbol)
        timing = normalize_timing(earning.get("time"))
        candidates.append(
            {
                "symbol": symbol,
                "company_name": profile.get("companyName", symbol),
                "earnings_date": earning.get("date"),
                "earnings_timing": timing,
                "market_cap": market_cap,
                "sector": profile.get("sector", "N/A"),
                "industry": profile.get("industry", "N/A"),
                "price": profile.get("price", 0),
            }
        )

    print(f"Candidates after filtering: {len(candidates)}", file=sys.stderr)

    if not candidates:
        print("No candidates found matching criteria.", file=sys.stderr)
        sys.exit(0)

    # Optionally cap candidates (sort by market cap descending)
    if args.max_candidates and args.max_candidates > 0 and len(candidates) > args.max_candidates:
        candidates.sort(key=lambda x: x.get("market_cap", 0), reverse=True)
        candidates = candidates[: args.max_candidates]
        print(f"Capped to {len(candidates)} candidates (by market cap).", file=sys.stderr)

    # Phase 2: Fetch historical prices
    print("\n--- Phase 2: Fetch Historical Prices ---", file=sys.stderr)

    results = []
    for i, candidate in enumerate(candidates):
        symbol = candidate["symbol"]
        print(
            f"  [{i + 1}/{len(candidates)}] Fetching {symbol}...",
            file=sys.stderr,
            end="",
        )

        price_data = yahoo.get_historical_prices(symbol, days=250)
        daily_prices = price_data.get("historical") if price_data else None

        if not daily_prices or len(daily_prices) < 50:
            print(
                f" SKIP (insufficient data: {len(daily_prices) if daily_prices else 0} days)",
                file=sys.stderr,
            )
            continue

        # Phase 3: Score all 5 factors
        analysis = analyze_stock(
            daily_prices,
            candidate["earnings_date"],
            candidate["earnings_timing"],
        )

        composite = analysis["composite"]
        gap_pct = analysis["gap"]["gap_pct"]

        # Apply min gap filter
        if abs(gap_pct) < args.min_gap:
            print(f" SKIP (gap {gap_pct:.1f}% < min {args.min_gap}%)", file=sys.stderr)
            continue

        current_price = daily_prices[0]["close"] if daily_prices else candidate["price"]  # type: ignore[index]

        result = {
            "symbol": symbol,
            "company_name": candidate["company_name"],
            "earnings_date": candidate["earnings_date"],
            "earnings_timing": candidate["earnings_timing"],
            "gap_pct": gap_pct,
            "composite_score": composite["composite_score"],
            "grade": composite["grade"],
            "grade_description": composite["grade_description"],
            "guidance": composite["guidance"],
            "weakest_component": composite["weakest_component"],
            "strongest_component": composite["strongest_component"],
            "component_breakdown": composite["component_breakdown"],
            "current_price": round(current_price, 2),
            "market_cap": candidate["market_cap"],
            "sector": candidate["sector"],
            "industry": candidate["industry"],
            "components": {
                "gap_size": analysis["gap"],
                "pre_earnings_trend": analysis["pre_earnings_trend"],
                "volume_trend": analysis["volume_trend"],
                "ma200_position": analysis["ma200_position"],
                "ma50_position": analysis["ma50_position"],
            },
        }
        results.append(result)
        print(
            f" Grade {composite['grade']} (score: {composite['composite_score']:.1f})",
            file=sys.stderr,
        )

    print(f"\nScored {len(results)} stocks.", file=sys.stderr)

    # Apply entry quality filter if requested
    all_results = results[:]
    if args.apply_entry_filter:
        results = apply_entry_filter(results)
        print(f"After entry filter: {len(results)} stocks.", file=sys.stderr)
        all_results = results[:]

    # Sort by composite score descending
    results.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
    all_results.sort(key=lambda x: x.get("composite_score", 0), reverse=True)

    # Take top N
    top_results = results[: args.top]

    # Phase 4: Generate reports
    print("\n--- Phase 4: Generate Reports ---", file=sys.stderr)

    api_stats = finnhub.get_api_stats()
    metadata = {
        "generated_at": datetime.now().isoformat(),
        "generator": "earnings-trade-analyzer",
        "generator_version": "2.0.0",
        "data_source": "finnhub",
        "lookback_days": args.lookback_days,
        "total_screened": len(all_results),
        "min_market_cap": args.min_market_cap,
        "min_gap": args.min_gap,
        "entry_filter_applied": args.apply_entry_filter,
        "api_stats": api_stats,
    }

    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    json_path = os.path.join(args.output_dir, f"earnings_trade_analyzer_{timestamp}.json")
    md_path = os.path.join(args.output_dir, f"earnings_trade_analyzer_{timestamp}.md")

    generate_json_report(top_results, metadata, json_path, all_results=all_results)
    generate_markdown_report(top_results, metadata, md_path, all_results=all_results)

    print(f"JSON report: {json_path}", file=sys.stderr)
    print(f"Markdown report: {md_path}", file=sys.stderr)
    print(f"API calls used: {api_stats['api_calls_made']}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
