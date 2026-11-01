#!/data/data/com.termux/files/usr/bin/bash
# Instalador do Acervo no Realme (Termux). Pode rodar de novo a qualquer
# momento: ele só completa o que falta e nunca apaga dados.
#
#   pkg install -y git && git clone https://github.com/souzaq001/lcfilessave ~/acervo
#   bash ~/acervo/scripts/termux/instalar.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="$HOME/acervo-dados"
CONF="$REPO/acervo.toml"
VENV="$REPO/server/.venv"
BOOT="$HOME/.termux/boot"

say()  { printf '\n\033[1;36m› %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
ask()  { local a; read -r -p "  $1 [s/N] " a; [[ "$a" =~ ^[sS]$ ]]; }

[[ "${PREFIX:-}" == *com.termux* ]] || { echo "Rode este script dentro do Termux, no celular."; exit 1; }

say "1/9 Pacotes do sistema (pode levar alguns minutos)"
pkg update -y >/dev/null
pkg install -y python git exiftool ffmpeg poppler tesseract nodejs-lts termux-api \
  python-pillow python-cryptography libheif openssl curl >/dev/null
ok "python, exiftool, ffmpeg, poppler, tesseract, node"
# numpy speeds up near-duplicate search; optional, the server works without it.
pkg install -y python-numpy >/dev/null 2>&1 && ok "numpy (quase-duplicados rápidos)" \
  || warn "python-numpy não instalou; quase-duplicados usam Python puro. Tudo bem."

say "2/9 pydantic-core (base do FastAPI)"
if python -c "import pydantic_core" 2>/dev/null; then
  ok "já instalado"
elif pkg install -y python-pydantic-core >/dev/null 2>&1; then
  ok "instalado pelo pkg"
else
  warn "Sem pacote pronto: vou compilar (precisa do Rust; leva de 20 a 40 minutos, uma vez só)."
  pkg install -y rust binutils >/dev/null
  export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk)"
  pip install pydantic-core
  ok "compilado"
fi

say "3/9 Ambiente Python do Acervo"
[[ -x "$VENV/bin/python" ]] || python -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -e "$REPO/server"
if "$VENV/bin/pip" install --quiet pillow-heif 2>/dev/null; then
  ok "HEIC direto (pillow-heif)"
else
  warn "pillow-heif não instalou; miniaturas de HEIC usam a prévia embutida (exiftool). Tudo bem."
fi
ok "servidor instalado"

say "4/9 Interface"
if [[ -f "$REPO/web/package.json" ]]; then
  (cd "$REPO/web" && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent)
  ok "interface compilada"
else
  warn "pasta web/ sem package.json; usando a página provisória"
fi

say "5/9 Configuração"
if [[ -f "$CONF" ]]; then
  ok "mantida a configuração que já existe ($CONF): nada a responder"
fi
# The server finds its Wi-Fi and Tailscale addresses by itself every time it starts
# (acervo/publicname.py); this one only goes into the first certificate.
IP="$(termux-wifi-connectioninfo 2>/dev/null | python -c 'import json,sys; print(json.load(sys.stdin).get("ip",""))' 2>/dev/null || true)"
[[ "$IP" == "0.0.0.0" ]] && IP=""
STORAGE_OK=""
storage_access() {
  [[ -n "$STORAGE_OK" ]] && return
  termux-setup-storage || true
  sleep 3
  STORAGE_OK=1
}
BACKUP_DIR=""
SD_DIR=""
if [[ ! -f "$CONF" ]]; then
if ask "Guardar uma cópia diária do catálogo na memória compartilhada (recomendado)?"; then
  storage_access
  BACKUP_DIR="$HOME/storage/shared/Acervo-copia-do-catalogo"
fi
if ask "Usar o cartão microSD para guardar tudo o que passar pela triagem (recomendado se houver cartão)?"; then
  storage_access
  if [[ -d "$HOME/storage/external-1" ]]; then
    SD_DIR="$(readlink -f "$HOME/storage/external-1")/acervo"
    mkdir -p "$SD_DIR" && ok "cartão: $SD_DIR"
    warn "O cartão precisa estar como ARMAZENAMENTO PORTÁTIL (exFAT), nunca formatado como memória interna."
  else
    warn "Cartão não encontrado (~/storage/external-1). Depois de colocar o cartão: rode"
    warn "mkdir -p ~/storage/external-1/acervo, acrescente ao $CONF a linha"
    warn "sd_dir = \"$HOME/storage/external-1/acervo\"  e rode:  acervo-ctl restart"
  fi
