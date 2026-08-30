#!/usr/bin/env bash
# Shim: delega pro install.sh na raiz do projeto. Mantido por retrocompat —
# novos usuários devem usar ../install.sh direto.
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/../install.sh" "$@"
