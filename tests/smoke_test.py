"""
tests/smoke_test.py — live end-to-end check (NOT part of the pytest suite).

Sends one real request to a running API and prints the ranked results.
Because it needs a live server, all work happens inside main() so that
pytest (which collects this file via the ``*_test.py`` pattern) never
performs network I/O at import time.

Usage:
    python tests/smoke_test.py
    MACROMATCH_API_URL=https://your-api.onrender.com python tests/smoke_test.py
"""

import os
import sys

import requests

DEFAULT_BASE = "http://127.0.0.1:8000"


def main() -> int:
    base = os.environ.get("MACROMATCH_API_URL", DEFAULT_BASE).rstrip("/")
    print(f"POST {base}/suggest-alternative")

    try:
        resp = requests.post(
            f"{base}/suggest-alternative",
            json={
                "product": "Paneer",
                "city": "Bangalore",
                "diet_rules": ["vegan"],
                "allergens": ["dairy"],
                "priority": "protein",
            },
            timeout=90,  # free-tier hosts may need ~1 min to wake up
        )
    except requests.exceptions.RequestException as exc:
        print(f"FAILED: could not reach {base}\n  {type(exc).__name__}: {exc}")
        print("Is the API running?  uvicorn backend.main:app --reload")
        return 1

    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(resp.text)
        return 1

    data = resp.json()
    for alt in data.get("alternatives", []):
        print(f"\nRank {alt['rank']}: {alt['name']} (match_score={alt['match_score']})")
        print(f"  Explanation: {alt['explanation'][:150]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
