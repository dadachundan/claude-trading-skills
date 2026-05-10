#!/usr/bin/env python3
"""
Probe FMP stable institutional-ownership endpoints to find the working URL.
Run this after any FMP API migration to confirm which path is live.

Usage:
    python3 check_institutional_endpoint.py
    python3 check_institutional_endpoint.py --symbol MSFT
"""

import argparse
import os
import sys

import requests

BASE = "https://financialmodelingprep.com"

CANDIDATES = [
    f"{BASE}/stable/institutional-ownership/institutional-holders-by-company",
    f"{BASE}/stable/institutional-holder",
    f"{BASE}/stable/institutional-ownership",
]


def probe(url: str, symbol: str, api_key: str) -> tuple[int, object]:
    try:
        r = requests.get(url, params={"symbol": symbol}, headers={"apikey": api_key}, timeout=10)
        try:
            body = r.json()
        except Exception:
            body = r.text[:200]
        return r.status_code, body
    except requests.exceptions.RequestException as e:
        return -1, str(e)


def check_institutional_endpoint(symbol: str = "AAPL") -> str | None:
    """Probe candidate stable URLs and return the first working one, or None."""
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        print("ERROR: FMP_API_KEY environment variable not set")
        return None

    print(f"Probing institutional-holder stable endpoints for {symbol}...\n")

    working_url = None
    for url in CANDIDATES:
        status, body = probe(url, symbol, api_key)
        if status == 200 and isinstance(body, list) and body:
            print(f"✅  {status}  {url}")
            print(f"     {len(body)} records  —  sample keys: {list(body[0].keys())[:6]}")
            if working_url is None:
                working_url = url
        elif status == 200:
            print(f"⚠️   {status}  {url}  (empty or wrong shape: {type(body).__name__})")
        else:
            snippet = str(body)[:120] if body else ""
            print(f"❌  {status}  {url}  {snippet}")

    print()
    if working_url:
        print(f"Working URL: {working_url}")
        print(f"\nUpdate shared/fmp_base.py get_institutional_holders() to use this path.")
    else:
        print("No working endpoint found — institutional data unavailable on this subscription.")
    return working_url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe FMP institutional-holder stable endpoints")
    parser.add_argument("--symbol", default="AAPL", help="Symbol to test (default: AAPL)")
    args = parser.parse_args()

    result = check_institutional_endpoint(args.symbol)
    sys.exit(0 if result else 1)
