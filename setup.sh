#!/bin/bash
# setup.sh — GCP VM 최초 1회 세팅 스크립트
# 실행: bash setup.sh

set -e
echo "===================================="
echo "  업비트 자동매매 VM 초기 세팅 시작"
echo "===================================="

# 1. 패키지 업데이트
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git

# 2. 가상환경 생성
python3 -m venv venv
source venv/bin/activate

# 3. 의존성 설치
pip install --upgrade pip
pip install -r requirements.txt

# 4. .env 파일 생성 안내
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  .env 파일이 생성되었습니다."
    echo "    아래 명령어로 API 키 / 대시보드 비밀번호를 입력해주세요:"
    echo "    nano .env"
    echo ""
fi

# 5. systemd 서비스 등록 (트레이더)
WORK_DIR=$(pwd)
USER_NAME=$(whoami)

sudo tee /etc/systemd/system/upbit-trader.service > /dev/null <<EOF
[Unit]
Description=Upbit Auto Trader
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${WORK_DIR}
ExecStart=${WORK_DIR}/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 6. systemd 서비스 등록 (대시보드)
sudo tee /etc/systemd/system/upbit-dashboard.service > /dev/null <<EOF
[Unit]
Description=Upbit Trader Dashboard (Streamlit)
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${WORK_DIR}
EnvironmentFile=${WORK_DIR}/.env
ExecStart=${WORK_DIR}/venv/bin/streamlit run dashboard.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 7. sudoers — 배포 스크립트가 비밀번호 없이 systemctl 재시작 가능하도록
SUDOERS_FILE="/etc/sudoers.d/upbit-trader"
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl restart upbit-trader, /bin/systemctl restart upbit-dashboard, /bin/systemctl status upbit-trader, /bin/systemctl status upbit-dashboard" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
fi

sudo systemctl daemon-reload
sudo systemctl enable upbit-trader
sudo systemctl enable upbit-dashboard

echo ""
echo "===================================="
echo "  세팅 완료!"
echo ""
echo "  다음 단계:"
echo "  1. nano .env                                 (API 키 + DASHBOARD_PASSWORD 입력)"
echo "  2. sudo systemctl start upbit-trader         (트레이더 시작)"
echo "  3. sudo systemctl start upbit-dashboard      (대시보드 시작)"
echo "  4. http://<VM_외부_IP>:8501                  (대시보드 접속)"
echo ""
echo "  로그 보기:"
echo "  - journalctl -u upbit-trader -f"
echo "  - journalctl -u upbit-dashboard -f"
echo "===================================="
