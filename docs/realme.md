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
| `acervo-ctl duckdns` | Configura o endereço seguro (DuckDNS + Let's Encrypt); `--mostrar` mostra os endereços |
| `acervo-ctl verificar` | Para o servidor, confere disco × catálogo, corrige o que der e religa |
| `acervo-ctl token migracao` | Token para levar o Acervo para outra máquina (`docs/migrar.md`) |

Quando o celular reinicia, o Acervo sobe sozinho uns 20 segundos depois.

## 5. Endereço seguro e acesso fora de casa

Rode `acervo-ctl duckdns` uma vez (passo a passo em `docs/iphone.md`, item 2). O
Acervo ganha dois endereços com certificado do Let's Encrypt, que o Safari e o app
do Mac aceitam sem instalar nada:

- **casa** (ex.: `https://fulano-casa.duckdns.org:8765`) aponta para o IP do celular no Wi-Fi;
- **fora** (ex.: `https://fulano.duckdns.org:8765`) aponta para o IP dele no Tailscale.
  Por ele o Acervo funciona igual a dentro de casa, sempre com senha.

O servidor descobre os dois IPs sozinho a cada 10 minutos e atualiza o DuckDNS se
mudarem; o certificado é renovado antes de vencer. Nenhuma porta fica aberta para a
internet (regra 7). Para isso funcionar, deixe o **Tailscale ligado** no celular
(VPN sempre ativa) e reserve o IP dele no roteador.

Os nomes ficam num registro público de certificados (como todo site com HTTPS),
mas só levam a endereços da sua casa e do seu Tailscale. Não use seu nome completo neles.

## 6. Onde ficam os arquivos (e o cartão microSD antigo)

O caminho de cada arquivo:

```
iPhone/Mac ──► Entrada ──triagem──► Acervo ──lote (app do computador)──► armazenamento
               └──────── memória interna do celular ────────┘           (HD, SSD, pendrive…)
```

- **Entrada** e **Acervo** ficam na memória interna até o lote. Por padrão a
  Entrada não tem limite (`inbox_max_gb = 0`): os envios só param se o disco acabar.
- Até o lote, esses arquivos **só existem no celular**. Por isso o Acervo avisa
  (faixa no app e notificação): **lote pronto** com 5 GB (`archive_batch_gb`) ou
  com algo mantido há **14 dias** (`archive_alert_days`); **pouco espaço** acima de
  80% (`storage_alert_pct`); **Entrada esperando** com 7 dias ou 5 GB
  (`inbox_alert_days`, `inbox_alert_gb`).
- A cópia diária do catálogo (`catalog_backup_dir`, que o `instalar.sh` oferece)
  guarda datas, lugares e em que armazenamento está cada coisa.

### Cartão microSD antigo (aposentado em 01/11/2026)

O cartão deixou de ser memória de transição: nada novo vai para ele, e a opção
`sd_for_library` não existe mais (se sobrou no `acervo.toml`, é ignorada).

Se o seu `acervo.toml` ainda tem `sd_dir`, **deixe o cartão no celular**: o que
estava nele volta sozinho para a memória interna, aos poucos, com cada cópia
relida e conferida por SHA-256 antes de apagar a do cartão. Se faltar espaço na
memória interna, esses itens saem direto do cartão no próximo lote para um
armazenamento. `acervo-ctl status` mostra quanto ainda está no cartão; tirar o
cartão antes da hora faz aparecer o aviso “Cartão microSD não encontrado”.

Quando não sobrar nada no cartão, apague a linha `sd_dir` do `~/acervo/acervo.toml`
e rode `acervo-ctl restart`. Depois o cartão pode ser formatado e usado para
outra coisa.

## 7. Temperatura

O celular vive na tomada, e OCR e miniaturas esquentam o processador. Com a
bateria a 40 °C (`max_temp_c`), as tarefas de fundo pausam e voltam quando ela
esfria 3 °C. Envios e triagem continuam funcionando durante a pausa.
`acervo-ctl status` mostra a temperatura. Deixe o celular em lugar ventilado, fora
de capinha.

## O que roda no celular

| Peça | Pacote no Termux |
|---|---|
| Python 3, FastAPI, uvicorn | `python` + `pip` |
| pydantic-core | `python-pydantic-core` ou compilado com `rust` |
| Pillow, cryptography | `python-pillow`, `python-cryptography` |
| numpy (opcional, quase-duplicados rápidos) | `python-numpy` |
| exiftool, ffmpeg, pdftotext, tesseract | `exiftool`, `ffmpeg`, `poppler`, `tesseract` |
| bateria / Wi-Fi | `termux-api` (+ app Termux:API) |
| Interface (compilada uma vez) | `nodejs-lts` |
