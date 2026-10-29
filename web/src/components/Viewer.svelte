<script lang="ts">
  import { untrack } from 'svelte';
  import Icon from './Icon.svelte';
  import { api } from '../lib/api';
  import { runAction } from '../lib/actions';
  import {
    bytes,
    captureDateTime,
    daysUntil,
    duration,
    kindLabel,
    num,
    plural,
    sourceLabel,
    suggestionLabel,
  } from '../lib/format';
  import { findMountedVolume, guessRelPath, isNative, native } from '../lib/native';
  import { toast } from '../lib/state.svelte';
  import { closeViewer, viewer } from '../lib/viewer.svelte';
  import type { ItemDetail } from '../lib/types';

  const list = $derived(viewer.list);
  const item = $derived(list && viewer.index >= 0 ? list.items[viewer.index] : null);
  let detail = $state<ItemDetail | null>(null);
  let showInfo = $state(typeof window !== 'undefined' && window.innerWidth >= 1200);
  let playingLive = $state(false);
  let imgLoaded = $state(false);
  let mountPath = $state<string | null>(null);
  let dialog = $state<HTMLElement | null>(null);

  $effect(() => {
    const it = item;
    if (!it) return;
    untrack(() => {
      detail = null;
      playingLive = false;
      imgLoaded = false;
      mountPath = null;
    });
    let alive = true;
    api
      .item(it.id)
      .then((d) => alive && (detail = d))
      .catch(() => {});
    if (isNative() && it.volume && !it.on_server) {
      void findMountedVolume(it.volume.id).then((p) => alive && (mountPath = p));
    }
    // Preload neighbours for snappy navigation.
    for (const n of [viewer.index + 1, viewer.index - 1]) {
      const nb = list?.items[n];
      if (nb?.preview_url && nb.kind === 'photo') new Image().src = nb.preview_url;
    }
    if (list && viewer.index >= list.items.length - 5) void list.more();
    return () => {
      alive = false;
    };
  });

  $effect(() => {
    if (!item) return;
    const prev = document.activeElement as HTMLElement | null;
    untrack(() => dialog?.focus());
    document.documentElement.style.overflow = 'hidden';
    return () => {
      document.documentElement.style.overflow = '';
      prev?.focus?.();
    };
  });

  function step(d: number) {
    if (!list) return;
    const n = viewer.index + d;
    if (n >= 0 && n < list.items.length) viewer.index = n;
  }

  function onKey(e: KeyboardEvent) {
    if (!item) return;
    const t = e.target as HTMLElement;
    if (t.tagName === 'INPUT' || t.tagName === 'VIDEO') {
      if (e.key !== 'Escape') return;
    }
    if (e.key === 'Escape') closeViewer();
    else if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'i') showInfo = !showInfo;
    else return;
    e.preventDefault();
  }

  // Touch swipe: horizontal to navigate, downward to close.
  let sx = 0;
  let sy = 0;
  let dx = $state(0);
  let swiping = false;
  function ts(e: TouchEvent) {
    if (e.touches.length !== 1) return;
    sx = e.touches[0].clientX;
    sy = e.touches[0].clientY;
    swiping = true;
  }
  function tm(e: TouchEvent) {
    if (!swiping) return;
    const x = e.touches[0].clientX - sx;
    const y = e.touches[0].clientY - sy;
    if (Math.abs(x) > Math.abs(y)) dx = x;
  }
  function te(e: TouchEvent) {
    if (!swiping) return;
    swiping = false;
    const x = e.changedTouches[0].clientX - sx;
    const y = e.changedTouches[0].clientY - sy;
    dx = 0;
    if (Math.abs(x) > 60 && Math.abs(x) > Math.abs(y)) step(x < 0 ? 1 : -1);
    else if (y > 110 && Math.abs(y) > Math.abs(x) * 1.5) closeViewer();
  }

  async function toggleImportant() {
    if (!item || !list) return;
    const target = !item.important;
    const id = item.id;
    list.patch(id, { important: target });
    const r = await runAction([id], target ? 'important' : 'unimportant', { quiet: true });
    if (!r || !r.ok.includes(id)) list.patch(id, { important: !target });
    else toast(target ? 'Marcado como importante' : 'Desmarcado', 'ok', undefined, 2000);
  }

  async function moveTo(action: 'discard' | 'keep' | 'restore') {
    if (!item || !list) return;
    const id = item.id;
    const r = await runAction([id], action, {
      undo: action === 'discard' ? () => void runAction([id], 'restore', { reload: true }) : undefined,
    });
    if (r?.ok.includes(id)) {
      list.remove([id]);
      if (!list.items.length) closeViewer();
      else if (viewer.index >= list.items.length) viewer.index = list.items.length - 1;
    }
  }

  async function openOnDrive() {
    if (!item || !mountPath) return;
    const f = detail?.files.find((x) => x.role === 'original');
    const rel = f?.rel_path ?? guessRelPath(item);
    try {
      await native.openOnVolume(mountPath, rel);
    } catch (e) {
      toast(`Não foi possível abrir: ${(e as Error).message}`, 'error');
    }
  }

  const dims = $derived(item?.width && item?.height ? `${num(item.width)} × ${num(item.height)}` : null);
  const mp = $derived(item?.width && item?.height ? Math.round((item.width * item.height) / 1e5) / 10 : null);
  const onDriveOnly = $derived(!!item && !item.on_server && !!item.volume);
  const canTrash = $derived(!!item && item.state !== 'archived' && item.state !== 'trash');
