"""
同一保有者で複数の異なる銘柄が全部同じsecコードになっているケースを検出する。
= 保有者自身のコードが誤入力されているケース
"""
import json, glob, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")

# filer -> {sec -> [names]}
filer_sec_names = defaultdict(lambda: defaultdict(set))
# docId -> entry (for repair reference)
docid_entry = {}
docid_date = {}

for f in sorted(glob.glob("data/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    date = d["date"]
    for e in d.get("new", []) + d.get("chg", []):
        sec = e.get("sec", "")
        filer = e.get("filer", "")
        name = e.get("name", "")
        did = e.get("docId", "")
        if sec and filer:
            filer_sec_names[filer][sec].add(name)
        docid_entry[did] = e
        docid_date[did] = date

print("=== 同一保有者で同じsecが複数の異なる銘柄に使われているケース ===")
suspicious_filers = {}
for filer, sec_map in filer_sec_names.items():
    for sec, names in sec_map.items():
        if len(names) >= 2:  # 同じsecで2つ以上の異なる銘柄名
            suspicious_filers[filer] = (sec, names)
            print(f"\n保有者: {filer}")
            print(f"  sec={sec} で {len(names)} 銘柄: {list(names)[:5]}")

print(f"\n=== 疑わしい保有者: {len(suspicious_filers)} 件 ===")
