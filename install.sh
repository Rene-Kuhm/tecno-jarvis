#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  python3 install.py "$@"
elif command -v python >/dev/null 2>&1; then
  python install.py "$@"
else
  echo "[Tecno--J.A.R.V.I.S installer] Python 3.10+ no esta instalado."
  exit 1
fi
