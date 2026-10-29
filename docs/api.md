# API do servidor

Contrato entre o servidor (`server/`), a interface (`web/`), o app do Mac
(`mac/`) e os Atalhos do iPhone. Tudo em JSON, UTF-8. Datas do servidor em UTC
ISO-8601; `captured_at` é hora local da captura (`AAAA-MM-DDTHH:MM:SS`).

## Autenticação

Tudo em `/api/*` exige login, exceto `/api/health` e `/api/auth/*`.

- **Navegador / PWA:** cookie `acervo_session` (HttpOnly, SameSite=Lax), criado no login.
- **App do Mac e Atalhos:** cabeçalho `Authorization: Bearer <token>`.
- **Sem senha definida:** só pedidos vindos do próprio computador (127.0.0.1) são aceitos.
  O servidor se recusa a escutar na rede sem senha.

| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| GET | `/api/auth/status` | — | `{password_set, authenticated, method}` (`method`: `cookie`/`token`/`local`/`null`) |
| POST | `/api/auth/login` | `{password, client?}` | `{token}` + cookie. 401 se errada; 429 após muitas tentativas |
| POST | `/api/auth/logout` | — | `{ok}` |
| POST | `/api/auth/app-token` | — (precisa estar logado) | `{token}` de longa duração para os comandos nativos do app do Mac |

Tokens de longa duração para os Atalhos: `acervo token criar "iPhone"` no servidor.

## Objeto `Item`

```json
{
  "id": 12, "sha256": "…", "kind": "photo",
  "mime": "image/heic", "size_bytes": 2345678,
  "original_name": "IMG_1234.HEIC", "standard_name": "2024-05-01_1012_IMG_1234.HEIC",
  "captured_at": "2024-05-01T10:12:33", "captured_tz": "-03:00", "date_uncertain": false,
  "uploaded_at": "…", "source": "iphone-daily",
  "state": "library", "important": false,
  "volume": {"id": "uuid", "name": "VOLUME-001"},
  "width": 4032, "height": 3024, "duration_ms": null,
  "gps": {"lat": -23.5, "lon": -46.6}, "place": "São Paulo, SP, BR", "camera": "Apple iPhone 13",
  "is_live_photo": true, "is_screenshot": false, "origin_app": null,
  "on_server": true,
  "thumb_url": "/api/items/12/thumb",
  "preview_url": "/api/items/12/preview",
  "original_url": "/api/items/12/original",
  "live_video_url": "/api/items/12/original?role=live-video",
  "trashed_at": null, "trash_expires_at": null
}
```

`state`: `inbox` (Entrada), `library` (Acervo), `trash` (Lixeira), `archived` (no HD — aparece
no Acervo com o selo `volume.name`). `thumb_url` é `null` enquanto a miniatura não existe.
`original_url`/`preview_url` são `null` quando o original só está no HD.

## Navegar e buscar

**`GET /api/items`** — parâmetros:

| Parâmetro | Valores | Padrão |
|---|---|---|
| `view` | `library` (Acervo + arquivados), `inbox`, `trash` | `library` |
| `kind` | `all`, `photo`, `video`, `document`, `audio`, `other` | `all` |
| `q` | texto livre (nome, lugar, câmera, texto do documento; ignora acentos; prefixo) | — |
| `year`, `month` | filtros | — |
| `start` | `AAAA-MM`: começa no fim desse mês (rolagem rápida) | — |
| `important` | `1` | — |
| `archived` | `1` só no HD, `0` só no servidor | — |
| `cursor` | valor `next_cursor` da página anterior | — |
| `limit` | 1–500 | 200 |

Resposta: `{items: [Item], next_cursor: string|null, total: int}`. Ordem: mais recente primeiro.
Na lixeira a ordem é por `trashed_at`.

**`GET /api/timeline`** — mesmos filtros (`view`, `kind`, `q`, `important`, `archived`).
Resposta: `{months: [{year, month, count}]}` do mais recente ao mais antigo.

**`GET /api/items/{id}`** — `Item` + `files: [{id, role, size_bytes, mime, on_server, volumes: ["VOLUME-001"], rel_path, drive_copies: [{volume, rel_path}]}]`
(`rel_path` = caminho do arquivo no HD do item, para abrir o original com o HD plugado)
+ `suggestions: [{id, kind}]`.

