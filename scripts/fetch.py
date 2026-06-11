#!/usr/bin/env python3
"""EDINET 大量保有報告書 fetcher → index.html generator"""

import requests
import re
import time
import os
import json
import zipfile
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
API = "https://api.edinet-fsa.go.jp/api/v2"

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "companies_cache.json")

_sub_key = os.environ.get("EDINET_API_KEY", "")

def _params(**kw):
    """Merge Subscription-Key into params dict"""
    if _sub_key:
        kw["Subscription-Key"] = _sub_key
    return kw

UA = {"User-Agent": "holdings-radar/1.0 (https://github.com/jpn-x/holdings-radar)"}

NEW_TYPES = {"28", "29"}   # 大量保有報告書
CHG_TYPES = {"30", "31"}   # 変更報告書
ALL_TYPES = NEW_TYPES | CHG_TYPES


def get_date():
    now = datetime.now(JST)
    d = now.date()
    if now.hour < 7:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def api_get(path, **kwargs):
    r = requests.get(f"{API}/{path}", params=_params(**kwargs), headers=UA, timeout=60)
    r.raise_for_status()
    return r.json()


def load_companies():
    """
    Build secCode(4桁) → company name map from local cache.
    Cache is built by running: python scripts/build_cache.py
    (EDINET API に company list エンドポイントは存在しないため手動ビルド)
    """
    cache_path = os.path.abspath(CACHE_FILE)
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            m = json.load(f)
        print(f"  company cache: {len(m)} entries")
        return m
    print("  companies_cache.json not found. Showing secCode only.")
    print("  Tip: Run 'python scripts/build_cache.py' to generate it.")
    return {}


def get_docs(date):
    data = api_get("documents.json", date=date, type=2)
    all_results = data.get("results", [])
    # Debug: show docTypeCode distribution
    from collections import Counter
    code_counts = Counter(d.get("docTypeCode") for d in all_results)
    print(f"  Total docs: {len(all_results)}, types: {dict(sorted(code_counts.items()))}")
    filtered = [d for d in all_results if d.get("docTypeCode") in ALL_TYPES]
    return filtered


def parse_desc(desc):
    """
    Extract ratio% and direction from docDescription.
    e.g. '大量保有報告書（保有割合　13.74%）'
         '変更報告書（保有割合　10.60%）（増加）'
    """
    ratio = None
    direction = None
    if not desc:
        return ratio, direction
    m = re.search(r'(\d{1,3}\.?\d*)\s*%', desc)
    if m:
        val = float(m.group(1))
        if 0 < val <= 100:
            ratio = val
    if "増加" in desc:
        direction = "増加"
    elif "減少" in desc:
        direction = "減少"
    return ratio, direction


def xbrl_ratio(doc_id):
    """Download document zip and extract holding ratio from XBRL"""
    try:
        r = requests.get(f"{API}/documents/{doc_id}",
                         params=_params(type=1), headers=UA, timeout=60, stream=True)
        r.raise_for_status()
        raw = b"".join(r.iter_content(65536))
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if not name.lower().endswith((".xbrl", ".xml")):
                    continue
                txt = zf.read(name).decode("utf-8", errors="ignore")
                for pat in [
                    r'[Hh]olding[Rr]atio[^>]*>(\d{1,3}\.?\d+)<',
                    r'HoldingRatioOfVotingRights[^>]*>(\d{1,3}\.?\d+)<',
                    r'>(\d{1,3}\.\d{1,2})</[a-zA-Z_:]*[Rr]atio[a-zA-Z_]*>',
                ]:
                    m = re.search(pat, txt)
                    if m:
                        val = float(m.group(1))
                        if 0 < val <= 100:
                            return val
    except Exception as e:
        print(f"    xbrl fail {doc_id}: {e}")
    return None


def build_entry(doc, companies):
    dt = doc.get("docTypeCode", "")
    sec = (doc.get("secCode") or "").rstrip("0")
    filer = doc.get("filerName", "")
    desc = doc.get("docDescription", "")
    company_name = companies.get(sec, "")
    ratio, direction = parse_desc(desc)
    is_new = dt in NEW_TYPES
    return {
        "docId": doc.get("docID", ""),
        "sec": sec,
        "name": company_name,
        "filer": filer,
        "ratio": ratio,
        "direction": direction or ("新規" if is_new else "変更"),
        "isNew": is_new,
    }


