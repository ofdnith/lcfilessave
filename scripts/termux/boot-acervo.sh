#!/data/data/com.termux/files/usr/bin/bash
# Copiado pelo instalar.sh para ~/.termux/boot/acervo.sh.
# O app Termux:Boot roda isto quando o celular liga.
termux-wake-lock
sleep 20   # espera o Wi-Fi conectar
"$HOME/bin/acervo-ctl" start
