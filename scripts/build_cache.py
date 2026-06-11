#!/usr/bin/env python3
"""
Build companies_cache.json (secCode -> 銘柄名) from EDINET 書類一覧.
大量保有の対象企業は有価証券報告書を提出している上場会社なので、
過去数日分の全書類から secCode+filerName を収集して逆引きマップを作る。

Usage:
    python scripts/build_cache.py
    # EDINET_API_KEY が必要な場合は環境変数にセット
"""

import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
API = "https://api.edinet-fsa.go.jp/api/v2"
UA = {"User-Agent": "holdings-radar-cache-builder/1.0"}
CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "companies_cache.json")

_sub_key = os.environ.get("EDINET_API_KEY", "")

def params(**kw):
    if _sub_key:
        kw["Subscription-Key"] = _sub_key
    return kw


def get_docs_for_date(date_str):
    """Get all documents for a date"""
    r = requests.get(f"{API}/documents.json",
                     params=params(date=date_str, type=2),
                     headers=UA, timeout=60)
    r.raise_for_status()
    return r.json().get("results", [])


def main():
    # 上場企業の書類提出が多い過去 10 営業日分を取得
    cache_path = os.path.abspath(CACHE_FILE)
    company_map = {}

    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            company_map = json.load(f)
        print(f"Loaded existing cache: {len(company_map)} entries")

    now = datetime.now(JST)
    d = now.date()
    fetched = 0
    target_days = 10

    print(f"Fetching {target_days} business days to build company name map...")

    while fetched < target_days:
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        date_str = d.strftime("%Y-%m-%d")
        try:
            docs = get_docs_for_date(date_str)
            for doc in docs:
                sec = (doc.get("secCode") or "").rstrip("0")
                name = (doc.get("filerName") or "").strip()
                # 有報・半期報などの提出者が発行会社 = 上場企業
                if sec and name and doc.get("docTypeCode") in {"120", "130", "140", "150", "160", "170"}:
                    company_map[sec] = name
            print(f"  {date_str}: {len(docs)} docs, map size now {len(company_map)}")
        except Exception as e:
            print(f"  {date_str}: ERROR {e}")

        fetched += 1
        d -= timedelta(days=1)
        time.sleep(1)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(company_map, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"\nSaved {len(company_map)} companies to {cache_path}")


if __name__ == "__main__":
    main()
