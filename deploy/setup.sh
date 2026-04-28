#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 24.04 server for the rotation bot.
# Run as root on a clean droplet:  bash setup.sh
set -euo pipefail

BOT_USER="botuser"
BOT_HOME="/home/${BOT_USER}"
REPO_DIR="${BOT_HOME}/binance-bot-"

echo "==> Updating package lists..."
apt-get update -y
apt-get upgrade -y

echo "==> Installing system packages..."
apt-get install -y \
    python3 python3-venv python3-pip \
    git curl ufw \
    build-essential

echo "==> Creating bot user..."
if ! id -u "${BOT_USER}" &>/dev/null; then
    adduser --disabled-password --gecos "" "${BOT_USER}"
fi

echo "==> Cloning repo as ${BOT_USER}..."
if [[ ! -d "${REPO_DIR}/.git" ]]; then
    sudo -u "${BOT_USER}" git clone https://github.com/acgpct/binance-bot-.git "${REPO_DIR}"
else
    echo "  repo already cloned, pulling latest"
    sudo -u "${BOT_USER}" git -C "${REPO_DIR}" pull --ff-only
fi

echo "==> Creating Python venv + installing dependencies..."
sudo -u "${BOT_USER}" python3 -m venv "${REPO_DIR}/.venv"
sudo -u "${BOT_USER}" "${REPO_DIR}/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "${BOT_USER}" "${REPO_DIR}/.venv/bin/pip" install --quiet -r "${REPO_DIR}/requirements.txt"

echo "==> Seeding .env if missing..."
if [[ ! -f "${REPO_DIR}/.env" ]]; then
    sudo -u "${BOT_USER}" cp "${REPO_DIR}/.env.example" "${REPO_DIR}/.env"
    chmod 600 "${REPO_DIR}/.env"
    chown "${BOT_USER}:${BOT_USER}" "${REPO_DIR}/.env"
    echo "  .env seeded — edit it with your testnet keys before starting the service"
fi

echo "==> Installing systemd service..."
cp "${REPO_DIR}/deploy/binance-bot.service" /etc/systemd/system/binance-bot.service
systemctl daemon-reload

echo "==> Configuring basic firewall (ssh only)..."
ufw allow OpenSSH
ufw --force enable

echo
echo "==> ✅ Setup complete."
echo
echo "Next steps:"
echo "  1. Edit testnet keys:    nano ${REPO_DIR}/.env"
echo "  2. Start the bot:        systemctl enable --now binance-bot"
echo "  3. Watch the logs:       journalctl -u binance-bot -f"
echo "  4. Check status:         systemctl status binance-bot"
