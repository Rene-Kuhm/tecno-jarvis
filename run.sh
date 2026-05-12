#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[Tecno--J.A.R.V.I.S runner] No se encontro .venv."
  echo "Ejecuta sh install.sh primero."
  exit 1
fi

".venv/bin/python" main.py
