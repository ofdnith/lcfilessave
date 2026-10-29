# Acervo — Especificação

> Cópia do documento "Acervo — Prompt de desenvolvimento" (29/10/2026), a fonte
> da verdade do projeto. Mudanças no plano entram aqui, com a data.

## Objetivo

O Acervo é uma ferramenta pessoal de backup e organização de fotos, vídeos,
documentos e outros arquivos, hospedada num celular Android antigo (Realme 9)
dentro de casa. Não é um "drive" permanente: é uma estação de triagem. O celular
recebe, organiza e guarda temporariamente; HDs externos são o arquivo definitivo.

- **Usuário:** uma pessoa só, com iPhone e MacBook.
- **Prioridades:** organização, facilidade e desempenho de upload, busca rápida
  estilo Google Fotos/Drive.
- **Ciclo de vida de um arquivo:**
  1. iPhone ou Mac envia o arquivo para o servidor (manual ou backup diário automático).
  2. O arquivo cai na **Entrada** e espera triagem.
  3. Aprovado, vai para o **Acervo**, organizado por data e tipo, com busca.
  4. Quando o servidor encher (~80 GB), um lote é transferido pelo Mac para um HD
     numerado (VOLUME-001, 002…), com verificação por hash.
  5. O servidor apaga o lote, mas mantém miniatura + metadados no catálogo: o
     acervo inteiro continua navegável e buscável, com o selo do volume onde está
     o original.

**Papel da IA:** engenheiro principal. Fases pequenas e testáveis, cada decisão
técnica explicada em uma ou duas frases, perguntar antes de mudar qualquer regra
inviolável. O dono não é desenvolvedor experiente em Android e usa iPhone e MacBook.

**Idioma:** código, nomes de variáveis e comentários em inglês; interface,
mensagens ao usuário e documentação em português do Brasil.

## Arquitetura e stack

Três partes compartilham a mesma interface: o servidor no Realme, o web app no
iPhone e o app nativo no Mac. Só o app do Mac acessa discos externos. O catálogo
é o centro: garante a deduplicação e mantém o acervo buscável depois de arquivado.

| Parte | Tecnologia | Responsabilidade |
|---|---|---|
| Servidor | Python 3 no Termux; FastAPI + uvicorn | API, catálogo, servir a interface |
| Upload | Copyparty (upload em pedaços, retomável, WebDAV) com hook após upload | Receber arquivos rápido; chamar o organizador |
| Organização | exiftool, ffmpeg, Pillow (+ libheif para HEIC) | Datas, GPS, miniaturas, renomear, mover |
| Banco | SQLite + FTS5 | Catálogo, busca, hashes, volumes |
| Interface | Svelte + Vite + TypeScript, build estático | Abas, busca, triagem, linha do tempo |
| iPhone | PWA + app Atalhos | Uso diário, backup automático |
| Mac | Tauri 2 (Rust) reaproveitando a interface | Tudo do web app + discos, arquivamento, verificação |
| Acesso remoto | Tailscale | Acesso fora de casa sem abrir portas |

Se a integração com o Copyparty se mostrar frágil, pode-se propor upload
retomável próprio (protocolo tus), justificando a troca.

## Regras invioláveis

Valem para todo o código. Nenhuma fase pode quebrá-las sem aprovação explícita do dono.

1. **O backup diário nunca apaga nada do iPhone.** Apagar do iPhone só acontece
   pelo fluxo manual "Esvaziar iPhone", e só depois da verificação.
2. **Tudo que chega pelo backup diário cai na Entrada**, com contador visível
   ("128 itens aguardando triagem"). Nada vai direto para o Acervo.
3. **Nada é apagado de lugar nenhum sem verificação por hash** (SHA-256) da cópia de destino.
4. **Nenhum arquivo repetido é armazenado.**
5. **Originais intactos:** nunca recomprimir, converter ou alterar o arquivo
   original. Miniaturas e versões de prévia são arquivos separados.
6. **Descarte passa por lixeira** (30 dias) antes de apagar de vez.
7. **Servidor nunca exposto à internet.** Acesso só pela rede local e pelo
   Tailscale, sempre com senha.
8. **O acervo não depende do projeto existir:** todo HD leva um
   `ABRIR-ACERVO.html` que funciona offline, em qualquer computador, sem instalar nada.

## Deduplicação — requisito central

O mesmo conteúdo nunca é enviado duas vezes, nem armazenado duas vezes, mesmo que
já tenha ido para um HD. A identidade de um arquivo é o **SHA-256 do conteúdo**,
nunca o nome. Checagem em camadas, da mais barata para a mais cara:

