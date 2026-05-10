#!/usr/bin/env python3
"""
Finnhub Earnings Calendar Fetcher

Retrieves upcoming earnings announcements from the Finnhub API,
filters by market cap (>$2B) for US stocks, and outputs structured JSON data.

Usage:
    # With environment variable (next 7 days by default)
    export FINNHUB_API_KEY="your-key"
    python fetch_earnings_finnhub.py

    # Explicit date range
    python fetch_earnings_finnhub.py --from 2025-11-03 --to 2025-11-09

    # With API key as argument
    python fetch_earnings_finnhub.py --from 2025-11-03 --to 2025-11-09 --api-key YOUR_KEY

    # Help
    python fetch_earnings_finnhub.py --help
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import requests


class FinnhubEarningsCalendar:
    """Finnhub Earnings Calendar API client."""

    BASE_URL = "https://finnhub.io/api/v1"
    MIN_MARKET_CAP = 2_000_000_000  # $2B
    # 60 calls/minute free tier → 1.1s gap keeps us safely under
    _PROFILE_CALL_INTERVAL = 1.1

    def __init__(self, api_key: str, us_only: bool = True):
        self.api_key = api_key
        self.us_only = us_only

    def fetch_earnings_calendar(self, start_date: str, end_date: str) -> Optional[list[dict]]:
        """Fetch earnings calendar from Finnhub API.

        Returns list of raw earnings dicts, or None on error.
        """
        url = f"{self.BASE_URL}/calendar/earnings"
        params = {"from": start_date, "to": end_date, "token": self.api_key}

        try:
            response = requests.get(url, params=params, timeout=30)

            if response.status_code == 401:
                print("❌ ERROR: Invalid API key", file=sys.stderr)
                print("Get free API key: https://finnhub.io/register", file=sys.stderr)
                return None

            if response.status_code == 429:
                print("❌ ERROR: Rate limit exceeded (60 calls/minute)", file=sys.stderr)
                print("Wait a minute and retry.", file=sys.stderr)
                return None

            response.raise_for_status()
            data = response.json()
            earnings = data.get("earningsCalendar", [])
            print(f"✓ Retrieved {len(earnings)} earnings announcements", file=sys.stderr)
            return earnings

        except requests.exceptions.Timeout:
            print("❌ ERROR: Request timeout. Please try again.", file=sys.stderr)
            return None

        except requests.exceptions.ConnectionError:
            print("❌ ERROR: Connection error. Check your internet connection.", file=sys.stderr)
            return None

        except Exception as e:
            print(f"❌ ERROR: Unexpected error: {str(e)}", file=sys.stderr)
            return None

    def fetch_company_profiles(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch Finnhub stock/profile2 for each symbol with rate limiting.

        Returns dict mapping symbol → profile.
        """
        profiles = {}
        total = len(symbols)
        print(f"✓ Fetching profiles for {total} companies...", file=sys.stderr)

        for i, symbol in enumerate(symbols):
            url = f"{self.BASE_URL}/stock/profile2"
            params = {"symbol": symbol, "token": self.api_key}

            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                profile = response.json()

                # Finnhub returns {} for unknown/non-equity symbols
                if profile and profile.get("ticker"):
                    profiles[symbol] = profile

                if (i + 1) % 20 == 0:
                    print(f"  ✓ Fetched {i + 1}/{total} profiles", file=sys.stderr)

            except Exception as e:
                print(
                    f"  ⚠️  Warning: Failed to fetch profile for {symbol}: {str(e)}",
                    file=sys.stderr,
                )

            # Rate-limit: stay under 60 calls/minute
            if i < total - 1:
                time.sleep(self._PROFILE_CALL_INTERVAL)

        print(f"✓ Retrieved {len(profiles)} company profiles", file=sys.stderr)
        return profiles

    def filter_by_market_cap(self, earnings: list[dict], profiles: dict[str, dict]) -> list[dict]:
        """Filter earnings to US mid-cap+ stocks and enrich with profile data."""
        filtered = []

        for earning in earnings:
            symbol = earning.get("symbol")
            if not symbol:
                continue

            profile = profiles.get(symbol)
            if not profile:
                continue

            # Finnhub marketCapitalization is in millions
            market_cap_millions = profile.get("marketCapitalization") or 0
            market_cap = market_cap_millions * 1_000_000

            if market_cap < self.MIN_MARKET_CAP:
                continue

            if self.us_only and profile.get("country", "") != "US":
                continue

            earning["marketCap"] = market_cap
            earning["companyName"] = profile.get("name", symbol)
            earning["sector"] = profile.get("finnhubIndustry", "N/A")
            earning["industry"] = profile.get("finnhubIndustry", "N/A")
            earning["exchange"] = profile.get("exchange", "N/A")

            filtered.append(earning)

        label = "US " if self.us_only else ""
        print(
            f"✓ Filtered to {len(filtered)} {label}mid-cap+ companies"
            f" (>${self.MIN_MARKET_CAP / 1e9:.0f}B)",
            file=sys.stderr,
        )
        return filtered

    def normalize_timing(self, time_value: Optional[str]) -> str:
        """Map Finnhub hour values to BMO / AMC / TAS.

        Finnhub hour field: "bmo" | "amc" | "dmh" (during market hours) | ""
        """
        if not time_value:
            return "TAS"

        t = time_value.lower().strip()
        if t == "bmo":
            return "BMO"
        if t == "amc":
            return "AMC"
        return "TAS"  # "dmh" and anything unknown → TAS

    def format_market_cap(self, market_cap: float) -> str:
        """Format market cap in human-readable form ($3.0T, $150.0B, $500M)."""
        if market_cap >= 1e12:
            return f"${market_cap / 1e12:.1f}T"
        elif market_cap >= 1e9:
            return f"${market_cap / 1e9:.1f}B"
        elif market_cap >= 1e6:
            return f"${market_cap / 1e6:.0f}M"
        else:
            return f"${market_cap:,.0f}"

    def process_earnings(self, earnings: list[dict]) -> list[dict]:
        """Standardise Finnhub fields into the canonical output schema."""
        processed = []

        for earning in earnings:
            timing = self.normalize_timing(earning.get("hour"))
            market_cap = earning.get("marketCap", 0)

            processed.append(
                {
                    "symbol": earning.get("symbol"),
                    "companyName": earning.get("companyName", earning.get("symbol")),
                    "date": earning.get("date"),
                    "timing": timing,
                    "marketCap": market_cap,
                    "marketCapFormatted": self.format_market_cap(market_cap),
                    "sector": earning.get("sector", "N/A"),
                    "industry": earning.get("industry", "N/A"),
                    "epsEstimated": earning.get("epsEstimate"),
                    "revenueEstimated": earning.get("revenueEstimate"),
                    "fiscalDateEnding": None,  # not provided by Finnhub
                    "exchange": earning.get("exchange", "N/A"),
                }
            )

        return processed

    def sort_earnings(self, earnings: list[dict]) -> list[dict]:
        """Sort by date → timing (BMO first) → market cap descending."""
        timing_order = {"BMO": 1, "AMC": 2, "TAS": 3}

        return sorted(
            earnings,
            key=lambda x: (
                x.get("date", ""),
                timing_order.get(x.get("timing", "TAS"), 3),
                -x.get("marketCap", 0),
            ),
        )


