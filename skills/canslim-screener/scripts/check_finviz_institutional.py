#!/usr/bin/env python3
"""
Test Finviz institutional ownership fallback for one or more symbols.

Usage:
    python3 check_finviz_institutional.py
    python3 check_finviz_institutional.py --symbols AAPL MSFT NVDA
"""

import argparse
import sys
from finviz_stock_client import FinvizStockClient

DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA"]


def check(symbols: list[str]) -> None:
    client = FinvizStockClient(rate_limit_seconds=1.0)

    for symbol in symbols:
        print(f"\n{symbol}")
        print("-" * 40)
        try:
            data = client.get_institutional_ownership(symbol)
            if not data:
                print("  No data returned")
                continue
            pct = data.get("inst_own_pct")
            if pct is not None:
                print(f"  ✅ inst_own_pct : {pct:.1f}%")
            else:
                print("  ⚠️  inst_own_pct : None")
            for k, v in data.items():
                if k != "inst_own_pct":
                    print(f"     {k}: {v}")
        except Exception as e:
            print(f"  ❌ ERROR: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Finviz institutional ownership fallback")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    args = parser.parse_args()

    check(args.symbols)
