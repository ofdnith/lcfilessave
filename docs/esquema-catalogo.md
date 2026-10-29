# Esquema do catálogo (`catalogo.db`)

O catálogo é um SQLite com busca FTS5. O SQL fica em
[`server/acervo/migrations/0001_initial.sql`](../server/acervo/migrations/0001_initial.sql).
Nomes de tabelas e colunas estão em inglês (regra do projeto); abaixo, a tradução.

## Princípios

- **A identidade de um arquivo é o SHA-256 do conteúdo.** `files.sha256` é único
  no catálogo inteiro — Entrada, Acervo, Lixeira e HDs.
- **Linhas de `items` nunca são apagadas.** Um item descartado vira `purged`: o
  arquivo some, o hash fica. Sem isso, o backup diário reenviaria todo dia as
  fotos que você descartou, já que elas continuam no iPhone.
- **O banco protege as regras sozinho.** Mesmo que um bug apareça numa fase
  futura, os gatilhos (triggers) do SQLite recusam a operação perigosa.
- **Tudo em disco, tudo retomável.** Modo WAL + `synchronous = FULL`: uma
  alteração confirmada sobrevive até a queda de energia ou o Android matando o
  processo.

## Estados de um item

```
            ┌──────────► trash ──────► purged   (após 30 dias; final)
            │              │
 inbox ─────┤              └──► volta para inbox/library (restaurar)
 (Entrada)  │
            └──► library ──────► archived  (só com cópia verificada em HD)
                 (Acervo)  ◄──────┘
```

| Estado | Nome na interface | Original está em |
|---|---|---|
| `inbox` | Entrada | servidor (`entrada/`) |
| `library` | Acervo | servidor (`acervo/AAAA/MM/tipo/`) |
| `trash` | Lixeira | servidor (`lixeira/`) |
| `archived` | Acervo, com selo `VOLUME-00N` | HD |
| `purged` | — (invisível) | lugar nenhum; só o hash resta |

Qualquer outra transição é recusada pelo banco.

## Tabelas

| Tabela | Para quê | Campos principais |
|---|---|---|
| `items` | O que o usuário vê: uma foto, um vídeo, um documento, uma Live Photo | `sha256` (único), `phash`, `kind`, `captured_at` + `captured_tz` + `date_source`, `source`, `original_name`, `standard_name`, `state`, `volume_id`, `important`, dimensões, duração, GPS, `place`, câmera, dicas de triagem |
| `files` | Os bytes. 1 por item, 2 numa Live Photo (`original` + `live-video`) | `sha256` (único global), `rel_path` (NULL quando só existe no HD) |
| `volumes` | HDs numerados | `id` (UUID do `volume.json`), `name` (`VOLUME-001`), capacidade, status |
| `volume_copies` | Onde cada arquivo está em cada HD | `file_id`, `volume_id`, `rel_path`, `verified_at` |
| `volume_checks` | Verificações de saúde dos HDs | tipo (parcial/completa), arquivos lidos, problemas |
| `upload_sessions` | Cada envio; gera o relatório "X novos · Y já existiam · Z quase-duplicados" | contadores, `expected_count` vs `received_verified_count` |
| `fingerprints` | Deduplicação camada 1: (nome, data de criação, tamanho) → item | chave composta |
| `dedupe_hits` | Cada vez que algo enviado já existia, e em qual camada foi pego | `layer` 1–4 |
| `suggestions` + `suggestion_items` | Grupos sugeridos na triagem (quase-duplicados, capturas de tela, rajadas, WhatsApp, vídeos grandes) | nunca descartam sozinhos |
| `events` | Log de toda operação destrutiva ou de movimentação | **somente inclusão**: o banco recusa editar ou apagar |
| `jobs` | Fila de trabalho pesado (metadados, miniaturas, pHash, OCR…) | sobrevive ao processo ser morto; `only_when_charging` |
| `settings` | Pares chave/valor (ex.: data do último backup diário) | |
| `search_fts` | Índice de busca FTS5 | nome, lugar, câmera, texto; ignora acentos ("sao" acha "São"); prefixo |
| `schema_migrations` | Migrações aplicadas, com checksum | |

## Refinamentos em relação ao plano original

Cada um explicado em uma frase:

- **`volume_copies` separada de `files`:** a transferência copia, relê e
  verifica cada arquivo antes de liberar o apagamento, então "copiado" e
  "verificado" precisam ser registrados por arquivo e por HD.
- **Estado `purged`:** sem guardar o hash do que foi descartado, o backup
  diário traria de volta tudo que você já jogou fora.
- **`fingerprints` como tabela própria:** a data de criação que o iPhone
  informa nem sempre é igual à do EXIF, então a impressão da camada 1 precisa
  ser guardada exatamente como o cliente a enviou.
- **`captured_at` em hora local + `captured_tz`:** a linha do tempo deve mostrar
  a hora em que a foto foi tirada, onde foi tirada; o fuso fica à parte.
- **`date_source = 'upload'`** é o que a interface mostra como "data incerta".
- **`jobs`:** o Android mata processos; a fila em disco garante que miniaturas
  e metadados retomem de onde pararam.
- **`expected_count` / `received_verified_count`** em `upload_sessions`
  sustentam o "1.243 de 1.243 recebidos e verificados — seguro apagar do iPhone".

## Garantias impostas pelo banco (com teste)

| Garantia | Regra | Teste |
|---|---|---|
| Mesmo conteúdo não vira dois itens nem dois arquivos | 4 | `test_same_content_cannot_be_two_*` |
| Arquivo só sai do servidor com cópia **verificada** em HD (ou após purga) | 3 | `test_server_copy_cannot_be_dropped_*` |
| Item só é marcado `archived` com **todos** os arquivos verificados (Live Photo inclusa) | 3 | `test_live_photo_needs_both_files_verified` |
| Purga só a partir da Lixeira; purga é final | 6 | `test_inbox_cannot_jump_to_purged`, `test_purged_is_final` |
| Item novo sempre começa na Entrada | 2 | `test_new_items_land_in_inbox` |
| Log de eventos não pode ser alterado | — | `test_events_are_append_only` |

O prazo de 30 dias da lixeira é conferido pelo código da Fase 2 (o banco não
sabe a data "de hoje" de forma confiável).

## Migrações

- Arquivos `NNNN_descricao.sql` em `server/acervo/migrations/`, em sequência.
- Cada migração roda numa transação única, junto com a mudança de versão.
- Antes de atualizar um catálogo existente, uma cópia é salva em
  `catalogo.db.bak-v<versão antiga>`.
- **Nunca edite uma migração já aplicada:** o servidor detecta pelo checksum e
  se recusa a abrir. Crie uma nova.
- Um catálogo mais novo que o código também é recusado.