def get_api_key(args_key: Optional[str]) -> Optional[str]:
    """Resolve API key: CLI arg → env var."""
    if args_key:
        print("✓ API key provided via --api-key argument", file=sys.stderr)
        return args_key

    key = os.environ.get("FINNHUB_API_KEY")
    if key:
        print("✓ API key loaded from FINNHUB_API_KEY environment variable", file=sys.stderr)
        return key

    print("❌ ERROR: No API key found", file=sys.stderr)
    print("", file=sys.stderr)
    print("Options:", file=sys.stderr)
    print("  1. Set environment variable: export FINNHUB_API_KEY='your-key'", file=sys.stderr)
    print("  2. Pass as argument: --api-key YOUR_KEY", file=sys.stderr)
    print("  3. Get free key: https://finnhub.io/register", file=sys.stderr)
    return None


def validate_date(date_str: str) -> bool:
    """Return True if date_str is a valid YYYY-MM-DD date."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def build_parser() -> argparse.ArgumentParser:
    today = datetime.now().date()
    default_from = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    default_to = (today + timedelta(days=7)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(
        description="Fetch upcoming earnings from Finnhub (US stocks, >$2B market cap)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  export FINNHUB_API_KEY='your-key'\n"
            "  python fetch_earnings_finnhub.py\n"
            "  python fetch_earnings_finnhub.py --from 2025-11-03 --to 2025-11-09\n"
            "  python fetch_earnings_finnhub.py --api-key YOUR_KEY\n"
        ),
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default=default_from,
        metavar="YYYY-MM-DD",
        help=f"Start date (default: tomorrow, {default_from})",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default=default_to,
        metavar="YYYY-MM-DD",
        help=f"End date (default: 7 days from today, {default_to})",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="Finnhub API key (default: $FINNHUB_API_KEY env var)",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Validate dates
    for label, val in [("--from", args.from_date), ("--to", args.to_date)]:
        if not validate_date(val):
            print(f"❌ ERROR: Invalid {label} date: {val} (expected YYYY-MM-DD)", file=sys.stderr)
            sys.exit(1)

    api_key = get_api_key(args.api_key)
    if not api_key:
        sys.exit(1)

    print("", file=sys.stderr)
    print(f"📅 Fetching earnings calendar: {args.from_date} to {args.to_date}", file=sys.stderr)
    print("", file=sys.stderr)

    client = FinnhubEarningsCalendar(api_key)

    print("Step 1: Fetching earnings calendar...", file=sys.stderr)
    earnings = client.fetch_earnings_calendar(args.from_date, args.to_date)
    if earnings is None:
        sys.exit(1)

    if not earnings:
        print("⚠️  No earnings announcements found for date range", file=sys.stderr)
        print(json.dumps([], indent=2))
        sys.exit(0)

    print("", file=sys.stderr)
    print("Step 2: Fetching company profiles...", file=sys.stderr)
    symbols = list({e.get("symbol") for e in earnings if e.get("symbol")})
    profiles = client.fetch_company_profiles(symbols)

    print("", file=sys.stderr)
    print("Step 3: Filtering by market cap and US listing...", file=sys.stderr)
    filtered = client.filter_by_market_cap(earnings, profiles)

    if not filtered:
        print("⚠️  No US companies with market cap >$2B found", file=sys.stderr)
        print(json.dumps([], indent=2))
        sys.exit(0)

    print("", file=sys.stderr)
    print("Step 4: Processing earnings data...", file=sys.stderr)
    processed = client.process_earnings(filtered)

    print("", file=sys.stderr)
    print("Step 5: Sorting by date, timing, and market cap...", file=sys.stderr)
    sorted_earnings = client.sort_earnings(processed)

    print(f"✓ Final dataset: {len(sorted_earnings)} companies", file=sys.stderr)
    print("", file=sys.stderr)
    print("✓ Complete! Writing JSON output...", file=sys.stderr)
    print(json.dumps(sorted_earnings, indent=2))


if __name__ == "__main__":
    main()
