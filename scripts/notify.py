#!/usr/bin/env python3
"""리포트에서 요약을 뽑아 텔레그램으로 '요약 + 링크'를 보낸다.

사용법:
  python scripts/notify.py --report reports/ABSI/2026-07-17.md \\
      --url https://user.github.io/stock-report/ABSI/2026-07-17.html
  python scripts/notify.py --failure "ABSI 리포트 생성 실패" --url <actions run url>

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import argparse
import html
import os
import pathlib
import re
import sys
import urllib.request

API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 4096
SUMMARY_LIMIT = 900

# "## 🎯 오늘의 한 줄" 부터 다음 --- 또는 다음 헤딩 직전까지
ONELINER_RE = re.compile(
    r"^##\s*🎯\s*오늘의 한 줄\s*$\n(?P<body>.*?)(?=^---\s*$|^#{1,3}\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
# "| 종가 | **$1.23** (+4.5%, +$0.05) |" 형태
CLOSE_RE = re.compile(r"^\|\s*종가\s*\|\s*(?P<val>.+?)\s*\|\s*$", re.MULTILINE)


def strip_md(text: str) -> str:
    """텔레그램 HTML 모드에 넣기 전에 마크다운 장식을 걷어낸다."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_message(report: pathlib.Path, url: str) -> str:
    md = report.read_text(encoding="utf-8")

    m = ONELINER_RE.search(md)
    oneliner = strip_md(m["body"]) if m else "(요약 섹션을 찾지 못했습니다 — 전체 리포트를 확인하세요.)"
    if len(oneliner) > SUMMARY_LIMIT:
        oneliner = oneliner[:SUMMARY_LIMIT].rstrip() + " …"

    c = CLOSE_RE.search(md)
    close = f"\n💵 <b>종가</b> {html.escape(strip_md(c['val']))}\n" if c else ""

    # reports/{티커}/{YYYY-MM-DD}.md
    ticker, date = report.parent.name, report.stem
    return (
        f"📊 <b>{html.escape(ticker)} 데일리 리포트</b> — {html.escape(date)}\n"
        f"{close}"
        f"\n🎯 <b>오늘의 한 줄</b>\n{html.escape(oneliner)}\n"
        f"\n📄 <a href=\"{html.escape(url, quote=True)}\">전체 리포트 (9개 섹션) 보기</a>"
    )


def send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요합니다.")

    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 20].rstrip() + "\n… (생략)"

    import json

    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
    ).encode()

    req = urllib.request.Request(
        API.format(token=token), data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"텔레그램 전송 완료 (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        # 토큰이 에러 본문에 섞여 나가지 않도록 본문만 출력
        sys.exit(f"텔레그램 전송 실패 (HTTP {e.code}): {e.read().decode(errors='replace')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=pathlib.Path, help="마크다운 리포트 경로")
    ap.add_argument("--url", required=True, help="HTML 리포트 URL (실패 시엔 Actions 실행 URL)")
    ap.add_argument("--failure", help="실패 알림 메시지")
    args = ap.parse_args()

    if args.failure:
        send(
            f"⚠️ <b>리포트 생성 실패</b>\n\n{html.escape(args.failure)}\n\n"
            f'🔧 <a href="{html.escape(args.url, quote=True)}">실행 로그 보기</a>'
        )
        return

    if not args.report or not args.report.is_file():
        sys.exit(f"리포트 파일을 찾을 수 없습니다: {args.report}")
    send(build_message(args.report, args.url))


if __name__ == "__main__":
    main()
