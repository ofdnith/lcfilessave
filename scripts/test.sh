#!/usr/bin/env bash
# Roda todos os testes automatizados do servidor.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/server/.venv"

[[ -x "$VENV/bin/pytest" ]] || { echo "Rode antes: scripts/setup-mac.sh" >&2; exit 1; }

cd "$ROOT/server"
exec "$VENV/bin/pytest" "$@"
