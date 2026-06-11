#!/usr/bin/env python3
"""
Diagnose: show all docTypeCodes and sample descriptions for today's EDINET data.
Run: python scripts/diagnose.py
"""
import requests, os
from collections import defaultdict

API = "https://api.edinet-fsa.go.jp/api/v2"
UA = {"User-Agent": "holdings-radar-diag/1.0"}
KEY = os.environ.get("EDINET_API_KEY", "")

def p(**kw):
    if KEY: kw["Subscription-Key"] = KEY
    return kw

date = input("日付 (YYYY-MM-DD, Enterで今日): ").strip() or __import__('datetime').date.today().strftime("%Y-%m-%d")

r = requests.get(f"{API}/documents.json", params=p(date=date, type=2), headers=UA, timeout=60)
docs = r.json().get("results", [])
print(f"\n{date}: {len(docs)} 件\n")

by_code = defaultdict(list)
for d in docs:
    by_code[d.get("docTypeCode","")].append(d)

for code in sorted(by_code):
    samples = by_code[code]
    print(f"[{code}] {len(samples)}件")
    for d in samples[:2]:
        filer = d.get("filerName","")[:25]
        desc  = d.get("docDescription","")[:50]
        sec   = d.get("secCode","")
        print(f"  filer={filer}  sec={sec}  desc={desc}")
    print()
