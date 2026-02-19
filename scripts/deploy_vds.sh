#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   DEPLOY_HOST=194.87.55.48 DEPLOY_USER=root ./scripts/deploy_vds.sh
# Optional:
#   DEPLOY_PORT=22
#   DEPLOY_PATH=/opt/bridge-bot

DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/bridge-bot}"

if [[ -z "$DEPLOY_HOST" ]]; then
  echo "ERROR: DEPLOY_HOST is required (example: 194.87.55.48)" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found in repository root. Copy .env.example -> .env and fill tokens." >&2
  exit 1
fi

SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_OPTS=(-p "$DEPLOY_PORT" -o StrictHostKeyChecking=accept-new)

REMOTE_TMP="$(mktemp -u)/bridge-bot.tar.gz"

echo "[1/4] Packing project..."
tar \
  --exclude-vcs \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='state/archives' \
  -czf /tmp/bridge-bot.tar.gz .

echo "[2/4] Uploading archive to ${SSH_TARGET}..."
scp "${SSH_OPTS[@]}" /tmp/bridge-bot.tar.gz "${SSH_TARGET}:${REMOTE_TMP}"

echo "[3/4] Preparing server and deploying..."
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" bash -s -- "$DEPLOY_PATH" "$REMOTE_TMP" <<'REMOTE'
set -euo pipefail
DEPLOY_PATH="$1"
REMOTE_TMP="$2"

mkdir -p "$DEPLOY_PATH"
cd "$DEPLOY_PATH"

tar -xzf "$REMOTE_TMP" -C "$DEPLOY_PATH"
rm -f "$REMOTE_TMP"

if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

docker compose pull || true
docker compose up -d --build
REMOTE

echo "[4/4] Done. Service status:"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "cd '$DEPLOY_PATH' && docker compose ps"

echo "Deployment completed successfully."
