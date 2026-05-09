"""stable/historical-price-eod/full normalization for earnings-trade-analyzer.

get_historical_prices() returns the standard dict contract:
{"symbol": "SPY", "historical": [...]}
Callers must extract ["historical"] themselves.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fmp_client import FMPClient


def _make_client():
    client = FMPClient(api_key="test_key", max_api_calls=200)
    client.max_retries = 0
    return client


def _mock_response(status_code, json_payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload
    resp.text = ""
    return resp


class TestEODFlatListSuccess:
    @patch("fmp_base.requests.Session")
    def test_get_historical_prices_returns_dict(self, mock_session_class):
        """Flat list response from stable endpoint -> normalised to standard dict."""
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

        result = client.get_historical_prices("SPY", days=2)
        assert isinstance(result, dict), (
            f"expected dict, got {type(result).__name__}"
        )
        rows = result["historical"]
        assert len(rows) == 2
        assert rows[0]["date"] == "2026-04-29"
        assert rows[0]["close"] == 501.0
        assert "symbol" not in rows[0], "row-level symbol should be stripped"

        # URL regression
        first_call = mock_session.get.call_args_list[0]
        url = first_call[0][0]
        params = first_call[1]["params"]
        assert "historical-price-eod/full" in url
        assert "from" in params and "to" in params
        assert "timeseries" not in params
