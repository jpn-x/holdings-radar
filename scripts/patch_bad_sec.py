"""
sec=8001（伊藤忠商事コード）が誤って入ったエントリを修正する。
- 正しいコードがわかるものは修正
- わからないものは sec="" にして "—" 表示にする
"""
import json, glob, os

# docId -> 正しいコード（確認済み）
CORRECT = {
    # スカパーJSATホールディングス: 9412（同日の別エントリから確認）
    "S100Y02Z": "9412",
    # サンフロンティア不動産: 8934（ユーザー確認済み）
    "S100XXR3": "8934",
    "S100XZBI": "8934",
    "S100XZMH": "8934",
    "S100XE25": "8410",  # 2026-01-05 セブン銀行
    "S100XYM0": "6345",  # 2026-04-14 アイチコーポレーション
    "S100XZEU": "2593",  # 2026-04-16 伊藤忠食品
    "S100Y2VO": "2593",  # 2026-05-11 伊藤忠食品
}

changed = 0
for f in sorted(glob.glob("data/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    modified = False
    for e in d.get("new", []) + d.get("chg", []):
        doc_id = e.get("docId", "")
        if doc_id in CORRECT and e.get("sec") in ("8001", ""):
            old = e["sec"]
            e["sec"] = CORRECT[doc_id]
            print(f"  {d['date']} | {doc_id} | {old} -> {e['sec'] or '(empty)'} | {e.get('name','')}")
            modified = True
            changed += 1
    if modified:
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(d, fp, ensure_ascii=False, indent=2)

print(f"\n計 {changed} 件修正")
