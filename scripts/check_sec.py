import json, glob

print("=== sec=8001 entries with docId ===")
for f in sorted(glob.glob("data/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    for e in d.get("new", []) + d.get("chg", []):
        if e.get("sec") == "8001":
            print(f"{d['date']} | docId={e.get('docId','')} | name={e.get('name','')} | filer={e.get('filer','')[:25]}")
