# 업비트 BTC 자동매매 프로그램

**1시간봉 추세 눌림목 전략** + ATR 기반 손절 + 분할 익절 + 일일 리스크 한도

---

## 전략 요약

### 매수 (모두 만족 시)
| 조건 | 내용 |
|------|------|
| 추세 | 현재가 > MA200, MA50 > MA200 |
| 눌림목 | 현재가 ≤ MA20 × 1.005 |
| 모멘텀 | RSI(14) ∈ [35, 50] |
| 반등 | 현재 종가 > 직전 고가, 또는 현재 종가 > 시가 (양봉) |
| 안전 | 일일 손실/연속손절 한도 내, 슬리피지 ≤ 0.5%, 변동성 정상 |

### 매도
| 트리거 | 동작 |
|--------|------|
| 손절 | `max(매수가×0.98, 매수가 - 1.5×ATR)` 도달 → 전량 |
| 1차 익절 | +1.5% 도달 → 초기 수량의 50% 매도, 손절가 본전으로 상향 |
| 2차 익절 | +3.0% 도달 → 초기 수량의 30% 추가 매도 |
| 트레일링 | 잔여 20%, 진입 후 고점 대비 -1.2% 하락 시 매도 |
| 추세 이탈 | 현재가 < MA50 → 잔여 전량 청산 |

### 리스크 관리
- **포지션 크기**: 1회 진입 = 유효예산의 15% (`POSITION_PCT`)
- **일일 손실 한도**: 배정예산의 -3% 도달 시 당일 신규 매수 차단
- **연속 손절**: 3회 도달 시 당일 신규 매수 차단
- **변동성 차단**: 직전 1H봉 변동폭이 ATR × 3 이상이면 사이클 스킵
- **슬리피지 검사**: 호가 기준 예상 체결가가 0.5% 이상 불리하면 매수 취소

### 운영
| 항목 | 값 |
|------|------|
| 실행 주기 | 매 정시 (1시간봉) |
| 거래 대상 | KRW-BTC (단일 종목) |
| 배정 예산 | 1,000,000원 (변경 가능) |
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
# 상태 확인
sudo systemctl status upbit-trader

# 실시간 로그
journalctl -u upbit-trader -f

# 재시작
sudo systemctl restart upbit-trader

# 중지
sudo systemctl stop upbit-trader

# 거래 내역 확인
cat trades.csv

# 현황 확인
cat status.json
```

---

## 거래 기록 파일

| 파일 | 내용 |
|------|------|
| `trades.csv` | 매수/매도 전체 내역 (매수가, 매도가, 손익, MA20/50/200, RSI, ATR 등) |
| `status.json` | 누적 손익, 승률, 일일 실현손익 / 연속손절 / 거래중단 플래그 |
| `position.json` | 현재 보유 포지션 상태 (매수가, ATR, 손절가, 고점, TP 진행) |
| `trader.log` | 실행 로그 전체 |

---

## 주의사항

- `.env` 파일은 절대 GitHub에 올리지 마세요 (`.gitignore`에 포함됨)
- 처음에는 소액으로 1~2주 모니터링 후 예산 증액 권장
- 본 전략은 **상승장 한정**으로 진입합니다 (MA200 위에서만). 강한 하락장에서는 자동으로 매수가 멈춥니다.
- 분할 익절 구조상 한 번의 큰 상승에서 전량 익절되지 않습니다 — 잔여 20%는 트레일링 스탑으로 추적합니다.
- 자동매매는 어디까지나 보조 도구입니다. 정기적으로 거래내역과 상태를 확인하세요.
