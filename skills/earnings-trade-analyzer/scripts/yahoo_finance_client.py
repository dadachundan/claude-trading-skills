#!/usr/bin/env python3
"""
Yahoo Finance + SEC EDGAR client for Earnings Trade Analyzer.

Data sources (all free, no API key required):
  - Earnings calendar: SEC EDGAR EFTS (8-K filings with Item 2.02)
  - Historical OHLCV:  yfinance Ticker.history()
  - Company profiles:  yfinance Ticker.info

EDGAR approach:
  Companies must file Form 8-K Item 2.02 ("Results of Operations") within
  4 business days of reporting earnings. We search EDGAR's full-text search
  API for these filings to discover which stocks reported in a date range.
  Tickers are extracted from the filing's display_names field.
"""

import contextlib
import io
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance", file=sys.stderr)
    sys.exit(1)


class YahooFinanceClient:
    """Data client combining SEC EDGAR (earnings calendar) and yfinance (prices/profiles)."""

    # Yahoo Finance exchange codes for US primary listings
    US_EXCHANGES = {"NMS", "NYQ", "PCX", "NGM", "NCM", "AMEX", "BTS"}

    RATE_LIMIT_DELAY = 0.3  # seconds between requests

    PROFILE_WORKERS = 2  # parallel threads for profile fetching

    # SEC EDGAR EFTS full-text search
    EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
    EDGAR_USER_AGENT = "EarningsTradeAnalyzer/2.0 contact@example.com"
    EDGAR_PAGE_SIZE = 100  # max supported by EFTS

    def __init__(self):
        self.cache: dict = {}
        self._api_calls: int = 0
        self._last_call_time: float = 0
        self._edgar_session = requests.Session()
        self._edgar_session.headers.update({"User-Agent": self.EDGAR_USER_AGENT})

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_call_time = time.time()

    # ------------------------------------------------------------------
    # Earnings calendar via SEC EDGAR 8-K Item 2.02
    # ------------------------------------------------------------------

    def get_earnings_calendar(self, from_date: str, to_date: str) -> list[dict]:
        """Fetch stocks that reported earnings in [from_date, to_date].

        Searches SEC EDGAR for 8-K filings containing Item 2.02
        ("Results of Operations and Financial Condition"), which companies
        are legally required to file within 4 business days of announcing
        earnings. Tickers are extracted from the filing display_names.

        Returns:
            List of dicts with keys: symbol, date, time (always 'unknown'
            since EDGAR doesn't capture BMO/AMC timing).
        """
        cache_key = f"earnings_{from_date}_{to_date}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        all_hits = self._edgar_fetch_all(from_date, to_date)

        seen = set()
        results = []
        for hit in all_hits:
            src = hit.get("_source", {})

            # Only keep 8-K filings that include Item 2.02 (earnings results)
            if "2.02" not in src.get("items", []):
                continue

            file_date = src.get("file_date", "")
            if not file_date:
                continue

            for display_name in src.get("display_names", []):
                ticker = self._extract_ticker(display_name)
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
                results.append(
                    {
                        "symbol": ticker,
                        "date": file_date,
                        "time": "unknown",
                        "_yf_quote": {},
                    }
                )

        self.cache[cache_key] = results
        return results

    def _edgar_fetch_all(self, from_date: str, to_date: str) -> list[dict]:
        """Paginate EDGAR EFTS to retrieve all 8-K hits for the date range."""
        all_hits = []
        offset = 0

        while True:
            params = {
                "q": '"Results of Operations"',
                "dateRange": "custom",
                "startdt": from_date,
                "enddt": to_date,
                "forms": "8-K",
                "from": offset,
            }
            try:
                self._rate_limit()
                resp = self._edgar_session.get(
                    self.EDGAR_EFTS_URL, params=params, timeout=20
                )
                self._api_calls += 1
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(
                    f"WARNING: EDGAR EFTS request failed (offset {offset}): {e}",
                    file=sys.stderr,
                )
                break

            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            all_hits.extend(hits)

            total = data.get("hits", {}).get("total", {}).get("value", 0)
            offset += len(hits)
            if offset >= total or len(hits) < self.EDGAR_PAGE_SIZE:
                break

        return all_hits

    @staticmethod
    def _extract_ticker(display_name: str) -> Optional[str]:
        """Extract ticker from EDGAR display_name like 'COMPANY NAME  (TICK)  (CIK ...)'."""
        m = re.search(r"\(([A-Z]{1,5})\)", display_name)
        return m.group(1) if m else None

    # ------------------------------------------------------------------
    # Company profiles via Yahoo Finance batch quote API
    # ------------------------------------------------------------------

    def get_company_profiles_batch(self, earnings_entries: list[dict]) -> dict[str, dict]:
        """Fetch company profiles using yfinance with parallel threads.

        Phase 1: fast_info (lightweight) for all symbols in parallel →
                 market cap + exchange for filtering. No auth issues.
        Phase 2: full Ticker.info for symbols that pass a broad pre-filter
                 ($1B+ market cap, US exchange) → company name + sector.

        Profile dict keys: companyName, mktCap, country, exchangeShortName,
                           sector, industry, price.
        """
        symbols = [e.get("symbol", "") for e in earnings_entries if e.get("symbol")]
        results: dict[str, dict] = {}
        uncached = [s for s in symbols if f"profile_{s}" not in self.cache]

        for s in symbols:
            if f"profile_{s}" in self.cache:
                results[s] = self.cache[f"profile_{s}"]

        if uncached:
            print(f"Fetching {len(uncached)} profiles (phase 1: fast_info)...", file=sys.stderr)

        # Phase 1: fast_info — market cap + exchange, no auth required
        fast_profiles: dict[str, dict] = {}

        def _fast_one(symbol: str) -> tuple[str, dict | None]:
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    fi = yf.Ticker(symbol).fast_info
                exchange = getattr(fi, "exchange", "") or ""
                return symbol, {
                    "mktCap": getattr(fi, "market_cap", 0) or 0,
                    "country": "US" if exchange in self.US_EXCHANGES else "",
                    "exchangeShortName": exchange,
                    "price": getattr(fi, "last_price", 0) or 0,
                }
            except Exception as e:
                print(f"  WARNING: fast_info failed for {symbol}: {e}", file=sys.stderr)
                return symbol, None

        with ThreadPoolExecutor(max_workers=self.PROFILE_WORKERS) as ex:
            for symbol, data in ex.map(_fast_one, uncached):
                if data:
                    fast_profiles[symbol] = data

        print(f"  Phase 1 complete: {len(fast_profiles)}/{len(uncached)} symbols returned data", file=sys.stderr)

        us_count = sum(1 for p in fast_profiles.values() if p["country"] == "US")
        large_cap_count = sum(1 for p in fast_profiles.values() if p["country"] == "US" and p["mktCap"] >= 1_000_000_000)
        print(f"  US exchange: {us_count}, US $1B+: {large_cap_count}", file=sys.stderr)

        # Phase 2: full info for US candidates above $1B to get name/sector
        enrich_targets = [
            s for s, p in fast_profiles.items()
            if p["country"] == "US" and p["mktCap"] >= 1_000_000_000
        ]

        if enrich_targets:
            print(f"Fetching {len(enrich_targets)} profiles (phase 2: full info)...", file=sys.stderr)

        def _full_one(symbol: str) -> tuple[str, dict | None]:
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    info = yf.Ticker(symbol).info
                if not info:
                    return symbol, None
                return symbol, {
                    "companyName": info.get("longName") or info.get("shortName") or symbol,
                    "sector": info.get("sector") or "N/A",
                    "industry": info.get("industry") or "N/A",
                }
            except Exception:
                return symbol, None

        enriched: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=self.PROFILE_WORKERS) as ex:
            for symbol, data in ex.map(_full_one, enrich_targets):
                if data:
                    enriched[symbol] = data

        # Merge phases into final profiles
        for symbol, fast in fast_profiles.items():
            extra = enriched.get(symbol, {})
            profile = {
                "companyName": extra.get("companyName", symbol),
                "mktCap": fast["mktCap"],
                "country": fast["country"],
                "exchangeShortName": fast["exchangeShortName"],
                "sector": extra.get("sector", "N/A"),
                "industry": extra.get("industry", "N/A"),
                "price": fast["price"],
            }
            self.cache[f"profile_{symbol}"] = profile
            results[symbol] = profile

        return results

    def get_company_profiles_from_quotes(
        self, earnings_entries: list[dict]
    ) -> dict[str, dict]:
        """Fetch company profiles from yfinance for earnings candidates.

        Falls back to Ticker.info for each symbol since EDGAR-sourced
        earnings entries don't carry pre-fetched quote data.
        """
        results = {}

        for entry in earnings_entries:
            symbol = entry.get("symbol", "")
            if not symbol:
                continue

            cache_key = f"profile_{symbol}"
            if cache_key in self.cache:
                results[symbol] = self.cache[cache_key]
                continue

            info = self._fetch_ticker_info(symbol)
            if not info:
                continue

            market_cap = info.get("marketCap") or 0
            exchange = info.get("exchange") or ""
            name = info.get("longName") or info.get("shortName") or symbol
            sector = info.get("sector") or "N/A"
            industry = info.get("industry") or "N/A"
            price = (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or 0
            )

            profile = {
                "companyName": name,
                "mktCap": market_cap,
                "exchangeShortName": exchange,
                "sector": sector,
                "industry": industry,
                "price": price,
            }

            self.cache[cache_key] = profile
            results[symbol] = profile

        return results

    def _fetch_ticker_info(self, symbol: str) -> Optional[dict]:
        """Fetch Ticker.info with rate limiting. Returns None on failure."""
        try:
            self._rate_limit()
            info = yf.Ticker(symbol).info
            self._api_calls += 1
            return info if isinstance(info, dict) and info else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Historical prices via yfinance
    # ------------------------------------------------------------------

    def get_historical_prices(self, symbol: str, days: int = 250) -> Optional[dict]:
        """Fetch historical daily OHLCV (split/dividend adjusted).

        Returns {"symbol": ..., "historical": [...]} with most-recent-first
        ordering, matching the original FMPClient contract so all calculators
        work unchanged.
        """
        cache_key = f"prices_{symbol}_{days}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        for attempt in range(3):
            try:
                self._rate_limit()
                ticker = yf.Ticker(symbol)
                fetch_days = int(days * 1.5) + 30
                with contextlib.redirect_stderr(io.StringIO()):
                    hist = ticker.history(period=f"{fetch_days}d", auto_adjust=True)
                self._api_calls += 1
                break
            except Exception as e:
                if "Too Many Requests" in str(e) or "Rate limited" in str(e):
                    wait = 5 * (2 ** attempt)
                    print(f"  Rate limited, retrying {symbol} in {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"WARNING: Failed to fetch prices for {symbol}: {e}", file=sys.stderr)
                return None
        else:
            print(f"WARNING: Failed to fetch prices for {symbol} after 3 attempts", file=sys.stderr)
            return None

        try:
            if hist.empty:
                return None

            rows = []
            for dt_idx, row in hist.iterrows():
                rows.append(
                    {
                        "date": dt_idx.strftime("%Y-%m-%d"),
                        "open": round(float(row["Open"]), 4),
                        "high": round(float(row["High"]), 4),
                        "low": round(float(row["Low"]), 4),
                        "close": round(float(row["Close"]), 4),
                        "volume": int(row["Volume"]),
                    }
                )

            # yfinance returns oldest-first; reverse to most-recent-first
            rows.reverse()

            if days and days > 0:
                rows = rows[:days]

            if not rows:
                return None

            result = {"symbol": symbol, "historical": rows}
            self.cache[cache_key] = result
            return result

        except Exception as e:
            print(f"WARNING: Failed to fetch prices for {symbol}: {e}", file=sys.stderr)
            return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        self.cache = {}

    def get_api_stats(self) -> dict:
        return {
            "cache_entries": len(self.cache),
            "api_calls_made": self._api_calls,
            "data_source": "sec_edgar_yfinance",
        }
