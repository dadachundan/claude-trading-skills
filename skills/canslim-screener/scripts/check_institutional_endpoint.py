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

# (url, params) pairs — vary both path and param name
CANDIDATES = [
    # stable — symbol as query param
    (f"{BASE}/stable/institutional-ownership/institutional-holders-by-company", {"symbol": None}),
    (f"{BASE}/stable/institutional-holder",                                     {"symbol": None}),
    (f"{BASE}/stable/institutional-ownership",                                  {"symbol": None}),
    (f"{BASE}/stable/institutional-ownership/symbol-ownership",                 {"symbol": None}),
    (f"{BASE}/stable/institutional-ownership/portfolio-holdings-summary",       {"symbol": None}),
    (f"{BASE}/stable/ownership/institutional-holders",                          {"symbol": None}),
    (f"{BASE}/stable/institutional-ownership/list",                             {"symbol": None}),
    # stable — ticker as query param (some endpoints use "ticker" not "symbol")
    (f"{BASE}/stable/institutional-ownership/institutional-holders-by-company", {"ticker": None}),
    (f"{BASE}/stable/institutional-holder",                                     {"ticker": None}),
]


def probe(url: str, params: dict, api_key: str) -> tuple[int, object]:
    try:
        r = requests.get(url, params=params, headers={"apikey": api_key}, timeout=10)
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
    seen = set()
    for url, param_template in CANDIDATES:
        params = {k: symbol for k, v in param_template.items()}
        key = (url, tuple(sorted(params.keys())))
        if key in seen:
            continue
        seen.add(key)
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        status, body = probe(url, params, api_key)
        if status == 200 and isinstance(body, list) and body:
            print(f"✅  {status}  {url}?{param_str}")
            print(f"     {len(body)} records  —  sample keys: {list(body[0].keys())[:6]}")
            if working_url is None:
                working_url = (url, list(params.keys())[0])
        elif status == 200:
            print(f"⚠️   {status}  {url}?{param_str}  (shape: {type(body).__name__}, body: {str(body)[:80]})")
        elif status == 404:
            print(f"❌  {status}  {url}?{param_str}  (path not found)")
        elif status == 429:
            print(f"⚠️   {status}  {url}?{param_str}  (endpoint exists — subscription upgrade required)")
        else:
            snippet = str(body)[:100] if body else ""
            print(f"❌  {status}  {url}?{param_str}  {snippet}")

    print()
    if working_url:
        url, param_key = working_url
        print(f"Working URL: {url}?{param_key}={{symbol}}")
        print(f"\nUpdate shared/fmp_base.py get_institutional_holders() to use this path.")
    else:
        print("No working endpoint found — institutional data unavailable on this subscription.")
    return working_url[0] if working_url else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe FMP institutional-holder stable endpoints")
    parser.add_argument("--symbol", default="AAPL", help="Symbol to test (default: AAPL)")
    args = parser.parse_args()

    result = check_institutional_endpoint(args.symbol)
    sys.exit(0 if result else 1)
