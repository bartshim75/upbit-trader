#!/bin/bash
# setup.sh — GCP VM 최초 1회 세팅 스크립트
# 실행: bash setup.sh

set -e
echo "===================================="
echo "  업비트 자동매매 VM 초기 세팅 시작"
echo "===================================="

# 1. 패키지 업데이트
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git nginx

# 2. 가상환경 생성 (기존 환경은 보존)
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 3. 의존성 설치
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

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
DASHBOARD_LISTEN_PORT=$("${WORK_DIR}/venv/bin/python" -c "import config; print(config.DASHBOARD_PORT)")

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

# 6. systemd 서비스 등록 (대시보드 API)
sudo tee /etc/systemd/system/upbit-dashboard.service > /dev/null <<EOF
[Unit]
Description=Upbit Trader Dashboard API (FastAPI)
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${WORK_DIR}
EnvironmentFile=${WORK_DIR}/.env
ExecStartPre=+/usr/bin/install -d -o www-data -g www-data /var/www/upbit-trader-dashboard
ExecStartPre=+/usr/bin/install -m 0644 ${WORK_DIR}/web/index.html ${WORK_DIR}/web/styles.css ${WORK_DIR}/web/theme.js ${WORK_DIR}/web/app.js /var/www/upbit-trader-dashboard/
ExecStartPre=+/usr/bin/install -d -o www-data -g www-data /var/www/upbit-trader-dashboard/assets
ExecStartPre=+/usr/bin/install -m 0644 ${WORK_DIR}/brand-assets/app-icon-upbit-trader.png /var/www/upbit-trader-dashboard/assets/
ExecStart=${WORK_DIR}/venv/bin/python -m uvicorn dashboard:app --host 127.0.0.1 --port ${DASHBOARD_LISTEN_PORT} --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 7. Nginx — 정적 파일 제공 + /api 프록시
sudo tee /etc/nginx/sites-available/upbit-trader-dashboard > /dev/null <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    root /var/www/upbit-trader-dashboard;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript application/json;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;

    location /api/ {
        proxy_pass http://127.0.0.1:${DASHBOARD_LISTEN_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30s;
    }

    location /assets/ {
        expires 7d;
        try_files \$uri =404;
    }

    location / {
        expires -1;
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/upbit-trader-dashboard /etc/nginx/sites-enabled/upbit-trader-dashboard
sudo nginx -t

# 8. sudoers — 배포 스크립트가 비밀번호 없이 systemctl 재시작 가능하도록
SUDOERS_FILE="/etc/sudoers.d/upbit-trader"
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl restart upbit-trader, /bin/systemctl restart upbit-dashboard, /bin/systemctl status upbit-trader, /bin/systemctl status upbit-dashboard" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
fi

sudo systemctl daemon-reload
sudo systemctl enable upbit-trader
sudo systemctl enable upbit-dashboard
sudo systemctl enable nginx
sudo systemctl restart nginx

echo ""
echo "===================================="
echo "  세팅 완료!"
echo ""
echo "  다음 단계:"
echo "  1. nano .env                                 (API 키 + DASHBOARD_PASSWORD 입력)"
echo "  2. sudo systemctl start upbit-trader         (트레이더 시작)"
echo "  3. sudo systemctl start upbit-dashboard      (대시보드 시작)"
echo "  4. http://<VM_외부_IP>                       (대시보드 접속)"
echo ""
echo "  로그 보기:"
echo "  - journalctl -u upbit-trader -f"
echo "  - journalctl -u upbit-dashboard -f"
echo "===================================="