**`GET /api/items/{id}/thumb`** — WebP 320 px. 404 se ainda não existe.
**`GET /api/items/{id}/preview`** — imagem que o navegador mostra (JPEG/PNG/WebP/GIF originais
são servidos direto; HEIC e outros viram JPEG 1600 px). Para vídeo, o próprio vídeo (com Range).
**`GET /api/items/{id}/original?role=original|live-video`** — o arquivo original, com Range.
410 `{error, volume}` se só existe no HD.

**`GET /api/stats`**

```json
{
  "inbox_count": 128, "trash_count": 3, "archived_count": 900, "suggestions_open": 4,
  "tabs":       {"all": {"count": 0, "bytes": 0}, "photo": {…}, "video": {…}, "document": {…}, "audio": {…}, "other": {…}},
  "inbox_tabs": { …mesmo formato… },
  "storage": {
    "server_bytes": 62000000000, "budget_bytes": 80000000000,
    "disk_total_bytes": 0, "disk_free_bytes": 0, "used_pct": 62.0, "alert": false,
    "weeks_to_next_drive": 2.1,  // null se desconhecido ou acima de 2 anos
    "inbox_bytes": 41000000000, "inbox_max_bytes": 100000000000,  // null = sem limite
    "inbox_alert": false,        // Entrada passou de 90% do limite
    "inbox_oldest_at": "…", "inbox_waiting_days": 9,
    "inbox_reminder": {"reasons": ["dias", "tamanho"], "days": 9, "bytes": 6200000000},
                                 // null, ou: há item na Entrada há inbox_alert_days dias / passou de inbox_alert_gb
    "sd": {                      // null se não há sd_dir
      "present": true, "for_library": true,
      "total_bytes": 0, "free_bytes": 0, "used_pct": 71.0,
      "library_bytes": 0,        // Acervo que já está no cartão
      "pending_bytes": 0,        // Acervo ainda só na memória interna (sendo copiado)
      "alert": false,            // cartão ausente ou acima de storage_alert_pct: hora de um lote para o HD
      "health": {                // verificação diária (o cartão inteiro a cada 30 dias)
        "damaged": 0, "damaged_names": [],      // até 5 nomes
        "checked_recent_pct": 100.0,            // % do cartão conferido nos últimos 30 dias
        "last_check_at": "…"
      }
    }
  },
  "daily_backup": {"last_at": "…", "overdue": false}
}
```

## Triagem

**`POST /api/items/actions`** `{ids: [int], action}` — `action`:

| Ação | De → para |
|---|---|
| `keep` | Entrada → Acervo (arquivo vai para `acervo/AAAA/MM/tipo/`) |
| `discard` | Entrada ou Acervo → Lixeira |
| `restore` | Lixeira → estado anterior |
| `important` / `unimportant` | marca/desmarca |

Resposta: `{ok: [ids], failed: [{id, error}]}`. Itens no HD não podem ir para a lixeira.

**`POST /api/trash/purge-expired`** → `{purged: int}` (também roda sozinho uma vez por dia).

**`GET /api/suggestions?status=open`** → `{suggestions: [{id, kind, created_at, items: [Item]}]}`.
`kind`: `near-duplicate`, `screenshot`, `burst`, `whatsapp`, `large-video`.
**`POST /api/suggestions/{id}/dismiss`** → `{ok}`. Sugestões se resolvem sozinhas quando nenhum
item delas continua na Entrada. Nenhuma sugestão descarta nada.

## Envio

### Sessões

Toda remessa abre uma sessão — é ela que gera o relatório e o "seguro apagar do iPhone".

| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| POST | `/api/sessions` | `{source, expected_count?, client_label?}` | `Session` |
| GET | `/api/sessions/{id}` | — | `Session` |
| POST | `/api/sessions/{id}/finish` | — | `Session` |

`source`: `iphone-daily`, `iphone-manual`, `iphone-empty`, `mac`, `web`, `webdav`.

```json
{
  "id": 7, "source": "web", "status": "open",
  "expected_count": 500, "received_verified_count": 498,
  "new_count": 450, "existing_count": 48, "near_dup_count": 3, "failed_count": 0,
  "summary_text": "450 novos · 48 já existiam · 3 quase-duplicados para revisar",
  "safe_to_delete": false
}
```

`client_key` é o identificador do arquivo no cliente (o caminho, por exemplo). Cada `client_key`
conta uma vez na sessão, mesmo com reenvios; duas fotos idênticas no iPhone são duas chaves.
Na pré-checagem, `key` faz esse papel.

