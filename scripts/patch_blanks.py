"""
sec が空欄のエントリ（分割型XBRLの解析漏れ）を修正版parserで再解析して埋める。
1エントリずつXBRL再取得するので全日再取得より速い。日ごとに保存（中断可）。
"""
import sys, os, json, glob, time
sys.path.insert(0, os.path.dirname(__file__))
from fetch import xbrl_parse, load_all_days, generate_html, DATA_DIR
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

files = sorted(glob.glob(os.path.join(DATA_DIR, "2???-??-??.json")))
total_fixed = 0
for path in files:
    with open(path, encoding="utf-8") as f:
        day = json.load(f)
    changed = False
    for e in day.get("new", []) + day.get("chg", []):
        if e.get("sec"):
            continue
        xr, xn, xc, xp = xbrl_parse(e["docId"])
        if xc:
            e["sec"] = xc
        if xn and not e.get("name"):
            e["name"] = xn
        if xr is not None and e.get("ratio") is None:
            e["ratio"] = xr
        if xp is not None and e.get("prev_ratio") is None:
            e["prev_ratio"] = xp
        if xc or xn or xr is not None:
            changed = True
            total_fixed += 1
        time.sleep(0.25)
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(day, f, ensure_ascii=False, indent=2)
        print(f"{os.path.basename(path)}: 修正あり (累計 {total_fixed})")

# index.html 再生成
days = load_all_days()
html = generate_html(days, datetime.now(JST).strftime("%Y年%m月%d日 %H:%M JST"))
with open(os.path.join(os.path.dirname(__file__), "..", "index.html"), "w", encoding="utf-8") as f:
    f.write(html)
print(f"\n完了: {total_fixed}件修正 → index.html再生成")
