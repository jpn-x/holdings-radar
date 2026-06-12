import json, sys
sys.stdout.reconfigure(encoding="utf-8")
targets = [
    ("data/2026-01-05.json", "S100XE25"),
    ("data/2026-04-14.json", "S100XYM0"),
    ("data/2026-04-16.json", "S100XZEU"),
    ("data/2026-05-11.json", "S100Y2VO"),
]
for f, did in targets:
    d = json.load(open(f, encoding="utf-8"))
    for e in d.get("new", []) + d.get("chg", []):
        if e.get("docId") == did:
            print(f"{f}: name={e['name']} | filer={e['filer']} | ratio={e['ratio']}")