`safe_to_delete` só é `true` quando `expected_count` foi informado, cada arquivo foi
conferido por SHA-256 (enviado ou já conhecido por hash).

### Pré-checagem

**`POST /api/precheck`**
`{session_id?, entries: [{key, name?, created_at?, size?, sha256?}]}`
→ `{results: [{key, known, by: "hash"|"fingerprint"|null, state, item_id, verified}]}`

- Com `sha256`: compara pelo conteúdo (`verified: true` quando conhecido). Com `session_id`,
  conta como recebido e verificado na sessão.
- Só com `name` + `created_at` + `size`: impressão (camada 1). Serve para pular envio;
  nunca conta como verificado.
- `state` pode ser `purged` (descartado antes): não reenviar.

### Upload retomável (tus 1.0.0)

Base: `/api/uploads`. Extensões: `creation`, `termination`.

- `POST /api/uploads` com `Upload-Length` e `Upload-Metadata`
  (chaves em base64: `filename` obrigatório; `filetype`, `lastModified` em ms, `source`,
  `session_id`, `sha256`, `client_key`). → `201 Location: /api/uploads/{id}`
- `HEAD /api/uploads/{id}` → `Upload-Offset`, `Upload-Length`
- `PATCH /api/uploads/{id}` (`Content-Type: application/offset+octet-stream`, `Upload-Offset`)
  → `204 Upload-Offset`. Ao completar, o servidor processa o arquivo.
- `DELETE /api/uploads/{id}` cancela.
- `GET /api/uploads/{id}/result` → `UploadResult`

```json
{"status": "new", "item_id": 12, "message": "Recebido"}
```

`status`: `receiving`, `new`, `duplicate`, `in_trash` (oferecer restaurar), `discarded`
(descartado antes), `attached` (vídeo da Live Photo juntado à foto), `failed`.

Envie as fotos antes dos vídeos de um mesmo lote: assim o vídeo da Live Photo encontra a foto.

### Upload simples (Atalhos e app do Mac)

**`POST /api/upload`** — `multipart/form-data` com o campo `file`, **ou** corpo cru com o
cabeçalho `X-Filename` (nome codificado em URL). Parâmetros (query ou form): `source`,
`session_id`, `created_at` (ISO ou ms), `sha256`, `client_key`. → `UploadResult`.
Se `sha256` vier e não bater com o recebido: `failed` (arquivo corrompido no caminho).

### Backup diário

**`GET /api/daily`** → `{last_at, overdue}`. A sessão `iphone-daily` ao terminar atualiza
`last_at`; `overdue` é `true` depois de 48 h.

## HDs e arquivamento (app do Mac)

| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| GET | `/api/volumes` | — | `{volumes: [Volume], archive_copies}` |
| POST | `/api/volumes` | `{capacity_bytes, filesystem, id?}` | `Volume` (nome `VOLUME-NNN` automático; `id` = UUID gerado pelo app, opcional) |
| POST | `/api/volumes/{id}/seen` | `{used_bytes?}` | `Volume` |
| GET | `/api/archive/plan?volume_id=…&max_bytes=…` | — | `{files: [PlanFile], total_bytes}` |
| GET | `/api/files/{file_id}/content` | — | bytes do original (404 se já saiu do servidor) |
| GET | `/api/volumes/{id}/catalog.db` | — | catálogo só deste HD (usado pelo bundle) |
| GET | `/api/volumes/{id}/abrir.html` | — | `ABRIR-ACERVO.html` deste HD (usado pelo bundle) |
| POST | `/api/archive/verified` | `{volume_id, copies: [{file_id, rel_path, sha256}]}` | `{accepted: [ids], rejected: [{file_id, error}]}` |
| POST | `/api/archive/commit` | `{volume_id}` | `{archived_items, freed_bytes}` |
| GET | `/api/volumes/{id}/bundle` | — | `{files: [{path, url}]}` |
| GET | `/api/volumes/{id}/sample?n=50&full=0` | — | `{files: [{file_id, rel_path, sha256}]}` |
| POST | `/api/volumes/{id}/checks` | `{kind, files_checked, problems: [{file_id, error}]}` | `Volume` |

