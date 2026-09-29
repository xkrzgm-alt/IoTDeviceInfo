#!/usr/bin/env bash
# Deploy the IoTdeviceInfo FastAPI service to the Aliyun host.
# Run from the IoTdeviceInfo project root using Bash/WSL/Git Bash.
set -Eeuo pipefail

SSH_TARGET="${SSH_TARGET:-root@118.31.49.14}"
REMOTE_DIR="${REMOTE_DIR:-/root/IoTdeviceInfo}"
REMOTE_PORT="${REMOTE_PORT:-8080}"
HEALTH_PATH="${HEALTH_PATH:-/health}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FILES=(
  "hongdian_client.py"
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
ssh "$SSH_TARGET" "cd '$REMOTE_DIR' && tar czf '$backup' backend config.py router_code.py hongdian_client.py .env"

echo "Installing files..."
ssh "$SSH_TARGET" "install -m 0644 '$staging/hongdian_client.py' '$REMOTE_DIR/hongdian_client.py' && install -m 0644 '$staging/backend/routers/query.py' '$REMOTE_DIR/backend/routers/query.py' && install -m 0644 '$staging/backend/models/schemas.py' '$REMOTE_DIR/backend/models/schemas.py' && cd '$REMOTE_DIR' && python3 -m compileall -q backend hongdian_client.py"

echo "Restarting FastAPI..."
ssh "$SSH_TARGET" "pid=\$(pgrep -f '/usr/bin/python3 -m uvicorn backend.main:app' | head -n1 || true); if [ -n \"\$pid\" ]; then kill \"\$pid\"; fi; for i in \$(seq 1 20); do pgrep -f '/usr/bin/python3 -m uvicorn backend.main:app' >/dev/null || break; sleep 1; done; nohup /usr/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port '$REMOTE_PORT' > '$REMOTE_DIR/uvicorn.log' 2>&1 < /dev/null &"

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
