# 📈 데일리 종목 리포트 자동화

매일 **07:00 KST**에 GitHub Actions가 Claude를 헤드리스로 실행해 관심종목 리포트를 만들고,
GitHub Pages에 HTML로 올린 뒤 텔레그램으로 **요약 + 링크**를 보냅니다.

```
22:00 UTC (= 07:00 KST, 화~토)
  → config/tickers.json 의 종목마다 Claude 리서치 (웹서치·웹페치)
  → reports/{티커}/{날짜}.md 생성 + 커밋
  → site/ 로 HTML 렌더링 → GitHub Pages 배포
  → 텔레그램: "오늘의 한 줄" 요약 + 리포트 URL
```

## 저장 규칙

원본(git 축적)과 웹(매번 재생성)이 같은 경로 구조를 씁니다.

| 대상 | 경로 | 예시 |
|---|---|---|
| 마크다운 원본 | `reports/{티커}/{YYYY-MM-DD}.md` | `reports/ABSI/2026-07-18.md` |
| HTML | `site/{티커}/{YYYY-MM-DD}.html` | `site/ABSI/2026-07-18.html` |
| 공개 URL | `{Pages주소}/{티커}/{YYYY-MM-DD}.html` | `…github.io/stock-report/ABSI/2026-07-18.html` |

```
reports/
├── ABSI/
│   ├── 2026-07-17.md
│   └── 2026-07-18.md
└── OKLO/
    └── 2026-07-18.md
```

- **날짜 = 데이터 기준일이 아니라 리포트를 만든 날(KST)** 입니다. 07:00 KST에 돌므로
  `ABSI/2026-07-18.md`(토)에는 **7/17 금요일 미국장 종가**가 담깁니다. 실제 기준일은
  리포트 본문의 "가격 데이터 기준" 줄에 표기됩니다.
- 이 경로 규칙은 `render.py`가 티커·날짜를 파싱하는 근거입니다. 규칙에 안 맞는 파일
  (예: `reports/ABSI/메모.md`)은 경고만 남기고 건너뛰므로 사이트가 깨지지 않습니다.
- 지난 리포트는 지우지 않고 계속 쌓입니다.

---

## 셋업 (최초 1회)

### 1. 저장소 만들기

```bash
git init && git add -A && git commit -m "초기 셋업"
gh repo create stock-report --public --source=. --push
```

> ⚠️ **Pages는 무료 계정에선 public 저장소만 됩니다.** private으로 두려면 GitHub Pro가 필요합니다.
> 리포트를 공개하고 싶지 않다면 아래 "비공개로 쓰기"를 보세요.

### 2. Claude GitHub App 설치 ⚠️ 필수

https://github.com/apps/claude → **Install** → 이 저장소 선택.

빠뜨리면 워크플로우가 이 에러로 실패합니다:
`Claude Code is not installed on this repository`

`github_token` 으로 우회할 수 없습니다. App 설치가 필수입니다.

### 3. Claude OAuth 토큰 발급

로컬 터미널에서:

```bash
claude setup-token
```

Claude 구독 계정으로 로그인하면 장기 토큰이 출력됩니다. 이 값을 복사해두세요.

### 4. 텔레그램 봇 준비

1. 텔레그램에서 **@BotFather** 에게 `/newbot` → 봇 이름 지정 → **봇 토큰** 수령
2. 만든 봇과 대화를 **먼저 시작**하고 아무 메시지나 전송 (이걸 해야 채팅 ID가 잡힙니다)
3. 채팅 ID 확인:
   ```bash
   curl -s "https://api.telegram.org/bot<봇토큰>/getUpdates" \
     | python3 -c "import sys,json; [print(u['message']['chat']['id']) for u in json.load(sys.stdin)['result'] if 'message' in u]"
   ```
   결과가 비어 있으면 2번을 안 한 것. 그룹으로 받으려면 봇을 그룹에 초대 후 같은 방법 (ID가 `-100…` 으로 시작).

### 5. GitHub Secrets 등록

저장소 **Settings → Secrets and variables → Actions → Repository secrets** 에 등록합니다.
(위쪽 *Environment secrets* 아님 — `report` 잡에서 안 보입니다.)