fi
  read -r -p "  Seu e-mail (só vai junto dos avisos para o serviço da Apple; Enter para pular): " EMAIL
  {
    echo "# Gerado pelo instalar.sh em $(date '+%d/%m/%Y'). Comentários: acervo.example.toml"
    echo "data_dir = \"$DATA\""
    echo "host = \"0.0.0.0\""
    echo "port = 8765"
    echo "server_name = \"Realme\""
    echo "https = true"
    [[ -n "$IP" ]] && echo "tls_names = [\"$IP\"]"
    [[ -n "$BACKUP_DIR" ]] && echo "catalog_backup_dir = \"$BACKUP_DIR\""
    if [[ -n "$SD_DIR" ]]; then
      echo "sd_dir = \"$SD_DIR\""
      echo "sd_for_library = true"
    fi
    echo "inbox_max_gb = 100"
    echo "inbox_alert_days = 7"
    echo "inbox_alert_gb = 5"
    echo "max_temp_c = 40"
    echo "storage_alert_pct = 80"
    echo "archive_batch_gb = 5"
    echo "archive_copies = 1"
    if [[ -n "${EMAIL:-}" ]]; then echo "push_contact = \"mailto:$EMAIL\""; fi
  } > "$CONF"
  ok "criado $CONF"
fi
ACERVO="$VENV/bin/acervo --config $CONF"
$ACERVO migrate

say "6/9 Senha"
if $VENV/bin/python - "$DATA/catalogo.db" <<'EOF'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
sys.exit(0 if c.execute("SELECT 1 FROM settings WHERE key='password_hash'").fetchone() else 1)
EOF
then
  ok "senha já definida (para trocar: acervo-ctl senha)"
else
  $ACERVO senha
fi

say "7/9 HTTPS, endereço seguro, cidades e OCR em português"
$ACERVO certificado
# acme.sh gets the Let's Encrypt certificates for the DuckDNS names (acervo duckdns).
command -v openssl >/dev/null || pkg install -y openssl-tool >/dev/null 2>&1 || true
if [[ -f "$HOME/.acme.sh/acme.sh" ]]; then
  ok "acme.sh já instalado"
else
  ACME_TMP="$(mktemp -d)"
  if git clone -q --depth 1 https://github.com/acmesh-official/acme.sh "$ACME_TMP/acme.sh" \
     && (cd "$ACME_TMP/acme.sh" && sh ./acme.sh --install --home "$HOME/.acme.sh" \
         --config-home "$HOME/.acme.sh/data" --no-cron --no-profile >/dev/null); then
    ok "acme.sh (certificados do Let's Encrypt)"
  else
    warn "acme.sh não instalou agora; rode o instalador de novo mais tarde"
  fi
  rm -rf "$ACME_TMP"
fi
if [[ -f "$DATA/certificados/duckdns.json" ]]; then
  ok "endereço seguro (DuckDNS) já configurado"
elif ask "Configurar agora o endereço seguro (DuckDNS)? Com ele, o Safari e o app do Mac funcionam sem instalar certificado"; then
  $ACERVO duckdns || warn "não terminou; rode depois: acervo-ctl duckdns"
else
  warn "sem endereço seguro: o Safari e o app do Mac vão pedir o certificado. Configure com: acervo-ctl duckdns"
fi
$ACERVO baixar-cidades || warn "sem internet agora; rode depois: acervo-ctl cidades"
TESS="$PREFIX/share/tessdata"
if [[ ! -f "$TESS/por.traineddata" ]]; then
  curl -fsSL -o "$TESS/por.traineddata" \
    https://github.com/tesseract-ocr/tessdata_fast/raw/main/por.traineddata && ok "OCR em português" \
    || warn "não baixou o português do OCR; o OCR usa inglês"
fi

say "8/9 Início automático e supervisor"
mkdir -p "$BOOT" "$HOME/bin" "$DATA/logs"
install -m 755 "$REPO/scripts/termux/boot-acervo.sh" "$BOOT/acervo.sh"
install -m 755 "$REPO/scripts/termux/acervo-ctl" "$HOME/bin/acervo-ctl"
grep -q 'HOME/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
ok "Termux:Boot vai iniciar o Acervo quando o celular ligar"

say "9/9 Iniciando"
"$HOME/bin/acervo-ctl" start
sleep 5
"$HOME/bin/acervo-ctl" status || true

cat <<EOF

────────────────────────────────────────────────────────────────────
 PRONTO. Abra no iPhone ou no Mac:   https://$IP:8765
 Antes, instale o certificado:       https://$IP:8765/ca.crt
 (passo a passo em docs/iphone.md)

 Token para os Atalhos do iPhone:    acervo-ctl token iPhone
────────────────────────────────────────────────────────────────────
 CHECKLIST MANUAL — sem isto o Android mata o servidor (docs/realme.md)

 [ ] Opções do desenvolvedor → "Desativar restrições de processos filhos"
     (ou, pelo Mac com cabo:  adb shell settings put global
      settings_enable_monitor_phantom_procs false)
 [ ] Configurações → Bateria → Termux → "Permitir atividade em segundo
     plano" e "Início automático"; faça o mesmo com Termux:Boot e Termux:API
 [ ] Na tela de apps recentes, trave o Termux (cadeado)
 [ ] No roteador: reserve o IP $IP para este celular
 [ ] Bateria: ative "Carregamento otimizado"/limite de carga, se existir
 [ ] NUNCA desinstale o Termux: os dados ficam dentro dele ($DATA)
────────────────────────────────────────────────────────────────────
EOF
