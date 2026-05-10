#!/usr/bin/env python3
"""
Finnhub API client — earnings calendar and company profiles.

Free-tier endpoints used:
  GET /calendar/earnings  — earnings dates with real BMO/AMC timing
  GET /stock/profile2     — company name, market cap (millions), country

Rate limit: 60 calls/minute (free tier) → 1.1-second gap between requests.
"""

import sys
import time
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)


class FinnhubClient:
    """Finnhub API client for earnings calendar and company profiles."""

    BASE_URL = "https://finnhub.io/api/v1"
    RATE_LIMIT_DELAY = 1.1  # seconds between calls (60 calls/min free tier)

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cache: dict = {}
        self._api_calls: int = 0
        self._last_call_time: float = 0.0
        self._session = requests.Session()

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_call_time = time.time()

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        params["token"] = self.api_key
        self._rate_limit()
        resp = self._session.get(f"{self.BASE_URL}{endpoint}", params=params, timeout=30)
        self._api_calls += 1
        resp.raise_for_status()
        return resp.json()

    def get_earnings_calendar(self, from_date: str, to_date: str) -> list[dict]:
        """Return earnings announcements in [from_date, to_date].

        Each entry: {"symbol", "date", "time"} where "time" is the raw
        Finnhub hour value: "bmo", "amc", "dmh", or "".
        Deduplicates by symbol (first occurrence wins).
        """
        cache_key = f"earnings_{from_date}_{to_date}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            data = self._get("/calendar/earnings", {"from": from_date, "to": to_date})
        except Exception as e:
            print(f"WARNING: Finnhub earnings fetch failed: {e}", file=sys.stderr)
            return []

        seen: set[str] = set()
        results: list[dict] = []
        for entry in data.get("earningsCalendar", []):
            symbol = entry.get("symbol", "")
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            results.append({
                "symbol": symbol,
                "date": entry.get("date", ""),
                "time": entry.get("hour", ""),
                "revenueEstimate": entry.get("revenueEstimate") or 0,
            })

        self.cache[cache_key] = results
        return results

    def get_company_profiles_from_quotes(self, earnings_entries: list[dict]) -> dict[str, dict]:
        """Fetch /stock/profile2 for each symbol in earnings_entries.

        Returns {symbol: profile} where profile has:
          companyName, mktCap (full dollars), country, exchangeShortName,
          sector, industry, price (always 0 — not in profile2).

        marketCapitalization from Finnhub is in millions; mktCap is converted.
        """
        results: dict[str, dict] = {}
        symbols = [e.get("symbol", "") for e in earnings_entries if e.get("symbol")]
        total = len(symbols)
        if total:
            print(f"Fetching {total} Finnhub profiles...", file=sys.stderr)

        for i, symbol in enumerate(symbols):
            cache_key = f"profile_{symbol}"
            if cache_key in self.cache:
                results[symbol] = self.cache[cache_key]
                continue

            try:
                data = self._get("/stock/profile2", {"symbol": symbol})
            except Exception as e:
                print(f"  ⚠️  Warning: profile failed for {symbol}: {e}", file=sys.stderr)
                continue

            if not data or not data.get("ticker"):  # empty {} for unknown symbols
                continue

            market_cap = (data.get("marketCapitalization") or 0) * 1_000_000

            profile: dict = {
                "companyName": data.get("name", symbol),
                "mktCap": market_cap,
                "country": data.get("country", ""),
                "exchangeShortName": data.get("exchange", ""),
                "sector": data.get("finnhubIndustry", "N/A"),
                "industry": data.get("finnhubIndustry", "N/A"),
                "price": 0,
            }

            self.cache[cache_key] = profile
            results[symbol] = profile

            if (i + 1) % 20 == 0:
                print(f"  ✓ {i + 1}/{total} profiles fetched", file=sys.stderr)

        return results

    def get_api_stats(self) -> dict:
        return {
            "cache_entries": len(self.cache),
            "api_calls_made": self._api_calls,
            "data_source": "finnhub",
        }
