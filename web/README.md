# Interface web

Svelte 5 + Vite + TypeScript, compilada para arquivos estáticos em `web/dist`,
que o servidor entrega. A mesma interface roda no navegador do Mac, como PWA no
iPhone e dentro do app do Mac (Tauri). As telas Dispositivos e Esvaziar iPhone
só aparecem dentro do app do Mac (quando `window.__TAURI__` existe).

Dependências: só `svelte`, `vite`, `typescript`, `svelte-check`,
`tus-js-client` (envio retomável), `hash-wasm` (SHA-256 no navegador) e
`leaflet` (mapa de Lugares, carregado só quando a tela abre). Tudo em
JavaScript puro; instala também no Termux (Android ARM64).

O mapa usa os mapas do OpenStreetMap, baixados direto pelo aparelho que olha
(o servidor não manda nada para fora). Sem internet, os pontos e a lista de
lugares continuam funcionando.

## Desenvolver

Precisa do Node 20 ou mais novo.

```bash
# terminal 1: o servidor em http://127.0.0.1:8765
scripts/dev.sh

# terminal 2: a interface com recarga automática
cd web
npm install
npm run dev        # abre em http://localhost:5173
```

O Vite repassa `/api` e `/ca.crt` para o servidor em `127.0.0.1:8765`. Sem
senha definida, o servidor aceita pedidos do próprio computador sem login.

## Compilar

```bash
cd web
npm run build      # gera web/dist (o servidor passa a usar na hora)
npm run check      # confere tipos (svelte-check), deve dar 0 erros
```

## Ícones

Os PNGs em `public/icons` já vêm prontos. Para redesenhar a partir das mesmas
formas de `public/icons/icon.svg`:

```bash
python3 scripts/make-icons.py   # precisa do Pillow
```

## Onde fica cada coisa

- `src/lib/api.ts` — todas as chamadas à API (`docs/api.md`)
- `src/lib/uploader.svelte.ts` — envio: sessão → SHA-256 → pré-checagem → tus → resultado
- `src/lib/native.ts` — comandos do app do Mac
- `src/lib/devices.svelte.ts` — HDs, transferência verificada e verificação de saúde
- `src/lib/empty-iphone.svelte.ts` — fluxo Esvaziar iPhone
- `src/views/` — telas; `src/components/` — peças reaproveitadas
- `src/lib/albums.svelte.ts`, `src/lib/sheets.svelte.ts` — álbuns e as folhas de confirmação/escolha de álbum
- `src/lib/cluster.ts` — agrupamento dos pontos do mapa (grade simples, sem plugin)
- `src/lib/push.ts` — avisos (Web Push) no web app instalado
- `public/sw.js` — service worker: casca do app (nunca guarda `/api`) e avisos

As rotas usam `#/` (ex.: `/#/entrada`), então o servidor só precisa entregar `/`.
