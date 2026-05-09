"""7-way parameterized contract test for FMP client `get_historical_prices`.

Issue #64 truncate contract: every skill-local copy of `fmp_client.py` must
respect `days=N` (truncate to at most N rows, most-recent-first).

All skill fmp_client.py files are now thin shims re-exporting from shared/fmp_base.py.
The patch target is `fmp_base.requests.Session` (where the HTTP call lives).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Ensure shared/ is importable so fmp_base can be referenced directly.
_shared_dir = str(REPO_ROOT / "shared")
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

FMP_CLIENT_FILES = [
    "skills/canslim-screener/scripts/fmp_client.py",
    "skills/earnings-trade-analyzer/scripts/fmp_client.py",
    "skills/ftd-detector/scripts/fmp_client.py",
    "skills/macro-regime-detector/scripts/fmp_client.py",
    "skills/market-top-detector/scripts/fmp_client.py",
    "skills/pead-screener/scripts/fmp_client.py",
    "skills/vcp-screener/scripts/fmp_client.py",
    "skills/ibd-distribution-day-monitor/scripts/fmp_client.py",
]


def _load_fmp_module(rel_path: str):
    abs_path = REPO_ROOT / rel_path
    if not abs_path.exists():
        pytest.skip(f"{rel_path} not present")
    skill_name = abs_path.parent.parent.name.replace("-", "_")
    module_name = f"_fmp_client_truncate_test_{skill_name}"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, str(abs_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _build_mock_response(rows: int):
    payload = [
        {
            "symbol": "SPY",
            "date": f"2026-04-{30 - i:02d}",
            "open": 500.0,
            "high": 502.0,
            "low": 499.0,
            "close": 500.0 + i,
            "adjClose": 500.0 + i,
            "volume": 1_000_000 + i,
        }
        for i in range(rows)
    ]
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.text = ""
    return response


@pytest.mark.parametrize("client_path", FMP_CLIENT_FILES)
def test_get_historical_prices_truncates_to_days(client_path, monkeypatch):
    """Every fmp_client copy must truncate `historical` to `days=N` rows, most-recent-first."""
    monkeypatch.setenv("FMP_API_KEY", "test_key")
    module = _load_fmp_module(client_path)

    import fmp_base

    mock_response = _build_mock_response(5)
    with patch.object(fmp_base.requests.Session, "get", return_value=mock_response):
        client = module.FMPClient(api_key="test_key")
        # Disable retries to keep the test fast.
        if hasattr(client, "max_retries"):
            client.max_retries = 0
        result = client.get_historical_prices("SPY", days=2)

    assert result is not None, f"{client_path}: get_historical_prices returned None"

    # `earnings-trade-analyzer` may return Optional[list[dict]] directly,
    # while others return Optional[dict] with a "historical" key.
    if isinstance(result, list):
        historical = result
    else:
        historical = result.get("historical", [])

    assert len(historical) == 2, (
        f"{client_path}: expected truncation to 2 rows, got {len(historical)}"
    )

    # Most-recent-first ordering preserved.
    assert historical[0].get("date") == "2026-04-30", (
        f"{client_path}: row[0] date = {historical[0].get('date')}, expected 2026-04-30"
    )
    assert historical[1].get("date") == "2026-04-29", (
        f"{client_path}: row[1] date = {historical[1].get('date')}, expected 2026-04-29"
    )
