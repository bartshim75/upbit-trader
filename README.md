# 업비트 BTC + DOGE 자동매매 프로그램

**1시간봉 Regime 자동 선택 전략**: 종목별 독립 설정으로 TREND 눌림목 + SIDEWAYS BB 평균회귀 + ATR 기반 리스크 관리

---

## 운용 종목

| 종목 | 기본 활성화 | 상태 파일 | 전략 성격 |
|------|-------------|-----------|-----------|
| `KRW-BTC` | 예 | `status.json`, `position.json`*(trailing)* / `positions.json`*(fixed)*, `baseline.json` | 보수적인 장기 추세/눌림목 |
| `KRW-DOGE` | 예 | `status_KRW_DOGE.json`, `position_KRW_DOGE.json`*(trailing)* / `positions_KRW_DOGE.json`*(fixed)*, `baseline_KRW_DOGE.json` | ETH 대비 최근 90일 상대 추세 우위, 더 빠른 추세 감지 + 넓은 리스크 허용 |

DOGE를 끄려면 `.env`에 `ENABLE_DOGE=false`를 설정합니다.

## 전략 요약

### 매수
| Regime | 조건 |
|------|------|
| TREND | 현재가 > 장기 MA, 중기 MA > 장기 MA, 현재가 > 중기 MA, 눌림목, RSI 허용 구간, 반등 캔들 |
| SIDEWAYS | 저가가 BB 하단 근처, 현재가 ≤ BB 중간선, 양봉 반등, RSI 과매도, 장기 MA 대비 과도한 이탈 아님 |
| BEAR / NEUTRAL | 신규 매수 차단 |
| 안전 | 일일 손실/연속손절 한도 내, 종목별 슬리피지 한도 내, 변동성 정상 |

BTC와 DOGE는 위 구조만 공유하고, MA 기간/RSI/손절/익절/슬리피지/예산/상태 파일은 서로 독립입니다.

### 매도

종목별로 두 가지 모드 중 하나를 선택할 수 있습니다 (`.env`로 설정).

#### `trailing` 모드 (기본값) — 분할 익절 + 트레일링
| 트리거 | 동작 |
|--------|------|
| 손절 | `max(매수가×0.98, 매수가 - 1.5×ATR)` 도달 → 전량 |
| 1차 익절 | +1.5% 도달 → 초기 수량의 50% 매도, 손절가 본전으로 상향 |
| 2차 익절 | +3.0% 도달 → 초기 수량의 30% 추가 매도 |
| 트레일링 | 잔여 20%, 진입 후 고점 대비 -1.8% 하락 시 매도 |
| 추세 이탈 | 현재가 < MA50 → 잔여 전량 청산 |
| 동시 보유 | **최대 1포지션** (보유 중에는 신규 매수 평가 자체를 안 함) |

#### `fixed` 모드 — 정액 익절 + 다중 포지션
| 트리거 | 동작 |
|--------|------|
| 익절 | 매수가 +`FIXED_TP_PCT` (기본 +3%) 도달 → 해당 포지션 전량 매도 |
| 손절 | 매수가 +`FIXED_SL_PCT` (기본 -8%) 도달 → 해당 포지션 전량 손절 |
| 트레일링 / 추세이탈 | **없음** (계속 보유) |
| 동시 보유 | **다중 포지션 허용** — 매수 신호 뜰 때마다 자금 있는 한 추가 매수 |
| 매수 중단 | 보유 KRW가 1회 진입 금액보다 작아지면 신규 매수 자동 중단 |

**모드 선택 우선순위**: `BTC_EXIT_STRATEGY` / `DOGE_EXIT_STRATEGY` > `EXIT_STRATEGY` (글로벌 기본값)

```ini
# 예시 1) BTC만 fixed +3%, DOGE는 trailing (기본)
BTC_EXIT_STRATEGY=fixed
BTC_FIXED_TP_PCT=0.03

# 예시 2) 둘 다 fixed, 비율 다르게
BTC_EXIT_STRATEGY=fixed
BTC_FIXED_TP_PCT=0.03
DOGE_EXIT_STRATEGY=fixed
DOGE_FIXED_TP_PCT=0.025

# 예시 3) 글로벌로 한 번에 fixed 적용 (BTC_/DOGE_ 미설정일 때만 적용)
EXIT_STRATEGY=fixed
FIXED_TP_PCT=0.03
```

> ⚠️ **모드 전환 시 주의**: 보유 포지션이 있는 상태에서 모드를 바꾸면 이전 모드의 포지션 파일이 그대로 남아 무시됩니다. 깔끔히 가려면 보유분을 먼저 청산하고 (`position.json` / `positions.json` 비어있는 상태) `.env` 변경 → 봇 재시작 권장.

> ℹ️ **fixed 모드는 고정 손절(-8%)이 존재합니다.** 가격이 매수가 대비 -8% 이하로 하락 시 손절(`FIXED_SL`)이 작동하여 추가 손실을 방지합니다. 익절은 +`FIXED_TP_PCT`로 제한되며, 트레일링 스탑이나 추세 이탈 청산은 동작하지 않습니다.

