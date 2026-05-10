"""Tests for FMP Client VIX term structure and stable endpoint behavior."""

import os
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestVixTermStructure:
    """Test VIX term structure auto-classification."""

    def _make_client(self):
        """Create a mock FMPClient without real API key."""
        with patch.dict(os.environ, {"FMP_API_KEY": "test_key"}):
            from fmp_client import FMPClient

            client = FMPClient(api_key="test_key")
        return client

    def test_steep_contango(self):
        """VIX/VIX3M < 0.85 -> steep_contango."""
        client = self._make_client()
        client.get_quote = MagicMock(
            side_effect=lambda s: [{"price": 12.0}] if "VIX3M" not in s else [{"price": 16.0}]
        )
        result = client.get_vix_term_structure()
        assert result is not None
        assert result["classification"] == "steep_contango"
        assert result["ratio"] < 0.85

    def test_contango(self):
        """VIX/VIX3M 0.85-0.95 -> contango."""
        client = self._make_client()
        client.get_quote = MagicMock(
            side_effect=lambda s: [{"price": 14.0}] if "VIX3M" not in s else [{"price": 15.5}]
        )
        result = client.get_vix_term_structure()
        assert result["classification"] == "contango"

    def test_flat(self):
        """VIX/VIX3M 0.95-1.05 -> flat."""
        client = self._make_client()
        client.get_quote = MagicMock(
            side_effect=lambda s: [{"price": 15.0}] if "VIX3M" not in s else [{"price": 15.2}]
        )
        result = client.get_vix_term_structure()
        assert result["classification"] == "flat"

    def test_backwardation(self):
        """VIX/VIX3M > 1.05 -> backwardation."""
        client = self._make_client()
        client.get_quote = MagicMock(
            side_effect=lambda s: [{"price": 22.0}] if "VIX3M" not in s else [{"price": 18.0}]
        )
        result = client.get_vix_term_structure()
        assert result["classification"] == "backwardation"

    def test_unavailable(self):
        """VIX3M unavailable -> None."""
        client = self._make_client()
        client.get_quote = MagicMock(
            side_effect=lambda s: [{"price": 15.0}] if "VIX3M" not in s else None
        )
        result = client.get_vix_term_structure()
        assert result is None


def _mock_response(status_code, json_data=None, text=""):
    """Create a mock requests.Response."""
    resp = Mock()
    resp.status_code = status_code
    resp.json = Mock(return_value=json_data)
    resp.text = text
    return resp


