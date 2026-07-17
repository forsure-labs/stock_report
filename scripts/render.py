#!/usr/bin/env python3
"""reports/*.md 를 site/ 아래 HTML로 렌더링하고 index.html 을 만든다."""

import html
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import markdown

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
KST = timezone(timedelta(hours=9))

PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<main>
{nav}
{body}
</main>
</body>
</html>
"""

CSS = """
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #666; --line: #e3e3e3;
  --accent: #2f6feb; --code-bg: #f5f5f5; --quote-bg: #f7f9fc;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a; --fg: #e6e6e6; --muted: #9aa0a6; --line: #2c2f36;
    --accent: #6aa3ff; --code-bg: #1e2127; --quote-bg: #1b1f27;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo",
    "Pretendard", "Noto Sans KR", sans-serif;
  line-height: 1.7; font-size: 16px;
}
main { max-width: 820px; margin: 0 auto; padding: 24px 18px 80px; }
h1 { font-size: 1.75rem; line-height: 1.3; margin: 0 0 .5em; }
h2 {
  font-size: 1.3rem; margin: 2.2em 0 .6em;
  padding-bottom: .3em; border-bottom: 2px solid var(--line);
}
h3 { font-size: 1.08rem; margin: 1.6em 0 .5em; }
a { color: var(--accent); }
hr { border: 0; border-top: 1px solid var(--line); margin: 2em 0; }
.table-wrap { overflow-x: auto; margin: 1em 0; -webkit-overflow-scrolling: touch; }
table { border-collapse: collapse; width: 100%; font-size: .92rem; }
th, td { border: 1px solid var(--line); padding: 8px 10px; text-align: left; }
th { background: var(--code-bg); font-weight: 600; white-space: nowrap; }
blockquote {
  margin: 1em 0; padding: .8em 1em; background: var(--quote-bg);
  border-left: 4px solid var(--accent); border-radius: 0 6px 6px 0;
}
blockquote p { margin: 0; }
code {
  background: var(--code-bg); padding: .15em .4em;
  border-radius: 4px; font-size: .88em;
}
pre { background: var(--code-bg); padding: 14px; border-radius: 8px; overflow-x: auto; }
pre code { background: none; padding: 0; }
ul, ol { padding-left: 1.4em; }
nav.top { font-size: .9rem; margin-bottom: 2em; color: var(--muted); }
.index-list { list-style: none; padding: 0; }
.index-list li {
  border: 1px solid var(--line); border-radius: 8px;
  padding: 12px 14px; margin-bottom: 10px;
}
.index-list .date { color: var(--muted); font-size: .85rem; }
.footer { margin-top: 3em; color: var(--muted); font-size: .82rem; }
"""

# reports/{티커}/{YYYY-MM-DD}.md — 티커는 부모 폴더명, 날짜는 파일명
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]*$")


def wrap_tables(html_text: str) -> str:
    """모바일에서 표가 가로 스크롤되도록 감싼다."""
    return html_text.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>"
    )


def render_report(md_path: pathlib.Path) -> Optional[Dict[str, str]]:
    ticker, date = md_path.parent.name, md_path.stem
    if not TICKER_RE.match(ticker) or not DATE_RE.match(date):
        rel = md_path.relative_to(REPORTS)
        print(f"  건너뜀 (경로 규칙 불일치): {rel}", file=sys.stderr)
        return None

    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "nl2br"])
    body = wrap_tables(md.convert(md_path.read_text(encoding="utf-8")))

    out_rel = f"{ticker}/{date}.html"
    out_path = SITE / out_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        PAGE.format(
            title=f"{ticker} 데일리 리포트 {date}",
            css=CSS,
            nav='<nav class="top"><a href="../index.html">← 전체 리포트 목록</a></nav>',
            body=body,
        ),
        encoding="utf-8",
    )
    return {"ticker": ticker, "date": date, "href": out_rel}


def render_index(entries: List[Dict[str, str]]) -> None:
    entries.sort(key=lambda e: (e["date"], e["ticker"]), reverse=True)
    items = "\n".join(
        f'<li><a href="{html.escape(e["href"])}">📊 {html.escape(e["ticker"])} 데일리 리포트</a>'
        f'<div class="date">{html.escape(e["date"])}</div></li>'
        for e in entries
    )
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    body = (
        "<h1>📈 데일리 종목 리포트</h1>\n"
        f'<ul class="index-list">{items}</ul>\n'
        f'<p class="footer">마지막 갱신: {now} · 자동 생성 · 투자 판단의 근거로 사용하지 마세요.</p>'
    )
    (SITE / "index.html").write_text(
        PAGE.format(title="데일리 종목 리포트", css=CSS, nav="", body=body),
        encoding="utf-8",
    )


def main() -> int:
    if not REPORTS.exists():
        print("reports/ 디렉토리가 없습니다.", file=sys.stderr)
        return 1

    SITE.mkdir(exist_ok=True)
    (SITE / ".nojekyll").touch()

    entries = [e for p in sorted(REPORTS.glob("*/*.md")) if (e := render_report(p))]
    if not entries:
        print("렌더링할 리포트가 없습니다.", file=sys.stderr)
        return 1

    render_index(entries)
    print(f"{len(entries)}개 리포트를 site/ 에 렌더링했습니다.")
    print(json.dumps(entries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
