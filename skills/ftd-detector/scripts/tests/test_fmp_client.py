"""Tests for FMP client using stable endpoints (no v3 fallback)."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts directory is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fmp_client import FMPClient


def _make_client():
    """Create an FMPClient with a fake API key and zero rate-limit delay."""
    client = FMPClient(api_key="test_key")
    client.RATE_LIMIT_DELAY = 0
    return client


def _mock_response(status_code, json_data=None):
    """Create a mock response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = f"HTTP {status_code}"
    return resp


# =========================================================================
# Stable endpoint success/failure
# =========================================================================


class TestStableEndpoint:
    """Stable endpoint success and failure behavior."""

    def test_quote_stable_success(self):
        """Stable 200 returns data."""
        client = _make_client()
        quote_data = [{"symbol": "^GSPC", "price": 5000.0}]
        stable_resp = _mock_response(200, quote_data)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return stable_resp

        client.session.get = MagicMock(side_effect=side_effect)
        result = client.get_quote("^GSPC")
        assert result == quote_data
        assert call_count == 1

    def test_quote_stable_failure_returns_none(self):
        """Stable 403 returns None."""
        client = _make_client()
        resp_403 = _mock_response(403)
        client.session.get = MagicMock(return_value=resp_403)
        result = client.get_quote("^GSPC")
        assert result is None

    def test_historical_stable_failure_returns_none(self):
        """Stable 403 returns None for historical prices."""
        client = _make_client()
        resp_403 = _mock_response(403)
        client.session.get = MagicMock(return_value=resp_403)
        result = client.get_historical_prices("^GSPC", days=80)
        assert result is None

    def test_batch_quote_skips_symbol_check(self):
        """Multi-symbol (batch) quote does not apply symbol mismatch check."""
        client = _make_client()
        batch_data = [{"symbol": "^GSPC", "price": 5000}, {"symbol": "^VIX", "price": 20}]
        resp = _mock_response(200, batch_data)
        client.session.get = MagicMock(return_value=resp)

        result = client.get_quote("^GSPC,^VIX")
        assert result == batch_data
        assert client.session.get.call_count == 1


# =========================================================================
# Caller regression
# =========================================================================


class TestCallerRegression:
    """Verify ftd_detector.main() handles FMPClient failures correctly."""

    def test_ftd_detector_exits_on_historical_failure(self):
        """get_historical_prices -> None => main() calls sys.exit(1) (fatal)."""
        with (
            patch.dict(os.environ, {"FMP_API_KEY": "test_key"}),  # pragma: allowlist secret
            patch("sys.argv", ["ftd_detector.py"]),
        ):
            # Import inside patch to pick up env var
            import ftd_detector

            with (
                patch.object(FMPClient, "get_historical_prices", return_value=None),
                patch.object(
                    FMPClient,
                    "get_quote",
                    return_value=[{"symbol": "^GSPC", "price": 5000.0}],
                ),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    ftd_detector.main()
                assert exc_info.value.code == 1

    def test_ftd_detector_continues_on_quote_failure(self):
        """get_quote -> None => main() continues with warning (non-fatal)."""
        with (
            patch.dict(os.environ, {"FMP_API_KEY": "test_key"}),  # pragma: allowlist secret
            patch("sys.argv", ["ftd_detector.py"]),
        ):
            import ftd_detector

            sp500_hist = {
                "historical": [
                    {
                        "date": f"2026-03-{20 - i:02d}",
                        "open": 5000.0,
                        "high": 5010.0,
                        "low": 4990.0,
                        "close": 5000.0 - i * 10,
                        "volume": 3_000_000_000,
                    }
                    for i in range(80)
                ]
            }
            qqq_hist = {
                "historical": [
                    {
                        "date": f"2026-03-{20 - i:02d}",
                        "open": 450.0,
                        "high": 455.0,
                        "low": 445.0,
                        "close": 450.0 - i,
                        "volume": 50_000_000,
                    }
                    for i in range(80)
                ]
            }

            def mock_hist(symbol, days=365):
                if symbol == "^GSPC":
                    return sp500_hist
                elif symbol == "QQQ":
                    return qqq_hist
                return None

            with (
                patch.object(FMPClient, "get_historical_prices", side_effect=mock_hist),
                patch.object(FMPClient, "get_quote", return_value=None),
                patch.object(ftd_detector, "generate_json_report"),
                patch.object(ftd_detector, "generate_markdown_report"),
            ):
                # Should NOT raise SystemExit — quote failure is non-fatal
                ftd_detector.main()


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
