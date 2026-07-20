#!/usr/bin/env python3
"""사전 데이터 수집기 (fetcher).

Claude 가 웹서치로 긁으면 환각·토큰낭비가 생기는 '순수 조회값' 섹션을
결정론적으로 API 에서 받아 json 으로 떨군다. Claude 는 이 json 을
'확정 사실'로 읽고, 판단·요약·스크래핑(2·3·5·6·7)만 직접 한다.

담당 섹션:
  1 주가 스냅샷      → yfinance
  4 내부자 거래       → SEC EDGAR (Form 4)
  5 공식 공시 (보조)  → SEC EDGAR (submissions)
  8 금리              → yfinance 국채 수익률 (+ FRED 있으면 기준금리)
  9 섹터 지수          → yfinance (섹터 ETF)

설계 원칙:
  - 각 모듈은 독립적으로 try/except. 하나 실패해도 나머지는 채운다.
  - 못 받은 값은 null + error 메시지. 절대 지어내지 않는다.
    (프롬프트에서 Claude 가 이 null 을 '미확인'으로 처리하게 한다)
  - 모든 값에 as_of / source 를 붙인다.

사용:
  python scripts/fetch.py --ticker ABSI --date 2026-07-20 \
      --out reports/ABSI/2026-07-20.data.json
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "tickers.json"

# SEC 는 User-Agent 로 연락처를 요구한다 (없으면 403).
SEC_UA = os.environ.get("SEC_USER_AGENT", "forsure-labs stock-report forsure.labs@gmail.com")

# 섹터 → 대표 ETF 기본 매핑. tickers.json 에 sector_etf 가 있으면 그걸 우선.
SECTOR_ETF_DEFAULT = {
    "바이오": ["XBI", "IBB"],
    "원전": ["NLR", "URA"],
    "반도체": ["SMH", "SOXX"],
    "에너지": ["XLE"],
    "기술": ["XLK", "QQQ"],
}

# 국채 수익률 (yahoo 심볼 → 만기 라벨). 현재 yahoo 는 수익률을 퍼센트 그대로 준다
# (^TNX close 4.54 = 4.54%). 과거처럼 ×10(45.4) 로 오지 않으므로 스케일 조정 없음.
TREASURY = {
    "^IRX": "13주 (3M)",
    "^FVX": "5년",
    "^TNX": "10년",
    "^TYX": "30년",
}


def now_kst_iso():
    from datetime import timedelta
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_ticker_cfg(ticker):
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    for t in cfg.get("tickers", []):
        if t.get("ticker", "").upper() == ticker.upper():
            return t
    return {"ticker": ticker}


# ── 1 주가 스냅샷 + 9 섹터 지수 (yfinance) ──────────────────────────────
def fetch_price(ticker):
    import yfinance as yf

    tk = yf.Ticker(ticker)
    hist = tk.history(period="7d")
    if hist.empty:
        raise RuntimeError("가격 히스토리가 비어있음")

    close = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
    change_abs = close - prev
    change_pct = (change_abs / prev * 100) if prev else None
    volume = int(hist["Volume"].iloc[-1])
    as_of = hist.index[-1].strftime("%Y-%m-%d")

    info = {}
    try:
        info = tk.info or {}
    except Exception:
        info = {}

    def g(*keys):
        for k in keys:
            v = info.get(k)
            if v not in (None, "", 0):
                return v
        return None

    return {
        "as_of": as_of,
        "source": "yfinance",
        "data": {
            "close": round(close, 4),
            "change_abs": round(change_abs, 4),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "volume": volume,
            "week52_low": g("fiftyTwoWeekLow"),
            "week52_high": g("fiftyTwoWeekHigh"),
            "market_cap": g("marketCap"),
            "eps_ttm": g("trailingEps"),
            "roa": g("returnOnAssets"),
            "currency": g("currency") or "USD",
        },
        "error": None,
    }


def fetch_sector_index(cfg):
    import yfinance as yf

    etfs = cfg.get("sector_etf")
    if not etfs:
        sector = cfg.get("sector", "")
        for key, default in SECTOR_ETF_DEFAULT.items():
            if key in sector:
                etfs = default
                break
    if not etfs:
        return {"as_of": None, "source": "yfinance", "data": [], "error": "섹터 ETF 매핑 없음 — tickers.json 에 sector_etf 추가 권장"}

    out = []
    for sym in etfs:
        try:
            h = yf.Ticker(sym).history(period="7d")
            if h.empty:
                continue
            c = float(h["Close"].iloc[-1])
            p = float(h["Close"].iloc[-2]) if len(h) >= 2 else c
            out.append({
                "symbol": sym,
                "close": round(c, 2),
                "change_pct": round((c - p) / p * 100, 2) if p else None,
                "as_of": h.index[-1].strftime("%Y-%m-%d"),
            })
        except Exception as e:
            out.append({"symbol": sym, "error": str(e)})
    return {"as_of": now_kst_iso(), "source": "yfinance", "data": out, "error": None}


# ── 8 금리 (yfinance 국채 + FRED 선택) ──────────────────────────────────
def fetch_rates():
    import yfinance as yf

    yields = {}
    for sym, label in TREASURY.items():
        try:
            h = yf.Ticker(sym).history(period="5d")
            if not h.empty:
                yields[label] = round(float(h["Close"].iloc[-1]), 3)  # 이미 퍼센트
        except Exception:
            pass

    fed_funds = None
    fred_err = None
    key = os.environ.get("FRED_API_KEY")
    if key:
        try:
            url = ("https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id=DFEDTARU&api_key={key}&file_type=json"
                   "&sort_order=desc&limit=1")
            obs = _http_json(url)["observations"][0]
            fed_funds = float(obs["value"])
        except Exception as e:
            fred_err = str(e)
    else:
        fred_err = "FRED_API_KEY 없음 — 기준금리는 Claude 가 확인해야 함"

    return {
        "as_of": now_kst_iso(),
        "source": "yfinance(국채) + FRED(기준금리)",
        "data": {
            "fed_funds_upper_pct": fed_funds,
            "treasury_yields_pct": yields or None,
        },
        "error": fred_err,
        "note": "경제지표 발표 일정(CPI/PPI/FOMC/PCE)은 fetcher 미수집 — Claude 가 리서치",
    }


# ── 4 내부자 거래 + 5 공시 (SEC EDGAR) ──────────────────────────────────
def resolve_cik(ticker, cfg):
    if cfg.get("cik"):
        return str(cfg["cik"]).zfill(10)
    data = _http_json("https://www.sec.gov/files/company_tickers.json")
    for row in data.values():
        if row.get("ticker", "").upper() == ticker.upper():
            return str(row["cik_str"]).zfill(10)
    raise RuntimeError(f"CIK 를 찾지 못함: {ticker}")


def fetch_edgar(ticker, cfg):
    """최근 공시 목록(5)과 Form 4 존재 여부(4)를 SEC submissions 에서 뽑는다.

    Form 4 상세(매수/매도/수량/가격/RSU)는 XML 파싱이 무거워 여기선
    '최근 Form 4 제출 목록'만 준다. 상세 해석은 Claude 가 링크로 확인.
    """
    cik = resolve_cik(ticker, cfg)
    sub = _http_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accns = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])

    filings, form4 = [], []
    cik_int = int(cik)
    for i, form in enumerate(forms):
        date = dates[i] if i < len(dates) else None
        accn = accns[i] if i < len(accns) else ""
        doc = docs[i] if i < len(docs) else ""
        url = (f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
               f"{accn.replace('-', '')}/{doc}") if accn and doc else None
        row = {"form": form, "date": date, "url": url}
        if form == "4":
            if len(form4) < 15:
                form4.append(row)
        elif form in ("8-K", "10-Q", "10-K", "S-1", "424B5", "6-K", "S-3", "8-A12B"):
            if len(filings) < 15:
                filings.append(row)

    return {
        "insider_form4": {
            "as_of": now_kst_iso(),
            "source": f"SEC EDGAR (CIK {cik})",
            "data": form4,
            "error": None,
            "note": "제출 목록만 수집. 매수/매도·수량·가격·RSU 구분은 Claude 가 url 로 확인",
        },
        "recent_filings": {
            "as_of": now_kst_iso(),
            "source": f"SEC EDGAR (CIK {cik})",
            "data": filings,
            "error": None,
        },
    }


# ── 오케스트레이션 ──────────────────────────────────────────────────────
def build(ticker, date):
    cfg = load_ticker_cfg(ticker)
    result = {
        "ticker": ticker.upper(),
        "date": date,
        "generated_at": now_kst_iso(),
        "sections": {},
    }

    def run(name, fn):
        try:
            result["sections"][name] = fn()
        except Exception as e:
            result["sections"][name] = {"data": None, "error": f"{type(e).__name__}: {e}"}
            print(f"  ⚠️  {name} 실패: {e}", file=sys.stderr)

    run("price_snapshot", lambda: fetch_price(ticker))
    run("sector_index", lambda: fetch_sector_index(cfg))
    run("rates", fetch_rates)

    try:
        edgar = fetch_edgar(ticker, cfg)
        result["sections"].update(edgar)
    except Exception as e:
        result["sections"]["insider_form4"] = {"data": None, "error": f"{type(e).__name__}: {e}"}
        result["sections"]["recent_filings"] = {"data": None, "error": f"{type(e).__name__}: {e}"}
        print(f"  ⚠️  edgar 실패: {e}", file=sys.stderr)

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    data = build(args.ticker, args.date)
    out = args.out or f"reports/{args.ticker.upper()}/{args.date}.data.json"
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for s in data["sections"].values() if s.get("error") is None and s.get("data") not in (None, []))
    total = len(data["sections"])
    print(f"수집 완료 [{ok}/{total} 섹션] → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
