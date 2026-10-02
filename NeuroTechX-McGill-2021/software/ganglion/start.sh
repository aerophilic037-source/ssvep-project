#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$APP_DIR/../.." && pwd)"
if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
  echo "먼저 저장소 루트에서 python3 -m venv .venv 실행 후 requirements.txt를 설치하세요."
  exit 1
fi
exec "$REPO_DIR/.venv/bin/python" "$APP_DIR/app.py" "$@"
