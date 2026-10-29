# Acervo

Estação pessoal de triagem e backup de fotos, vídeos e documentos, rodando num
celular Android antigo (Realme 9) dentro de casa. O celular **recebe, organiza e
guarda temporariamente**; HDs externos numerados são o arquivo definitivo. O
catálogo continua navegável e buscável mesmo depois que os originais vão para o HD.

Caminho de um arquivo: **Entrada** na memória interna (até 100 GB) → triagem →
**Acervo no cartão microSD** (cópia conferida por SHA-256, para sobreviver à perda
do celular, conferido todo dia e navegável por um `ABRIR-ACERVO.html`) → **HD**,
em lotes, quando o cartão enche. Um aviso lembra da triagem com 7 dias ou 5 GB na Entrada. Veja [docs/realme.md](docs/realme.md#6-cartão-microsd--onde-fica-o-que-já-foi-triado).

```
 iPhone (web app + Atalhos) ─┐                         ┌─ HD VOLUME-001 (exFAT)
                             ├─► Realme (servidor) ◄───┤  originais + ABRIR-ACERVO.html
 Mac (app + navegador) ──────┘   catálogo, miniaturas  └─ HD VOLUME-002 …
                                    Entrada → Acervo → HD
```

| Guia | Para quê |
|---|---|
| [docs/realme.md](docs/realme.md) | Instalar o servidor no Realme (Termux) |
| [docs/migrar.md](docs/migrar.md) | Mudar o Acervo para um mini PC (ou outra máquina) |
| [docs/iphone.md](docs/iphone.md) | Web app, certificado, Atalhos e backup diário |
| [mac/README.md](mac/README.md) | Compilar e usar o app do Mac (HDs, Esvaziar iPhone) |
| [docs/especificacao.md](docs/especificacao.md) | O plano do projeto (fonte da verdade) |
| [docs/api.md](docs/api.md) | A API do servidor |
| [docs/esquema-catalogo.md](docs/esquema-catalogo.md) | O `catalogo.db`, tabela por tabela |
| [docs/riscos.md](docs/riscos.md) | Riscos e como cada um foi tratado |

## Situação

| Fase | O que entrega | Estado |
|---|---|---|
| 0 — Fundação | Servidor, catálogo com migrações, `/api/health` | ✅ |
| 1 — Núcleo | Upload retomável, deduplicação (camadas 1–4), organizador, miniaturas, abas, linha do tempo, busca | ✅ |
| 2 — Triagem | Entrada, lote, modo rápido, lixeira de 30 dias, sugestões | ✅ |
| 3 — Realme | `instalar.sh`, início automático, supervisor, senha, HTTPS, Tailscale | ✅ (falta rodar no aparelho) |
| 4 — iPhone | Atalho manual, backup diário, Esvaziar iPhone, PWA | ✅ (atalhos montados à mão, guia passo a passo) |
| 5 — App Mac e HDs | Tauri, Dispositivos, volumes, transferência verificada, `ABRIR-ACERVO.html`, saúde | ✅ (compilar no Mac) |
| 6 — Busca avançada | Lugar por GPS offline, texto de documentos, OCR só carregando, quase-duplicados (pHash), microSD | ✅ |
| 7 — Opcional | Busca semântica (CLIP) | ⏸ não feita — veja abaixo |

**Versão 0.2 — melhorias:**

| Melhoria | O que muda |
|---|---|
| Prévias médias | Toda foto e vídeo guarda uma prévia de 1024 px (~100 KB) para sempre: o arquivado no HD continua bonito de ver, e fora de casa carrega rápido |
| Triagem em um toque | "Manter tudo, menos as sugestões": só o que é duplicado, captura de tela ou WhatsApp fica para você decidir |
| Neste dia, Lugares, Álbuns | Fotos do mesmo dia em anos anteriores; mapa e lista de cidades; álbuns que nunca apagam nada |
| Atalhos sem complicação | Token criado pela interface; backup diário com 5 ações; links do iCloud dos atalhos prontos |
| Avisos no iPhone | Backup atrasado, servidor cheio, problema num HD, resumo do backup (Web Push, sem abrir portas) |
| Modo seguro fora de casa | Pelo Tailscale dá para ver e enviar, mas não apagar nem mexer em HDs |
| Migração | `acervo migrar` leva tudo para um mini PC conferindo cada arquivo; instalador para Linux com serviço do sistema |

**Fase 7:** o modelo CLIP precisa do `onnxruntime`, que não tem versão para o
Termux/Android; no Snapdragon 680 cada foto levaria segundos. A fila de tarefas
já tem o tipo `embedding` reservado: dá para fazer depois, rodando no Mac.

## Rodar no Mac (desenvolvimento)

1. Abra o Terminal na pasta do projeto.
2. `scripts/setup-mac.sh` — instala o Python 3.12, exiftool, ffmpeg, poppler,
   tesseract e Node pelo Homebrew (pergunta antes) e compila a interface.
3. `scripts/dev.sh` e abra **http://127.0.0.1:8765**.
4. Arraste fotos para a janela. Elas aparecem na **Entrada**; mantenha-as e veja
   no **Acervo**, organizadas por ano e mês.

Para parar: `Ctrl + C`. Os dados de teste ficam em `dev-dados/` (pode apagar).
Sem senha definida, o servidor só aceita este computador.

### Testes

```bash
scripts/test.sh            # servidor: 163 testes
cd web && npm run check    # interface: verificação de tipos
cd mac/src-tauri && cargo test
```

Os testes do servidor incluem os cinco obrigatórios da especificação (mesmo
arquivo com nome diferente; mesmo nome com conteúdo diferente; arquivo já
arquivado em HD; upload interrompido e retomado; dois uploads simultâneos) e
conferem que o próprio banco recusa apagar um arquivo sem cópia verificada.
Uma revisão independente de segurança dos dados encontrou 19 problemas (dois
deles podiam apagar a única cópia de uma foto); todos foram corrigidos e cada um
virou um teste em `server/tests/test_review_regressions.py`.

Medido aqui: 500 fotos enviadas em ~6 s, miniaturas em ~22 s (no Realme, espere
uns 3–5× mais), triagem de 500 itens em 0,4 s, busca em ~10 ms, procura de
quase-duplicados entre 100 mil fotos em 0,15 ms (com `numpy`; 8 ms sem).

Pensado para o Snapdragon 680: as tarefas de fundo pausam com a bateria a 40 °C,
o OCR lê uma cópia de 1600 px com um núcleo, e os pHash ficam em memória.

## Regras invioláveis — onde cada uma é garantida

| Regra | Garantia |
|---|---|
| 1. Backup diário nunca apaga do iPhone | Os atalhos não têm ação de apagar; o servidor não tem como apagar no iPhone |
| 2. Backup diário cai na Entrada | Todo item novo nasce `inbox` (padrão do banco) |
| 3. Nada é apagado sem verificação por hash | Gatilhos no banco recusam tirar um arquivo do servidor sem cópia verificada em HD; cópia entre discos relê o hash antes de apagar a origem |
| 4. Nada repetido | `sha256` único no catálogo inteiro, trava por hash no servidor |
| 5. Originais intactos | Originais só são lidos; miniaturas e prévias são arquivos separados |
| 6. Lixeira de 30 dias | `trash_days` não aceita menos de 30; purga só sai da lixeira |
| 7. Nunca exposto, sempre com senha | Servidor recusa escutar na rede sem senha; acesso só LAN + Tailscale |
| 8. `ABRIR-ACERVO.html` em todo HD | Gerado a cada transferência; funciona offline em qualquer navegador |

## Estrutura

```
lcfilessave/
├── server/          servidor Python (FastAPI) — Mac e Realme
│   ├── acervo/      código (ingest, library, jobs, api/, migrations/ …)
│   └── tests/
├── web/             interface Svelte (navegador, PWA do iPhone, app do Mac)
├── mac/             app Tauri do Mac (discos, transferência, Esvaziar iPhone)
├── scripts/         setup-mac.sh, dev.sh, test.sh, termux/ (Realme), linux/ (mini PC)
└── docs/
```

Pasta de dados no servidor:

```
acervo-dados/
├── entrada/       aguardando triagem
├── acervo/        AAAA/MM/{fotos,videos,docs,audios,outros}/
├── lixeira/       30 dias
├── miniaturas/    por sha256, nunca apagadas
├── previas/       cache descartável (HEIC → JPEG para o navegador)
├── geo/           base de cidades offline
├── certificados/  HTTPS próprio
├── tmp/           uploads em andamento
└── catalogo.db

cartão microSD (sd_dir)
├── acervo/        AAAA/MM/… — o que já passou pela triagem
├── lixeira/       descartes de itens que estavam no cartão
├── acervo-resgate/ cópia diária do catálogo + LEIA-ME.txt
├── corrompidos/   cópias que falharam na verificação (nunca apagadas)
├── .acervo/miniaturas/
└── ABRIR-ACERVO.html  navegador offline do cartão
```
