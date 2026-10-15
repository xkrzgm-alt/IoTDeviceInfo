#!/usr/bin/env bash
# Deploy the IoTdeviceInfo FastAPI service to the Aliyun host.
# Run from the IoTdeviceInfo project root using Bash/WSL/Git Bash.
# Credentials are managed separately via ops/credentials/sync_aliyun.py.
set -Eeuo pipefail

SSH_TARGET="${SSH_TARGET:-root@118.31.49.14}"
REMOTE_DIR="${REMOTE_DIR:-/root/IoTdeviceInfo}"
REMOTE_PORT="${REMOTE_PORT:-8080}"
HEALTH_PATH="${HEALTH_PATH:-/health}"
UPDATE_DEVICE_CREDENTIALS="${UPDATE_DEVICE_CREDENTIALS:-0}"

if [[ "$UPDATE_DEVICE_CREDENTIALS" != "0" ]]; then
  echo "Credential updates moved to ops/credentials/sync_aliyun.py" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FILES=(
  "config.py"
  "hongdian_client.py"
  "jc_module_client.py"
  "backend/routers/query.py"
  "backend/models/schemas.py"
)

for file in "${FILES[@]}"; do
  [[ -f "$file" ]] || { echo "Missing deployment file: $file" >&2; exit 1; }
done

command -v ssh >/dev/null || { echo "ssh is required" >&2; exit 1; }
command -v scp >/dev/null || { echo "scp is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  echo "Running tests..."
  python -m pytest -q tests
  python -m compileall -q .
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
staging="/tmp/iotdeviceinfo-deploy-${timestamp}-$$"
backup="/root/IoTdeviceInfo-backup-${timestamp}.tgz"

cleanup() {
  ssh "$SSH_TARGET" "rm -rf '$staging'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Preparing remote staging directory..."
ssh "$SSH_TARGET" "mkdir -p '$staging/backend/routers' '$staging/backend/models'"

for file in "${FILES[@]}"; do
  echo "Uploading $file..."
  scp "$file" "$SSH_TARGET:$staging/$file"
done

echo "Creating remote backup: $backup"
ssh "$SSH_TARGET" "cd '$REMOTE_DIR' && tar czf '$backup' backend config.py router_code.py hongdian_client.py jc_module_client.py"

echo "Installing files..."
ssh "$SSH_TARGET" "install -m 0644 '$staging/config.py' '$REMOTE_DIR/config.py' && install -m 0644 '$staging/hongdian_client.py' '$REMOTE_DIR/hongdian_client.py' && install -m 0644 '$staging/jc_module_client.py' '$REMOTE_DIR/jc_module_client.py' && install -m 0644 '$staging/backend/routers/query.py' '$REMOTE_DIR/backend/routers/query.py' && install -m 0644 '$staging/backend/models/schemas.py' '$REMOTE_DIR/backend/models/schemas.py' && cd '$REMOTE_DIR' && python3 -m compileall -q backend config.py hongdian_client.py jc_module_client.py"

echo "Restarting FastAPI via systemd..."
ssh "$SSH_TARGET" "systemctl restart iot-backend.service && systemctl is-active --quiet iot-backend.service"

echo "Waiting for health check..."
for attempt in $(seq 1 20); do
  if ssh "$SSH_TARGET" "curl -fsS --max-time 5 http://127.0.0.1:${REMOTE_PORT}${HEALTH_PATH}"; then
    echo
    echo "Deployment successful. Backup: $backup"
    exit 0
  fi
  sleep 2
done

echo "Health check failed. Inspect $REMOTE_DIR/uvicorn.log and restore $backup if needed." >&2
exit 1
