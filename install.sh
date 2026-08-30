#!/usr/bin/env bash
# PrimoVoice — installer do projeto inteiro.
#
# Faz:
#   1. confere ffmpeg e Python 3.12
#   2. cria venv em engine/.venv
#   3. instala o engine (pyproject.toml) — com [resemble] opcional
#   4. baixa modelos sob demanda (deepfilter é o único obrigatório)
#   5. cria symlink do painel em ~/Library/Application Support/Blackmagic Design/
#      DaVinci Resolve/Fusion/Scripts/Utility/PrimoVoice.py
#   6. imprime próximos passos
#
# Uso:
#   ./install.sh                  # instalação mínima (deepfilter + demucs)
#   ./install.sh --with-resemble  # + Resemble-Enhance (~300 MB a mais)
#   ./install.sh --no-panel       # pula o symlink do painel (CLI só)
#   ./install.sh --uninstall      # desfaz tudo (remove venv, symlink, .ok markers)
#
# Idempotente: pode rodar de novo sem quebrar.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="$HERE/engine"
VENV="$ENGINE_DIR/.venv"
PY="$VENV/bin/python"
RESOLVE_SCRIPTS="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
SYMLINK="$RESOLVE_SCRIPTS/PrimoVoice.py"
SRC_PANEL="$HERE/resolve/PrimoVoice.py"

WITH_RESEMBLE=0
NO_PANEL=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --with-resemble) WITH_RESEMBLE=1 ;;
    --no-panel)      NO_PANEL=1 ;;
    --uninstall)     UNINSTALL=1 ;;
    -h|--help)
      grep '^# ' "$0" | sed 's/^# //'
      exit 0
      ;;
    *) echo "flag desconhecida: $arg (use --help)" >&2; exit 2 ;;
  esac
done

# ----- Uninstall -----------------------------------------------------------
if [[ $UNINSTALL -eq 1 ]]; then
  echo "→ removendo venv..."
  rm -rf "$VENV"
  echo "→ removendo symlink do painel..."
  rm -f "$SYMLINK"
  echo "→ removendo marcadores .ok dos modelos..."
  rm -f "$HOME/Library/Application Support/PrimoVoice/models/"*.ok 2>/dev/null || true
  echo "✓ desinstalado."
  exit 0
fi

# ----- Pre-checks ---------------------------------------------------------
echo "→ conferindo pré-requisitos..."

if ! command -v ffmpeg >/dev/null; then
  echo "✗ ffmpeg não encontrado. Instale com: brew install ffmpeg" >&2
  exit 1
fi
if ! command -v ffprobe >/dev/null; then
  echo "✗ ffprobe não encontrado. Instale com: brew install ffmpeg" >&2
  exit 1
fi

# Python 3.12 (a versão pinned no requirements).
PYTHON="${PYTHON:-python3.12}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  if command -v brew >/dev/null; then
    echo "  $PYTHON não encontrado; instalando via Homebrew (vai pedir senha)..."
    brew install python@3.12
    PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
  else
    echo "✗ $PYTHON não encontrado. Instale Python 3.12 (https://www.python.org) ou via brew install python@3.12" >&2
    exit 1
  fi
fi
echo "  ✓ ffmpeg:   $(ffmpeg -version | head -1 | awk '{print $2, $3}')"
echo "  ✓ Python:   $($PYTHON --version)"
echo "  ✓ Repo:     $HERE"

# ----- Venv + engine install ----------------------------------------------
if [[ ! -d "$VENV" ]]; then
  echo "→ criando venv em $VENV..."
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip wheel
fi
# Sempre usa o Python do venv daqui pra frente (PEP 668: pip do system
# Python é bloqueado, venv é o caminho).
echo "→ instalando engine no venv..."
if [[ $WITH_RESEMBLE -eq 1 ]]; then
  "$VENV/bin/python" -m pip install -q -e "$ENGINE_DIR"[resemble]
else
  "$VENV/bin/python" -m pip install -q -e "$ENGINE_DIR"
fi

# ----- Modelos (download sob demanda) -------------------------------------
echo "→ conferindo modelos (download sob demanda na primeira execução)..."
"$VENV/bin/python" -m vc.cli models >/dev/null
# Dispara o download do deepfilter (obrigatório pro smoke default).
"$VENV/bin/python" -m vc.cli download deepfilter
# Demucs é opcional mas o painel recomenda — baixa se o user não vetou.
if [[ $WITH_RESEMBLE -eq 0 ]]; then
  "$VENV/bin/python" -m vc.cli download demucs || echo "  (demucs não baixou; sem ele o smoke fica sem faixa de música)"
fi
if [[ $WITH_RESEMBLE -eq 1 ]]; then
  "$VENV/bin/python" -m vc.cli download resemble || echo "  (resemble não baixou; sem ele o preset max-quality falha)"
fi

# ----- Symlink do painel no Resolve ---------------------------------------
if [[ $NO_PANEL -eq 0 ]]; then
  if [[ ! -f "$SRC_PANEL" ]]; then
    echo "  ! painel não encontrado em $SRC_PANEL; pulando symlink (use --no-panel pra suprimir)"
  else
    mkdir -p "$RESOLVE_SCRIPTS"
    if [[ -L "$SYMLINK" && "$(readlink "$SYMLINK")" == "$SRC_PANEL" ]]; then
      echo "  ✓ symlink do painel já no lugar"
    elif [[ -e "$SYMLINK" ]]; then
      echo "  ! $SYMLINK existe e não aponta pro repo; apaga manualmente se quiser re-linkar"
    else
      ln -s "$SRC_PANEL" "$SYMLINK"
      echo "  ✓ symlink do painel criado em $SYMLINK"
    fi
  fi
fi

# ----- Done ---------------------------------------------------------------
cat <<'EOF'

✓ PrimoVoice instalado.

Próximos passos:
  1. Abre o DaVinci Resolve
  2. Carrega uma timeline com áudio
  3. Workspace ▸ Scripts ▸ PrimoVoice
  4. Escolhe um preset e clica "Processar timeline"

Standalone (sem Resolve):
  engine/.venv/bin/primovoice presets
  engine/.venv/bin/primovoice process entrada.wav -o saida.wav --preset podcast

Para desinstalar:
  ./install.sh --uninstall
EOF
