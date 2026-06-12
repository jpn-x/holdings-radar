"""XBRLの中身を確認して何が8001を返しているか調べる"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch import xbrl_parse, _ixval
import zipfile, requests, io

API_KEY = os.environ.get("EDINET_API_KEY", "")
doc_id = "S100Y02Z"  # 2026-06-11 スカパーJSAT, filer=伊藤忠商事

url = f"https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}?type=1&Subscription-Key={API_KEY}"
resp = requests.get(url, timeout=30)
print(f"status: {resp.status_code}")
zf = zipfile.ZipFile(io.BytesIO(resp.content))
names = zf.namelist()
htm_files = [n for n in names if n.endswith(".htm")]
honbun = next((n for n in htm_files if "honbun" in n), None) or (htm_files[0] if htm_files else None)
print(f"honbun: {honbun}")
txt = zf.read(honbun).decode("utf-8", errors="ignore")

# 8001が含まれる行を探す
for i, line in enumerate(txt.splitlines()):
    if "8001" in line:
        print(f"LINE {i}: {line[:200]}")

print("\n--- SecurityCodeOfIssuer ---")
print(_ixval(txt, "SecurityCodeOfIssuer"))
print("--- IssuedCompanySecuritiesCode ---")
print(_ixval(txt, "IssuedCompanySecuritiesCode"))
print("--- SecuritiesCode ---")
print(_ixval(txt, "SecuritiesCode"))
