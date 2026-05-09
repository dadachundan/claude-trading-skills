import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from fmp_base import ApiCallBudgetExceeded, FMPClient  # noqa: F401, E402
