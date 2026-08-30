#!/usr/bin/env bash
# Smoke test do PrimoVoice.
# Roda o engine em tests/sample_in.wav e confere que a saída é gerada, tem a
# duração esperada e não saiu em silêncio. O resultado vai pra tests/out/, que
# está no .gitignore (é artefato reproduzível).
#
# Requisitos:
#   - engine instalado: cd engine && ./setup.sh
#   - modelos deepfilter (e idealmente demucs) baixados: engine/.venv/bin/python -m vc.cli download deepfilter
#   - ffmpeg/ffprobe no PATH
#
# Uso:
#   tests/smoke.sh

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
ENGINE_DIR="$ROOT/engine"
PY="$ENGINE_DIR/.venv/bin/python"
IN="$HERE/sample_in.wav"
OUT_DIR="$HERE/out"
OUT="$OUT_DIR/sample_out.wav"

# ---- Pre-checks -----------------------------------------------------------
if [[ ! -x "$PY" ]]; then
  echo "✗ engine não instalado: rode engine/setup.sh primeiro" >&2
  exit 1
fi
if ! command -v ffprobe >/dev/null; then
  echo "✗ ffprobe não encontrado (instale ffmpeg)" >&2
  exit 1
fi
if [[ ! -f "$IN" ]]; then
  echo "✗ fixture ausente: $IN" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

# ---- Run -----------------------------------------------------------------
echo "→ processando $IN"
echo "  cmd: (cd $ENGINE_DIR && $PY -m vc.cli process <in> -o <out> --speech 100 --music 10 --bg 10)"
# cwd=engine/ pra `vc` ser encontrado como módulo (-m vc.cli).
(cd "$ENGINE_DIR" && "$PY" -m vc.cli process "$IN" -o "$OUT" \
  --speech 100 --music 10 --bg 10 --no-normalize)

# ---- Validate ------------------------------------------------------------
# Duração da saída deve bater com a do input (6s do fixture).
IN_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
OUT_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")
IN_SR=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of csv=p=0 "$IN")
OUT_SR=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of csv=p=0 "$OUT")

echo "  in : ${IN_DUR}s @ ${IN_SR}Hz"
echo "  out: ${OUT_DUR}s @ ${OUT_SR}Hz"

# Tolerância de 0.1s na duração (ffmpeg pode arredondar).
awk -v a="$IN_DUR" -v b="$OUT_DUR" 'BEGIN{ if (a-b > 0.1 || b-a > 0.1) { exit 1 } }' \
  || { echo "✗ duração da saída diverge do input" >&2; exit 1; }

# SR deve bater.
if [[ "$IN_SR" != "$OUT_SR" ]]; then
  echo "✗ SR divergente: in=$IN_SR out=$OUT_SR" >&2
  exit 1
fi

# Pico da saída: max_volume em dBFS (0 = clipping, -∞ = silêncio).
# Usa ffmpeg volumedetect (zero-dep, já temos ffmpeg no pre-check).
# Saída em stderr no nível info, então precisa de `-v info` (não `-v error`).
PEAK=$(ffmpeg -v info -i "$OUT" -af "volumedetect" -f null - 2>&1 \
  | sed -n 's/.*max_volume:[[:space:]]*\([-0-9.]*\)[[:space:]]*dB.*/\1/p' \
  | head -1)
echo "  max_volume: ${PEAK} dBFS"
if [[ -z "$PEAK" ]]; then
  echo "✗ ffmpeg não reportou max_volume" >&2
  exit 1
fi
# Não pode estar estourada (max_volume > -0.5 dBFS = clipping) nem em
# silêncio (max_volume < -50 dBFS num fixture de 6s).
if awk -v p="$PEAK" 'BEGIN{ exit !(p > -0.5) }'; then
  echo "✗ saída estourada (max_volume=$PEAK dBFS, perto do clipping)" >&2
  exit 1
fi
if awk -v p="$PEAK" 'BEGIN{ exit !(p < -50) }'; then
  echo "✗ saída em silêncio (max_volume=$PEAK dBFS)" >&2
  exit 1
fi

echo "✓ smoke ok"
