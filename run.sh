#!/usr/bin/env bash
set -euo pipefail
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}"
