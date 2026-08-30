#!/usr/bin/env bash
# Cria o venv isolado do engine PrimoVoice e instala as dependências.
# Uso: ./setup.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

PY="${PYTHON:-python3.12}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "==> $PY não encontrado. Instalando via Homebrew…"
  brew install python@3.12
  PY="$(brew --prefix)/bin/python3.12"
fi

echo "==> Criando venv em .venv com $($PY --version)"
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Atualizando pip"
pip install --upgrade pip wheel

echo "==> Instalando dependências"
pip install -r requirements.txt

echo ""
echo "Pronto. Ative com:  source engine/.venv/bin/activate"
echo "Teste:  python -m vc.cli models"
