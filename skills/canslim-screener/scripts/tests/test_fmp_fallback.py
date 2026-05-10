#!/usr/bin/env python3
"""
Tests for FMP stable/v3 endpoint fallback in canslim-screener.

Tier A (4): Fallback logic
Tier B (4): Response normalization
Tier B+ (2): Shape validation
Caller regression (2): screen_canslim.py behavior on failure
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_client():
    """Create FMPClient with a fake API key."""
    with patch.dict(os.environ, {"FMP_API_KEY": "test_key"}):  # pragma: allowlist secret
        from fmp_client import FMPClient

        client = FMPClient(api_key="test_key")
    return client


def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Tier A — Fallback logic (4 tests)
# ---------------------------------------------------------------------------


class TestFallbackLogic:
    """Verify stable-first, v3-fallback behavior."""

    def test_quote_stable_success(self):
        """Stable 200 returns data; v3 is never called."""
        client = _make_client()
        stable_resp = _mock_response(200, [{"symbol": "^GSPC", "price": 5000}])

        call_count = {"n": 0}

        def fake_get(url, params=None, timeout=30):
            call_count["n"] += 1
            if "stable" in url:
                return stable_resp
            pytest.fail("v3 endpoint should not be called")

        client.session.get = fake_get
        result = client.get_quote("^GSPC")
        assert result == [{"symbol": "^GSPC", "price": 5000}]
        assert call_count["n"] == 1

    def test_quote_both_fail(self):
        """Both endpoints 403 → returns None."""
        client = _make_client()
        resp_403 = _mock_response(403, None, "Forbidden")

        client.session.get = MagicMock(return_value=resp_403)
        result = client.get_quote("^GSPC")
        assert result is None

    def test_historical_both_fail(self):
        """Stable 403 → returns None."""
        client = _make_client()
        resp_403 = _mock_response(403, None, "Forbidden")
        client.session.get = MagicMock(return_value=resp_403)
        result = client.get_historical_prices("^GSPC", days=80)
        assert result is None


# ---------------------------------------------------------------------------
# Batch quote (1 test)
# ---------------------------------------------------------------------------


class TestBatchQuote:
    def test_batch_quote_skips_symbol_check(self):
        """Multi-symbol (batch) quote does not apply symbol mismatch check."""
        client = _make_client()
        batch_data = [{"symbol": "^GSPC", "price": 5000}, {"symbol": "^VIX", "price": 20}]
        resp = _mock_response(200, batch_data)
        client.session.get = MagicMock(return_value=resp)

        result = client.get_quote("^GSPC,^VIX")
        assert result == batch_data
        assert client.session.get.call_count == 1


class TestEODFlatListSuccess:
    """Issue #64: stable EOD flat list -> public method success (regression)."""

    @patch("fmp_client.requests.Session")
    def test_get_historical_prices_normalizes_flat_list(self, mock_session_class):
        """Flat list response from new EOD endpoint -> dict contract preserved."""
        mock_session = MagicMock()
        mock_session.get.return_value = _mock_response(
            200,
            [
                {
                    "symbol": "SPY",
                    "date": "2026-04-29",
                    "open": 500.0,
                    "high": 502.0,
                    "low": 499.0,
                    "close": 501.0,
                    "volume": 1_000_000,
                },
                {
                    "symbol": "SPY",
                    "date": "2026-04-28",
                    "open": 498.0,
                    "high": 501.0,
                    "low": 497.0,
                    "close": 500.0,
                    "volume": 1_100_000,
                },
            ],
        )
        mock_session_class.return_value = mock_session

        client = _make_client()
        client.session = mock_session
        client.max_retries = 0

        result = client.get_historical_prices("SPY", days=2)
        assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
        assert result["symbol"] == "SPY"
        assert len(result["historical"]) == 2
        assert result["historical"][0]["close"] == 501.0

        # URL regression: must hit /historical-price-eod/full with from/to (not timeseries)
        first_call = mock_session.get.call_args_list[0]
        url = first_call[0][0]
        params = first_call[1]["params"]
        assert "historical-price-eod/full" in url
        assert "from" in params and "to" in params
        assert "timeseries" not in params
