# Riscos do plano

Ordenados pelo estrago que podem causar. Cada um diz como foi tratado no código.

| # | Risco | Situação |
|---|---|---|
| 1 | Um HD só é uma cópia só | Opção `archive_copies = 2` pronta; o padrão é 1 — **decisão do dono** |
| 2 | Camada 1 dizer "já tenho" por engano | Resolvido: "seguro apagar" exige hash de cada arquivo |
| 3 | Descartadas voltando todo dia | Resolvido: estado `purged` guarda o hash |
| 4 | `pydantic-core` no Termux | Instalador tenta o pacote pronto e, se faltar, compila |
| 5 | PWA exige HTTPS | Resolvido: autoridade de certificado própria (`acervo certificado`) |
| 6 | Limites dos Atalhos | Documentado em `docs/iphone.md`; Live Photo completa só pelo Mac |
| 7 | Copyparty + FastAPI | Resolvido: upload retomável próprio (tus) dentro do FastAPI |
| 8 | Dados apagados se o Termux sair | Avisos no instalador + cópia diária do catálogo |
| 9 | exFAT sem journaling | App do Mac grava `.part`, `fsync`, renomeia e relê o hash |
| 10 | Miniaturas crescendo | WebP 400 px (~20 KB); prévias grandes são cache descartável |
| 11 | HEIC no Termux | `pillow-heif` se instalar; senão a prévia embutida via exiftool |
| 12 | Bateria sempre na tomada | Checklist do instalador; bateria visível em Ajustes |

## 1. Um único HD é uma única cópia — **decisão do dono**

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

**Tratamento:** o app Tailscale do Android não emite certificados, então o
Acervo tem a própria autoridade de certificado (`acervo certificado`). Você
instala o `ca.crt` uma vez no iPhone e no Mac, e o HTTPS vale em casa e pelo Tailscale.

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
