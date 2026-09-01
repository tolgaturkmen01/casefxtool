#!/usr/bin/env bash
set -euo pipefail
[ -d .venv ] || python -m venv .venv
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
else
  source .venv/Scripts/activate
fi
pip install -q -r requirements.txt
exec pytest -q
