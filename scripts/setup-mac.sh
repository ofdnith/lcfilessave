#!/usr/bin/env bash
# Prepara o ambiente de desenvolvimento no Mac (roda uma vez, e de novo quando
# as dependências mudarem). Não instala nada fora da pasta do projeto, exceto
# o Python via Homebrew se você autorizar.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="$ROOT/server"

say()  { printf '\033[1;36m›\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Achar um Python 3.11+ (o do macOS é 3.9, antigo demais)
PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$(command -v "$candidate")"
    break
  fi
done

if [[ -z "$PY" ]]; then
  if command -v brew >/dev/null 2>&1; then
    say "Python 3.11+ não encontrado. Instalar python@3.12 pelo Homebrew? [s/N]"
    read -r answer
    [[ "$answer" =~ ^[sS]$ ]] || fail "Instale um Python 3.11+ e rode este script de novo."
    brew install python@3.12
    PY="$(brew --prefix python@3.12)/bin/python3.12"
  else
    fail "Precisa de Python 3.11+. Instale o Homebrew (https://brew.sh) e rode: brew install python@3.12"
  fi
fi
say "Usando $("$PY" --version) em $PY"

# 2. SQLite com tabelas STRICT
"$PY" - <<'EOF' || fail "O SQLite deste Python é antigo (precisa 3.37+). Use o Python do Homebrew."
import sqlite3, sys
print(f"  SQLite {sqlite3.sqlite_version}")
sys.exit(0 if sqlite3.sqlite_version_info >= (3, 37) else 1)
EOF

# 3. Ambiente virtual com o servidor e as ferramentas de teste
if [[ ! -x "$SERVER/.venv/bin/python" ]]; then
  say "Criando ambiente virtual em server/.venv"
  "$PY" -m venv "$SERVER/.venv"
fi
say "Instalando dependências"
"$SERVER/.venv/bin/pip" install --quiet --upgrade pip
"$SERVER/.venv/bin/pip" install --quiet -e "$SERVER[dev]"

# 4. Configuração local de desenvolvimento
if [[ ! -f "$ROOT/acervo.toml" ]]; then
  cp "$ROOT/acervo.example.toml" "$ROOT/acervo.toml"
  say "Criado acervo.toml (dados de teste em ./dev-dados)"
fi

say "Pronto. Próximos passos:"
echo "    scripts/dev.sh    # sobe o servidor em http://127.0.0.1:8765"
echo "    scripts/test.sh   # roda os testes"
