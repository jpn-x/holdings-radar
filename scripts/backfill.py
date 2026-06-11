#!/usr/bin/env python3
"""
Backfill historical large-holding data from EDINET.
Usage: python scripts/backfill.py [--from 2026-01-01] [--to 2026-06-11]
Already-saved dates are skipped automatically.
"""
import sys, os, time, argparse
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date, timedelta
from fetch import (
    get_docs, build_entry, xbrl_parse, load_companies,
    save_day, load_all_days, generate_html, DATA_DIR,
    _params, UA, API
)
import json, requests
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)

def already_saved(d: str) -> bool:
    return os.path.exists(os.path.join(DATA_DIR, f"{d}.json"))

def fetch_day(date_str, companies):
    docs = get_docs(date_str)
    if not docs:
        print(f"  {date_str}: 0件 (休日 or データなし) → スキップ")
        return None, None

    new_entries, chg_entries = [], []
    for i, doc in enumerate(docs):
        e = build_entry(doc, companies)
        if not e["sec"] or not e["name"] or e["ratio"] is None or e.get("prev_ratio") is None:
            xratio, xname, xcode, xprev = xbrl_parse(e["docId"])
            if not e["sec"] and xcode:   e["sec"] = xcode
            if not e["name"] and xname:  e["name"] = xname
            if e["ratio"] is None and xratio: e["ratio"] = xratio
            if e.get("prev_ratio") is None and xprev is not None: e["prev_ratio"] = xprev
            time.sleep(0.3)

        if e["isNew"]:
            new_entries.append(e)
        else:
            chg_entries.append(e)

    print(f"  {date_str}: 新規{len(new_entries)}件 変更{len(chg_entries)}件")
    return new_entries, chg_entries

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2026-01-05")
    ap.add_argument("--to",   dest="end",   default=date.today().strftime("%Y-%m-%d"))
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    all_days = list(weekdays(start, end))

    print(f"Backfill {args.start} → {args.end} ({len(all_days)} 平日)")
    print("Loading company master...")
    companies = load_companies()

    done = 0
    for d in all_days:
        ds = d.isoformat()
        if already_saved(ds):
            print(f"  {ds}: 既存 → スキップ")
            continue
        try:
            new_e, chg_e = fetch_day(ds, companies)
            if new_e is not None:
                save_day(ds, new_e, chg_e)
                done += 1
        except Exception as ex:
            print(f"  {ds}: ERROR {ex}")
        time.sleep(0.5)

    # 全日分で index.html を再生成
    print("\nindex.html を再生成中...")
    days = load_all_days()
    updated = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")
    out = os.path.join(os.path.dirname(__file__), "..", "index.html")
    html = generate_html(days, updated)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Done: {done} 日取得, 合計 {len(days)} 日分 → index.html 更新")

if __name__ == "__main__":
    main()
