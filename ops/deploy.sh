#!/usr/bin/env bash
# gbrain · deploy workers on the VPS (run as root once the repo is at /opt/gbrain)
# Usage:  sudo bash ops/deploy.sh
set -euo pipefail

APP_DIR=/opt/gbrain
APP_USER=gbrain

echo "==> system deps"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip

echo "==> service user"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

echo "==> venv + deps"
cd "$APP_DIR"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

echo "==> permissions"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
[ -f "$APP_DIR/.env" ] && chmod 600 "$APP_DIR/.env" || echo "  ! create $APP_DIR/.env (cp .env.example .env) and set DATABASE_URL"

echo "==> systemd units"
cp ops/systemd/gbrain-normalize.service /etc/systemd/system/
cp ops/systemd/gbrain-sweeper.service   /etc/systemd/system/
cp ops/systemd/gbrain-sweeper.timer     /etc/systemd/system/
systemctl daemon-reload

echo
echo "Next:"
echo "  1) ensure $APP_DIR/.env has DATABASE_URL (Supabase direct, port 5432)"
echo "  2) sudo -u $APP_USER ./.venv/bin/python -m tests.test_dedup   # must print ALL PASSED"
echo "  3) systemctl enable --now gbrain-normalize gbrain-sweeper.timer"
echo "  4) journalctl -u gbrain-normalize -f"
