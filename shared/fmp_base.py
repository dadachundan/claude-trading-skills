#!/usr/bin/env python3
"""
Shared FMP API client for all trading skills.

Single canonical implementation — individual skill fmp_client.py files are
thin shims that add this directory to sys.path and re-export FMPClient and
ApiCallBudgetExceeded from here.

Features:
- Rate limiting (300 ms between requests)
- Automatic retry on 429 errors
- Session-level in-memory cache
- stable → v3 endpoint fallback with circuit breaker
- Optional API call budget (raises ApiCallBudgetExceeded when exceeded)
"""

import os
import sys
import time
from datetime import date, timedelta
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Endpoint fallback helpers: stable (new users) → v3 (legacy users)
# ---------------------------------------------------------------------------


def _stable_quote_url(base, symbols_str, params):
    params["symbol"] = symbols_str
    return base, params


def _v3_quote_url(base, symbols_str, params):
    return f"{base}/{symbols_str}", params


def _stable_hist_url(base, symbols_str, params):
    params["symbol"] = symbols_str
    # stable EOD endpoint ignores `timeseries`; convert to from/to range.
    # Use 2× calendar days to cover N trading days (252/365 ≈ 0.69, so ×2
    # leaves headroom).
    days = params.pop("timeseries", None)
    if days is not None:
        today = date.today()
        params["from"] = (today - timedelta(days=int(days) * 2)).isoformat()
        params["to"] = today.isoformat()
    return base, params


def _v3_hist_url(base, symbols_str, params):
    return f"{base}/{symbols_str}", params


_FMP_ENDPOINTS = {
    "quote": [
        ("https://financialmodelingprep.com/stable/quote", _stable_quote_url),
        ("https://financialmodelingprep.com/api/v3/quote", _v3_quote_url),
    ],
    "historical": [
        ("https://financialmodelingprep.com/stable/historical-price-eod/full", _stable_hist_url),
        ("https://financialmodelingprep.com/api/v3/historical-price-full", _v3_hist_url),
    ],
}


