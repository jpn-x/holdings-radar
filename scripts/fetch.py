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
DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")

_sub_key = os.environ.get("EDINET_API_KEY", "")

def _params(**kw):
    """Merge Subscription-Key into params dict"""
    if _sub_key:
        kw["Subscription-Key"] = _sub_key
    return kw

UA = {"User-Agent": "holdings-radar/1.0 (https://github.com/jpn-x/holdings-radar)"}

# EDINET docTypeCode（3桁ゼロパディング）
# 340 = 大量保有報告書
# 341 = 大量保有報告書（特例対象株券等）
# 350 = 変更報告書（特例対象株券等）
# 変更報告書（非特例）は description で判定
# 360 = 訂正報告書（大量保有報告書・変更報告書）は除外
NEW_CODES = {"340", "341"}
CHG_CODES = {"350", "351"}

def is_target_doc(doc):
    """大量保有・変更報告書を判定。特例対象株券等（投信ETF用）は除外。"""
    code = doc.get("docTypeCode", "")
    desc = doc.get("docDescription") or ""
    # 訂正・特例は除外
    if "訂正" in desc:
        return False
    if "特例対象" in desc:
        return False
    if code in NEW_CODES or code in CHG_CODES:
        return True
    if "大量保有報告書" in desc or "変更報告書" in desc:
        return True
    return False

def doc_category(doc):
    """新規か変更かを判定"""
    code = doc.get("docTypeCode", "")
    desc = doc.get("docDescription") or ""
    if code in NEW_CODES or "大量保有報告書" in desc:
        return "new"
    return "change"


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
    filtered = [d for d in all_results if is_target_doc(d)]
    print(f"  Total: {len(all_results)} docs, large-holding: {len(filtered)}")
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


def _ixval(txt, elem_name):
    """Extract first value of an inline XBRL element by its taxonomy name attribute."""
    # <ix:nonNumeric name="ns:ElemName" ...>value</ix:nonNumeric>
    m = re.search(
        rf'<ix:non(?:Numeric|Fraction)[^>]+name="[^"]*:{re.escape(elem_name)}"[^>]*>\s*([^<]+?)\s*</ix:non',
        txt
    )
    return m.group(1).strip() if m else None


def xbrl_parse(doc_id):
    """Download XBRL zip and return (ratio_pct, issuer_name, issuer_code).

    Reads the inline XBRL (ixbrl.htm) first because it stores ratios already
    in % form (22.47) while the .xbrl stores decimals (0.2247).
    Supports both jplvh_cor (特例 schema) and jplh_cor (regular schema).
    """
    try:
        r = requests.get(f"{API}/documents/{doc_id}",
                         params=_params(type=1), headers=UA, timeout=60, stream=True)
        r.raise_for_status()
        raw = b"".join(r.iter_content(65536))
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            # Prefer honbun (本文) ixbrl.htm; fall back to any .htm then .xbrl
            htm_files = [n for n in names if n.endswith(".htm")]
            honbun = next((n for n in htm_files if "honbun" in n), None) or (htm_files[0] if htm_files else None)

            txt = zf.read(honbun).decode("utf-8", errors="ignore") if honbun else ""

            # 発行会社名
            issuer_name = (
                _ixval(txt, "NameOfIssuer") or            # jplvh_cor
                _ixval(txt, "IssuedCompanyName") or        # jplh_cor
                _ixval(txt, "NameOfIssuingCompany")
            )
            # 証券コード（4桁）
            issuer_code = (
                _ixval(txt, "SecurityCodeOfIssuer") or    # jplvh_cor (発行会社コード)
                _ixval(txt, "IssuedCompanySecuritiesCode") or
                _ixval(txt, "SecuritiesCodeOfIssuer")
                # ※ SecuritiesCode は除外: 保有者自身のコードを返す誤検知が多い
            )
            if issuer_code:
                issuer_code = issuer_code.strip()
                # 4桁数字 or グロース市場の英数混在コード（例: 436A）
                # 4桁数字 or 3桁数字+英字（グロース: 436A等） or 4桁数字+英字
                if not re.fullmatch(r'[0-9]{3,4}[A-Z]?', issuer_code):
                    issuer_code = None

            def _to_pct(raw):
                if not raw:
                    return None
                try:
                    v = float(raw.replace(",", ""))
                    v = v * 100 if v < 1.0 else v
                    return v if 0 < v <= 100 else None
                except ValueError:
                    return None

            ratio = _to_pct(
                _ixval(txt, "HoldingRatioOfShareCertificatesEtc") or
                _ixval(txt, "HoldingRatioOfVotingRights") or
                _ixval(txt, "HoldingRatio")
            )
            prev_ratio = _to_pct(
                _ixval(txt, "HoldingRatioOfShareCertificatesEtcPerLastReport") or
                _ixval(txt, "HoldingRatioOfVotingRightsPerLastReport") or
                _ixval(txt, "HoldingRatioPerLastReport")
            )

            return ratio, issuer_name, issuer_code, prev_ratio
    except Exception as e:
        print(f"    xbrl fail {doc_id}: {e}")
    return None, None, None, None


