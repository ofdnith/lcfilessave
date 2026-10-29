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
IP="$(termux-wifi-connectioninfo 2>/dev/null | python -c 'import json,sys; print(json.load(sys.stdin).get("ip",""))' 2>/dev/null || true)"
if [[ -z "$IP" || "$IP" == "0.0.0.0" ]]; then
  read -r -p "  IP do celular no Wi-Fi (ex.: 192.168.0.50): " IP
fi
ok "IP local: $IP (reserve este IP no roteador — veja docs/realme.md)"
TS_NAME=""
echo "  Dica: no painel do Tailscale (login.tailscale.com → Machines), renomeie este celular para 'acervo'."
echo "  Assim o endereço é sempre acervo.<sua-rede>.ts.net, mesmo se um dia o servidor mudar de aparelho."
read -r -p "  Nome do Tailscale deste celular (ex.: acervo.tail1234.ts.net) — Enter para pular: " TS_NAME || true
BACKUP_DIR=""
if ask "Guardar uma cópia diária do catálogo na memória compartilhada (recomendado)?"; then
  termux-setup-storage || true
  sleep 3
  BACKUP_DIR="$HOME/storage/shared/Acervo-copia-do-catalogo"
fi
if [[ ! -f "$CONF" ]]; then
  {
    echo "# Gerado pelo instalar.sh em $(date '+%d/%m/%Y'). Comentários: acervo.example.toml"
    echo "data_dir = \"$DATA\""
    echo "host = \"0.0.0.0\""
    echo "port = 8765"
    echo "server_name = \"Realme\""
    echo "https = true"
    echo -n "tls_names = [\"$IP\""; [[ -n "$TS_NAME" ]] && echo -n ", \"$TS_NAME\""; echo "]"
    [[ -n "$BACKUP_DIR" ]] && echo "catalog_backup_dir = \"$BACKUP_DIR\""
    echo "storage_alert_pct = 80"
    echo "archive_batch_gb = 80"
    echo "archive_copies = 1"
  } > "$CONF"
  ok "criado $CONF"
else
  ok "mantido $CONF (já existia)"
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

say "7/9 HTTPS, cidades e OCR em português"
$ACERVO certificado
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
