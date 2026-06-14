"""
全既存日を新フィルター（機関投資家特例を含む）で再取得し直す。
チェックポイント付き（中断→続きから再開）。
Usage: python scripts/refetch.py
"""
import sys, os, time, json, glob, re
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime
from zoneinfo import ZoneInfo
from backfill import fetch_day
from fetch import save_day, load_all_days, generate_html, load_companies, DATA_DIR

JST = ZoneInfo("Asia/Tokyo")
CKPT = os.path.join(DATA_DIR, ".refetch_done.json")


def main():
    # 対象＝既存の YYYY-MM-DD.json 全部（古い順）
    days = sorted(
        os.path.basename(f)[:10]
        for f in glob.glob(os.path.join(DATA_DIR, "2???-??-??.json"))
    )
    done = set()
    if os.path.exists(CKPT):
        with open(CKPT, encoding="utf-8") as f:
            done = set(json.load(f).get("done", []))
        print(f"チェックポイント: {len(done)}/{len(days)} 日は再取得済み → スキップ")

    companies = load_companies()
    todo = [d for d in days if d not in done]
    print(f"再取得対象: {len(todo)} 日")

    for i, ds in enumerate(todo):
        try:
            new_e, chg_e = fetch_day(ds, companies)
            if new_e is not None:
                save_day(ds, new_e, chg_e)
            done.add(ds)
        except Exception as ex:
            print(f"  {ds}: ERROR {ex}")
            time.sleep(2)
            continue
        # 5日ごとにチェックポイント保存
        if i % 5 == 0:
            with open(CKPT, "w", encoding="utf-8") as f:
                json.dump({"done": sorted(done)}, f)
        time.sleep(0.3)

    # チェックポイント最終保存
    with open(CKPT, "w", encoding="utf-8") as f:
        json.dump({"done": sorted(done)}, f)

    # index.html 再生成
    print("\nindex.html 再生成中...")
    all_days = load_all_days()
    updated = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M JST")
    out = os.path.join(os.path.dirname(__file__), "..", "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(generate_html(all_days, updated))

    if len(done) >= len(days):
        os.remove(CKPT)
        print(f"完走: {len(done)} 日 再取得完了")
    else:
        print(f"途中: {len(done)}/{len(days)} 日（再実行で続きから）")


if __name__ == "__main__":
    main()
