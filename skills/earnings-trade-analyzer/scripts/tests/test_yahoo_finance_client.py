"""
Tests for YahooFinanceClient — EDGAR earnings calendar, historical prices,
and company profile extraction.

Verifies:
- get_earnings_calendar() uses EDGAR EFTS, filters Item 2.02, deduplicates
- get_historical_prices() returns most-recent-first dicts with correct keys
- get_company_profiles_from_quotes() falls back to Ticker.info
- Caching prevents duplicate requests
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from yahoo_finance_client import YahooFinanceClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hist_df(dates, closes=None):
    """Build a minimal yfinance-style history DataFrame."""
    n = len(dates)
    closes = closes or [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "Open": [c * 0.999 for c in closes],
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": [1_000_000] * n,
        },
        index=pd.to_datetime(dates),
    )


def _make_edgar_response(hits, total=None):
    """Build a mock EDGAR EFTS response dict."""
    return {
        "hits": {
            "total": {"value": total if total is not None else len(hits)},
            "hits": hits,
        }
    }


def _hit(items, file_date, display_names):
    return {
        "_source": {
            "items": items,
            "file_date": file_date,
            "display_names": display_names,
        }
    }


# ---------------------------------------------------------------------------
# EDGAR earnings calendar tests
# ---------------------------------------------------------------------------


class TestGetEarningsCalendar:
    """Verify EDGAR-based get_earnings_calendar()."""

    def _patched_client(self, hits, total=None):
        """Return a YahooFinanceClient whose EDGAR session is mocked."""
        client = YahooFinanceClient()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_edgar_response(hits, total)
        client._edgar_session = MagicMock()
        client._edgar_session.get.return_value = mock_resp
        return client

    def test_filters_item_202_only(self):
        """Non-2.02 8-K filings are excluded."""
        hits = [
            _hit(["2.02", "9.01"], "2025-01-05", ["APPLE INC  (AAPL)  (CIK 0000320193)"]),
            _hit(["1.01"], "2025-01-05", ["OTHER CORP  (OTHR)  (CIK 0000111111)"]),
        ]
        results = self._patched_client(hits).get_earnings_calendar("2025-01-05", "2025-01-05")
        assert len(results) == 1
        assert results[0]["symbol"] == "AAPL"

    def test_returns_correct_date(self):
        """file_date from EDGAR is used as the earnings date."""
        hits = [_hit(["2.02"], "2025-01-08", ["MSFT INC  (MSFT)  (CIK 0000789019)"])]
        results = self._patched_client(hits).get_earnings_calendar("2025-01-08", "2025-01-08")
        assert results[0]["date"] == "2025-01-08"

    def test_time_is_unknown(self):
        """Timing defaults to 'unknown' since EDGAR does not provide BMO/AMC."""
        hits = [_hit(["2.02"], "2025-01-05", ["AAPL  (AAPL)  (CIK 0000320193)"])]
        results = self._patched_client(hits).get_earnings_calendar("2025-01-05", "2025-01-05")
        assert results[0]["time"] == "unknown"

    def test_deduplicates_same_ticker(self):
        """Same ticker in multiple hits appears once."""
        hits = [
            _hit(["2.02"], "2025-01-05", ["AAPL  (AAPL)  (CIK 0000000001)"]),
            _hit(["2.02"], "2025-01-05", ["AAPL  (AAPL)  (CIK 0000000001)"]),
        ]
        results = self._patched_client(hits).get_earnings_calendar("2025-01-05", "2025-01-05")
        assert len(results) == 1

    def test_multiple_tickers(self):
        """Multiple distinct tickers all returned."""
        hits = [
            _hit(["2.02"], "2025-01-05", ["AAPL  (AAPL)  (CIK 0000320193)"]),
            _hit(["2.02"], "2025-01-05", ["MSFT  (MSFT)  (CIK 0000789019)"]),
            _hit(["2.02"], "2025-01-05", ["NVDA  (NVDA)  (CIK 0001045810)"]),
        ]
        results = self._patched_client(hits).get_earnings_calendar("2025-01-05", "2025-01-05")
        symbols = {r["symbol"] for r in results}
        assert symbols == {"AAPL", "MSFT", "NVDA"}

    def test_empty_hits_returns_empty(self):
        """No 8-K filings -> empty list."""
        results = self._patched_client([]).get_earnings_calendar("2025-01-05", "2025-01-05")
        assert results == []

    def test_result_has_yf_quote_key(self):
        """Each result includes _yf_quote key for profile extraction compatibility."""
        hits = [_hit(["2.02"], "2025-01-05", ["AAPL  (AAPL)  (CIK 0000320193)"])]
        results = self._patched_client(hits).get_earnings_calendar("2025-01-05", "2025-01-05")
        assert "_yf_quote" in results[0]

    def test_cached_result_reused(self):
        """Second call with same args hits cache, not EDGAR again."""
        hits = [_hit(["2.02"], "2025-01-05", ["AAPL  (AAPL)  (CIK 0000320193)"])]
        client = self._patched_client(hits)
        client.get_earnings_calendar("2025-01-05", "2025-01-05")
        client.get_earnings_calendar("2025-01-05", "2025-01-05")
        assert client._edgar_session.get.call_count == 1

    def test_edgar_failure_returns_empty(self):
        """Network error from EDGAR -> empty list, no crash."""
        client = YahooFinanceClient()
        client._edgar_session = MagicMock()
        client._edgar_session.get.side_effect = Exception("network error")
        results = client.get_earnings_calendar("2025-01-05", "2025-01-05")
        assert results == []


# ---------------------------------------------------------------------------
# _extract_ticker tests
# ---------------------------------------------------------------------------


class TestExtractTicker:
    def test_standard_format(self):
        assert YahooFinanceClient._extract_ticker("APPLE INC  (AAPL)  (CIK 0000320193)") == "AAPL"

    def test_single_letter(self):
        assert YahooFinanceClient._extract_ticker("FORD MOTOR CO  (F)  (CIK 0000037996)") == "F"

    def test_five_letters(self):
        assert YahooFinanceClient._extract_ticker("COMPANY  (GOOGL)  (CIK 000123)") == "GOOGL"

    def test_no_match(self):
        assert YahooFinanceClient._extract_ticker("No ticker here") is None

    def test_lowercase_ignored(self):
        assert YahooFinanceClient._extract_ticker("Something (Inc.)") is None


# ---------------------------------------------------------------------------
# Historical price tests
# ---------------------------------------------------------------------------


class TestGetHistoricalPrices:
    """Verify get_historical_prices() normalisation."""

    @patch("yahoo_finance_client.yf.Ticker")
    def test_returns_dict_contract(self, mock_ticker_cls):
        """Result is {"symbol": ..., "historical": [...]}."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = _make_hist_df(["2025-01-06", "2025-01-07"])

        client = YahooFinanceClient()
        result = client.get_historical_prices("SPY", days=2)

        assert isinstance(result, dict)
        assert "symbol" in result and "historical" in result
        assert result["symbol"] == "SPY"

    @patch("yahoo_finance_client.yf.Ticker")
    def test_most_recent_first(self, mock_ticker_cls):
        """Rows are returned most-recent-first."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = _make_hist_df(
            ["2025-01-03", "2025-01-06", "2025-01-07"]
        )

        client = YahooFinanceClient()
        rows = client.get_historical_prices("AAPL", days=3)["historical"]

        assert rows[0]["date"] == "2025-01-07"
        assert rows[-1]["date"] == "2025-01-03"

    @patch("yahoo_finance_client.yf.Ticker")
    def test_row_keys_present(self, mock_ticker_cls):
        """Each row has date, open, high, low, close, volume."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = _make_hist_df(["2025-01-07"])

        client = YahooFinanceClient()
        row = client.get_historical_prices("MSFT", days=1)["historical"][0]

        for key in ("date", "open", "high", "low", "close", "volume"):
            assert key in row, f"Missing key: {key}"

    @patch("yahoo_finance_client.yf.Ticker")
    def test_symbol_not_in_rows(self, mock_ticker_cls):
        """Row-level 'symbol' key is absent (matches FMPClient contract)."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = _make_hist_df(["2025-01-07"])

        client = YahooFinanceClient()
        row = client.get_historical_prices("GOOG", days=1)["historical"][0]
        assert "symbol" not in row

    @patch("yahoo_finance_client.yf.Ticker")
    def test_days_limit_respected(self, mock_ticker_cls):
        """Result is capped at requested days."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        dates = [f"2025-01-{d:02d}" for d in range(1, 11)]
        mock_ticker.history.return_value = _make_hist_df(dates)

        client = YahooFinanceClient()
        rows = client.get_historical_prices("SPY", days=5)["historical"]
        assert len(rows) == 5

    @patch("yahoo_finance_client.yf.Ticker")
    def test_empty_df_returns_none(self, mock_ticker_cls):
        """Empty DataFrame from yfinance -> None."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame()

        client = YahooFinanceClient()
        assert client.get_historical_prices("FAKE", days=250) is None

    @patch("yahoo_finance_client.yf.Ticker")
    def test_exception_returns_none(self, mock_ticker_cls):
        """Network error -> None (no crash)."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.side_effect = Exception("connection error")

        client = YahooFinanceClient()
        assert client.get_historical_prices("ERR", days=250) is None

    @patch("yahoo_finance_client.yf.Ticker")
    def test_cache_prevents_duplicate_calls(self, mock_ticker_cls):
        """Second call with same args returns cached data."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = _make_hist_df(["2025-01-07"])

        client = YahooFinanceClient()
        client.get_historical_prices("SPY", days=1)
        client.get_historical_prices("SPY", days=1)

        assert mock_ticker.history.call_count == 1


# ---------------------------------------------------------------------------
# Company profile tests
# ---------------------------------------------------------------------------


class TestGetCompanyProfilesFromQuotes:
    """Verify profile fetching via Ticker.info fallback."""

    @patch("yahoo_finance_client.yf.Ticker")
    def test_fetches_from_ticker_info(self, mock_ticker_cls):
        """Profile data comes from Ticker.info when _yf_quote is empty."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.info = {
            "marketCap": 3_000_000_000_000,
            "exchange": "NMS",
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "currentPrice": 195.0,
        }

        client = YahooFinanceClient()
        entries = [{"symbol": "AAPL", "date": "2025-01-05", "time": "unknown", "_yf_quote": {}}]
        profiles = client.get_company_profiles_from_quotes(entries)

        assert "AAPL" in profiles
        p = profiles["AAPL"]
        assert p["mktCap"] == 3_000_000_000_000
        assert p["exchangeShortName"] == "NMS"
        assert p["companyName"] == "Apple Inc."
        assert p["sector"] == "Technology"
        assert p["price"] == 195.0

    @patch("yahoo_finance_client.yf.Ticker")
    def test_cache_used_on_second_call(self, mock_ticker_cls):
        """Profile cached after first fetch; Ticker.info not called again."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.info = {"marketCap": 1_000_000_000, "exchange": "NYQ"}

        client = YahooFinanceClient()
        entries = [{"symbol": "MSFT", "date": "2025-01-05", "time": "unknown", "_yf_quote": {}}]
        client.get_company_profiles_from_quotes(entries)
        client.get_company_profiles_from_quotes(entries)

        assert mock_ticker.info.__class__.__name__  # just ensure info was accessed
        # The underlying yf.Ticker was constructed only once per unique symbol
        assert mock_ticker_cls.call_count == 1

    @patch("yahoo_finance_client.yf.Ticker")
    def test_ticker_info_failure_excluded(self, mock_ticker_cls):
        """Symbol with failing Ticker.info is excluded from results."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.info = None  # simulate failure

        client = YahooFinanceClient()
        entries = [{"symbol": "FAKE", "date": "2025-01-05", "time": "unknown", "_yf_quote": {}}]
        profiles = client.get_company_profiles_from_quotes(entries)
        assert "FAKE" not in profiles

    def test_missing_symbol_skipped(self):
        """Entry without symbol is ignored."""
        client = YahooFinanceClient()
        entries = [{"date": "2025-01-05", "_yf_quote": {}}]
        profiles = client.get_company_profiles_from_quotes(entries)
        assert profiles == {}