| Camada | Onde | Como funciona | Evita |
|---|---|---|---|
| 1. Pré-checagem por impressão | Antes do upload | Cliente envia `(nome original, data de criação, tamanho)` para `POST /api/precheck`; o servidor responde quais já conhece | Gastar banda com o que já existe |
| 2. Hash no cliente | Antes do upload (Mac e, quando viável, iPhone) | Cliente calcula SHA-256 e consulta `POST /api/precheck` por hash | Reenvio de arquivo renomeado |
| 3. Hash no servidor | Após o upload, antes de catalogar | Servidor recalcula SHA-256; se já existe, descarta a cópia nova e registra a ocorrência | Qualquer duplicado que passou pelas camadas 1 e 2 |
| 4. Catálogo global | Sempre | O catálogo guarda hashes de **tudo**: Entrada, Acervo, Lixeira e todos os volumes de HD | Reenviar algo já arquivado em HD |
| 5. Quase-duplicados | Na triagem | Hash perceptual (pHash) agrupa versões parecidas | Só sugere; **nunca descarta sozinho** |

Regras adicionais:

- **Live Photo** (HEIC + MOV) é um item com dois arquivos, deduplicada como par.
- **Upload simultâneo** do mesmo arquivo por dois clientes: trava por hash no
  servidor; o segundo recebe "já existe".
- **Item na Lixeira reenviado:** o servidor avisa e oferece restaurar.
- **Relatório:** toda sessão de upload termina com "X novos · Y já existiam · Z
  quase-duplicados para revisar".
- **Testes obrigatórios:** mesmo arquivo com nome diferente; mesmo nome com
  conteúdo diferente; arquivo já arquivado em HD; upload interrompido e
  retomado; dois uploads simultâneos.

## Modelo de dados e organização

Catálogo em SQLite com FTS5 — detalhado em [`esquema-catalogo.md`](esquema-catalogo.md).

Estrutura de pastas no servidor:

```
/dados/
├── entrada/              arquivos aguardando triagem
├── acervo/AAAA/MM/{fotos,videos,docs,audios,outros}/
├── lixeira/              30 dias
├── miniaturas/           por sha256, nunca apagadas
└── catalogo.db
```

- **Data:** EXIF `DateTimeOriginal` para foto/vídeo (via exiftool); data de
  modificação para os demais; fallback = data do upload, marcada como "data incerta".
- **Nome padrão:** `AAAA-MM-DD_HHMM_<nome original>.<ext>`; colisão de nome com
  conteúdo diferente ganha sufixo `_2`.
- **Estrutura de um HD:** a mesma árvore `AAAA/MM/tipo/`, mais
  `.acervo/volume.json` (UUID, nome, data), `.acervo/catalogo.db` (só os itens
  daquele volume), `.acervo/miniaturas/` e `ABRIR-ACERVO.html` na raiz. Formato: exFAT.

## Funcionalidades por módulo

**Upload**

- Rápido e retomável: arquivos em pedaços, envio paralelo, continua de onde parou.
- Mac: arrastar e soltar no app; Finder via WebDAV como alternativa.
- iPhone, manual: atalho "Mandar pro backup" no menu Compartilhar.
- iPhone, **backup diário**: automação do Atalhos (gatilho: conectar ao
  carregador à noite, ou horário fixo), sem confirmação. Envia só o que é novo,
  usando a pré-checagem. Ao final, notifica "Backup diário: 37 fotos, 4 vídeos".
  A interface mostra a data do último backup diário e alerta se passar de 48 h.
- **Esvaziar iPhone:** importação em massa pelo Mac (Captura de Imagem, com
  cabo) para uma pasta, enviada ao servidor; a interface mostra "1.243 de 1.243
  recebidos e verificados — seguro apagar do iPhone". Apagar é ação manual do usuário.
- Originais garantidos: HEIC, Live Photos e vídeos sem compressão (testar e
  documentar a configuração do iPhone).

**Triagem (aba Entrada)**

- Contador de itens aguardando.
- Ações em lote: manter, descartar, marcar como importante.
- Modo rápido: um item por vez; ← descarta, → mantém (teclado no Mac, deslizar no iPhone).
- Sugestões agrupadas: quase-duplicados, capturas de tela, rajadas, mídia do
  WhatsApp, vídeos grandes.

**Interface e busca**

- Tema escuro, visual moderno estilo Google Fotos/Drive; web app instalável no
  iPhone (PWA, barra inferior) e app Mac (barra lateral).
- Abas por tipo: Tudo, Fotos, Vídeos, Documentos, Áudios, Outros — grade para
  mídia, lista para documentos; contador de itens e espaço em cada aba.
