# 업비트 BTC 자동매매 프로그램

이동평균선(MA) + RSI 기반 단기매매 자동화 프로그램

---

## 전략 요약

| 항목 | 내용 |
|------|------|
| 매수 신호 | 단기MA(7) > 장기MA(25) 골든크로스 + RSI < 70 |
| 매도 신호 | 단기MA(7) < 장기MA(25) 데드크로스 |
| 손절 | 매수가 대비 -2% |
| 익절 | 매수가 대비 +3% |
| 실행 주기 | 매 정시 (1시간봉 기준) |
| 배정 예산 | 1,000,000원 |
| 1회 매수 | 100,000원 |

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
| `trades.csv` | 매수/매도 전체 내역 (매수가, 매도가, 손익, 손익률, 사유 등) |
| `status.json` | 누적 손익, 승률, 거래횟수 요약 |
| `trader.log` | 실행 로그 전체 |

---

## 주의사항

- `.env` 파일은 절대 GitHub에 올리지 마세요 (`.gitignore`에 포함됨)
- 처음엔 소액으로 1~2주 테스트 후 예산 증액 권장
- 이동평균선 전략은 횡보장에서 손절이 잦을 수 있음
