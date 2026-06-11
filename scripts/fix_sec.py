#!/usr/bin/env python3
"""
既存の data/*.json の sec フィールドを修正する。

EDINETの secCode が保有者（holder）のコードを返すバグの影響で、
上場している保有者が提出した報告書のエントリで sec が保有者コード
（例: 伊藤忠=8001）になっているものを検出し、XBRLから正しい発行会社
コードに書き直す。

検出方法: 同じ sec に複数の異なる銘柄名 → 保有者コードと判断
"""
import json, os, time, sys
sys.path.insert(0, os.path.dirname(__file__))
from collections import defaultdict
from fetch import xbrl_parse, load_all_days, generate_html, DATA_DIR
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def main():
    print("Loading all data files...")
    all_files = sorted(
        f for f in os.listdir(DATA_DIR) if f.endswith(".json")
    )

    # 全エントリを読み込み、sec → {name} のマップを作る
    sec_names: dict[str, set] = defaultdict(set)
    all_data: dict[str, dict] = {}  # filename -> parsed json

    for fname in all_files:
        path = os.path.join(DATA_DIR, fname)
        data = json.loads(open(path, encoding="utf-8").read())
        all_data[fname] = data
        for e in data.get("new", []) + data.get("chg", []):
            if e["sec"] and e["name"]:
                sec_names[e["sec"]].add(e["name"])

    # 同一 sec で複数の銘柄名 → 保有者コードが誤って入っている
    bad_secs = {sec for sec, names in sec_names.items() if len(names) > 1}
    print(f"Bad secs detected ({len(bad_secs)}): {sorted(bad_secs)}")

    if not bad_secs:
        print("No bad secs found. Data looks correct.")
        return

    # bad_secs に該当するエントリを全て収集
    to_fix: list[tuple[str, dict]] = []  # (filename, entry_ref)
    for fname, data in all_data.items():
        for e in data.get("new", []) + data.get("chg", []):
            if e["sec"] in bad_secs:
                to_fix.append((fname, e))

    print(f"Entries to fix: {len(to_fix)}")
    fixed = 0
    errors = 0

    for i, (fname, e) in enumerate(to_fix):
        print(f"  [{i+1}/{len(to_fix)}] docId={e['docId']} sec={e['sec']:6} name={e['name'][:18]}")
        _, xname, xcode, _ = xbrl_parse(e["docId"])
        if xcode and xcode != e["sec"]:
            print(f"    → sec: {e['sec']} → {xcode}  name: {e['name'][:15]} → {(xname or e['name'])[:15]}")
            e["sec"] = xcode
            if xname:
                e["name"] = xname
            fixed += 1
        elif not xcode:
            print(f"    → XBRL code not found, keeping as-is")
            errors += 1
        else:
            print(f"    → already correct ({xcode})")
        time.sleep(0.3)

    # 変更された JSON を上書き保存
    print(f"\nSaving {len(all_data)} files...")
    for fname, data in all_data.items():
        path = os.path.join(DATA_DIR, fname)
        open(path, "w", encoding="utf-8").write(
            json.dumps(data, ensure_ascii=False, indent=2)
        )

    # index.html を再生成
    print("Regenerating index.html...")
    days = load_all_days()
    updated = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")
    out = os.path.join(os.path.dirname(__file__), "..", "index.html")
    open(out, "w", encoding="utf-8").write(generate_html(days, updated))

    print(f"\nDone: {fixed} entries fixed, {errors} XBRL errors, index.html regenerated.")


if __name__ == "__main__":
    main()