class TestStableEndpoint:
    """Test stable endpoint behavior in FMPClient."""

    def _make_client(self):
        """Create FMPClient with mocked session."""
        with patch.dict(os.environ, {"FMP_API_KEY": "test_key"}):
            from fmp_client import FMPClient

            client = FMPClient(api_key="test_key")
        client.RATE_LIMIT_DELAY = 0  # disable rate limiting in tests
        return client

    def test_quote_stable_success(self):
        """Stable 200 returns data."""
        client = self._make_client()
        quote_data = [{"symbol": "^GSPC", "price": 5500.0}]

        call_log = []

        def mock_get(url, params=None, timeout=None):
            call_log.append(url)
            return _mock_response(200, quote_data)

        client.session.get = mock_get
        result = client.get_quote("^GSPC")

        assert result == quote_data
        assert len(call_log) == 1
        assert "stable" in call_log[0]

    def test_quote_stable_failure_returns_none(self):
        """Stable 403 returns None."""
        client = self._make_client()

        def mock_get(url, params=None, timeout=None):
            return _mock_response(403, text="Forbidden")

        client.session.get = mock_get
        result = client.get_quote("^GSPC")
        assert result is None

    def test_batch_quote_skips_symbol_check(self):
        """Multi-symbol (batch) quote does not apply symbol mismatch check."""
        client = self._make_client()
        batch_data = [{"symbol": "^GSPC", "price": 5000}, {"symbol": "^VIX", "price": 20}]
        resp = _mock_response(200, batch_data)
        client.session.get = MagicMock(return_value=resp)

        result = client.get_quote("^GSPC,^VIX")
        assert result == batch_data
        assert client.session.get.call_count == 1

    def test_market_top_exits_on_sp500_failure(self):
        """main() exits with code 1 when S&P 500 data unavailable."""
        from fmp_client import FMPClient

        with (
            patch.object(FMPClient, "__init__", lambda self, **kw: None),
            patch.object(FMPClient, "get_quote", return_value=None),
            patch.object(FMPClient, "get_historical_prices", return_value=None),
            patch.object(
                FMPClient,
                "get_api_stats",
                return_value={
                    "cache_entries": 0,
                    "api_calls_made": 0,
                    "rate_limit_reached": False,
                },
            ),
            patch("sys.argv", ["market_top_detector.py"]),
        ):
            # Need to set required attributes that __init__ would set
            def fake_init(self, **kw):
                self.api_key = "test"  # pragma: allowlist secret
                self.session = MagicMock()
                self.cache = {}
                self.last_call_time = 0
                self.rate_limit_reached = False
                self.retry_count = 0
                self.max_retries = 1
                self.api_calls_made = 0

            with patch.object(FMPClient, "__init__", fake_init):
                import market_top_detector

                with pytest.raises(SystemExit) as exc_info:
                    market_top_detector.main()
                assert exc_info.value.code == 1

    def test_market_top_continues_on_vix_failure(self, capsys):
        """main() continues with warning when VIX unavailable (non-fatal)."""
        from fmp_client import FMPClient

        sp500_quote = [{"symbol": "^GSPC", "price": 5500.0, "yearHigh": 5600.0}]
        sp500_hist = {
            "symbol": "^GSPC",
            "historical": [
                {
                    "date": f"2026-03-{20 - i:02d}",
                    "close": 5500.0 - i * 10,
                    "volume": 3_000_000_000,
                    "open": 5490.0 - i * 10,
                    "high": 5510.0 - i * 10,
                    "low": 5480.0 - i * 10,
                }
                for i in range(260)
            ],
        }
        qqq_quote = [{"symbol": "QQQ", "price": 480.0, "yearHigh": 500.0}]
        qqq_hist = {
            "symbol": "QQQ",
            "historical": [
                {
                    "date": f"2026-03-{20 - i:02d}",
                    "close": 480.0 - i,
                    "volume": 50_000_000,
                    "open": 479.0 - i,
                    "high": 481.0 - i,
                    "low": 478.0 - i,
                }
                for i in range(260)
            ],
        }

        def mock_quote(symbols):
            if symbols == "^GSPC":
                return sp500_quote
            if symbols == "QQQ":
                return qqq_quote
            if symbols == "^VIX":
                return None  # VIX fails
            if symbols == "^VIX3M":
                return None
            # Return generic quote for ETFs
            return [
                {
                    "symbol": symbols.split(",")[0],
                    "price": 100.0,
                    "yearHigh": 110.0,
                    "changesPercentage": 0.5,
                    "volume": 1_000_000,
                    "avgVolume": 1_000_000,
                }
            ]

        def mock_hist(symbol, days=365):
            if symbol == "^GSPC":
                return sp500_hist
            if symbol == "QQQ":
                return qqq_hist
            # Generic history for ETFs
            return {
                "symbol": symbol,
                "historical": [
                    {
                        "date": f"2026-03-{20 - i:02d}",
                        "close": 100.0 + i * 0.1,
                        "volume": 1_000_000,
                        "open": 99.9 + i * 0.1,
                        "high": 100.1 + i * 0.1,
                        "low": 99.8 + i * 0.1,
                    }
                    for i in range(min(days, 260))
                ],
            }

        def mock_batch_quotes(symbols):
            result = {}
            for s in symbols:
                q = mock_quote(s)
                if q:
                    for item in q:
                        result[item.get("symbol", s)] = item
            return result

        def mock_batch_hist(symbols, days=50):
            result = {}
            for s in symbols:
                d = mock_hist(s, days)
                if d and "historical" in d:
                    result[s] = d["historical"]
            return result

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"FMP_API_KEY": "test_key"}),  # pragma: allowlist secret
                patch(
                    "sys.argv",
                    [
                        "market_top_detector.py",
                        "--static-basket",
                        "--no-auto-breadth",
                        "--breadth-200dma",
                        "60.0",
                        "--put-call",
                        "0.70",
                        "--vix-term",
                        "contango",
                        "--output-dir",
                        tmpdir,
                    ],
                ),
            ):
                from fmp_client import FMPClient

                with (
                    patch.object(FMPClient, "get_quote", side_effect=mock_quote),
                    patch.object(FMPClient, "get_historical_prices", side_effect=mock_hist),
                    patch.object(FMPClient, "get_batch_quotes", side_effect=mock_batch_quotes),
                    patch.object(FMPClient, "get_batch_historical", side_effect=mock_batch_hist),
                ):
                    import importlib

                    import market_top_detector

                    importlib.reload(market_top_detector)

                    # Should NOT raise SystemExit — VIX failure is non-fatal
                    try:
                        market_top_detector.main()
                    except SystemExit:
                        pytest.fail("main() should not exit when only VIX fails")

            captured = capsys.readouterr()
            assert "WARN" in captured.out or "VIX unavailable" in captured.out


class TestEODFlatListSuccess:
    """Issue #64: stable EOD flat list -> public method success (regression)."""

    def _make_client(self):
        with patch.dict(os.environ, {"FMP_API_KEY": "test_key"}):
            from fmp_client import FMPClient

            client = FMPClient(api_key="test_key")
        client.max_retries = 0
        return client

    @patch("fmp_client.requests.Session")
    def test_get_historical_prices_normalizes_flat_list(self, mock_session_class):
        """Flat list response from new EOD endpoint -> dict contract preserved."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
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
        ]
        mock_resp.text = ""
        mock_session.get.return_value = mock_resp
        mock_session_class.return_value = mock_session

        client = self._make_client()
        client.session = mock_session

        result = client.get_historical_prices("SPY", days=2)
        assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
        assert result["symbol"] == "SPY"
        assert len(result["historical"]) == 2
        assert result["historical"][0]["close"] == 501.0

        # URL regression: must hit /historical-price-eod/full with from/to
        first_call = mock_session.get.call_args_list[0]
        url = first_call[0][0]
        params = first_call[1]["params"]
        assert "historical-price-eod/full" in url
        assert "from" in params and "to" in params
        assert "timeseries" not in params
