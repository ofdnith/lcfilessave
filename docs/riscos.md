# Riscos do plano

Ordenados pelo estrago que podem causar. Cada um diz como foi tratado no código.
Desde 01/11/2026 o destino dos lotes se chama **armazenamento** (HD, SSD, pendrive…);
onde abaixo diz "HD", vale para qualquer armazenamento.

| # | Risco | Situação |
|---|---|---|
| 1 | Um armazenamento só é uma cópia só | Opção `archive_copies = 2` pronta; o padrão é 1 — **decisão do dono** |
| 2 | Camada 1 dizer "já tenho" por engano | Resolvido: "seguro apagar" exige hash de cada arquivo |
| 3 | Descartadas voltando todo dia | Resolvido: estado `purged` guarda o hash |
| 4 | `pydantic-core` no Termux | Instalador tenta o pacote pronto e, se faltar, compila |
| 5 | PWA exige HTTPS | Resolvido: endereço seguro (DuckDNS + Let's Encrypt); reserva: autoridade própria |
| 6 | Limites dos Atalhos | Documentado em `docs/iphone.md`; Live Photo completa só pelo Mac |
| 7 | Copyparty + FastAPI | Resolvido: upload retomável próprio (tus) dentro do FastAPI |
| 8 | Dados apagados se o Termux sair | Avisos no instalador + cópia diária do catálogo |
| 9 | exFAT sem journaling | App do Mac grava `.part`, `fsync`, renomeia e relê o hash |
| 10 | Miniaturas crescendo | WebP 400 px (~20 KB); prévias grandes são cache descartável |
| 11 | HEIC no Termux | `pillow-heif` se instalar; senão a prévia embutida via exiftool |
| 12 | Bateria sempre na tomada | Checklist do instalador; tarefas pausam acima de `max_temp_c`; OCR leve |
| 13 | O celular guarda a única cópia até o lote | Aviso de lote pronto (5 GB ou 14 dias), aviso de espaço, cópia diária do catálogo; microSD aposentado |
| 14 | Entrada parada | Só existe no celular; aviso com 7 dias ou 5 GB sem triagem |

## 1. Um único armazenamento é uma única cópia — **decisão do dono**

Depois do arquivamento, o servidor apaga o lote e o original passa a existir em
**um só HD**. HDs falham (queda, desgaste, setor ruim), e a verificação de
saúde só detecta o problema — não recupera o arquivo.

**Proposta:** cada lote é gravado em dois HDs (`VOLUME-001` e o espelho
`VOLUME-001B`), guardados em lugares diferentes. O esquema já suporta: um
arquivo pode ter cópias verificadas em vários volumes. Alternativa mais barata:
uma cópia extra só dos itens marcados como importantes.

## 2. A camada 1 (nome + data + tamanho) pode dizer "já tenho" para um arquivo novo

Se dois arquivos diferentes coincidirem em nome, data e tamanho, o segundo não
seria enviado. É raro, mas no fluxo **Esvaziar iPhone** isso seria perda de foto.

**Tratamento já previsto no esquema:** a camada 1 só vale para economizar banda
no backup diário. A confirmação "seguro apagar do iPhone" exige que **cada**
arquivo tenha sido recebido e conferido por SHA-256 (`received_verified_count`).

## 3. Fotos descartadas voltariam todo dia

O backup diário nunca apaga do iPhone (regra 1), então uma foto descartada
continua lá e seria reenviada no dia seguinte.

**Tratamento já no esquema:** o item descartado vira `purged`, o hash fica no
catálogo para sempre e a pré-checagem responde "já conheço — descartado".

## 4. FastAPI depende de `pydantic-core`, que é difícil de instalar no Termux

O `pydantic-core` é escrito em Rust e não há pacote pronto oficial para
Android; no Termux é preciso compilar (demorado, precisa de `pkg install rust`)
ou usar binários feitos pela comunidade.

**Proposta:** antes de avançar muito na Fase 1, fazer um teste de 15 minutos no
Realme (`pip install fastapi uvicorn`). Se falhar ou demorar demais, trocar
para **Starlette** — a base do próprio FastAPI, 100% Python. O código muda
pouco, porque já evito recursos exclusivos do FastAPI.

## 5. PWA no iPhone exige HTTPS

Sem HTTPS, o Safari não ativa o *service worker*: o web app até vai para a tela
inicial, mas não funciona como app (sem cache, sem modo offline).

**Tratamento:** o app Tailscale do Android não emite certificados. O caminho
principal é o **endereço seguro** (`acervo duckdns`): dois nomes no DuckDNS que
apontam para o IP do Wi-Fi e o do Tailscale, com certificado do Let's Encrypt
pelo desafio de DNS (ninguém conecta de fora; regra 7 intacta). O servidor
acompanha os IPs e renova sozinho, e escolhe o certificado pelo nome pedido (SNI).
Sem ele, sobra a autoridade de certificado própria (`acervo certificado`), que
precisa ser instalada e marcada como confiável em cada aparelho; o Safari e o app
do Mac recusam o servidor enquanto isso não for feito.

**Dependências novas:** DuckDNS e Let's Encrypt precisam estar no ar para
*renovar* (o certificado vale 90 dias e é renovado com 30 de folga). Alguns
roteadores bloqueiam nomes da internet que apontam para IPs da casa ("proteção
contra DNS rebinding"); se o endereço de casa não abrir no Wi-Fi, é isso.

**O que fica público:** os dois nomes e os IPs internos para onde apontam (o do
Wi-Fi, 192.168…, e o do Tailscale, 100.…) aparecem no DNS de qualquer um, e os
nomes entram nos registros públicos de certificados (Certificate Transparency).
Isso não abre acesso a nada (esses IPs só funcionam dentro de casa e do seu
Tailscale), mas escolha nomes que não digam quem você é, se isso importar. O token
do DuckDNS fica só no servidor (`certificados/duckdns.json` e a pasta do acme.sh,
ambos só para o dono); `acervo-ctl duckdns --remover` apaga os dois.

## 6. Atalhos do iPhone têm limites

- O backup diário roda com tempo e memória limitados; vídeos grandes podem
  estourar o tempo e o atalho para no meio.
- Dependendo do caminho usado, o Atalhos entrega JPEG em vez de HEIC ou perde a
  parte de vídeo da Live Photo (regra 5).
- Calcular SHA-256 de vídeos no iPhone é lento — a camada 2 no iPhone
  provavelmente não é viável.

**Proposta:** o backup diário envia em lotes pequenos e retoma no dia seguinte;
vídeos grandes ficam para o fluxo Esvaziar iPhone (pelo Mac, com cabo). A
configuração exata que preserva originais será testada e documentada na Fase 4.

## 7. Copyparty + FastAPI = dois processos, duas senhas, dois pontos de falha

O plano prevê o Copyparty para upload e o FastAPI para API e catálogo. No
Android, cada processo a mais é um alvo para o "signal 9", e a ligação entre
eles (hook após upload) precisa ser à prova de interrupção.

**Proposta:** começar a Fase 1 com upload retomável próprio no FastAPI
(protocolo **tus**, um processo só, uma senha só), e manter o Copyparty apenas
se o WebDAV para o Finder fizer falta. Decidimos ao aprovar a Fase 1.

## 8. Onde guardar os dados no Realme

A pasta interna do Termux é rápida, mas **é apagada se o Termux for
desinstalado**. O armazenamento compartilhado sobrevive, mas é mais lento e o
SQLite não se dá bem com ele.

**Proposta:** dados na pasta interna, o `instalar.sh` avisando em letras
grandes para nunca desinstalar o Termux, e uma cópia diária do `catalogo.db`
para o armazenamento compartilhado. Decidido na Fase 3.

## 9. exFAT não tem journaling

Desplugar o HD no meio de uma escrita pode corromper o sistema de arquivos.

**Tratamento (Fase 5):** gravar em arquivo temporário, forçar escrita em disco
(`fsync`), renomear, reler e conferir o hash — só então registrar
`verified_at`. Ejetar sempre pelo app.

## 10. Miniaturas crescem para sempre

As miniaturas nunca são apagadas. Com 300 mil itens a ~40 KB cada, são ~12 GB
— uma fatia relevante dos ~100 GB do Realme.

**Proposta:** miniaturas em WebP de 320 px (~15–25 KB) e o indicador de espaço
contando as miniaturas à parte.

## 11. HEIC no Termux

Gerar miniatura de HEIC exige `libheif`. O pacote existe no Termux, mas o
`pillow-heif` pode precisar ser compilado.

**Plano B:** extrair a prévia JPEG que o próprio iPhone embute no HEIC (via
`exiftool`), ou usar `ffmpeg`. Testado na Fase 3.

## 12. Bateria sempre na tomada

Um celular carregando 24 h por dia pode inchar a bateria.

**Proposta:** ativar o limite de carga do Realme, se existir; o `instalar.sh`
lembra disso, e o servidor mostra a temperatura e o nível da bateria (Fase 3).

**Tratamento:** carregando, o OCR rodaria sem parar numa importação grande. Por
isso as tarefas de fundo pausam com a bateria a `max_temp_c` (40 °C por padrão)
e só voltam 3 °C abaixo; o OCR lê uma cópia de 1600 px em tons de cinza, com
um núcleo, em vez do original de 12–48 MP. `acervo-ctl status` mostra a temperatura.

## 13. O celular guarda a única cópia até o lote

Desde 01/11/2026 o cartão microSD não é mais memória de transição: o que passa
pela triagem fica na memória interna do celular até ir num lote para um
armazenamento. Até lá, é a única cópia; se o celular se perder ou quebrar, vai junto.
(Antes, o cartão era essa cópia — e cartões falham mais que memória interna.)

**Tratamento:** lotes pequenos e frequentes. Um aviso (faixa no app e
notificação) aparece quando o próximo lote chega a `archive_batch_gb` (5 GB) ou
quando algo mantido está só no servidor há `archive_alert_days` dias (14); outro
quando a memória passa de `storage_alert_pct` (80%), que fica urgente e diário
com 95% ou menos de 3 GB livres. A cópia diária do catálogo (`catalog_backup_dir`)
guarda datas, lugares e em que armazenamento está cada coisa. O que ainda estava
no cartão volta sozinho para a memória interna, cada cópia conferida por SHA-256
antes de apagar a do cartão (ou sai direto do cartão no próximo lote, se faltar espaço).

## 14. A Entrada só existe no celular

O que ainda não passou pela triagem está só na memória interna. Se o celular se
perder, isso vai junto.

**Tratamento:** um aviso no topo do Acervo (e notificação, no máximo a cada 3
dias) quando algo está na Entrada há `inbox_alert_days` dias (7) ou quando ela
passa de `inbox_alert_gb` (5 GB). Depois da triagem, o lote leva tudo para um armazenamento (risco 13).
