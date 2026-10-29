# Instalar o Acervo no Realme 9

Tempo: uns 30 minutos (até 1 hora se precisar compilar o `pydantic-core`).
Deixe o celular **carregando e no Wi-Fi** durante a instalação.

## 1. Apps (pela F-Droid, não pela Play Store)

A versão do Termux da Play Store é antiga e não funciona.

1. No Realme, abra o navegador e baixe a F-Droid em **f-droid.org**. Instale
   (o Android vai pedir para permitir "instalar apps desconhecidos").
2. Na F-Droid, instale **Termux**, **Termux:Boot** e **Termux:API**.
3. Abra o **Termux:Boot** uma vez (só abrir e fechar — isso ativa o início automático).
4. Na Play Store, instale o **Tailscale** e entre com a sua conta (a mesma do iPhone e do Mac).

## 2. Instalar

Abra o **Termux** e digite (pode copiar e colar):

```bash
pkg install -y git && git clone https://github.com/souzaq001/lcfilessave ~/acervo && bash ~/acervo/scripts/termux/instalar.sh
```

O instalador vai perguntar:

- **IP do celular** — normalmente ele descobre sozinho.
- **Nome do Tailscale** — antes, em **login.tailscale.com → Machines**, renomeie o
  Realme para **`acervo`**. O nome fica `acervo.<sua-rede>.ts.net` e vale para
  sempre, mesmo se o servidor um dia for para um mini PC (veja `docs/migrar.md`).
  Pode pular e rodar o instalador de novo depois.
- **Cópia diária do catálogo** — responda **s**. O Android vai pedir acesso aos arquivos: permita.
- **Senha** — a senha que você vai digitar no iPhone e no Mac. Mínimo 8 caracteres.

No final ele mostra o endereço (`https://192.168.x.x:8765`) e um checklist.

## 3. Checklist para o Android não matar o servidor

O Android 12+ encerra processos em segundo plano ("signal 9"). Sem estes ajustes
o servidor cai algumas horas depois. O supervisor reinicia sozinho, mas é melhor
evitar a queda.

1. **Opções do desenvolvedor**
   - Configurações → Sobre o telefone → Versão → toque 7 vezes em **Número da versão**.
   - Configurações → Configurações adicionais → **Opções do desenvolvedor** →
     ative **Desativar restrições de processos filhos**
     (em inglês: *Disable child process restrictions*).
   - **Se essa opção não existir**, faça pelo Mac, com o cabo USB:
     1. No Realme: Opções do desenvolvedor → ative **Depuração USB**.
     2. No Mac, no Terminal: `brew install android-platform-tools`
     3. Conecte o cabo, aceite o aviso no celular e rode:
        ```bash
        adb shell "settings put global settings_enable_monitor_phantom_procs false"
        adb shell "/system/bin/device_config set_sync_disabled_for_tests persistent"
        adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
        ```
     Isso não precisa ser refeito, exceto depois de uma atualização do Android.
2. **Bateria** — Configurações → Bateria → (Mais configurações / Uso de bateria por app) →
   **Termux** → *Permitir atividade em segundo plano* e *Início automático*.
   Repita para **Termux:Boot** e **Termux:API**.
3. **Apps recentes** — abra a lista de apps recentes, segure o Termux e toque no **cadeado**.
4. **IP fixo** — no app/site do seu roteador, procure "Reserva de DHCP" ou "IP fixo"
   e reserve o IP do Realme. Assim o endereço nunca muda.
5. **Bateria sempre na tomada** — se houver "Carregamento otimizado" ou limite de carga
   (Configurações → Bateria → Mais configurações), ative. Deixe o celular em lugar ventilado.
6. **Nunca desinstale o Termux.** Os dados ficam dentro dele (`~/acervo-dados`); desinstalar apaga tudo.

## 4. Usar no dia a dia

No Termux:

| Comando | O que faz |
|---|---|
| `acervo-ctl status` | Mostra se está tudo bem, espaço livre e ferramentas |
| `acervo-ctl restart` | Reinicia o servidor |
| `acervo-ctl logs` | Mostra o registro ao vivo (saia com Ctrl+C) |
| `acervo-ctl token iPhone` | Cria um token para os Atalhos do iPhone |
| `acervo-ctl senha` | Troca a senha |
| `acervo-ctl atualizar` | Baixa a versão nova do Acervo e reinstala (os dados ficam) |
| `acervo-ctl verificar` | Para o servidor, confere disco × catálogo, corrige o que der e religa |
| `acervo-ctl token migracao` | Token para levar o Acervo para outra máquina (`docs/migrar.md`) |

Quando o celular reinicia, o Acervo sobe sozinho uns 20 segundos depois.

## 5. Acesso fora de casa

Com o Tailscale ligado no iPhone/Mac, use `https://<nome>.ts.net:8765`. Nenhuma porta
fica aberta para a internet (regra 7). Se você não informou o nome do Tailscale na
instalação, rode de novo o instalador ou acrescente o nome em `tls_names` no
`~/acervo/acervo.toml`, rode `~/acervo/server/.venv/bin/acervo --config ~/acervo/acervo.toml certificado`
e `acervo-ctl restart`. O certificado da autoridade (o que você instalou no iPhone) não muda.

## 6. Cartão microSD (opcional)

Com um cartão, o Acervo pode guardar ali o que já foi triado quando a memória
interna passar do alerta (80%). No Android o Termux só escreve numa pasta própria do cartão:

1. Rode `termux-setup-storage`.
2. Descubra o caminho: `ls ~/storage/` → use `~/storage/external-1` (que aponta para
   `/storage/XXXX-XXXX/Android/data/com.termux/files`).
3. No `~/acervo/acervo.toml`, acrescente `sd_dir = "/storage/XXXX-XXXX/Android/data/com.termux/files/acervo"`.
4. `acervo-ctl restart`.

Atenção: essa pasta também é apagada se o Termux for desinstalado.

## O que roda no celular

| Peça | Pacote no Termux |
|---|---|
| Python 3, FastAPI, uvicorn | `python` + `pip` |
| pydantic-core | `python-pydantic-core` ou compilado com `rust` |
| Pillow, cryptography | `python-pillow`, `python-cryptography` |
| exiftool, ffmpeg, pdftotext, tesseract | `exiftool`, `ffmpeg`, `poppler`, `tesseract` |
| bateria / Wi-Fi | `termux-api` (+ app Termux:API) |
| Interface (compilada uma vez) | `nodejs-lts` |