```json
Volume = {"id": "uuid", "name": "VOLUME-001", "capacity_bytes": 0, "used_bytes": 0,
          "status": "active", "created_at": "…", "last_seen_at": "…",
          "item_count": 900, "last_full_check_at": "…",
          "last_check": {"kind": "partial", "finished_at": "…", "files_checked": 50, "problems": 0}}
PlanFile = {"file_id": 1, "item_id": 1, "sha256": "…", "size_bytes": 0,
            "rel_path": "2024/05/fotos/2024-05-01_1012_IMG_1234.HEIC",
            "url": "/api/files/1/content"}
```

Fluxo da transferência:

1. `GET /api/archive/plan` → lista do lote (até `archive_batch_gb`).
2. Para cada arquivo: baixar para `rel_path.part` no HD, `fsync`, renomear, **reler do HD**
   e calcular o SHA-256.
3. `POST /api/archive/verified` com o hash relido. O servidor só aceita se bater.
4. `POST /api/archive/commit`: itens com todos os arquivos verificados em
   `archive_copies` HDs viram `archived` e saem do servidor. O banco recusa o contrário.
5. `GET /api/volumes/{id}/bundle` e gravar cada arquivo no HD
   (`.acervo/catalogo.db`, `.acervo/miniaturas/…`, `ABRIR-ACERVO.html`).

`.acervo/volume.json` no HD: `{"id": "uuid", "name": "VOLUME-001", "created_at": "…", "acervo": 1}`.

## Outros

- `GET /api/health` — sem login. Estado do servidor, catálogo e disco; `storage` traz os mesmos
  campos de Entrada e cartão de `/api/stats`, e `thermal` = `{temperature, max_temp_c, paused}`.
- `GET /api/settings` → `{archive_batch_gb, trash_days, archive_copies, server_name, version, battery,
  inbox_max_gb, sd_for_library, thermal}`.
- `GET /ca.crt` — certificado para instalar no iPhone/Mac quando o HTTPS próprio está ativo.

---

# Versão 0.2 — melhorias

Tudo abaixo soma-se ao que está acima; nada mudou de forma incompatível.

## Prévia média (fica para sempre)

Toda foto e vídeo ganha uma prévia WebP de até 1024 px (~100 KB), gerada junto com a
miniatura e **guardada mesmo depois que o original vai para o HD**.

- `Item.medium_url`: `/api/items/{id}/medium` ou `null` (ainda não gerada / tipo sem imagem).
- `GET /api/items/{id}/medium` → `image/webp`. 404 se não existe.
- No visualizador: mostrar `medium_url` primeiro (rápido, inclusive fora de casa) e só
  carregar `preview_url`/`original_url` quando a pessoa pedir ("Ver original") ou der zoom.

## Triagem em um toque

- `GET /api/inbox/summary` → `{total, flagged, clean}` — `flagged` = itens da Entrada que
  estão em alguma sugestão aberta; `clean` = o resto.
- `POST /api/inbox/keep-clean` → `{kept, flagged_left}` — mantém (Entrada → Acervo) todos
  os itens que **não** estão em sugestão aberta. Os sinalizados ficam para decidir.

## Neste dia

`GET /api/memories?date=MM-DD` (padrão: hoje no servidor) →
`{date: "10-29", years: [{year: 2023, years_ago: 3, count: 41, items: [Item]}]}`
— só Acervo/arquivados, fotos e vídeos, anos anteriores, até 30 itens por ano (os
importantes primeiro). `years` vazio quando não há nada.

## Lugares e mapa

- `GET /api/places` → `{places: [{place, count, lat, lon, cover: Item}]}` (até 500, mais fotos primeiro).
- `GET /api/map/points` → `{points: [[id, lat, lon], …]}` — tudo do Acervo com GPS, compacto.
- `GET /api/items?place=<texto exato de place>` filtra por lugar.
- Mapa: Leaflet com mapas do OpenStreetMap (precisa de internet no aparelho que olha; o
  servidor não manda nada para fora). Atribuição "© OpenStreetMap" obrigatória.

## Álbuns

| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| GET | `/api/albums` | — | `{albums: [Album]}` |
| POST | `/api/albums` | `{name}` | `Album` |
| PATCH | `/api/albums/{id}` | `{name?, cover_item_id?}` | `Album` |
| DELETE | `/api/albums/{id}` | — | `{ok}` (apaga só o álbum, nunca os itens) |
| POST | `/api/albums/{id}/items` | `{ids}` | `{added}` |
| POST | `/api/albums/{id}/items/remove` | `{ids}` | `{removed}` |