### 리스크 관리
- **사용자 기존 자산 보호 (baseline)**: 봇 첫 실행 시 종목별 거래소 잔고를 각 baseline 파일에 기록. 봇은 이 수량을 절대 매도하지 않음. 봇은 자기가 매수한 수량만 추적/매도함.
- **포지션 크기**: 1회 진입 = 종목별 유효예산 × `POSITION_PCT` (DOGE는 `DOGE_POSITION_PCT`)
- **일일 손실 한도**: 종목별 배정예산 기준 손실 한도 도달 시 해당 종목 신규 매수 차단
- **연속 손절**: 종목별 연속 손절 한도 도달 시 해당 종목 신규 매수 차단
- **변동성 차단**: 직전 1H봉 변동폭이 ATR × 3 이상이면 사이클 스킵
- **슬리피지 검사**: 호가 기준 예상 체결가가 0.5% 이상 불리하면 매수 취소

### 운영
| 항목 | 값 |
|------|------|
| 실행 주기 | 매 정시 (1시간봉) |
| 거래 대상 | KRW-BTC + KRW-DOGE |
| 기본 배정 예산 | BTC 1,000,000원 / DOGE 300,000원 (변경 가능) |
| 캔들 데이터 | 250봉 (MA200 계산) |

---

## 1단계 — 로컬 맥북 (개발 환경)

```bash
# 1. 폴더 이동
cd /Users/shawn/Dev/ClaudeCode/upbit-trader

# 2. 가상환경 생성 & 패키지 설치
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env
nano .env   # API 키 입력

# 4. 실행 (테스트)
python main.py
```

---

## 2단계 — GitHub 연동

```bash
# GitHub에 레포 생성 후
git init
git remote add origin https://github.com/[계정]/upbit-trader.git
git add .
git commit -m "초기 세팅"
git push -u origin main
```

---

## 3단계 — GCP VM 배포

### VM 최초 세팅

```bash
# GCP Console에서 VM 생성
# - 리전: us-central1 (무료)
# - 머신: e2-micro
# - OS: Ubuntu 22.04 LTS
# - 외부IP: 고정 IP 할당

# VM SSH 접속 후
git clone https://github.com/[계정]/upbit-trader.git
cd upbit-trader
bash setup.sh

# API 키 입력
nano .env

# 서비스 시작
sudo systemctl start upbit-trader
```

### 업비트 API 키에 VM IP 등록

업비트 → 마이페이지 → Open API 관리 → IP 등록란에 GCP VM 외부 IP 입력

---

## 4단계 — CI/CD (GitHub Actions) 설정

GitHub 레포 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 값 |
|-------------|-----|
| `GCP_VM_IP` | GCP VM 외부 IP |
| `GCP_VM_USER` | VM 유저명 (보통 `ubuntu`) |
| `GCP_VM_SSH_KEY` | SSH 개인키 내용 (`~/.ssh/id_rsa` 전체 내용) |

이후 맥북에서 코드 수정 → `git push` → VM 자동 배포

---

## 운영 명령어 (VM에서)

```bash
# 트레이더
sudo systemctl status upbit-trader
sudo systemctl start  upbit-trader
sudo systemctl stop   upbit-trader
sudo systemctl restart upbit-trader
journalctl -u upbit-trader -f

# 대시보드
sudo systemctl status upbit-dashboard
sudo systemctl restart upbit-dashboard
journalctl -u upbit-dashboard -f

# baseline (사용자 기존 자산 보호)
python reset_baseline.py --show                 # 활성 종목 baseline 확인
python reset_baseline.py                        # 활성 종목 현재 잔고로 재설정 (= 모두 보호)
python reset_baseline.py --ticker KRW-DOGE      # DOGE만 재설정
python reset_baseline.py --zero                 # baseline=0 (= 모두 봇이 운용)

# 데이터 직접 확인
cat trades.csv
cat status.json
cat baseline.json
```

---

## VM 재부팅 / 리셋 시 자동 재시작

**결론: 별도 명령어 입력 불필요.** VM이 켜지면 트레이더와 대시보드가 자동으로 올라옵니다.

[setup.sh](setup.sh)에서 두 가지 장치를 걸어둡니다:

1. **`Restart=always` + `RestartSec=10`** — 프로세스가 죽으면 10초 후 systemd가 자동 재시작.
2. **`systemctl enable upbit-trader upbit-dashboard`** — VM 부팅 시 systemd가 두 서비스를 자동 시작.

| 상황 | 동작 |
|------|------|
| VM 재부팅 / 리셋 | 부팅 후 systemd가 자동 시작 ✅ |
| 프로세스만 크래시 | 10초 후 자동 재시작 ✅ |
| VM 자체 정지 (free tier 한도 초과 등) | VM을 다시 켜야 함 — 켜지면 자동 시작 |

### 정상 작동 확인 (VM 재부팅 후)

```bash
sudo systemctl status upbit-trader
sudo systemctl status upbit-dashboard
```

`active (running)` + `enabled` 두 가지가 모두 표시되면 OK. 만약 `disabled`면 한 번만:

```bash
sudo systemctl enable upbit-trader upbit-dashboard
```

