#!/usr/bin/env bash
# Sobe o servidor para desenvolvimento, reiniciando sozinho quando o código muda.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/server/.venv"

[[ -x "$VENV/bin/acervo" ]] || { echo "Rode antes: scripts/setup-mac.sh" >&2; exit 1; }
[[ -f "$ROOT/acervo.toml" ]] || cp "$ROOT/acervo.example.toml" "$ROOT/acervo.toml"

cd "$ROOT/server"
exec "$VENV/bin/acervo" --config "$ROOT/acervo.toml" serve --reload "$@"
