"""
Tests for FinnhubClient — earnings calendar, company profiles, and historical OHLCV.

All tests mock network calls so no real API key is needed.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from finnhub_client import FinnhubClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client():
    """FinnhubClient with dummy key and instant rate limiting."""
    c = FinnhubClient(api_key="test-key")
    c.RATE_LIMIT_DELAY = 0  # skip sleeps in tests
    return c


def _mock_get(client, return_value: dict):
    """Patch FinnhubClient._get to return return_value without a real HTTP call."""
    mock = MagicMock(return_value=return_value)
    client._get = mock
    return mock


# ---------------------------------------------------------------------------
# get_earnings_calendar
# ---------------------------------------------------------------------------


class TestGetEarningsCalendar:
    def test_returns_list_with_correct_keys(self):
        client = _make_client()
        _mock_get(
            client,
            {
                "earningsCalendar": [
                    {"symbol": "AAPL", "date": "2025-11-05", "hour": "amc"},
                    {"symbol": "MSFT", "date": "2025-11-05", "hour": "bmo"},
                ]
            },
        )
        results = client.get_earnings_calendar("2025-11-05", "2025-11-05")
        assert len(results) == 2
        assert results[0]["symbol"] == "AAPL"
        assert results[0]["date"] == "2025-11-05"
        assert results[0]["time"] == "amc"
        assert results[1]["time"] == "bmo"

    def test_deduplicates_same_symbol(self):
        client = _make_client()
        _mock_get(
            client,
            {
                "earningsCalendar": [
                    {"symbol": "AAPL", "date": "2025-11-05", "hour": "amc"},
                    {"symbol": "AAPL", "date": "2025-11-05", "hour": "amc"},
                ]
            },
        )
        results = client.get_earnings_calendar("2025-11-05", "2025-11-05")
        assert len(results) == 1

    def test_dmh_timing_preserved(self):
        client = _make_client()
        _mock_get(
            client,
            {"earningsCalendar": [{"symbol": "XYZ", "date": "2025-11-05", "hour": "dmh"}]},
        )
        results = client.get_earnings_calendar("2025-11-05", "2025-11-05")
        assert results[0]["time"] == "dmh"

    def test_empty_hour_preserved(self):
        client = _make_client()
        _mock_get(
            client,
            {"earningsCalendar": [{"symbol": "XYZ", "date": "2025-11-05", "hour": ""}]},
        )
        results = client.get_earnings_calendar("2025-11-05", "2025-11-05")
        assert results[0]["time"] == ""

    def test_caches_result(self):
        client = _make_client()
        mock = _mock_get(
            client, {"earningsCalendar": [{"symbol": "AAPL", "date": "2025-11-05", "hour": "amc"}]}
        )
        client.get_earnings_calendar("2025-11-05", "2025-11-05")
        client.get_earnings_calendar("2025-11-05", "2025-11-05")
        assert mock.call_count == 1

    def test_api_failure_returns_empty(self):
        client = _make_client()
        client._get = MagicMock(side_effect=Exception("network error"))
        results = client.get_earnings_calendar("2025-11-05", "2025-11-05")
        assert results == []

    def test_skips_entries_without_symbol(self):
        client = _make_client()
        _mock_get(
            client,
            {
                "earningsCalendar": [
                    {"symbol": "", "date": "2025-11-05", "hour": "amc"},
                    {"symbol": "MSFT", "date": "2025-11-05", "hour": "bmo"},
                ]
            },
        )
        results = client.get_earnings_calendar("2025-11-05", "2025-11-05")
        assert len(results) == 1
        assert results[0]["symbol"] == "MSFT"


# ---------------------------------------------------------------------------
# get_company_profiles_from_quotes
# ---------------------------------------------------------------------------


class TestGetCompanyProfiles:
    def _profile_response(self, symbol="AAPL", mkt_cap_millions=3_000_000, country="US"):
        return {
            "ticker": symbol,
            "name": f"{symbol} Inc",
            "marketCapitalization": mkt_cap_millions,
            "country": country,
            "exchange": "NASDAQ NMS",
            "finnhubIndustry": "Technology",
        }

    def test_converts_market_cap_to_dollars(self):
        """Finnhub marketCapitalization is in millions; output mktCap must be in dollars."""
        client = _make_client()
        _mock_get(client, self._profile_response(mkt_cap_millions=3_000_000))
        entries = [{"symbol": "AAPL"}]
        profiles = client.get_company_profiles_from_quotes(entries)
        assert profiles["AAPL"]["mktCap"] == 3_000_000_000_000  # $3T

    def test_profile_keys_present(self):
        client = _make_client()
        _mock_get(client, self._profile_response())
        profiles = client.get_company_profiles_from_quotes([{"symbol": "AAPL"}])
        p = profiles["AAPL"]
        for key in ("companyName", "mktCap", "country", "exchangeShortName", "sector", "industry", "price"):
            assert key in p, f"Missing key: {key}"

    def test_country_field_preserved(self):
        client = _make_client()
        _mock_get(client, self._profile_response(country="US"))
        profiles = client.get_company_profiles_from_quotes([{"symbol": "AAPL"}])
        assert profiles["AAPL"]["country"] == "US"

    def test_non_us_country_preserved(self):
        client = _make_client()
        _mock_get(client, self._profile_response(country="GB"))
        profiles = client.get_company_profiles_from_quotes([{"symbol": "BP"}])
        assert profiles["BP"]["country"] == "GB"

    def test_unknown_symbol_excluded(self):
        """Empty Finnhub response (no ticker) -> excluded from results."""
        client = _make_client()
        _mock_get(client, {})  # no "ticker" key
        profiles = client.get_company_profiles_from_quotes([{"symbol": "FAKE"}])
        assert "FAKE" not in profiles

    def test_caches_profile(self):
        client = _make_client()
        mock = _mock_get(client, self._profile_response())
        entries = [{"symbol": "AAPL"}]
        client.get_company_profiles_from_quotes(entries)
        client.get_company_profiles_from_quotes(entries)
        assert mock.call_count == 1

    def test_api_failure_excluded(self):
        client = _make_client()
        client._get = MagicMock(side_effect=Exception("timeout"))
        profiles = client.get_company_profiles_from_quotes([{"symbol": "ERR"}])
        assert profiles == {}

    def test_missing_symbol_skipped(self):
        client = _make_client()
        profiles = client.get_company_profiles_from_quotes([{"date": "2025-01-05"}])
        assert profiles == {}


# ---------------------------------------------------------------------------
# get_historical_prices
# ---------------------------------------------------------------------------


class TestGetHistoricalPrices:
    def _candle_response(self, n=5):
        """Build a minimal Finnhub candle response with n bars, oldest-first."""
        import time as _time

        base_ts = int(_time.time()) - n * 86400
        return {
            "s": "ok",
            "t": [base_ts + i * 86400 for i in range(n)],
            "o": [100.0 + i * 0.5 for i in range(n)],
            "h": [101.0 + i * 0.5 for i in range(n)],
            "l": [99.0 + i * 0.5 for i in range(n)],
            "c": [100.5 + i * 0.5 for i in range(n)],
            "v": [1_000_000 + i * 10_000 for i in range(n)],
        }

    def test_returns_dict_contract(self):
        client = _make_client()
        _mock_get(client, self._candle_response())
        result = client.get_historical_prices("AAPL", days=5)
        assert result is not None
        assert "symbol" in result
        assert "historical" in result
        assert result["symbol"] == "AAPL"

    def test_most_recent_first(self):
        """Finnhub returns oldest-first; client must reverse to most-recent-first."""
        client = _make_client()
        _mock_get(client, self._candle_response(n=3))
        rows = client.get_historical_prices("AAPL", days=3)["historical"]
        # First row should have the highest close (most recent bar)
        assert rows[0]["close"] > rows[-1]["close"]

    def test_row_keys_present(self):
        client = _make_client()
        _mock_get(client, self._candle_response(n=1))
        row = client.get_historical_prices("AAPL", days=1)["historical"][0]
        for key in ("date", "open", "high", "low", "close", "volume"):
            assert key in row

    def test_days_limit_respected(self):
        client = _make_client()
        _mock_get(client, self._candle_response(n=10))
        rows = client.get_historical_prices("AAPL", days=5)["historical"]
        assert len(rows) == 5

    def test_no_data_returns_none(self):
        client = _make_client()
        _mock_get(client, {"s": "no_data"})
        assert client.get_historical_prices("FAKE", days=250) is None

    def test_empty_arrays_returns_none(self):
        client = _make_client()
        _mock_get(client, {"s": "ok", "c": [], "t": [], "o": [], "h": [], "l": [], "v": []})
        assert client.get_historical_prices("FAKE", days=250) is None

    def test_api_failure_returns_none(self):
        client = _make_client()
        client._get = MagicMock(side_effect=Exception("connection error"))
        assert client.get_historical_prices("ERR", days=250) is None

    def test_caches_result(self):
        client = _make_client()
        mock = _mock_get(client, self._candle_response())
        client.get_historical_prices("SPY", days=5)
        client.get_historical_prices("SPY", days=5)
        assert mock.call_count == 1


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_get_api_stats_structure(self):
        client = _make_client()
        stats = client.get_api_stats()
        assert "api_calls_made" in stats
        assert "cache_entries" in stats
        assert "data_source" in stats
        assert stats["data_source"] == "finnhub"

    def test_clear_cache(self):
        client = _make_client()
        client.cache["foo"] = "bar"
        client.clear_cache()
        assert client.cache == {}

    def test_api_calls_counted(self):
        """_api_calls is incremented by the real _get, not the mock; verify mock was called."""
        client = _make_client()
        mock = _mock_get(
            client,
            {"earningsCalendar": [{"symbol": "AAPL", "date": "2025-11-05", "hour": "amc"}]},
        )
        client.get_earnings_calendar("2025-11-05", "2025-11-05")
        assert mock.call_count == 1