def _normalize_eod_flat_list(data, symbols_str: str, limit: Optional[int] = None):
    """Convert stable/historical-price-eod/full flat list to v3-compatible dict.

    Input  : [{"symbol": "SPY", "date": "...", "open": ..., ...}, ...]
    Output : {"symbol": "SPY", "historical": [{"date": ..., "open": ..., ...}, ...]}

    Returns data unchanged when it is not a list (v3 dict / historicalStockList
    passthrough). Returns None when no row matches the requested symbol.

    If `limit` is set (original `timeseries=N` value), the historical list is
    truncated to preserve the legacy "most-recent N rows" contract. Truncation
    assumes descending date order, which the FMP EOD endpoint provides.

    Empty list [] is handled by the caller's falsy check before reaching here.
    """
    if not isinstance(data, list):
        return data
    if not data:
        return None
    norm_target = symbols_str.replace("-", ".")
    matched_symbol = None
    historical = []
    for row in data:
        if not isinstance(row, dict):
            continue
        # Single-symbol endpoint may omit per-row "symbol"; treat as a match.
        row_sym = row.get("symbol") or symbols_str
        if row_sym.replace("-", ".") != norm_target:
            continue
        matched_symbol = matched_symbol or row_sym
        historical.append({k: v for k, v in row.items() if k != "symbol"})
    if not historical:
        return None
    if limit is not None and limit > 0:
        historical = historical[:limit]
    return {"symbol": matched_symbol or symbols_str, "historical": historical}


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class ApiCallBudgetExceeded(Exception):
    """Raised when the API call budget has been exhausted."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class FMPClient:
    """FMP API client with rate limiting, caching, fallback, and optional budget."""

    BASE_URL = "https://financialmodelingprep.com/api/v3"
    STABLE_URL = "https://financialmodelingprep.com/stable"
    RATE_LIMIT_DELAY = 0.3  # seconds between requests
    _ENDPOINT_FAILURE_THRESHOLD = 3

    def __init__(self, api_key: Optional[str] = None, max_api_calls: Optional[int] = None):
        """
        Args:
            api_key: FMP API key; falls back to FMP_API_KEY env var.
            max_api_calls: Hard cap on API calls per session. None = unlimited.
                           When exceeded, _rate_limited_get raises ApiCallBudgetExceeded.
        """
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FMP API key required. Set FMP_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.session = requests.Session()
        self.session.headers.update({"apikey": self.api_key})
        self.cache: dict = {}
        self.last_call_time: float = 0
        self.rate_limit_reached: bool = False
        self.retry_count: int = 0
        self.max_retries: int = 1
        self.api_calls_made: int = 0
        self.max_api_calls: Optional[int] = max_api_calls
        self._endpoint_failures: dict[str, int] = {}
        self._disabled_endpoints: set[str] = set()

    # ------------------------------------------------------------------
    # Core HTTP helpers
    # ------------------------------------------------------------------

    def _rate_limited_get(
        self, url: str, params: Optional[dict] = None, quiet: bool = False
    ) -> Optional[dict]:
        """Rate-limited GET with retry, budget enforcement, and error handling.

        Args:
            quiet: Suppress non-429 error messages (used for non-last fallback attempts).

        Raises:
            ApiCallBudgetExceeded: When max_api_calls is set and budget is exhausted.
        """
        if self.max_api_calls is not None and self.api_calls_made >= self.max_api_calls:
            raise ApiCallBudgetExceeded(
                f"API call budget exhausted: {self.api_calls_made}/{self.max_api_calls} calls used"
            )
        if self.rate_limit_reached:
            return None
        if params is None:
            params = {}

        elapsed = time.time() - self.last_call_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)

        try:
            response = self.session.get(url, params=params, timeout=30)
            self.last_call_time = time.time()
            self.api_calls_made += 1

            if response.status_code == 200:
                self.retry_count = 0
                return response.json()
            elif response.status_code == 429:
                self.retry_count += 1
                if self.retry_count <= self.max_retries:
                    if not quiet:
                        print("WARNING: Rate limit exceeded. Waiting 60 seconds...", file=sys.stderr)
                    time.sleep(60)
                    return self._rate_limited_get(url, params, quiet=quiet)
                else:
                    if not quiet:
                        print("ERROR: Daily API rate limit reached.", file=sys.stderr)
                    self.rate_limit_reached = True
                    return None
            else:
                if not quiet:
                    print(
                        f"ERROR: API request failed: {response.status_code} - {response.text[:200]}",
                        file=sys.stderr,
                    )
                return None
        except requests.exceptions.RequestException as e:
            if not quiet:
                print(f"ERROR: Request exception: {e}", file=sys.stderr)
            return None

    def _request_with_fallback(self, endpoint_key, symbols_str, extra_params=None):
        """Try stable endpoint first, fall back to v3 for legacy users.

        Returns parsed JSON in v3-compatible shape, or None if all endpoints fail.
        Non-last endpoints use quiet=True to suppress expected 403 noise.
        """
        params = dict(extra_params) if extra_params else {}
        endpoints = _FMP_ENDPOINTS[endpoint_key]
        is_single = "," not in symbols_str

        for i, (base_url, url_builder) in enumerate(endpoints):
            if base_url in self._disabled_endpoints:
                continue
            url, final_params = url_builder(base_url, symbols_str, dict(params))
            is_last = i == len(endpoints) - 1
            data = self._rate_limited_get(url, final_params, quiet=not is_last)
            if not data:
                self._record_endpoint_failure(base_url)
                continue

            if endpoint_key == "historical":
                limit = params.get("timeseries") if isinstance(params, dict) else None
                data = _normalize_eod_flat_list(data, symbols_str, limit=limit)
                if not data:
                    self._record_endpoint_failure(base_url)
                    continue

            valid = True
            if endpoint_key == "quote":
                if not isinstance(data, list) or len(data) == 0:
                    valid = False
                elif is_single and not any(
                    q.get("symbol", "").replace("-", ".") == symbols_str.replace("-", ".")
                    for q in data
                ):
                    valid = False

            if endpoint_key == "historical":
                if not isinstance(data, dict):
                    valid = False
                elif "historicalStockList" in data:
                    norm = symbols_str.replace("-", ".")
                    found = None
                    for entry in data["historicalStockList"]:
                        if entry.get("symbol", "").replace("-", ".") == norm:
                            found = {
                                "symbol": entry.get("symbol"),
                                "historical": entry.get("historical", []),
                            }
                            break
                    if found:
                        self._endpoint_failures[base_url] = 0
                        return found
                    valid = False
                elif "historical" not in data:
                    valid = False
                elif is_single and data.get("symbol"):
                    if data["symbol"].replace("-", ".") != symbols_str.replace("-", "."):
                        valid = False

            if valid:
                self._endpoint_failures[base_url] = 0
                return data
            self._record_endpoint_failure(base_url)
        return None

    def _record_endpoint_failure(self, base_url: str) -> None:
        failures = self._endpoint_failures.get(base_url, 0) + 1
        self._endpoint_failures[base_url] = failures
        if failures >= self._ENDPOINT_FAILURE_THRESHOLD:
            self._disabled_endpoints.add(base_url)

    # ------------------------------------------------------------------
    # Quote & price endpoints
    # ------------------------------------------------------------------

    def get_quote(self, symbols: str) -> Optional[list[dict]]:
        """Real-time quote for one or more comma-separated symbols."""
        cache_key = f"quote_{symbols}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        data = self._request_with_fallback("quote", symbols)
        if data:
            self.cache[cache_key] = data
        return data

    def get_historical_prices(self, symbol: str, days: int = 365) -> Optional[dict]:
        """Historical daily OHLCV. Returns dict with 'symbol' and 'historical' keys."""
        cache_key = f"prices_{symbol}_{days}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        data = self._request_with_fallback("historical", symbol, {"timeseries": days})
        if data:
            self.cache[cache_key] = data
        return data

    def get_batch_quotes(self, symbols: list[str], batch_size: int = 5) -> dict[str, dict]:
        """Fetch quotes for a list of symbols, batched to avoid URL length limits."""
        results = {}
        for i in range(0, len(symbols), batch_size):
            batch_str = ",".join(symbols[i : i + batch_size])
            quotes = self.get_quote(batch_str)
            if quotes:
                for q in quotes:
                    results[q["symbol"]] = q
        return results

    def get_batch_historical(self, symbols: list[str], days: int = 260) -> dict[str, list[dict]]:
        """Fetch historical prices for multiple symbols. Returns symbol → rows dict."""
        results = {}
        for symbol in symbols:
            data = self.get_historical_prices(symbol, days=days)
            if data and "historical" in data:
                results[symbol] = data["historical"]
        return results

    def get_aftermarket_quote(self, symbol: str) -> Optional[dict]:
        """Pre/after-market quote from stable/aftermarket-quote.

        Returns normalised dict with price, bid, ask, volume, high, low,
        timestamp, source. high/low may be None — callers must handle that.
        Returns None when no aftermarket data is available.
        """
        cache_key = f"aftermarket_{symbol}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.STABLE_URL}/aftermarket-quote"
        data = self._rate_limited_get(url, params={"symbol": symbol}, quiet=True)
        if not data:
            return None
        row = data[0] if isinstance(data, list) and data else data
        if not isinstance(row, dict):
            return None
        out = {
            "price": row.get("price"),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "volume": row.get("volume") or row.get("size"),
            "high": row.get("high"),
            "low": row.get("low"),
            "timestamp": row.get("timestamp") or row.get("date"),
            "source": "fmp_aftermarket_quote",
        }
        self.cache[cache_key] = out
        return out

    def get_intraday_ohlcv(
        self,
        symbol: str,
        interval: str = "5min",
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
    ) -> Optional[list[dict]]:
        """Intraday bars — stub; not yet implemented."""
        raise NotImplementedError(
            "Intraday OHLCV is not yet implemented in the shared client."
        )

    # ------------------------------------------------------------------
    # Company / profile endpoints
    # ------------------------------------------------------------------

    def get_profile(self, symbol: str) -> Optional[list[dict]]:
        """Company profile as a raw list (v3 shape). Returns None on error."""
        cache_key = f"profile_list_{symbol}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.BASE_URL}/profile/{symbol}"
        data = self._rate_limited_get(url)
        if data:
            self.cache[cache_key] = data
        return data

    def get_company_profile(self, symbol: str) -> Optional[dict]:
        """Company profile as a single dict (unwrapped). Returns None on error."""
        cache_key = f"profile_{symbol}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.BASE_URL}/profile/{symbol}"
        data = self._rate_limited_get(url)
        if isinstance(data, list) and data:
            profile = data[0]
            self.cache[cache_key] = profile
            return profile
        return None

    def get_company_profiles(self, symbols: list[str]) -> dict[str, dict]:
        """Batch profile fetch. Returns symbol → profile dict mapping."""
        results = {}
        batch_size = 100
        for i in range(0, len(symbols), batch_size):
            batch_str = ",".join(symbols[i : i + batch_size])
            cache_key = f"profiles_batch_{batch_str}"
            if cache_key in self.cache:
                for profile in self.cache[cache_key]:
                    results[profile["symbol"]] = profile
                continue
            url = f"{self.BASE_URL}/profile/{batch_str}"
            data = self._rate_limited_get(url)
            if data:
                self.cache[cache_key] = data
                for profile in data:
                    results[profile["symbol"]] = profile
        return results

    def get_profile_bulk(self, part: int = 0) -> Optional[list[dict]]:
        """Bulk profile download (Premium endpoint). Returns None on failure."""
        cache_key = f"profile_bulk_{part}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.STABLE_URL}/profile-bulk"
        data = self._rate_limited_get(url, params={"part": part}, quiet=True)
        if isinstance(data, list) and data:
            self.cache[cache_key] = data
            return data
        return None

    def get_sp500_constituents(self) -> Optional[list[dict]]:
        """S&P 500 constituent list. Returns list with symbol, name, sector, subSector."""
        cache_key = "sp500_constituents"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.BASE_URL}/sp500_constituent"
        data = self._rate_limited_get(url)
        if data:
            self.cache[cache_key] = data
        return data

    def get_institutional_holders(self, symbol: str) -> Optional[list[dict]]:
        """13F institutional holder data for a symbol."""
        cache_key = f"institutional_{symbol}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.BASE_URL}/institutional-holder/{symbol}"
        data = self._rate_limited_get(url)
        if data:
            self.cache[cache_key] = data
        return data

    # ------------------------------------------------------------------
    # Fundamental endpoints
    # ------------------------------------------------------------------

    def get_income_statement(
        self, symbol: str, period: str = "quarter", limit: int = 8
    ) -> Optional[list[dict]]:
        """Income statement (quarterly or annual). Returns list most-recent-first."""
        cache_key = f"income_{symbol}_{period}_{limit}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.BASE_URL}/income-statement/{symbol}"
        data = self._rate_limited_get(url, {"period": period, "limit": limit})
        if data:
            self.cache[cache_key] = data
        return data

    # ------------------------------------------------------------------
    # Macro / rates endpoints
    # ------------------------------------------------------------------

    def get_treasury_rates(self, days: int = 600) -> Optional[list[dict]]:
        """Treasury rate data. Returns list of dicts with date, year2, year10, etc."""
        cache_key = f"treasury_{days}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.STABLE_URL}/treasury-rates"
        data = self._rate_limited_get(url, {"limit": days})
        if data and isinstance(data, list):
            self.cache[cache_key] = data
            return data
        return None

    # ------------------------------------------------------------------
    # Derived / composite methods
    # ------------------------------------------------------------------

    def get_earnings_calendar(self, from_date: str, to_date: str) -> Optional[list[dict]]:
        """Earnings calendar for a date range (YYYY-MM-DD)."""
        cache_key = f"earnings_{from_date}_{to_date}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{self.STABLE_URL}/earnings-calendar"
        data = self._rate_limited_get(url, {"from": from_date, "to": to_date})
        if data:
            self.cache[cache_key] = data
        return data

    def get_vix_term_structure(self) -> Optional[dict]:
        """Compare VIX to VIX3M and classify term structure.

        Returns dict with vix, vix3m, ratio, classification, or None if
        VIX3M data is unavailable.
        """
        vix_quotes = self.get_quote("^VIX")
        vix3m_quotes = self.get_quote("^VIX3M")
        if not vix_quotes or not vix3m_quotes:
            return None
        vix_price = vix_quotes[0].get("price", 0)
        vix3m_price = vix3m_quotes[0].get("price", 0)
        if vix3m_price <= 0:
            return None
        ratio = vix_price / vix3m_price
        if ratio < 0.85:
            classification = "steep_contango"
        elif ratio < 0.95:
            classification = "contango"
        elif ratio <= 1.05:
            classification = "flat"
        else:
            classification = "backwardation"
        return {
            "vix": round(vix_price, 2),
            "vix3m": round(vix3m_price, 2),
            "ratio": round(ratio, 3),
            "classification": classification,
        }

    # ------------------------------------------------------------------
    # Math helpers
    # ------------------------------------------------------------------

    def calculate_ema(self, prices: list[float], period: int = 50) -> float:
        """EMA from a most-recent-first price list."""
        if len(prices) < period:
            return sum(prices) / len(prices)
        prices_asc = prices[::-1]
        ema = sum(prices_asc[:period]) / period
        k = 2 / (period + 1)
        for price in prices_asc[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    def calculate_sma(self, prices: list[float], period: int) -> float:
        """SMA from a most-recent-first price list."""
        if len(prices) < period:
            return sum(prices) / len(prices)
        return sum(prices[:period]) / period

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        """Clear the in-memory session cache."""
        self.cache = {}

    def get_api_stats(self) -> dict:
        stats = {
            "cache_entries": len(self.cache),
            "api_calls_made": self.api_calls_made,
            "rate_limit_reached": self.rate_limit_reached,
        }
        if self.max_api_calls is not None:
            stats["max_api_calls"] = self.max_api_calls
            stats["budget_remaining"] = max(0, self.max_api_calls - self.api_calls_made)
        return stats
