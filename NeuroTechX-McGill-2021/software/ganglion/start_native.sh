#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$APP_DIR/../.." && pwd)"
echo 'Ganglion 직접 연결 SSVEP: http://127.0.0.1:8004 — GUI와 다른 수집 스크립트를 종료하세요.'
exec "$REPO_DIR/.venv-brainflow-validation/bin/python" "$APP_DIR/native_app.py" "$@"
