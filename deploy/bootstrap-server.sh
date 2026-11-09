#!/usr/bin/env bash
# Hunter - first-time setup on a fresh Ubuntu 24.04 server (run as root once).
# Creates user "hunter", installs uv + Python 3.14.7, clones the repo, installs
# the locked environment, then enables the web app and the daily feed refresh.
# The web app listens on 127.0.0.1 only: reach it through an SSH tunnel
#   ssh -L 8765:127.0.0.1:8765 hunter@<server>
set -euo pipefail
REPO_URL="${REPO_URL:-https://github.com/welmarr/quant-hunter.git}"
BRANCH="${BRANCH:-integrate/v0-product-extension}"
HOME_DIR=/opt/hunter

apt-get update -y
apt-get install -y git curl ca-certificates ufw unattended-upgrades
ufw default deny incoming && ufw allow OpenSSH && ufw --force enable

id hunter >/dev/null 2>&1 || useradd --system --create-home --home-dir "$HOME_DIR" --shell /bin/bash hunter
sudo -u hunter bash -lc "curl -LsSf https://astral.sh/uv/0.12.10/install.sh | sh"
sudo -u hunter bash -lc "
  set -e
  cd $HOME_DIR
  [ -d app ] || git clone --branch $BRANCH $REPO_URL app
  cd app && git fetch && git checkout $BRANCH && git pull --ff-only
  ~/.local/bin/uv python install 3.14.7
  ~/.local/bin/uv sync --locked --group dev
"
install -d -o hunter -g hunter -m 0700 "$HOME_DIR/runtime" "$HOME_DIR/private"
install -m 0644 "$(dirname "$0")/systemd/hunter-web.service" /etc/systemd/system/
install -m 0644 "$(dirname "$0")/systemd/hunter-feeds.service" /etc/systemd/system/
install -m 0644 "$(dirname "$0")/systemd/hunter-feeds.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now hunter-feeds.timer
systemctl enable --now hunter-web.service
echo "Hunter installed. Web: ssh -L 8765:127.0.0.1:8765 hunter@<server>, then http://127.0.0.1:8765"
