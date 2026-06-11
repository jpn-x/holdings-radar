"""
sec="" のエントリのXBRLを再取得して正しいコードを埋める。
GitHub Actions から実行: python scripts/fix_missing_codes.py
"""
import os, sys, json, glob, time
sys.path.insert(0, os.path.dirname(__file__))
from fetch import xbrl_parse

fixed = 0
files_changed = 0

for f in sorted(glob.glob("data/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    modified = False

    for e in d.get("new", []) + d.get("chg", []):
        if e.get("sec", "") == "" and e.get("docId"):
            doc_id = e["docId"]
            print(f"  Re-fetching {doc_id} ({d['date']}) {e.get('name','')[:20]}")
            _, _, xcode, _ = xbrl_parse(doc_id)
            if xcode:
                e["sec"] = xcode
                print(f"    -> {xcode}")
                fixed += 1
                modified = True
            else:
                print(f"    -> (not found)")
            time.sleep(0.3)

    if modified:
        files_changed += 1
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(d, fp, ensure_ascii=False, indent=2)

print(f"\n計 {fixed} 件修正（{files_changed} ファイル更新）")

# HTML再生成
if fixed > 0:
    import subprocess
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "fetch.py"), "--regen-only"])