CLI로 하려면:

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN   # 3번에서 받은 토큰
gh secret set TELEGRAM_BOT_TOKEN        # 4번 봇 토큰
gh secret set TELEGRAM_CHAT_ID          # 4번 채팅 ID
gh secret set FRED_API_KEY              # (선택) 기준금리 수집용 — 없으면 Claude 가 대신 확인
```

> `FRED_API_KEY` 는 선택입니다. [FRED](https://fredaccount.stlouisfed.org/apikey) 에서 무료 발급.
> 없으면 fetcher 는 국채 수익률만 채우고 기준금리는 `null` 로 두며, Claude 가 웹서치로 보완합니다.

### 6. GitHub Pages 켜기

저장소 **Settings → Pages → Source** 를 **GitHub Actions** 로 지정합니다.

### 7. 테스트 실행

```bash
gh workflow run "데일리 종목 리포트" -f ticker=ABSI
gh run watch
```

---

## 종목 추가/제거

[`config/tickers.json`](config/tickers.json) 만 고치면 됩니다. 워크플로우 수정은 필요 없습니다.

```json
{
  "tickers": [
    { "ticker": "ABSI", "company": "Absci Corporation", "sector": "바이오 (임상단계 신약)",
      "exchange": "NASDAQ", "currency": "미국 / USD", "enabled": true },
    { "ticker": "OKLO", "company": "Oklo Inc.", "sector": "원전 (SMR)",
      "exchange": "NYSE", "currency": "미국 / USD", "enabled": true }
  ]
}
```

- `enabled: false` — 삭제하지 않고 잠시 끌 때
- `sector` 문구가 리포트 6·7번 섹터 모듈(바이오 = 임상/FDA, 원전 = NRC/DOE/PPA)을 결정합니다
- `sector_etf`(선택, 예: `["XBI","IBB"]`) — 섹션 9 섹터 지수용 ETF. 없으면 `sector` 문구로 자동 추정
- `cik`(선택) — SEC 조회용. 없으면 티커로 자동 해석
- 종목은 최대 2개씩 병렬로 돕니다 (`max-parallel`)

---

## 파일 구조

| 경로 | 역할 |
|---|---|
| `.github/workflows/daily-report.yml` | 스케줄·리서치·배포·전송 전체 파이프라인 |
| `config/tickers.json` | 종목 목록 (**여기만 고치면 됨**) |
| `prompts/daily-report.md` | 리포트 지시문 + 9개 섹션 출력 템플릿 |
| `scripts/fetch.py` | 사전 데이터 수집 (주가·내부자거래·금리·섹터지수 → `.data.json`) |
| `scripts/render.py` | md → HTML 렌더링, 목록 페이지 생성 |
| `scripts/notify.py` | 요약 추출 + 텔레그램 전송 |
| `reports/{티커}/{날짜}.md` | 생성된 마크다운 리포트 (자동 커밋, 아카이브) |

---

## 알아둘 점

- **스케줄 지연:** GitHub 무료 러너의 cron은 정시에 안 뜰 때가 많습니다 (보통 수 분, 혼잡 시 수십 분). 07:00 정각이 중요하면 시각을 앞당겨 잡으세요.
- **요약 추출:** `notify.py`는 리포트에서 `## 🎯 오늘의 한 줄` 제목을 찾아 요약을 뽑습니다. 지시문에서 이 문구를 바꾸면 요약이 깨집니다.
- **실패 시:** 리포트 생성이 실패하면 텔레그램으로 실패 알림 + Actions 로그 링크가 옵니다.
- **미국 공휴일:** 장이 쉰 날도 리포트는 생성됩니다 (전일 종가 기준). 원하면 워크플로우에 휴장일 스킵 로직을 추가하세요.

### 비공개로 쓰기

리포트를 공개하고 싶지 않고 GitHub Pro도 없다면, Pages 대신 **텔레그램 `.md` 파일 첨부**로 바꾸면 됩니다.
`publish` 잡의 Pages 관련 스텝을 지우고 `sendDocument` API로 교체하세요.

---

## ⚠️ 면책

자동 생성된 리포트이며 **투자 자문이 아닙니다.** 무료 공개 집계 데이터 기준이라 수치가 부정확하거나
지연될 수 있습니다. 투자 판단의 근거로 사용하지 마세요.