def build_entry(doc, companies):
    # doc.secCode = 提出者（保有者）のコード。発行会社のコードではないので使わない。
    # sec と name は XBRL パースで補完する。
    filer = doc.get("filerName") or ""
    desc = doc.get("docDescription") or ""
    ratio, direction = parse_desc(desc)
    is_new = doc_category(doc) == "new"
    return {
        "docId": doc.get("docID", ""),
        "sec": "",    # XBRL から補完
        "name": "",   # XBRL から補完
        "filer": filer,
        "ratio": ratio,
        "prev_ratio": None,
        "direction": direction or ("新規" if is_new else "変更"),
        "isNew": is_new,
    }


# ─── HTML ──────────────────────────────────────────────────────────────────────

def badge(e):
    direction = e["direction"]
    ratio = e["ratio"]
    prev = e.get("prev_ratio")
    if direction == "新規":
        return '<span class="badge badge-new">新規</span>'
    # 増減を計算（XBRLの前回比 or descriptionのdirection）
    if prev is not None and ratio is not None:
        diff = ratio - prev
        if abs(diff) >= 0.005:
            if diff > 0:
                return f'<span class="badge badge-up">▲ +{diff:.2f}%</span>'
            else:
                return f'<span class="badge badge-dn">▼ {diff:.2f}%</span>'
    if direction == "増加":
        return '<span class="badge badge-up">▲ 増加</span>'
    elif direction == "減少":
        return '<span class="badge badge-dn">▼ 減少</span>'
    return '<span class="badge badge-chg">変更</span>'


def make_row(e):
    ratio_str = f"{e['ratio']:.2f}%" if e["ratio"] is not None else "—"
    pdf_url = f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{e['docId']},,"
    if e["sec"]:
        code_cell = f'<a href="https://finance.yahoo.co.jp/quote/{e["sec"]}.T" target="_blank">{e["sec"]}</a>'
    else:
        code_cell = "—"
    return (
        f'<tr>'
        f'<td>{badge(e)}</td>'
        f'<td class="ratio">{ratio_str}</td>'
        f'<td><a href="{pdf_url}" target="_blank" class="btn-pdf">PDF</a></td>'
        f'<td class="code">{code_cell}</td>'
        f'<td class="company">{e["name"] or "—"}</td>'
        f'<td class="filer">{e["filer"] or "—"}</td>'
        f'</tr>'
        + warrant_row(e.get("sec") or "")
    )


def section_row(label, cnt, dot_cls):
    return (
        f'<tr class="section-row">'
        f'<td colspan="6">'
        f'<span class="dot {dot_cls}"></span>'
        f'{label}'
        f'<span class="cnt">{cnt} 件</span>'
        f'</td></tr>'
    )

def save_day(date, new_entries, chg_entries):
    """Save one day's entries to data/YYYY-MM-DD.json"""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": date, "new": new_entries, "chg": chg_entries}, f, ensure_ascii=False, indent=2)
    print(f"  Saved {path}")


def load_all_days():
    """Load all saved day JSONs, sorted newest first."""
    os.makedirs(DATA_DIR, exist_ok=True)
    days = []
    for fname in sorted(os.listdir(DATA_DIR), reverse=True):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", fname):
            with open(os.path.join(DATA_DIR, fname), encoding="utf-8") as f:
                days.append(json.load(f))
    return days