`Album = {id, name, count, cover: Item|null, created_at, updated_at}`.
`GET /api/items?album_id=N` e `/api/timeline?album_id=N` filtram pelo álbum e ignoram `view`:
mostram o que está na Entrada, no Acervo e nos HDs (o que está na lixeira não aparece).
`GET /api/items?ids=1,2,3` (até 500) traz vários itens de uma vez, em qualquer estado menos lixeira.
`GET /api/items/{id}` traz `albums: [{id, name}]`.

## Atalhos do iPhone sem complicação

- `GET /api/tokens` → `{tokens: [{id, label, created_at, last_used_at}]}`
- `POST /api/tokens` `{label}` → `{id, token}` (o token só aparece nessa resposta); 409 se o
  servidor ainda não tem senha ("Defina uma senha…"), 403 fora de casa no modo seguro
- `DELETE /api/tokens/{id}` → `{ok}`
- `GET /api/shortcuts` → `{links: {manual: url|null, daily: url|null}}` — links do iCloud
  dos atalhos prontos, configurados no `acervo.toml` (`shortcut_manual_url`, `shortcut_daily_url`).

Backup diário simplificado (o atalho fica com 4 ações):
- `GET /api/daily` agora também traz `since` (ISO: último backup menos 1 dia, ou 7 dias atrás)
  e `repairing`: `true` quando `since` voltou até uma foto do iPhone cuja cópia no cartão falhou
  na verificação (por até 3 dias), para o backup reenviá-la e o envio consertar a cópia.
- `POST /api/upload?source=iphone-daily` **sem** `session_id` → entra sozinho na sessão
  diária de hoje (criada na primeira foto).
- `POST /api/daily/finish` → `Session` da sessão de hoje (`summary_text` pronto para a
  notificação: "Backup diário: 37 fotos, 4 vídeos"). Sem sessão: "Backup diário: nada novo".

## Avisos (Web Push)

Só funciona no web app instalado na tela de início (iOS 16.4+) e com HTTPS.

- `GET /api/push/key` → `{public_key}` (VAPID, base64url) — 404 se o servidor não tem suporte.
- `POST /api/push/subscribe` `{subscription: <PushSubscription.toJSON()>, topics: [...]}` → `{ok}`
- `POST /api/push/unsubscribe` `{endpoint}` → `{ok}`
- `GET /api/push/status?endpoint=…` → `{subscribed, topics}`
- `POST /api/push/test` `{endpoint}` → `{ok}` (manda "Avisos do Acervo funcionando")
- Tópicos: `backup_atrasado` (passou de 48 h), `espaco` (passou do alerta),
  `hd_problema` (verificação achou erro), `backup_concluido` (resumo do backup diário).
- Payload que chega no service worker: `{title, body, url}` — abrir `url` ao tocar.

## Fora de casa: modo seguro

Pedidos que chegam pelo Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48) contam como
"fora de casa". Com `remote_mode = "seguro"` (padrão), fora de casa é proibido:
descartar, esvaziar lixeira, arquivar em HD (`/api/archive/*`, criar/verificar volume),
criar/revogar tokens e migração. Ver, buscar, baixar, enviar, manter, marcar importante e
álbuns continuam liberados. Bloqueado → 403 `{detail}` em português.

`GET /api/auth/status` traz também `{remote: bool, readonly: bool}` — com `readonly`, a
interface esconde os botões proibidos e mostra "Fora de casa · modo seguro".

## Migração (servidor antigo → servidor novo)

Usado pelo comando `acervo migrar` no servidor novo; precisa de um token (`acervo token criar migracao`).

| Método | Rota | Resposta |
|---|---|---|
| POST | `/api/migration/start` | `{active, started_at}` — servidor antigo entra em modo migração: tudo que altera dados responde 423 |
| POST | `/api/migration/cancel` | `{active: false}` |
| GET | `/api/migration/catalog` | cópia consistente do `catalogo.db` (API de backup do SQLite) |
| GET | `/api/migration/manifest` | `{files: [{kind, path, size, sha256}]}` — originais (sha do catálogo), miniaturas, prévias médias, certificados, base de cidades |
| GET | `/api/migration/file?kind=…&path=…` | bytes do arquivo (só caminhos do manifesto) |

`/api/health` traz `migration: {active, started_at}`; a interface mostra uma faixa
"Migração em andamento — o Acervo está só para consulta".
