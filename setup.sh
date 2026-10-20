#!/bin/bash
# One-command setup + run on Amazon Linux 2023.   Usage: bash setup.sh
# Optional: ADMIN_PASSWORD=mypass S3_BUCKET=my-bucket bash setup.sh
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin123}"
S3_BUCKET="${S3_BUCKET:-}"
SECRET_KEY="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"

echo "[1/4] Installing Python tools..."
sudo dnf install -y python3 python3-pip

echo "[2/4] Creating virtual environment & installing packages..."
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

echo "[3/4] Registering background service (auto-starts on reboot)..."
sudo tee /etc/systemd/system/noticeboard.service >/dev/null <<UNIT
[Unit]
Description=Campus Notice Board v2
After=network.target
[Service]
User=$USER
WorkingDirectory=$APP_DIR
Environment=ADMIN_PASSWORD=$ADMIN_PASSWORD
Environment=S3_BUCKET=$S3_BUCKET
Environment=SECRET_KEY=$SECRET_KEY
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/app.py
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable noticeboard
sudo systemctl restart noticeboard

echo "[4/4] Checking health..."
sleep 2
curl -s http://localhost:5000/health && echo
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
echo "Open in browser:  http://$IP:5000   (admin password: $ADMIN_PASSWORD)"