# ─── HTML ──────────────────────────────────────────────────────────────────────

def badge(direction):
    if direction == "新規":
        return '<span class="badge badge-new">新規</span>'
    elif direction == "増加":
        return '<span class="badge badge-up">▲ 増加</span>'
    elif direction == "減少":
        return '<span class="badge badge-dn">▼ 減少</span>'
    else:
        return '<span class="badge badge-chg">変更</span>'


def make_row(e):
    ratio_str = f"{e['ratio']:.2f}%" if e["ratio"] is not None else "—"
    pdf_url = f"https://api.edinet-fsa.go.jp/api/v2/documents/{e['docId']}?type=2"
    if e["sec"]:
        code_cell = f'<a href="https://finance.yahoo.co.jp/quote/{e["sec"]}.T" target="_blank">{e["sec"]}</a>'
    else:
        code_cell = "—"
    return (
        f'<tr>'
        f'<td>{badge(e["direction"])}</td>'
        f'<td class="code">{code_cell}</td>'
        f'<td class="company">{e["name"] or "—"}</td>'
        f'<td class="filer">{e["filer"] or "—"}</td>'
        f'<td class="ratio">{ratio_str}</td>'
        f'<td><a href="{pdf_url}" target="_blank" class="btn-pdf">PDF</a></td>'
        f'</tr>'
    )


def generate_html(new_entries, chg_entries, date):
    empty = '<tr><td colspan="6" class="empty">本日の提出書類はありません</td></tr>'
    new_rows = "".join(make_row(e) for e in new_entries) or empty
    chg_rows = "".join(make_row(e) for e in chg_entries) or empty
    updated = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>大量保有 Radar — {date}</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>