- Linha do tempo com rolagem rápida por ano e mês.
- Busca instantânea (nome, tipo, data) com filtros em chips; ⌘K no Mac; a busca
  respeita a aba aberta.
- Itens arquivados aparecem normalmente, com selo `VOLUME-002`.
- Indicador de espaço: "62 de 100 GB · faltam ~2 semanas para o próximo HD".

**App Mac — Dispositivos e arquivamento** (só enquanto o app está aberto)

- Seção Dispositivos: servidor + discos plugados, atualizada em 1–2 s.
- Reconhece volumes pelo UUID em `.acervo/volume.json`; ignora discos
  desconhecidos até o usuário clicar em Adicionar (checa exFAT).
- Volume plugado: originais disponíveis para abrir; botões "Transferir lote
  para cá" e "Verificar saúde".
- Transferência: copia, verifica cada hash, atualiza catálogos e o
  `ABRIR-ACERVO.html`, e só então libera o apagamento no servidor.
- Verificação de saúde: relê uma parte dos arquivos a cada conexão e mostra
  "última verificação completa há 8 meses · 0 problemas".

## Fases de entrega

Cada fase termina com algo que o dono consegue usar e testar sozinho.
Desenvolver e testar primeiro no MacBook; só depois instalar no Realme.

0. **Fundação:** repositório, estrutura de pastas, `catalogo.db` com migrações,
   configuração, scripts de dev no Mac. Entrega: servidor sobe no Mac e responde `/api/health`.
1. **Núcleo:** upload retomável, deduplicação (camadas 1 a 4), organizador
   (EXIF, renomear, pastas), miniaturas, catálogo, interface com abas, linha do
   tempo e busca simples. Entrega: subir 500 fotos pelo navegador do Mac e vê-las organizadas.
2. **Triagem:** aba Entrada, ações em lote, modo rápido, lixeira de 30 dias,
   sugestões (duplicados e capturas de tela).
3. **Realme:** `instalar.sh` para o Termux, início automático (Termux:Boot),
   supervisor que reinicia serviços, guia anti-kill, senha, Tailscale.
4. **iPhone:** atalho manual, automação de backup diário, fluxo Esvaziar iPhone
   com confirmação verificada, PWA instalável.
5. **App Mac e HDs:** app Tauri, seção Dispositivos, criação de volumes,
   transferência verificada, `ABRIR-ACERVO.html`, verificação de saúde.
6. **Busca avançada:** lugar por GPS (base de cidades offline), texto em
   documentos, OCR, quase-duplicados por pHash, tarefas noturnas só carregando, cartão microSD.
7. **Opcional:** busca semântica ("praia", "cachorro") com modelo CLIP pequeno,
   processada de madrugada.

## Restrições do hardware e do Android

| Item | Realidade | Consequência no código |
|---|---|---|
| Processador | Snapdragon 680, 8 núcleos ARM64 | Trabalho pesado em fila, com baixa prioridade |
| Memória | 6 ou 8 GB de RAM | Sem Docker, PostgreSQL, Redis; processar em streaming |
| Armazenamento | 128 GB UFS 2.2 (~100 GB livres) + microSD | Alerta em 80%; lote de arquivamento ~80 GB |
| Rede | Wi-Fi 5; USB-C 2.0 | Upload principal pelo Wi-Fi 5 GHz |
| Sistema | Android 14, Realme UI 5, sem atualizações de segurança | Nunca expor portas; só LAN + Tailscale |
| Ambiente | Termux (sem root), pela F-Droid | Python nativo; nada que exija glibc ou proot |
| Processos | Android 12+ mata processos em segundo plano ("signal 9") | Poucos processos; supervisor; estado em disco; tudo retomável e idempotente |

O `instalar.sh` deve imprimir o checklist manual: desativar restrições de
processos filhos (Opções do desenvolvedor) ou o comando ADB alternativo pelo
Mac; liberar atividade em segundo plano e início automático do Termux;
`termux-wake-lock`; IP fixo no roteador; limite de carga da bateria, se disponível.

## Como trabalhar

- **Uma fase por vez.** Ao fim de cada fase: o que foi feito, como testar (passo
  a passo para um não-especialista) e o que ficou pendente.
- **Testes automatizados** para organizador, deduplicação, catálogo e
  transferência para HD. Operações que apagam algo precisam de teste antes de existir.
- **Decisões em aberto:** propor, explicar em uma frase e seguir com a mais
  simples, a menos que afete uma regra inviolável.
- **Sem dependências pesadas** no servidor; toda dependência nova precisa rodar
  no Termux ARM64 (citar o pacote `pkg` ou `pip`).
- **README em português** sempre atualizado, com como rodar no Mac e no Realme.
