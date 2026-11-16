#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$APP_DIR/../.." && pwd)"
if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
  echo "저장소 .venv가 없습니다. software/ganglion/README.md의 설치 안내를 먼저 실행하세요."
  exit 1
fi
echo "Ganglion 단계별 EEG 검증: http://127.0.0.1:8002 (포트 변경 시 변경한 주소 사용)"
exec "$REPO_DIR/.venv/bin/python" "$APP_DIR/validation_app.py" "$@"
