#!/data/data/com.termux/files/usr/bin/bash
# Mantém o servidor do Acervo de pé: se ele cair (ou o Android matar com
# "signal 9"), espera um pouco e sobe de novo. Começa com 5 s de espera e
# dobra a cada queda rápida, até 2 minutos; volta a 5 s depois de 10 min no ar.
set -u

REPO="$HOME/acervo"
DATA="$HOME/acervo-dados"
CONF="$REPO/acervo.toml"
LOG="$DATA/logs/servidor.log"
mkdir -p "$DATA/logs"

delay=5
trap 'pkill -TERM -P $$; exit 0' TERM INT

while true; do
  # Log simples com rotação: guarda o anterior ao passar de 10 MB.
  if [[ -f "$LOG" && $(stat -c %s "$LOG") -gt 10485760 ]]; then
    mv -f "$LOG" "$LOG.1"
  fi
  echo "[$(date '+%F %T')] supervisor: iniciando servidor" >> "$LOG"
  started=$(date +%s)
  nice -n 5 "$REPO/server/.venv/bin/acervo" --config "$CONF" serve >> "$LOG" 2>&1 &
  wait $!
  code=$?
  echo "[$(date '+%F %T')] supervisor: servidor saiu (código $code)" >> "$LOG"
  if (( $(date +%s) - started > 600 )); then delay=5; else delay=$(( delay * 2 > 120 ? 120 : delay * 2 )); fi
  sleep "$delay"
done