def load_warrants():
    """MSワラント行使ウォッチデータ (warrants.json) を読み込む"""
    path = os.path.join(DATA_DIR, "warrants.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("items", {})


# generate_html 時にセットされるグローバル（make_row から参照）
WARRANTS = {}


def warrant_row(sec):
    """銘柄コードに対応する💣行使ウォッチ行（なければ空文字）"""
    w = WARRANTS.get(sec)
    if not w:
        return ""
    kai = f"第{w['kai']}回" if w.get("kai") else ""
    parts = []
    if w.get("kofu") is not None:
        parts.append(f"交付: {w['kofu']:,}株")
    if w.get("exercised") is not None:
        total = f"/{w['total']:,}個" if w.get("total") else ""
        pct = f" ({w['exercised_pct']}%)" if w.get("exercised_pct") is not None else ""
        parts.append(f"行使済: {w['exercised']:,}個{total}{pct}")
    if w.get("unexercised") is not None:
        if w["unexercised"] == 0:
            parts.append('<span class="w-done">☑ 未行使0個・終了</span>')
        else:
            shares = f"（{w['unexercised_shares']:,}株）" if w.get("unexercised_shares") else ""
            parts.append(f"<b>未行使残: {w['unexercised']:,}個{shares}</b>")
            if w.get("unexercised_shares") and w.get("outstanding"):
                dil = w["unexercised_shares"] / w["outstanding"] * 100
                parts.append(f"希薄化 {dil:.1f}%")
    if parts:
        detail = " ｜ ".join(parts)
    elif "行使完了" in (w.get("title") or ""):
        # 行使完了報告＝定義上、未行使ゼロ（弾切れ・安全）
        detail = '<span class="w-done">☑ 行使完了・残ゼロ</span>'
    else:
        detail = '<span class="w-warn">⚠ 数値不明・PDF確認</span>'
    return (
        f'<tr class="warrant-row"><td colspan="6">'
        f'💣 <a href="{w["pdf"]}" target="_blank">{kai}新株予約権 行使状況 ({w["date"]})</a>'
        f'<span class="w-detail"> ｜ {detail}</span>'
        f'</td></tr>'
    )


def make_day_block(day):
    """Render one day's data as table rows with section headers."""
    new_entries = day.get("new", [])
    chg_entries = day.get("chg", [])
    empty_new = '<tr><td colspan="6" class="empty">新規報告なし</td></tr>'
    empty_chg = '<tr><td colspan="6" class="empty">変更報告なし</td></tr>'
    new_rows = "".join(make_row(e) for e in new_entries) or empty_new
    chg_rows = "".join(make_row(e) for e in chg_entries) or empty_chg
    date = day["date"]
    return f"""
      <tr class="date-row"><td colspan="6">📅 {date}</td></tr>
      {section_row("大量保有報告書（新規）", len(new_entries), "dot-new")}
      {new_rows}
      {section_row("変更報告書", len(chg_entries), "dot-chg")}
      {chg_rows}
    """


def generate_html(days, updated_str):
    global WARRANTS
    WARRANTS = load_warrants()
    updated = updated_str
    date = days[0]["date"] if days else ""

    # 月別グループ化
    from collections import defaultdict
    by_month = defaultdict(list)
    for d in days:
        ym = d["date"][:7]  # "2026-06"
        by_month[ym].append(d)
    months = sorted(by_month.keys(), reverse=True)  # 新しい順

    # タブHTML
    tab_btns = "".join(
        f'<button class="tab-btn" data-month="{m}" onclick="switchTab(\'{m}\')">'
        f'{m.replace("-", " / ")}'
        f'</button>'
        for m in months
    )
    # 月ごとのテーブル本体
    panels = ""
    for m in months:
        m_days = by_month[m]
        rows = "".join(make_day_block(d) for d in m_days)
        total_new = sum(len(d.get("new",[])) for d in m_days)
        total_chg = sum(len(d.get("chg",[])) for d in m_days)
        panels += (
            f'<div class="tab-panel" id="panel-{m}" style="display:none">'
            f'<div class="panel-meta">{len(m_days)} 営業日 ／ 新規 {total_new} 件 ／ 変更 {total_chg} 件</div>'
            f'<div class="wrap"><table style="table-layout:fixed;width:100%">'
            f'<colgroup><col class="col-badge"><col class="col-ratio"><col class="col-pdf">'
            f'<col class="col-code"><col style="width:220px"><col></colgroup>'
            f'<thead><tr><th>区分</th><th class="ratio">保有割合</th><th></th>'
            f'<th>コード</th><th>銘柄名</th><th>保有者</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>'
        )
    first_month = months[0] if months else ""
    all_rows = ""  # unused now

    # 検索用の全データJSON（JS埋め込み）
    import json as _json
    all_entries = []
    for d in days:
        date_str = d["date"]
        for e in d.get("new", []) + d.get("chg", []):
            all_entries.append({
                "date": date_str,
                "sec":  e.get("sec") or "",
                "name": e.get("name") or "",
                "filer": e.get("filer") or "",
                "ratio": e.get("ratio"),
                "prev_ratio": e.get("prev_ratio"),
                "direction": e.get("direction") or "",
                "isNew": e.get("isNew", False),
                "docId": e.get("docId") or "",
            })
    all_entries_json = _json.dumps(all_entries, ensure_ascii=False)
    warrants_json = _json.dumps(WARRANTS, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>大量保有 Radar — {date}</title>
<meta name="description" content="EDINET 大量保有報告書・変更報告書 毎日自動集計">
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
thead th{{background:#1c2130;padding:9px 14px;text-align:left;color:var(--text);font-size:11px;font-weight:600;white-space:nowrap;border-bottom:1px solid var(--border)}}
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
td.filer{{color:var(--text);font-size:13px;max-width:300px}}
td.ratio{{font-weight:700;font-size:15px;text-align:right;white-space:nowrap;color:var(--text)}}
th.ratio{{text-align:right}}
col.col-badge{{width:130px}}
col.col-ratio{{width:90px}}
col.col-pdf{{width:56px}}
col.col-code{{width:70px}}
tr.section-row td{{background:#1c2130;padding:10px 16px;font-size:13px;font-weight:700;color:var(--text);border-top:2px solid var(--border);display:flex;align-items:center;gap:8px}}
tr.section-row{{display:table-row}}
tr.section-row td{{display:table-cell;vertical-align:middle}}
tr.section-row .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}}
tr.section-row .cnt{{font-size:12px;font-weight:normal;color:var(--muted);margin-left:6px}}
tr.warrant-row td{{background:#1d1620;border-left:3px solid #c084fc;padding:7px 16px 7px 24px;font-size:12.5px;color:var(--muted)}}
tr.warrant-row a{{color:#c084fc;text-decoration:none;font-weight:600}}
tr.warrant-row a:hover{{text-decoration:underline}}
tr.warrant-row .w-detail b{{color:#ff8c5c}}
tr.warrant-row .w-done{{color:var(--green)}}
tr.warrant-row .w-warn{{color:var(--gold)}}
tr.date-row td{{background:#0d0f14;padding:12px 16px;font-size:14px;font-weight:700;color:var(--gold);letter-spacing:.05em;border-top:3px solid rgba(245,200,66,.4)}}
tr.date-row:first-child td{{border-top:none}}
.search-bar{{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0 6px;align-items:center}}
.search-group{{display:flex;align-items:center;gap:6px}}
.search-label{{font-size:12px;color:var(--text);white-space:nowrap;font-weight:600}}
.search-input{{background:var(--surf);border:1px solid var(--gold);border-radius:7px;color:var(--text);font-size:13px;padding:6px 12px;width:160px;outline:none;transition:border-color .15s}}
.search-input:focus{{border-color:var(--gold);box-shadow:0 0 0 2px rgba(245,200,66,.2)}}
.search-input::placeholder{{color:var(--muted)}}
.btn-clear{{background:none;border:1px solid var(--border);border-radius:6px;color:var(--muted);font-size:12px;padding:5px 10px;cursor:pointer;transition:all .15s}}
.btn-clear:hover{{border-color:var(--red);color:var(--red)}}
#search-panel{{display:none}}
#search-panel .panel-meta{{font-size:12px;color:var(--muted);margin-bottom:10px}}
.tabs{{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 14px}}
.tab-btn{{background:transparent;border:1px solid var(--text);border-radius:7px;color:var(--text);font-size:13px;font-weight:600;padding:6px 16px;cursor:pointer;transition:all .15s}}
.tab-btn:hover{{border-color:var(--gold);color:var(--gold)}}
.tab-btn.active{{background:rgba(245,200,66,.15);border-color:var(--gold);color:var(--gold)}}
.panel-meta{{font-size:12px;color:var(--muted);margin-bottom:10px}}
.search-hint{{font-size:12px;color:var(--muted);margin:4px 0 12px}}
.btn-pdf{{display:inline-block;padding:3px 10px;border:1px solid var(--border);border-radius:5px;color:var(--text);font-size:11px;text-decoration:none;transition:all .15s;white-space:nowrap}}
.btn-pdf:hover{{border-color:var(--gold);color:var(--gold)}}
.btn-reload{{background:rgba(245,200,66,.1);border:1px solid rgba(245,200,66,.35);border-radius:6px;color:var(--gold);font-size:12px;font-weight:600;padding:5px 12px;cursor:pointer;transition:all .15s;white-space:nowrap}}
.btn-reload:hover{{background:rgba(245,200,66,.2);border-color:var(--gold)}}
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
  <button class="btn-reload" onclick="location.reload(true)" title="Shift+Ctrl+R と同じ強制リロード">強制リロード</button>
  <div class="meta">更新: {updated} JST &nbsp;｜&nbsp; データ: <a href="https://disclosure.edinet.go.jp/" target="_blank">EDINET</a></div>
</header>
<main>
<div class="search-bar">
  <div class="search-group">
    <span class="search-label">コード番号検索</span>
    <input class="search-input" id="inp-code" type="text" placeholder="例: 8001, 436A"
      oninput="doSearch()" onfocus="showHistory('code')" onblur="hideHistory('code')" autocomplete="off" list="">
    <datalist id="dl-code"></datalist>
  </div>
  <div class="search-group">
    <span class="search-label">保有者検索</span>
    <input class="search-input" id="inp-filer" type="text" placeholder="例: Evo Fund, 伊藤忠"
      oninput="doSearch()" onfocus="showHistory('filer')" onblur="hideHistory('filer')" autocomplete="off" list="">
    <datalist id="dl-filer"></datalist>
  </div>
  <button class="btn-clear" onclick="clearSearch()">✕ クリア</button>
</div>
<p class="search-hint">※ コード番号入力 or 保有者名入力で過去のデータ一覧に絞って表示します。</p>
<div class="tabs" id="tab-bar">{tab_btns}</div>
{panels}
<div id="search-panel">
  <div class="panel-meta" id="search-meta"></div>
  <div class="wrap"><table style="table-layout:fixed;width:100%">
    <colgroup><col class="col-badge"><col class="col-ratio"><col class="col-pdf">
    <col class="col-code"><col style="width:220px"><col></colgroup>
    <thead><tr><th>日付</th><th class="ratio">保有割合</th><th></th>
    <th>コード</th><th>銘柄名</th><th>保有者</th></tr></thead>
    <tbody id="search-tbody"></tbody>
  </table></div>
</div>
</main>
<script>
const ALL = {all_entries_json};
const WARRANTS = {warrants_json};

function warrantRow(sec) {{
  const w = WARRANTS[sec];
  if (!w) return '';
  const kai = w.kai ? `第${{w.kai}}回` : '';
  const parts = [];
  if (w.kofu != null) parts.push(`交付: ${{w.kofu.toLocaleString()}}株`);
  if (w.exercised != null) {{
    const total = w.total ? `/${{w.total.toLocaleString()}}個` : '';
    const pct = w.exercised_pct != null ? ` (${{w.exercised_pct}}%)` : '';
    parts.push(`行使済: ${{w.exercised.toLocaleString()}}個${{total}}${{pct}}`);
  }}
  if (w.unexercised != null) {{
    if (w.unexercised === 0) {{
      parts.push('<span class="w-done">☑ 未行使0個・終了</span>');
    }} else {{
      const sh = w.unexercised_shares ? `（${{w.unexercised_shares.toLocaleString()}}株）` : '';
      parts.push(`<b>未行使残: ${{w.unexercised.toLocaleString()}}個${{sh}}</b>`);
      if (w.unexercised_shares && w.outstanding)
        parts.push(`希薄化 ${{(w.unexercised_shares / w.outstanding * 100).toFixed(1)}}%`);
    }}
  }}
  let detail;
  if (parts.length) detail = parts.join(' ｜ ');
  else if ((w.title || '').includes('行使完了')) detail = '<span class="w-done">☑ 行使完了・残ゼロ</span>';
  else detail = '<span class="w-warn">⚠ 数値不明・PDF確認</span>';
  return `<tr class="warrant-row"><td colspan="6">💣 <a href="${{w.pdf}}" target="_blank">${{kai}}新株予約権 行使状況 (${{w.date}})</a><span class="w-detail"> ｜ ${{detail}}</span></td></tr>`;
}}

function badge(e) {{
  const d = e.direction, r = e.ratio, p = e.prev_ratio;
  if (d === '新規') return '<span class="badge badge-new">新規</span>';
  if (p !== null && r !== null) {{
    const diff = r - p;
    if (Math.abs(diff) >= 0.005) {{
      return diff > 0
        ? `<span class="badge badge-up">▲ +${{diff.toFixed(2)}}%</span>`
        : `<span class="badge badge-dn">▼ ${{diff.toFixed(2)}}%</span>`;
    }}
  }}
  if (d === '増加') return '<span class="badge badge-up">▲ 増加</span>';
  if (d === '減少') return '<span class="badge badge-dn">▼ 減少</span>';
  return '<span class="badge badge-chg">変更</span>';
}}

function makeRow(e) {{
  const ratio = e.ratio !== null ? e.ratio.toFixed(2)+'%' : '—';
  const pdf = `https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?${{e.docId}},,`;
  const code = e.sec
    ? `<a href="https://finance.yahoo.co.jp/quote/${{e.sec}}.T" target="_blank">${{e.sec}}</a>`
    : '—';
  return `<tr>
    <td>${{badge(e)}}</td>
    <td class="ratio">${{ratio}}</td>
    <td><a href="${{pdf}}" target="_blank" class="btn-pdf">PDF</a></td>
    <td class="code">${{code}}</td>
    <td class="company">${{e.name || '—'}}</td>
    <td class="filer">${{e.filer || '—'}}</td>
  </tr>` + warrantRow(e.sec);
}}

function doSearch() {{
  const code  = document.getElementById('inp-code').value.trim().toUpperCase();
  const filer = document.getElementById('inp-filer').value.trim();
  if (!code && !filer) {{ clearSearch(); return; }}

  const results = ALL.filter(e => {{
    const codeOk  = !code  || e.sec.toUpperCase().includes(code) || e.name.includes(document.getElementById('inp-code').value.trim());
    const filerOk = !filer || e.filer.includes(filer) || e.filer.toLowerCase().includes(filer.toLowerCase());
    return codeOk && filerOk;
  }});

  // 日付降順でソート済み（ALL は降順）
  document.getElementById('search-tbody').innerHTML = results.map(e => {{
    // 日付列を区分列に追加
    const ratio = e.ratio !== null ? e.ratio.toFixed(2)+'%' : '—';
    const pdf = `https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?${{e.docId}},,`;
    const code2 = e.sec
      ? `<a href="https://finance.yahoo.co.jp/quote/${{e.sec}}.T" target="_blank">${{e.sec}}</a>`
      : '—';
    return `<tr>
      <td><span style="font-size:11px;color:var(--muted)">${{e.date}}</span><br>${{badge(e)}}</td>
      <td class="ratio">${{ratio}}</td>
      <td><a href="${{pdf}}" target="_blank" class="btn-pdf">PDF</a></td>
      <td class="code">${{code2}}</td>
      <td class="company">${{e.name || '—'}}</td>
      <td class="filer">${{e.filer || '—'}}</td>
    </tr>` + warrantRow(e.sec);
  }}).join('');

  if (code)  addHist('code', document.getElementById('inp-code').value.trim());
  if (filer) addHist('filer', filer);
  document.getElementById('search-meta').textContent = `検索結果: ${{results.length}} 件`;
  document.getElementById('search-panel').style.display = 'block';
  document.getElementById('tab-bar').style.display = 'none';
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
}}

function clearSearch() {{
  document.getElementById('inp-code').value = '';
  document.getElementById('inp-filer').value = '';
  document.getElementById('search-panel').style.display = 'none';
  document.getElementById('tab-bar').style.display = '';
  switchTab(currentTab);
}}

function switchTab(m) {{
  currentTab = m;
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display='none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById('panel-'+m);
  if (panel) panel.style.display='';
  const btn = document.querySelector('[data-month="'+m+'"]');
  if (btn) btn.classList.add('active');
}}
let currentTab = '{first_month}';
switchTab('{first_month}');
// ページロード時の自動フォーカスを解除（テキストカーソルのチカチカ防止）
window.addEventListener('load', () => {{ if (document.activeElement) document.activeElement.blur(); }});

// ─── 検索履歴（localStorage） ───────────────────────────────
const HIST_KEY = {{ code: 'radar_hist_code', filer: 'radar_hist_filer' }};
const HIST_MAX = 10;

function getHist(type) {{
  try {{ return JSON.parse(localStorage.getItem(HIST_KEY[type]) || '[]'); }}
  catch {{ return []; }}
}}
function addHist(type, val) {{
  if (!val) return;
  let h = getHist(type).filter(x => x !== val);
  h.unshift(val);
  h = h.slice(0, HIST_MAX);
  localStorage.setItem(HIST_KEY[type], JSON.stringify(h));
  updateDatalist(type);
}}
function updateDatalist(type) {{
  const dl = document.getElementById('dl-' + type);
  if (!dl) return;
  dl.innerHTML = getHist(type).map(v => `<option value="${{v}}">`).join('');
}}
function showHistory(type) {{
  const inp = document.getElementById('inp-' + type);
  inp.setAttribute('list', 'dl-' + type);
  updateDatalist(type);
}}
function hideHistory(type) {{
  // 少し遅らせて選択を優先
  setTimeout(() => document.getElementById('inp-' + type)?.removeAttribute('list'), 200);
}}

// ページ読み込み時にdatalist初期化
updateDatalist('code');
updateDatalist('filer');
</script>
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

        # XBRL から補完（銘柄名・コード・保有割合・前回比が足りない場合）
        if not e["sec"] or not e["name"] or e["ratio"] is None or e.get("prev_ratio") is None:
            print(f"  [{i+1}/{len(docs)}] XBRL fetch {e['docId']}")
            xratio, xname, xcode, xprev = xbrl_parse(e["docId"])
            if xcode:
                # 保有者自身のコードを誤って返すケースを除外
                # EDINET API の secCode は提出者（保有者）のコードなので、一致したら却下
                filer_sec = (doc.get("secCode") or "").strip()
                if filer_sec and xcode == filer_sec:
                    print(f"    [warn] xcode={xcode} matches filer secCode — ignored")
                    xcode = None
            if xcode:
                e["sec"] = xcode  # 発行会社のコード（XBRLが正）
            if not e["name"] and xname:
                e["name"] = xname
            if e["ratio"] is None and xratio:
                e["ratio"] = xratio
            if e.get("prev_ratio") is None and xprev is not None:
                e["prev_ratio"] = xprev
            time.sleep(0.3)

        tag = "NEW" if e["isNew"] else "CHG"
        ratio_disp = f"{e['ratio']:.2f}%" if e["ratio"] else "N/A"
        print(f"  [{i+1}/{len(docs)}] [{tag}] {e['sec'] or '----':6} {(e['name'] or '?')[:18]:18} | {e['filer'][:22]:22} | {ratio_disp}")

        if e["isNew"]:
            new_entries.append(e)
        else:
            chg_entries.append(e)

    # 当日データを JSON に保存（0件の場合は保存しない）
    if new_entries or chg_entries:
        save_day(date, new_entries, chg_entries)
    else:
        print(f"  0件のため {date}.json は保存しません")

    # 全日分のデータを読み込んで index.html を生成
    days = load_all_days()
    updated_str = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")
    out = os.path.join(os.path.dirname(__file__), "..", "index.html")
    html = generate_html(days, updated_str)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Done - index.html generated ({len(new_entries)} new, {len(chg_entries)} changes, {len(days)} days total)")


if __name__ == "__main__":
    main()