</script>

<svelte:window onkeydown={onKey} />

{#if item && list}
  <div
    class="viewer"
    class:info-open={showInfo}
    role="dialog"
    aria-modal="true"
    aria-label={item.original_name}
    tabindex="-1"
    bind:this={dialog}
  >
    <header class="vbar">
      <button class="icon-btn" onclick={closeViewer} aria-label="Fechar (Esc)"><Icon name="close" /></button>
      <div class="title">
        <span class="name">{item.original_name}</span>
        <span class="pos num">{num(viewer.index + 1)} de {num(list.total || list.items.length)}</span>
      </div>
      <div class="acts">
        {#if item.is_live_photo && item.live_video_url}
          <button class="icon-btn" class:on={playingLive} onclick={() => (playingLive = !playingLive)} aria-label="Reproduzir Live Photo" title="Live Photo">
            <Icon name="live" />
          </button>
        {/if}
        <button class="icon-btn" class:star={item.important} onclick={toggleImportant} aria-pressed={item.important} aria-label="Importante" title="Importante">
          <Icon name="star" fill={item.important} />
        </button>
        {#if item.original_url}
          <a class="icon-btn" href={item.original_url} download={item.original_name} aria-label="Baixar original" title="Baixar original">
            <Icon name="download" />
          </a>
        {/if}
        {#if viewer.view === 'trash'}
          <button class="btn small keep" onclick={() => moveTo('restore')}><Icon name="restore" size={16} /> Restaurar</button>
        {:else if viewer.view === 'inbox'}
          <button class="btn small keep" onclick={() => moveTo('keep')}><Icon name="check" size={16} /> Manter</button>
        {/if}
        {#if canTrash}
          <button class="icon-btn" onclick={() => moveTo('discard')} aria-label="Mover para lixeira" title="Mover para lixeira">
            <Icon name="trash" />
          </button>
        {/if}
        <button class="icon-btn" class:on={showInfo} onclick={() => (showInfo = !showInfo)} aria-label="Informações (i)" title="Informações">
          <Icon name="info" />
        </button>
      </div>
    </header>

    <div class="stage" ontouchstart={ts} ontouchmove={tm} ontouchend={te} role="presentation">
      <div class="media" style:transform={dx ? `translateX(${dx}px)` : undefined}>
        {#if playingLive && item.live_video_url}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video src={item.live_video_url} autoplay playsinline onended={() => (playingLive = false)}></video>
        {:else if item.kind === 'video' && item.preview_url}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video src={item.preview_url} controls playsinline preload="metadata" poster={item.thumb_url ?? undefined}></video>
        {:else if item.kind === 'photo' && item.preview_url}
          {#if item.thumb_url && !imgLoaded}
            <img class="blur" src={item.thumb_url} alt="" aria-hidden="true" />
          {/if}
          <img class="full" class:loaded={imgLoaded} src={item.preview_url} alt={item.original_name} onload={() => (imgLoaded = true)} />
        {:else}
          <div class="doc">
            {#if item.thumb_url}
              <img class="doc-thumb" src={item.thumb_url} alt="" />
            {:else}
              <div class="doc-icon"><Icon name={item.kind === 'audio' ? 'audio' : item.kind === 'document' ? 'doc' : 'file'} size={48} /></div>
            {/if}
            <p class="doc-name">{item.original_name}</p>
            <p class="muted">{kindLabel[item.kind]} · {bytes(item.size_bytes)}</p>
            {#if item.kind === 'audio' && item.original_url}
              <audio src={item.original_url} controls preload="metadata"></audio>
            {/if}
            {#if onDriveOnly}
              <p class="drive-note">Original no {item.volume?.name}</p>
              {#if mountPath}
                <button class="btn primary" onclick={openOnDrive}><Icon name="open" size={16} /> Abrir no {item.volume?.name}</button>
              {/if}
            {:else if item.original_url}
              <a class="btn primary" href={item.original_url} target="_blank" rel="noopener">
                <Icon name="open" size={16} /> Abrir original
              </a>
            {/if}
          </div>
        {/if}
      </div>

      {#if onDriveOnly && (item.kind === 'photo' || item.kind === 'video')}
        <div class="drive-pill">
          <Icon name="drive" size={15} /> Original no {item.volume?.name}
          {#if mountPath}<button class="link" onclick={openOnDrive}>Abrir</button>{/if}
        </div>
      {/if}

      {#if viewer.index > 0}
        <button class="nav prev" onclick={() => step(-1)} aria-label="Anterior"><Icon name="left" size={26} /></button>
      {/if}
      {#if viewer.index < list.items.length - 1}
        <button class="nav next" onclick={() => step(1)} aria-label="Próximo"><Icon name="right" size={26} /></button>
      {/if}
    </div>

    {#if showInfo}
      <aside class="info" aria-label="Informações">
        <h2>Informações</h2>
        <dl>
          <dt>Data</dt>
          <dd>
            {captureDateTime(item)}
            {#if item.captured_tz}<span class="faint">{` (${item.captured_tz})`}</span>{/if}
            {#if item.date_uncertain}<span class="uncertain">data incerta</span>{/if}
          </dd>
          {#if item.place || item.gps}
            <dt>Lugar</dt>
            <dd>
              {item.place ?? 'Sem nome'}
              {#if item.gps}
                <a class="faint small" href="https://www.openstreetmap.org/?mlat={item.gps.lat}&mlon={item.gps.lon}#map=15/{item.gps.lat}/{item.gps.lon}" target="_blank" rel="noopener noreferrer">ver no mapa</a>
              {/if}
            </dd>
          {/if}
          {#if item.camera}<dt>Câmera</dt><dd>{item.camera}</dd>{/if}
          {#if dims}<dt>Dimensões</dt><dd class="num">{dims}{#if mp}<span class="faint">{` · ${String(mp).replace('.', ',')} MP`}</span>{/if}</dd>{/if}
          {#if item.duration_ms}<dt>Duração</dt><dd class="num">{duration(item.duration_ms)}</dd>{/if}
          <dt>Tamanho</dt><dd class="num">{bytes(item.size_bytes)}</dd>
          <dt>Tipo</dt><dd>{kindLabel[item.kind]} <span class="faint">· {item.mime}</span></dd>
          <dt>Origem</dt><dd>{sourceLabel[item.source] ?? item.source}{#if item.origin_app}<span class="faint">{` · ${item.origin_app}`}</span>{/if}</dd>
          <dt>Onde está</dt>
          <dd>
            {#if item.on_server}Servidor{/if}{#if item.on_server && item.volume} e {/if}{#if item.volume}<span class="vol">{item.volume.name}</span>{/if}
            {#if detail}
              {@const vols = [...new Set(detail.files.flatMap((f) => f.volumes))].filter((v) => v !== item.volume?.name)}
              {#if vols.length}<span class="faint">{` · cópias em ${vols.join(', ')}`}</span>{/if}
            {/if}
          </dd>
          {#if item.state === 'trash' && item.trash_expires_at}
            <dt>Lixeira</dt><dd>Apaga em {plural(daysUntil(item.trash_expires_at) ?? 0, 'dia', 'dias')}</dd>
          {/if}
          <dt>Nome no acervo</dt><dd class="mono">{item.standard_name}</dd>
          {#if detail && detail.files.length > 1}
            <dt>Arquivos</dt>
            <dd>
              {#each detail.files as f (f.id)}
                <div class="faint">{f.role === 'live-video' ? 'Vídeo da Live Photo' : f.role === 'original' ? 'Original' : f.role} · {bytes(f.size_bytes)}</div>
              {/each}
            </dd>
          {/if}
          {#if detail?.suggestions.length}
            <dt>Sugestões</dt><dd>{detail.suggestions.map((s) => suggestionLabel[s.kind]).join(', ')}</dd>
          {/if}
        </dl>
      </aside>
    {/if}
  </div>
{/if}

<style>
  .viewer {
    position: fixed;
    inset: 0;
    z-index: 100;
    background: #05070a;
    display: grid;
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
    outline: none;
    animation: fade 0.16s var(--ease);
  }
  .viewer.info-open {
    grid-template-columns: 1fr 340px;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  .vbar {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: calc(var(--sat) + 6px) calc(var(--sar) + 10px) 6px calc(var(--sal) + 10px);
    background: linear-gradient(to bottom, rgba(5, 7, 10, 0.9), rgba(5, 7, 10, 0.6));
    z-index: 2;
  }
  .vbar .icon-btn {
    color: #d5dde5;
  }
  .vbar .icon-btn.on {
    background: var(--raised);
    color: var(--accent);
  }
  .vbar .icon-btn.star {
    color: var(--accent);
  }
  .title {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    line-height: 1.25;
  }
  .name {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 600;
    font-size: 14px;
  }
  .pos {
    font-size: 12px;
    color: var(--faint);
  }
  .acts {
    display: flex;
    align-items: center;
    gap: 2px;
  }
  .stage {
    position: relative;
    overflow: hidden;
    display: grid;
    place-items: center;
    touch-action: pan-y pinch-zoom;
    padding-bottom: var(--sab);
  }
  .media {
    width: 100%;
    height: 100%;
    display: grid;
    place-items: center;
    position: relative;
  }
  .media > img,
  .media > video {
    grid-area: 1 / 1;
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
  }
  .media > video {
    width: 100%;
    height: 100%;
  }
  .full {
    opacity: 0;
    transition: opacity 0.18s;
  }
  .full.loaded {
    opacity: 1;
  }
  .blur {
    width: 100%;
    height: 100%;
    filter: blur(14px);
    transform: scale(1.04);
    opacity: 0.6;
  }
  .doc {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    text-align: center;
    padding: 24px;
    max-width: 420px;
  }
  .doc-thumb {
    max-width: 240px;
    max-height: 320px;
    border-radius: var(--r-md);
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
    margin-bottom: 10px;
  }
  .doc-icon {
    width: 104px;
    height: 104px;
    border-radius: 24px;
    background: var(--raised);
    display: grid;
    place-items: center;
    color: var(--info);
    margin-bottom: 10px;
  }
  .doc-name {
    font-size: 17px;
    font-weight: 600;
    margin: 0;
    word-break: break-word;
  }
  .doc p.muted {
    margin: 0 0 12px;
  }
  .doc audio {
    width: 300px;
    max-width: 100%;
    margin-bottom: 12px;
  }
  .drive-note {
    color: var(--accent);
    font-weight: 600;
  }
  .drive-pill {
    position: absolute;
    bottom: calc(var(--sab) + 16px);
    left: 50%;
    transform: translateX(-50%);
    display: inline-flex;
    gap: 8px;
    align-items: center;
    padding: 7px 14px;
    border-radius: 999px;
    background: rgba(30, 39, 49, 0.92);
    color: var(--accent);
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
  }
  .link {
    color: var(--text);
    text-decoration: underline;
    font-weight: 600;
  }
  .nav {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: rgba(30, 39, 49, 0.6);
    color: #fff;
    opacity: 0;
    transition: opacity 0.15s;
  }
  .stage:hover .nav,
  .nav:focus-visible {
    opacity: 1;
  }
  .prev {
    left: 14px;
  }
  .next {
    right: 14px;
  }
  @media (hover: none) {
    .nav {
      display: none;
    }
  }
  .info {
    background: var(--surface);
    border-left: 1px solid var(--line-soft);
    overflow-y: auto;
    padding: 18px 20px calc(var(--sab) + 24px);
  }
  .info h2 {
    font-size: 16px;
    margin-bottom: 14px;
  }
  dl {
    margin: 0;
    display: grid;
    gap: 3px 0;
  }
  dt {
    font-size: 12px;
    color: var(--faint);
    margin-top: 10px;
  }
  dd {
    margin: 0;
    font-size: 14px;
    word-break: break-word;
  }
  .uncertain {
    display: inline-block;
    margin-left: 6px;
    padding: 0 7px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--warn);
    font-size: 12px;
    font-weight: 600;
  }
  .small {
    font-size: 12.5px;
    margin-left: 6px;
  }
  .vol {
    padding: 0 5px;
    border-radius: 3px;
    background: #f3e7c9;
    color: #3b2c0c;
    font-size: 11px;
    font-weight: 750;
    border-left: 3px solid var(--accent);
  }
  .mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12.5px;
    color: var(--muted);
  }
  @media (max-width: 899px) {
    .viewer.info-open {
      grid-template-columns: 1fr;
      grid-template-rows: auto 1fr auto;
    }
    .info {
      grid-column: 1;
      max-height: 48vh;
      border-left: 0;
      border-top: 1px solid var(--line-soft);
      border-radius: var(--r-lg) var(--r-lg) 0 0;
    }
    .acts .btn {
      padding: 0 10px;
    }
  }
</style>
