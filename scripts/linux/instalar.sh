#!/usr/bin/env bash
# Instalador do Acervo num mini PC (Ubuntu 24.04 LTS / Debian 12, x86_64 ou ARM64).
# Pode rodar de novo a qualquer momento: só completa o que falta, nunca apaga dados.
#
#   sudo apt install -y git && git clone https://github.com/souzaq001/lcfilessave ~/acervo
#   bash ~/acervo/scripts/linux/instalar.sh
#
# Ele pergunta se é um Acervo novo ou uma migração (trazer tudo de outro servidor,
# por exemplo do Realme). Passo a passo completo: docs/migrar.md
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
CONF="$REPO/acervo.toml"
VENV="$REPO/server/.venv"
NODE_DIR="$HOME/.local/acervo-node"
ME="$(id -un)"

say()  { printf '\n\033[1;36m› %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ask()  { local a; read -r -p "  $1 [s/N] " a; [[ "$a" =~ ^[sS]$ ]]; }

[[ "$(uname -s)" == "Linux" ]] || die "Este instalador é para Linux. No Realme use scripts/termux/instalar.sh."
[[ $EUID -ne 0 ]] || die "Rode como seu usuário normal (sem sudo); ele pede a senha quando precisar."
command -v apt-get >/dev/null || die "Precisa de Ubuntu ou Debian (apt). Veja docs/migrar.md."

if [[ -f "$CONF" && "${1:-}" == "--atualizar" ]]; then
  MODE=1  # update: keep config and data, just refresh code, interface and service
  say "Atualizando o Acervo (dados e configuração ficam como estão)"
else
  say "Este mini PC vai ser:"
  echo "  1) um Acervo novo, vazio"
  echo "  2) o novo lar de um Acervo que já existe (migração, por exemplo do Realme)"
  read -r -p "  Escolha 1 ou 2: " MODE
  [[ "$MODE" == "1" || "$MODE" == "2" ]] || die "Responda 1 ou 2."
fi

say "1/8 Pacotes do sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git curl xz-utils sqlite3 \
  libimage-exiftool-perl ffmpeg poppler-utils tesseract-ocr tesseract-ocr-por >/dev/null
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "O Python deste sistema é antigo ($(python3 --version)). Use Ubuntu 24.04 LTS ou Debian 12."
ok "python $(python3 -c 'import platform; print(platform.python_version())'), exiftool, ffmpeg, poppler, tesseract"

say "2/8 Node.js (só para compilar a interface)"
NODE_BIN="$(command -v node || true)"
if [[ -n "$NODE_BIN" ]] && node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22)||(a===20&&b>=19)?0:1)'; then
  ok "node $(node --version) do sistema"
else
  case "$(uname -m)" in x86_64) ARCH=x64 ;; aarch64|arm64) ARCH=arm64 ;; *) die "Arquitetura $(uname -m) não suportada." ;; esac
  if [[ ! -x "$NODE_DIR/bin/node" ]]; then
    BASE="https://nodejs.org/dist/latest-v22.x"
    FILE="$(curl -fsSL "$BASE/SHASUMS256.txt" | awk -v a="linux-$ARCH.tar.xz" '$2 ~ a"$" {print $2}')"
    SUM="$(curl -fsSL "$BASE/SHASUMS256.txt" | awk -v f="$FILE" '$2 == f {print $1}')"
    TMP="$(mktemp -d)"
    curl -fsSL -o "$TMP/$FILE" "$BASE/$FILE"
    echo "$SUM  $TMP/$FILE" | sha256sum -c --quiet || die "Download do Node corrompido."
    mkdir -p "$NODE_DIR" && tar -xJf "$TMP/$FILE" -C "$NODE_DIR" --strip-components=1
    rm -rf "$TMP"
  fi
  export PATH="$NODE_DIR/bin:$PATH"
  ok "node $(node --version) (instalado só para o Acervo em $NODE_DIR)"
fi

say "3/8 Servidor e interface"
[[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -e "$REPO/server[heic,https]"
(cd "$REPO/web" && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent)
ok "instalado"

say "4/8 Onde guardar os dados"
if [[ -f "$CONF" ]]; then
  # Existing installation: the data folder is whatever acervo.toml says, never a new guess.
  DATA="$("$VENV/bin/acervo" --config "$CONF" config | awk -F': +' '/^pasta de dados/ {print $2}')"
  [[ -n "$DATA" ]] || die "Não consegui ler data_dir de $CONF."
else
  DEFAULT_DATA="$HOME/acervo-dados"
  read -r -p "  Pasta dos dados [$DEFAULT_DATA]: " DATA
  DATA="${DATA:-$DEFAULT_DATA}"
fi
mkdir -p "$DATA"
ok "$DATA ($(df -h "$DATA" | awk 'NR==2 {print $4}') livres)"

say "5/8 Rede"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -n "$IP" ]] || read -r -p "  Não achei o IP deste mini PC. Digite (ex.: 192.168.0.60): " IP
ok "IP local: $IP (reserve este IP no roteador)"
if ! command -v tailscale >/dev/null; then
  if ask "Instalar o Tailscale (acesso de fora de casa, sem abrir portas)?"; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
