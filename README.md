# Acervo

Estação pessoal de triagem e backup de fotos, vídeos e documentos, rodando num
celular Android antigo (Realme 9) dentro de casa. O celular **recebe, organiza e
guarda temporariamente**; HDs externos numerados são o arquivo definitivo. O
catálogo continua navegável e buscável mesmo depois que os originais vão para o HD.

A especificação completa está em [`docs/especificacao.md`](docs/especificacao.md).

## Situação

| Fase | O que entrega | Estado |
|---|---|---|
| 0 — Fundação | Servidor sobe no Mac, catálogo com migrações, `/api/health` | ✅ pronta |
| 1 — Núcleo | Upload, deduplicação, organização, miniaturas, interface | aguardando aprovação |
| 2 — Triagem | Entrada, lote, modo rápido, lixeira, sugestões | — |
| 3 — Realme | Instalação no Termux, senha, Tailscale | — |
| 4 — iPhone | Atalhos, backup diário, Esvaziar iPhone, PWA | — |
| 5 — App Mac e HDs | Tauri, volumes, transferência verificada | — |
| 6 — Busca avançada | GPS, texto, OCR, quase-duplicados | — |
| 7 — Opcional | Busca semântica | — |

## Como rodar no Mac

Você só precisa do Terminal. Na primeira vez:

1. Abra o Terminal e entre na pasta do projeto:
   ```bash
   cd caminho/para/lcfilessave
   ```
2. Prepare o ambiente (instala o Python 3.12 pelo Homebrew se faltar — ele pergunta antes):
   ```bash
   scripts/setup-mac.sh
   ```
3. Suba o servidor:
   ```bash
   scripts/dev.sh
   ```
4. Abra **http://127.0.0.1:8765** no navegador. Você deve ver "Tudo certo",
   a versão do catálogo e o espaço livre do disco.

Para parar o servidor, volte ao Terminal e aperte `Ctrl + C`.

Os dados de teste ficam em `dev-dados/`, dentro do projeto. Pode apagar essa
pasta à vontade: ela é recriada vazia na próxima vez que o servidor subir.

### Testes

```bash
scripts/test.sh
```

Todos devem passar (`43 passed`). Eles conferem, entre outras coisas, que o
próprio banco recusa apagar um arquivo do servidor sem cópia verificada em HD.

### Comandos úteis

```bash
server/.venv/bin/acervo config     # mostra a configuração em uso
server/.venv/bin/acervo migrate    # cria/atualiza o catálogo sem subir o servidor
```

A configuração fica em `acervo.toml` (criado a partir de `acervo.example.toml`
na primeira execução; os comentários explicam cada opção).

## Como rodar no Realme

Chega na Fase 3, com um `instalar.sh` para o Termux e o passo a passo para o
Android não matar o servidor.

## Estrutura do repositório

```
lcfilessave/
├── README.md                 este arquivo
├── CLAUDE.md                 regras para a IA de desenvolvimento
├── acervo.example.toml       modelo de configuração
├── docs/
│   ├── especificacao.md      o plano do projeto (fonte da verdade)
│   ├── esquema-catalogo.md   o catalogo.db explicado, tabela por tabela
│   └── riscos.md             riscos do plano e como cada um é tratado
├── server/                   servidor Python (FastAPI) — roda no Mac e no Realme
│   ├── pyproject.toml
│   ├── acervo/
│   │   ├── __main__.py       linha de comando: serve, migrate, config
│   │   ├── app.py            aplicação web
│   │   ├── config.py         leitura e validação do acervo.toml
│   │   ├── db.py             conexão SQLite e migrações
│   │   ├── storage.py        pastas de dados e espaço em disco
│   │   ├── api/              rotas da API (/api/…)
│   │   ├── migrations/       0001_initial.sql, 0002_…  (nunca editar uma aplicada)
│   │   └── static/           página provisória (a interface real vem na Fase 1)
│   └── tests/
├── web/                      interface Svelte (Fase 1)
├── mac/                      app Tauri para o Mac (Fase 5)
└── scripts/                  setup-mac.sh, dev.sh, test.sh
```

Pasta de dados (no Mac, `dev-dados/`; no Realme, definida na Fase 3):

```
dados/
├── entrada/       arquivos aguardando triagem
├── acervo/        AAAA/MM/{fotos,videos,docs,audios,outros}/
├── lixeira/       30 dias
├── miniaturas/    por sha256, nunca apagadas
├── tmp/           uploads em andamento
└── catalogo.db
```

## Regras invioláveis

1. O backup diário nunca apaga nada do iPhone.
2. Tudo que chega pelo backup diário cai na Entrada.
3. Nada é apagado de lugar nenhum sem verificação por hash (SHA-256).
4. Nenhum arquivo repetido é armazenado.
5. Originais intactos: nunca recomprimir, converter ou alterar.
6. Descarte passa por lixeira (30 dias).
7. Servidor nunca exposto à internet; só rede local e Tailscale, sempre com senha.
8. Todo HD leva um `ABRIR-ACERVO.html` que funciona offline.

As regras 3, 4 e 6 já são garantidas pelo próprio banco de dados — veja
[`docs/esquema-catalogo.md`](docs/esquema-catalogo.md).
