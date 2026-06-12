"""
MSワラント行使ウォッチ — warrant_watch.py
holdings-radar のデータから Evo Fund 等のMSワラント引受者が保有する銘柄を抽出し、
株探の開示一覧から「新株予約権…行使」系の最新PDFを取得して未行使残（爆弾リスク）を抽出する。
結果は data/warrants.json に保存。
"""
import os, re, json, glob, time, io, sys, unicodedata
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from pypdf import PdfReader

JST = ZoneInfo("Asia/Tokyo")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_PATH = os.path.join(DATA_DIR, "warrants.json")

# MSワラント引受で有名な保有者（正規化小文字で部分一致）
HOLDER_KEYWORDS = [
    "evo fund", "evofund",
    "マッコーリー", "macquarie",
    "cvi investments",
    "long corridor",
    "cantor",
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# 行使報告系タイトル（発行決議や払込完了は除外）
TITLE_RE = re.compile(r"新株予約権.{0,30}?(大量行使|月間行使状況|行使状況|行使完了)")


def collect_watch_codes() -> dict:
    """holdings データから監視対象の銘柄コードを抽出"""
    codes = {}
    for f in glob.glob(os.path.join(DATA_DIR, "2???-??-??.json")):
        with open(f, encoding="utf-8") as fp:
            d = json.load(fp)
        for lst in (d.get("new", []), d.get("chg", [])):
            for e in lst:
                filer = unicodedata.normalize("NFKC", e.get("filer") or "").lower()
                if e.get("sec") and any(k in filer for k in HOLDER_KEYWORDS):
                    codes[e["sec"]] = {
                        "name": e.get("name", ""),
                        "holder": e.get("filer", ""),
                    }
    return codes


def fetch_kabutan_news(code: str) -> list:
    """株探の開示一覧から (日時, タイトル, PDF URL) リストを返す（新しい順）
    アクセスブロック等のHTTPエラー時は例外を投げる（既存データ保持のため）"""
    url = f"https://kabutan.jp/stock/news?code={code}&nmode=4"
    r = requests.get(url, headers=UA, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"kabutan HTTP {r.status_code}")
    rows = []
    pat = re.compile(
        r'<time datetime="([^"]+)"[^>]*>.*?'
        r'href="https://kabutan\.jp/disclosures/pdf/(\d{8})/(\w+)/"[^>]*>([^<]+)',
        re.S)
    for m in pat.finditer(r.text):
        dt, ymd, docid, title = m.groups()
        rows.append({
            "datetime": dt,
            "title": title.strip(),
            "pdf": f"https://tdnet-pdf.kabutan.jp/{ymd}/{docid}.pdf",
            "viewer": f"https://kabutan.jp/disclosures/pdf/{ymd}/{docid}/",
        })
    return rows


def parse_pdf(pdf_url: str) -> dict:
    """行使状況PDFから数値を抽出"""
    r = requests.get(pdf_url, headers={**UA, "Referer": "https://kabutan.jp/"}, timeout=60)
    if r.status_code != 200 or "pdf" not in (r.headers.get("content-type") or ""):
        return {}
    try:
        txt = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
    except Exception as e:
        print(f"    pdf parse error: {e}")
        return {}
    t = re.sub(r"\s+", "", txt)
    t = unicodedata.normalize("NFKC", t)

    out = {}
    m = re.search(r"第(\d+)回(?:行使価額修正条項付)?新株予約権", t)
    if m:
        out["kai"] = int(m.group(1))
    # 交付株式数（月初からの / 対象月間の / 期間中の）
    m = re.search(r"(?:月初から|期間中|対象月間中?)の?交付株式数(?:[::]|は)?([\d,]+)株", t)
    if m:
        out["kofu"] = int(m.group(1).replace(",", ""))
    # 行使された数 + 発行総数 + 割合
    m = re.search(
        r"行使された新株予約権の数(?:及び(?:新株予約権の)?発行総数に対する行使比率)?"
        r"[^0-9]{0,20}([\d,]+)個"
        r"\(発行総数(?:([\d,]+)個に対する割合)?の?[::]?([\d.]+)%\)", t)
    if m:
        out["exercised"] = int(m.group(1).replace(",", ""))
        if m.group(2):
            out["total"] = int(m.group(2).replace(",", ""))
        out["exercised_pct"] = float(m.group(3))
    # 未行使（現時点/月末時点を優先、なければ前月末等の一般形）
    m = re.search(r"現時点における未行使(?:の)?新株予約権(?:の)?数(?:[::])?([\d,]+)個(?:\(([\d,]+)株\))?", t)
    if not m:
        m = re.search(r"(?:対象月の)?(?<!前)月末時点における未行使(?:の)?新株予約権(?:の)?数(?:[::])?([\d,]+)個(?:\(([\d,]+)株\))?", t)
    if not m:
        m = re.search(r"未行使(?:の)?新株予約権(?:の)?数(?:[::])?([\d,]+)個(?:\(([\d,]+)株\))?", t)
    if m:
        out["unexercised"] = int(m.group(1).replace(",", ""))
        if m.group(2):
            out["unexercised_shares"] = int(m.group(2).replace(",", ""))
    # 株数が無い場合: 交付株数÷行使個数 から1個あたり株数を逆算
    if "unexercised" in out and "unexercised_shares" not in out:
        if out.get("kofu") and out.get("exercised"):
            per = out["kofu"] // out["exercised"]
            if per > 0:
                out["unexercised_shares"] = out["unexercised"] * per
    # 発行済株式数（希薄化率の分母）
    m = re.search(r"発行済株式(?:総)?数(?:[::]|は)?([\d,]+)\(?株", t)
    if m:
        out["outstanding"] = int(m.group(1).replace(",", ""))
    return out


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    codes = collect_watch_codes()
    if only:
        codes = {c: v for c, v in codes.items() if c in only}
    print(f"監視対象: {len(codes)} 銘柄")

    # 既存結果を読み込み（増分更新）
    results = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            results = json.load(f).get("items", {})

    ok_count = 0
    for i, (code, info) in enumerate(sorted(codes.items())):
        print(f"[{i+1}/{len(codes)}] {code} {info['name'][:20]}")
        try:
            news = fetch_kabutan_news(code)
            ok_count += 1
        except Exception as e:
            print(f"    list error: {e} — 既存データ保持")
            time.sleep(1.5)
            continue
        hit = next((n for n in news if TITLE_RE.search(n["title"])), None)
        if not hit:
            print(f"    行使報告なし ({len(news)}件中)")
            results.pop(code, None)
            time.sleep(1.5)
            continue
        print(f"    {hit['datetime'][:10]} {hit['title'][:50]}")
        data = parse_pdf(hit["pdf"])
        time.sleep(1.5)
        entry = {
            "name": info["name"],
            "holder": info["holder"],
            "title": hit["title"],
            "date": hit["datetime"][:10],
            "pdf": hit["viewer"],
            **data,
        }
        results[code] = entry
        if data:
            print(f"    → 未行使: {data.get('unexercised')}個 ({data.get('unexercised_shares')}株)")
        else:
            print(f"    → 数値抽出できず（タイトルのみ保存）")

    if ok_count == 0:
        print("\n全銘柄アクセス失敗（ブロックの可能性）— warrants.json は更新しません")
        sys.exit(1)

    payload = {
        "updated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "items": results,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {OUT_PATH}: {len(results)} 銘柄")


if __name__ == "__main__":
    main()