---

## 5단계 — 모니터링 대시보드

브라우저에서 거래 내역 / 손익 / 포지션을 실시간으로 확인할 수 있습니다.

### 접속 방법
1. GCP 방화벽에서 `8501` 포트 개방 (아래 "GCP 방화벽 설정" 참고)
2. `.env`에 `DASHBOARD_PASSWORD=강력한비밀번호` 입력 후 `sudo systemctl restart upbit-dashboard`
3. 브라우저: `http://<VM_외부_IP>:8501`
4. 비밀번호 입력 후 대시보드 표시 (30초마다 자동 갱신)

### 표시 항목
- **KPI 6개**: 배정 예산 / 봇 운용 자산 / 누적 손익 / 오늘 손익 / 승률 / 거래 상태
- **포지션 카드**: trailing 모드 — 매수가, 현재가, 평가손익, 손절가, TP1/TP2 진행, 고점, 잔량 / fixed 모드 — 보유 N개 포지션 표 (진입시각, 매수가, 수량, 평가손익, 목표가까지 거리)
- **시장 상태**: MA20/50/200, RSI, ATR + 매수 6개 조건 체크리스트
- **차트**: 누적 실현손익 라인 / 일별 손익 막대 (최근 30일)
- **거래 내역**: 정렬/필터 가능한 표 + CSV 다운로드
- **로그**: `trader.log` 마지막 50줄

### GCP 방화벽 설정 (대시보드 포트 개방)
1. https://console.cloud.google.com/networking/firewalls/list
2. **방화벽 규칙 만들기** 클릭
3. 입력값:
   - 이름: `allow-dashboard`
   - 대상: `네트워크의 모든 인스턴스`
   - 소스 IPv4 범위: `0.0.0.0/0` (전 세계 허용 — 비밀번호로 보호)
   - 프로토콜/포트: TCP `8501`
4. **만들기**

### Cloudflare 도메인 매핑 (선택, 추후)
무료 도메인 + HTTPS + 캐시 + DDoS 보호를 한 번에 받을 수 있습니다.

**준비물**: 본인 소유 도메인 (예: `mybot.com`). Cloudflare에서도 ~$10/년에 등록 가능.

**절차**:
1. 도메인을 Cloudflare에 등록 (도메인 등록 시 자동, 외부 도메인은 NS 변경 필요)
2. Cloudflare 대시보드 → DNS → **Add record**
   - Type: `A`
   - Name: `trader` (→ `trader.mybot.com`이 됨)
   - IPv4 address: `<VM_외부_IP>`
   - Proxy status: **Proxied** (주황색 구름) — HTTPS 자동 + IP 숨김
   - TTL: Auto
3. 잠시 대기 (1~5분) 후 `https://trader.mybot.com` 접속

**Cloudflare 추가 설정 (보안 강화)**:
- SSL/TLS → 모드: `Full` (Cloudflare ↔ VM 자체 HTTPS는 불필요, VM은 8501 HTTP 그대로)
- Rules → **Origin Rules**에서 포트 변경:
  - When: Hostname = `trader.mybot.com`
  - Then: Rewrite to port `8501`
- (옵션) **Zero Trust** → Application 추가하여 Google/이메일 인증으로 추가 보호

이렇게 하면 GCP 방화벽 8501 포트는 Cloudflare IP 대역만 허용하도록 제한할 수 있어서 직접 접근이 차단됩니다.

---

## 거래 기록 파일

| 파일 | 내용 |
|------|------|
| `trades.csv` | 매수/매도 전체 내역 (매수가, 매도가, 손익, MA20/50/200, RSI, ATR 등) |
| `status.json` / `status_KRW_DOGE.json` | 종목별 누적 손익, 승률, 일일 실현손익 / 연속손절 / 거래중단 플래그 |
| `position.json` / `position_KRW_DOGE.json` | (trailing 모드) 종목별 단일 포지션 상태 (매수가, ATR, 손절가, 고점, TP 진행) |
| `positions.json` / `positions_KRW_DOGE.json` | (fixed 모드) 종목별 다중 포지션 리스트 (각 매수가, 수량, 목표가) |
| `baseline.json` / `baseline_KRW_DOGE.json` | 종목별 사용자 기존 보유 수량 (봇이 절대 매도하지 않음) |
| `trader.log` | 실행 로그 전체 |

---

## 주의사항

- `.env` 파일은 절대 GitHub에 올리지 마세요 (`.gitignore`에 포함됨)
- 처음에는 소액으로 1~2주 모니터링 후 예산 증액 권장
- 본 전략은 **상승장 한정**으로 진입합니다 (MA200 위에서만). 강한 하락장에서는 자동으로 매수가 멈춥니다.
- 분할 익절 구조상 한 번의 큰 상승에서 전량 익절되지 않습니다 — 잔여 20%는 트레일링 스탑으로 추적합니다.
- 자동매매는 어디까지나 보조 도구입니다. 정기적으로 거래내역과 상태를 확인하세요.
- **사용자 기존 자산은 자동으로 보호됩니다** (`baseline.json`). 봇은 자기가 매수한 수량만 매도합니다.