fi
TS_NAME=""
if command -v tailscale >/dev/null; then
  if ! tailscale status >/dev/null 2>&1; then
    echo "  Vamos entrar no Tailscale com o nome fixo 'acervo'."
    echo "  (Numa migração, renomeie antes o aparelho antigo para 'acervo-antigo' — docs/migrar.md.)"
    sudo tailscale up --hostname=acervo
  fi
  TS_NAME="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
  [[ -n "$TS_NAME" ]] && ok "Tailscale: $TS_NAME"
fi

if [[ ! -f "$CONF" ]]; then
  read -r -p "  Seu e-mail (só vai junto dos avisos para o serviço da Apple; Enter para pular): " EMAIL
  {
    echo "# Gerado pelo scripts/linux/instalar.sh em $(date '+%d/%m/%Y'). Comentários: acervo.example.toml"
    echo "data_dir = \"$DATA\""
    echo "host = \"0.0.0.0\""
    echo "port = 8765"
    echo "server_name = \"Mini PC\""
    echo "https = true"
    echo -n "tls_names = [\"$IP\", \"$(hostname)\""; [[ -n "$TS_NAME" ]] && echo -n ", \"$TS_NAME\""; echo "]"
    echo "storage_alert_pct = 80"
    echo "archive_batch_gb = 80"
    echo "archive_copies = 1"
    echo "remote_mode = \"seguro\""
    if [[ -n "${EMAIL:-}" ]]; then echo "push_contact = \"mailto:$EMAIL\""; fi
  } > "$CONF"
  ok "criado $CONF"
else
  ok "mantido $CONF"
fi
ACERVO="$VENV/bin/acervo --config $CONF"

if [[ "$MODE" == "2" ]]; then
  say "6/8 Migração: trazendo o acervo do servidor antigo"
  echo "  No servidor antigo (Termux do Realme), crie um token:   acervo-ctl token migracao"
  echo "  e veja a impressão do certificado com:                acervo-ctl status"
  read -r -p "  Endereço do servidor antigo (ex.: https://192.168.0.50:8765): " OLD
  sudo systemctl stop acervo 2>/dev/null || true
  until $ACERVO migrar --de "$OLD"; do
    ask "Algo falhou (a mensagem acima diz o quê). Tentar de novo de onde parou?" || die "Rode de novo quando quiser: $ACERVO migrar --de $OLD"
  done
else
  say "6/8 Senha"
  # An update changes the catalog schema: never under a running server.
  systemctl is-active --quiet acervo 2>/dev/null && sudo systemctl stop acervo
  $ACERVO migrate >/dev/null
  if $VENV/bin/python - "$DATA/catalogo.db" <<'EOF'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
sys.exit(0 if c.execute("SELECT 1 FROM settings WHERE key='password_hash'").fetchone() else 1)
EOF
  then ok "senha já definida"; else $ACERVO senha; fi
fi

say "7/8 HTTPS, cidades e serviço"
$ACERVO certificado   # mantém a autoridade que veio na migração: o iPhone continua confiando
[[ -f "$DATA/geo/cities.txt" ]] || $ACERVO baixar-cidades || warn "sem internet agora; depois: acervo-ctl cidades"
sudo tee /etc/systemd/system/acervo.service >/dev/null <<EOF
[Unit]
Description=Acervo (backup de fotos e documentos)
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$ME
ExecStart="$VENV/bin/acervo" --config "$CONF" serve
Restart=always
RestartSec=5
Nice=5
# Dá tempo para terminar uma gravação antes de parar
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable acervo >/dev/null
sudo systemctl restart acervo   # loads new code, schema and certificate (also on updates)
if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow from 10.0.0.0/8 to any port 8765 proto tcp >/dev/null
  sudo ufw allow from 172.16.0.0/12 to any port 8765 proto tcp >/dev/null
  sudo ufw allow from 192.168.0.0/16 to any port 8765 proto tcp >/dev/null
  sudo ufw allow in on tailscale0 to any port 8765 proto tcp >/dev/null
  ok "firewall: porta 8765 só para a rede de casa e o Tailscale"
fi
sed "s|^REPO_INSTALLED=.*|REPO_INSTALLED=\"$REPO\"|" "$REPO/scripts/linux/acervo-ctl" \
  | sudo tee /usr/local/bin/acervo-ctl >/dev/null
sudo chmod 755 /usr/local/bin/acervo-ctl
ok "serviço acervo ativo (sobe sozinho quando o mini PC liga)"

say "8/8 Conferindo"
sleep 4
acervo-ctl status || true

cat <<EOF

────────────────────────────────────────────────────────────────────
 PRONTO.  Em casa:          https://$IP:8765
EOF
[[ -n "$TS_NAME" ]] && echo "          De qualquer lugar: https://$TS_NAME:8765"
cat <<EOF
 Certificado para instalar (só se for um Acervo novo): https://$IP:8765/ca.crt
EOF
[[ "$MODE" == "2" ]] && cat <<EOF

 MIGRAÇÃO: confira o relatório em $DATA/MIGRACAO.txt e siga o
 "Depois da cópia" em docs/migrar.md antes de desligar o servidor antigo.
EOF
echo "────────────────────────────────────────────────────────────────────"
