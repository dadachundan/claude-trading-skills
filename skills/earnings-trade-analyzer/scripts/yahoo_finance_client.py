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

import re
import sys
import time
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

    YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
    YAHOO_QUOTE_BATCH_SIZE = 100

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
        """Batch-fetch company profiles using Yahoo Finance /v7/finance/quote.

        Fetches up to 100 symbols per HTTP request — much faster than
        per-symbol Ticker.info calls. Returns the same profile dict shape
        as get_company_profiles_from_quotes so callers are interchangeable.

        Profile dict keys: companyName, mktCap, country, exchangeShortName,
                           sector, industry, price.
        country is set to "US" when exchange is in US_EXCHANGES.
        """
        symbols = [e.get("symbol", "") for e in earnings_entries if e.get("symbol")]
        results: dict[str, dict] = {}
        uncached: list[str] = []

        for s in symbols:
            key = f"profile_{s}"
            if key in self.cache:
                results[s] = self.cache[key]
            else:
                uncached.append(s)

        total_batches = (len(uncached) + self.YAHOO_QUOTE_BATCH_SIZE - 1) // self.YAHOO_QUOTE_BATCH_SIZE
        if uncached:
            print(f"Fetching {len(uncached)} profiles in {total_batches} batch(es)...", file=sys.stderr)

        for i in range(0, len(uncached), self.YAHOO_QUOTE_BATCH_SIZE):
            batch = uncached[i : i + self.YAHOO_QUOTE_BATCH_SIZE]
            batch_profiles = self._fetch_quote_batch(batch)
            for symbol, profile in batch_profiles.items():
                self.cache[f"profile_{symbol}"] = profile
                results[symbol] = profile

        return results

    def _fetch_quote_batch(self, symbols: list[str]) -> dict[str, dict]:
        """Single /v7/finance/quote request for a batch of symbols."""
        try:
            resp = requests.get(
                self.YAHOO_QUOTE_URL,
                params={"symbols": ",".join(symbols)},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"WARNING: Yahoo Finance batch quote failed: {e}", file=sys.stderr)
            return {}

        profiles: dict[str, dict] = {}
        for quote in data.get("quoteResponse", {}).get("result", []):
            symbol = quote.get("symbol", "")
            if not symbol:
                continue
            exchange = quote.get("exchange", "")
            country = "US" if exchange in self.US_EXCHANGES else ""
            profiles[symbol] = {
                "companyName": quote.get("longName") or quote.get("shortName") or symbol,
                "mktCap": quote.get("marketCap") or 0,
                "country": country,
                "exchangeShortName": exchange,
                "sector": quote.get("sector") or "N/A",
                "industry": quote.get("industry") or "N/A",
                "price": quote.get("regularMarketPrice") or 0,
            }
        return profiles

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

        try:
            self._rate_limit()
            ticker = yf.Ticker(symbol)
            # Request extra calendar days to get enough trading days after weekends/holidays
            fetch_days = int(days * 1.5) + 30
            hist = ticker.history(period=f"{fetch_days}d", auto_adjust=True)
            self._api_calls += 1

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
