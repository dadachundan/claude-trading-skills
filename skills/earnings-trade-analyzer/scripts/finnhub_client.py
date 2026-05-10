#!/usr/bin/env python3
"""
Finnhub client for Earnings Trade Analyzer.

Data sources (all via Finnhub API, free tier: 60 calls/minute):
  - Earnings calendar: /calendar/earnings  — returns BMO/AMC/DMH timing
  - Company profiles:  /stock/profile2     — market cap (millions), country, industry
  - Historical OHLCV:  /stock/candle       — daily bars, resolution "D"

Rate limiting: 1.1-second gap between calls keeps usage under the free-tier limit.

Interface contract: method signatures and return schemas are identical to
YahooFinanceClient so analyze_earnings_trades.py works with either client.
"""

import sys
import time
from datetime import datetime, timedelta
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)


class FinnhubClient:
    """Finnhub data client for earnings discovery, profiles, and OHLCV."""

    BASE_URL = "https://finnhub.io/api/v1"
    # 60 calls/minute free tier → 1.1s gap stays safely under the limit
    RATE_LIMIT_DELAY = 1.1

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
        """Make a rate-limited GET to a Finnhub endpoint."""
        params = dict(params or {})
        params["token"] = self.api_key
        self._rate_limit()
        resp = self._session.get(f"{self.BASE_URL}{endpoint}", params=params, timeout=30)
        self._api_calls += 1
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Earnings calendar
    # ------------------------------------------------------------------

    def get_earnings_calendar(self, from_date: str, to_date: str) -> list[dict]:
        """Fetch earnings announcements from Finnhub /calendar/earnings.

        Returns list of dicts with keys: symbol, date, time.
        `time` is the raw Finnhub `hour` value: "bmo", "amc", "dmh", or "".
        Deduplicates by symbol (first occurrence wins).
        """
        cache_key = f"earnings_{from_date}_{to_date}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            data = self._get("/calendar/earnings", {"from": from_date, "to": to_date})
        except Exception as e:
            print(f"WARNING: Finnhub earnings calendar fetch failed: {e}", file=sys.stderr)
            return []

        seen: set[str] = set()
        results: list[dict] = []
        for entry in data.get("earningsCalendar", []):
            symbol = entry.get("symbol", "")
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            results.append(
                {
                    "symbol": symbol,
                    "date": entry.get("date", ""),
                    # expose as "time" to match the interface contract;
                    # normalize_timing() in the main script handles these values
                    "time": entry.get("hour", ""),
                }
            )

        self.cache[cache_key] = results
        return results

    # ------------------------------------------------------------------
    # Company profiles
    # ------------------------------------------------------------------

    def get_company_profiles_from_quotes(
        self, earnings_entries: list[dict]
    ) -> dict[str, dict]:
        """Fetch Finnhub stock/profile2 for each symbol in earnings_entries.

        Returns dict mapping symbol → profile with keys:
          companyName, mktCap (dollars), country, exchangeShortName,
          sector, industry, price (0 — not provided by profile2).

        `mktCap` is converted from Finnhub's millions to full dollars.
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
                print(
                    f"  ⚠️  Warning: profile fetch failed for {symbol}: {e}",
                    file=sys.stderr,
                )
                continue

            # Finnhub returns {} for unknown or non-equity symbols
            if not data or not data.get("ticker"):
                continue

            # marketCapitalization is in millions USD
            mkt_cap_millions = data.get("marketCapitalization") or 0
            market_cap = mkt_cap_millions * 1_000_000

            profile: dict = {
                "companyName": data.get("name", symbol),
                "mktCap": market_cap,
                "country": data.get("country", ""),
                "exchangeShortName": data.get("exchange", ""),
                "sector": data.get("finnhubIndustry", "N/A"),
                "industry": data.get("finnhubIndustry", "N/A"),
                # price not returned by profile2; current_price is filled
                # later from the most-recent candle bar in the main script
                "price": 0,
            }

            self.cache[cache_key] = profile
            results[symbol] = profile

            if (i + 1) % 20 == 0:
                print(f"  ✓ {i + 1}/{total} profiles fetched", file=sys.stderr)

        return results

    # ------------------------------------------------------------------
    # Historical OHLCV
    # ------------------------------------------------------------------

    def get_historical_prices(self, symbol: str, days: int = 250) -> Optional[dict]:
        """Fetch daily OHLCV from Finnhub /stock/candle (resolution D).

        Returns {"symbol": ..., "historical": [...]} with most-recent-first
        rows — identical contract to YahooFinanceClient.get_historical_prices().
        Each row: {"date", "open", "high", "low", "close", "volume"}.
        """
        cache_key = f"prices_{symbol}_{days}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Request 2× the trading days + buffer to ensure enough calendar days
        to_ts = int(datetime.now().timestamp())
        from_ts = int((datetime.now() - timedelta(days=days * 2 + 100)).timestamp())

        try:
            data = self._get(
                "/stock/candle",
                {"symbol": symbol, "resolution": "D", "from": from_ts, "to": to_ts},
            )
        except Exception as e:
            print(f"WARNING: Finnhub candle fetch failed for {symbol}: {e}", file=sys.stderr)
            return None

        if data.get("s") != "ok":
            return None

        closes = data.get("c", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        opens = data.get("o", [])
        timestamps = data.get("t", [])
        volumes = data.get("v", [])

        if not closes or len(closes) != len(timestamps):
            return None

        rows = []
        for i in range(len(closes)):
            dt = datetime.fromtimestamp(timestamps[i])
            rows.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "open": round(float(opens[i]), 4),
                    "high": round(float(highs[i]), 4),
                    "low": round(float(lows[i]), 4),
                    "close": round(float(closes[i]), 4),
                    "volume": int(volumes[i]),
                }
            )

        # Finnhub returns oldest-first; reverse to match expected contract
        rows.reverse()
        if days and days > 0:
            rows = rows[:days]

        if not rows:
            return None

        result = {"symbol": symbol, "historical": rows}
        self.cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        self.cache = {}

    def get_api_stats(self) -> dict:
        return {
            "cache_entries": len(self.cache),
            "api_calls_made": self._api_calls,
            "data_source": "finnhub",
        }