:root{{
  --bg:#0d0f14;--surf:#161a23;--border:#252a35;
  --text:#e8ecf4;--muted:#8892a4;
  --gold:#f5c842;--green:#3ddc84;--red:#ff5c5c;--blue:#4fa8ff;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Hiragino Sans','Noto Sans JP',sans-serif;font-size:14px;min-height:100vh}}
header{{background:var(--surf);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.logo{{width:32px;height:32px;flex-shrink:0}}
h1{{font-size:18px;font-weight:700;color:var(--gold);letter-spacing:.05em}}
.meta{{margin-left:auto;font-size:12px;color:var(--muted)}}
.meta a{{color:var(--muted);text-decoration:none}}
.meta a:hover{{color:var(--gold)}}
main{{padding:20px 24px;max-width:1280px;margin:0 auto}}
.sec-head{{display:flex;align-items:center;gap:8px;margin:28px 0 10px;font-size:15px;font-weight:700}}
.dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.dot-new{{background:var(--gold)}}
.dot-chg{{background:var(--blue)}}
.cnt{{font-size:12px;font-weight:normal;color:var(--muted)}}
.wrap{{overflow-x:auto;border-radius:10px;border:1px solid var(--border)}}
table{{width:100%;border-collapse:collapse}}
thead th{{background:#1c2130;padding:9px 14px;text-align:left;color:var(--muted);font-size:11px;font-weight:600;white-space:nowrap;border-bottom:1px solid var(--border)}}
tbody tr{{border-bottom:1px solid var(--border)}}
tbody tr:last-child{{border-bottom:none}}
tbody tr:hover{{background:rgba(255,255,255,.03)}}
td{{padding:10px 14px;vertical-align:middle}}
.badge{{display:inline-block;padding:3px 8px;border-radius:5px;font-size:11px;font-weight:700;white-space:nowrap}}
.badge-new{{background:rgba(245,200,66,.15);color:var(--gold);border:1px solid rgba(245,200,66,.3)}}
.badge-up{{background:rgba(61,220,132,.12);color:var(--green);border:1px solid rgba(61,220,132,.3)}}
.badge-dn{{background:rgba(255,92,92,.12);color:var(--red);border:1px solid rgba(255,92,92,.3)}}
.badge-chg{{background:rgba(79,168,255,.12);color:var(--blue);border:1px solid rgba(79,168,255,.3)}}
td.code{{font-weight:700;white-space:nowrap}}
td.code a{{color:var(--gold);text-decoration:none}}
td.code a:hover{{text-decoration:underline}}
td.company{{font-weight:600;max-width:200px}}
td.filer{{color:var(--muted);font-size:13px;max-width:300px}}
td.ratio{{font-weight:700;font-size:15px;text-align:right;white-space:nowrap;color:var(--text)}}
.btn-pdf{{display:inline-block;padding:3px 10px;border:1px solid var(--border);border-radius:5px;color:var(--muted);font-size:11px;text-decoration:none;transition:all .15s;white-space:nowrap}}
.btn-pdf:hover{{border-color:var(--gold);color:var(--gold)}}
.empty{{text-align:center;color:var(--muted);padding:24px;font-size:13px}}
footer{{text-align:center;padding:32px 16px;color:var(--muted);font-size:12px;line-height:2;margin-top:20px}}
footer a{{color:var(--muted);text-decoration:none}}
footer a:hover{{color:var(--gold)}}
@media(max-width:680px){{
  td.filer{{display:none}}
  main{{padding:12px}}
  td,th{{padding:8px 10px}}
  h1{{font-size:16px}}
}}
</style>
</head>
<body>
<header>
  <img src="favicon.svg" class="logo" alt="">
  <h1>大量保有 Radar</h1>
  <div class="meta">更新: {updated} JST &nbsp;｜&nbsp; データ: <a href="https://disclosure.edinet.go.jp/" target="_blank">EDINET</a></div>
</header>
<main>

<div class="sec-head">
  <span class="dot dot-new"></span>
  大量保有報告書（新規）
  <span class="cnt">{len(new_entries)} 件</span>
</div>
<div class="wrap">
  <table>
    <thead><tr>
      <th>区分</th><th>コード</th><th>銘柄名</th>
      <th>保有者</th><th style="text-align:right">保有割合</th><th></th>
    </tr></thead>
    <tbody>{new_rows}</tbody>
  </table>
</div>

<div class="sec-head">
  <span class="dot dot-chg"></span>
  変更報告書
  <span class="cnt">{len(chg_entries)} 件</span>
</div>
<div class="wrap">
  <table>
    <thead><tr>
      <th>区分</th><th>コード</th><th>銘柄名</th>
      <th>保有者</th><th style="text-align:right">保有割合</th><th></th>
    </tr></thead>
    <tbody>{chg_rows}</tbody>
  </table>
</div>

</main>
<footer>
  大量保有 Radar — EDINET 大量保有報告書・変更報告書 毎日自動集計<br>
  データ取得元: <a href="https://disclosure.edinet.go.jp/" target="_blank">EDINET（金融庁 電子開示システム）</a><br>
  当サイトは情報提供のみを目的としています。投資判断は自己責任でお願いします。
</footer>
</body>
</html>"""


# ─── main ──────────────────────────────────────────────────────────────────────

def main():
    date = os.environ.get("TARGET_DATE") or get_date()
    print(f"[holdings-radar] date={date}")

    print("Loading company master...")
    companies = load_companies()

    print(f"Fetching large-holding docs for {date}...")
    docs = get_docs(date)
    print(f"  {len(docs)} docs found")

    new_entries, chg_entries = [], []

    for i, doc in enumerate(docs):
        e = build_entry(doc, companies)

        if e["ratio"] is None:
            print(f"  [{i+1}/{len(docs)}] ratio missing → fetching XBRL {e['docId']}")
            e["ratio"] = xbrl_ratio(e["docId"])
            time.sleep(0.5)

        tag = "NEW" if e["isNew"] else "CHG"
        ratio_disp = f"{e['ratio']:.2f}%" if e["ratio"] else "N/A"
        print(f"  [{i+1}/{len(docs)}] [{tag}] {e['sec']:6} {(e['name'] or '?')[:18]:18} | {e['filer'][:22]:22} | {ratio_disp}")

        if e["isNew"]:
            new_entries.append(e)
        else:
            chg_entries.append(e)

    # index.html はリポジトリルートに生成
    out = os.path.join(os.path.dirname(__file__), "..", "index.html")
    html = generate_html(new_entries, chg_entries, date)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Done - index.html generated ({len(new_entries)} new, {len(chg_entries)} changes)")


if __name__ == "__main__":
    main()
