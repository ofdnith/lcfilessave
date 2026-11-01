<script lang="ts">
  // One item at a time: ← discard, → keep, ↑ important. Only discards can be undone (restore):
  // the catalog never lets an item go back from the Acervo to the Entrada.
  //
  // Speed: the card shows the 1024 px medium preview (≈100 KB, already made on arrival), never
  // the original — an iPhone HEIC would be converted on the phone for every card. Actions apply
  // on screen at once and are sent to the server in order in the background; a failure puts the
  // item back and says why. The next cards are fetched and decoded ahead of time.
  import { untrack } from 'svelte';
  import { SvelteMap } from 'svelte/reactivity';
  import Icon from './Icon.svelte';
  import { api, ApiError } from '../lib/api';
  import { bytes, captureDateTime, kindLabel, num } from '../lib/format';
  import { refreshStats } from '../lib/stats.svelte';
  import { app, invalidate, toast } from '../lib/state.svelte';
  import type { ItemList } from '../lib/itemlist.svelte';
  import type { Item } from '../lib/types';

  let { list, onclose }: { list: ItemList; onclose: () => void } = $props();

  type Verdict = 'keep' | 'discard' | 'important';

  let doneCount = $state(0);
  // Total at the start of the session; set once the first page arrives.
  let startTotal = $state(0);
  $effect(() => {
    if (!startTotal && list.total) startTotal = list.total + untrack(() => doneCount);
  });

  const item = $derived(list.items[0] ?? null);
  const next = $derived(list.items[1] ?? null);
  const progress = $derived(startTotal ? Math.min(100, (doneCount / startTotal) * 100) : 0);

  // --- what to show ------------------------------------------------------------------------
  /** Light image for the card: medium preview, else thumbnail, else (still processing) the preview. */
  function cardSrc(it: Item): string | null {
    if (it.kind !== 'photo' && it.kind !== 'video') return it.thumb_url;
    return it.medium_url ?? it.thumb_url ?? (it.kind === 'photo' ? it.preview_url : null);
  }
  // Each card takes its picture's exact shape, so tints, stamps and the card behind line up
  // with the photo (no transparent letterbox). Catalog size first, real size once loaded.
  const shapes = new SvelteMap<number, number>();
  function shape(it: Item): number {
    if (it.kind !== 'photo' && it.kind !== 'video') return 0.8;
    const r = shapes.get(it.id) ?? (it.width && it.height ? it.width / it.height : 0.75);
    return Math.min(5, Math.max(0.2, r));
  }
  function measured(it: Item, e: Event) {
    const im = e.currentTarget as HTMLImageElement;
    if (!im.naturalWidth || !im.naturalHeight) return;
    const r = im.naturalWidth / im.naturalHeight;
    const old = shapes.get(it.id) ?? (it.width && it.height ? it.width / it.height : 0);
    if (Math.abs(old - r) > 0.02) shapes.set(it.id, r);
  }
  let hdFor = $state<number | null>(null);
  let playingFor = $state<number | null>(null);
  let loadedFor = $state<number | null>(null);
  const showHd = $derived(!!item && hdFor === item.id && !!item.preview_url);
  const src = $derived(item ? (showHd ? item.preview_url : cardSrc(item)) : null);

  // Fetch and decode the next few cards so each swipe shows a ready picture.
  const ahead = new Map<string, HTMLImageElement>();
  $effect(() => {
    const want = list.items
      .slice(1, 5)
      .map(cardSrc)
      .filter((s): s is string => !!s);
    for (const url of want) {
      if (ahead.has(url)) continue;
      const im = new Image();
      im.decoding = 'async';
      im.src = url;
      im.decode().catch(() => {});
      ahead.set(url, im);
    }
    for (const url of [...ahead.keys()]) if (!want.includes(url)) ahead.delete(url);
  });

  $effect(() => {
    if (list.items.length < 8 && !list.done && !list.loading) void list.more();
  });

  // --- actions: optimistic, sent in order --------------------------------------------------
  let chain: Promise<void> = Promise.resolve();
  let pending = $state(0);
  function send(job: () => Promise<void>) {
    pending++;
    chain = chain
      .then(job)
      .catch(() => {})
      .finally(() => {
        pending--;
        if (pending === 0) statsSoon();
      });
  }
  let statsTimer: ReturnType<typeof setTimeout> | undefined;
  function statsSoon() {
    clearTimeout(statsTimer);
    statsTimer = setTimeout(() => void refreshStats(), 1200);
  }

  function errorText(e: unknown, fallback: string) {
    return e instanceof ApiError ? e.message : fallback;
  }

  /** Put an item back at the top of the pile (its action failed). */
  function putBack(it: Item) {
    if (list.items.some((i) => i.id === it.id)) return;
    list.items.unshift(it);
    list.total++;
    doneCount = Math.max(0, doneCount - 1);
  }

  // Discards that can still be undone, newest last.
  let discarded = $state<Item[]>([]);

  // The card that just left flies out while the next one is already usable.
  let ghost = $state<{ item: Item; src: string | null; dir: Verdict; key: number } | null>(null);
  let ghostKey = 0;
  let flash = $state<Verdict | null>(null);
  let flashTimer: ReturnType<typeof setTimeout> | undefined;

  function act(action: Verdict) {
    const it = item;
    if (!it) return;
    if (action === 'discard' && app.readonly) {
      toast('Fora de casa não dá para descartar (modo seguro).', 'info', undefined, 2500);
      return;
    }
    clearTimeout(flashTimer);
    flash = action;
    flashTimer = setTimeout(() => (flash = null), 260);

    if (action === 'important') {
      const target = !it.important;
      list.patch(it.id, { important: target });
      send(async () => {
        try {
          const r = await api.actions([it.id], target ? 'important' : 'unimportant');
          if (!r.ok.includes(it.id)) throw new Error(r.failed[0]?.error ?? 'Ação não concluída.');
        } catch (e) {
          list.patch(it.id, { important: !target });
          toast(errorText(e, e instanceof Error ? e.message : 'Ação não concluída.'), 'error');
        }
      });
      return;
    }

    ghost = { item: it, src: hdFor === it.id ? it.preview_url : cardSrc(it), dir: action, key: ++ghostKey };
    const k = ghostKey;
    setTimeout(() => {
      if (ghost?.key === k) ghost = null;
    }, 320);
    list.remove([it.id]);
    doneCount++;
    if (action === 'discard') discarded = [...discarded.slice(-19), it];

    send(async () => {
      try {
        const r = await api.actions([it.id], action);
        if (!r.ok.includes(it.id)) throw new Error(r.failed[0]?.error ?? 'Ação não concluída.');
      } catch (e) {
        discarded = discarded.filter((d) => d.id !== it.id);
        putBack(it);
        toast(`${it.original_name}: ${errorText(e, e instanceof Error ? e.message : 'Ação não concluída.')}`, 'error');
      }
    });
  }

  function undo() {
    const it = discarded[discarded.length - 1];
    if (!it) return;
    discarded = discarded.slice(0, -1);
    putBack({ ...it, state: 'inbox' });
    send(async () => {
      try {
        const r = await api.actions([it.id], 'restore');
        if (!r.ok.includes(it.id)) throw new Error(r.failed[0]?.error ?? 'Não foi possível desfazer.');
      } catch (e) {
        list.remove([it.id]);
        doneCount++;
        toast(errorText(e, e instanceof Error ? e.message : 'Não foi possível desfazer.'), 'error');
      }
    });
  }

  let closing = $state(false);
  async function close() {
    if (closing) return;
    closing = true;
    await chain; // let queued actions reach the server before the lists reload
    clearTimeout(statsTimer);
    void refreshStats();
    invalidate();
    onclose();
  }

  $effect(() => {
    const h = (e: BeforeUnloadEvent) => {
      if (pending > 0) e.preventDefault();
    };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  });

  function onKey(e: KeyboardEvent) {
    if ((e.target as HTMLElement).tagName === 'INPUT') return;
    if (e.key === 'ArrowLeft') act('discard');
    else if (e.key === 'ArrowRight') act('keep');
    else if (e.key === 'ArrowUp') act('important');
    else if ((e.key === 'z' && (e.metaKey || e.ctrlKey)) || e.key === 'Backspace') undo();
    else if (e.key === 'h' || e.key === 'H') toggleHd();
    else if (e.key === ' ' && item?.kind === 'video') playingFor = playingFor === item.id ? null : item.id;
    else if (e.key === 'Escape') void close();
    else return;
    e.preventDefault();
  }

  function toggleHd() {
    if (!item?.preview_url || item.kind !== 'photo') return;
    hdFor = hdFor === item.id ? null : item.id;
  }

  // --- swipe (touch, pen and mouse) --------------------------------------------------------
  let dx = $state(0);
  let dy = $state(0);
  let dragging = $state(false);
  let area = $state<HTMLElement | null>(null);
  let sx = 0;
  let sy = 0;
  let st = 0;
  let pid: number | null = null;

  function down(e: PointerEvent) {
    if (!item || (e.target as HTMLElement).closest('button, video, a')) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    pid = e.pointerId;
    sx = e.clientX;
    sy = e.clientY;
    st = performance.now();
    dragging = true;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent) {
    if (!dragging || e.pointerId !== pid) return;
    dx = e.clientX - sx;
    dy = Math.min(0, e.clientY - sy);
  }
  function up(e: PointerEvent) {
    if (!dragging || e.pointerId !== pid) return;
    dragging = false;
    pid = null;
    const w = area?.clientWidth ?? 400;
    const x = dx;
    const y = dy;
    const speed = Math.abs(x) / Math.max(1, performance.now() - st); // px per ms
    dx = 0;
    dy = 0;
    const horizontal = Math.abs(x) > Math.abs(y);
    const far = Math.abs(x) > Math.min(110, w * 0.22) || (speed > 0.6 && Math.abs(x) > 40);
    if (horizontal && far) act(x < 0 ? 'discard' : 'keep');
    else if (!horizontal && y < -110) act('important');
  }

  const hint = $derived<Verdict | null>(dx < -30 ? 'discard' : dx > 30 ? 'keep' : dy < -50 ? 'important' : null);
  const strength = $derived(Math.min(1, Math.max(Math.abs(dx) / 140, -dy / 160)));
</script>

<svelte:window onkeydown={onKey} />

<div class="quick" role="dialog" aria-modal="true" aria-label="Modo rápido">
  <header>
    <button class="icon-btn" onclick={close} aria-label="Sair do modo rápido" disabled={closing}><Icon name="close" /></button>
    <div class="prog">
      <div class="bar keep"><span style:width="{progress}%"></span></div>
      <span class="num muted">
        {num(doneCount)} triados · {num(list.total)} restantes
        {#if pending > 0}<span class="saving">· salvando…</span>{/if}
      </span>
    </div>
    <button class="btn small" disabled={!discarded.length} onclick={undo} title="Desfazer descarte (⌫)">
      <Icon name="undo" size={16} /> Desfazer
    </button>
  </header>

  <div
    class="card-area"
    bind:this={area}
    onpointerdown={down}
    onpointermove={move}
    onpointerup={up}
    onpointercancel={up}
    role="presentation"
  >
    {#if item}
      <div class="stack" class:moving={dragging || !!ghost}>
        {#if next}
          {@const nsrc = cardSrc(next)}
          <div class="card behind" style:--r={shape(next)} aria-hidden="true">
            {#if nsrc}<img src={nsrc} alt="" decoding="async" onload={(e) => measured(next, e)} />{/if}
          </div>
        {/if}

        {#key item.id}
          <figure
            class="card top"
            class:dragging
            class:fl-keep={flash === 'keep'}
            class:fl-discard={flash === 'discard'}
            class:fl-important={flash === 'important'}
            style:--r={shape(item)}
            style:transform={dx || dy ? `translate(${dx}px, ${dy}px) rotate(${dx / 28}deg)` : undefined}
          >
            {#if item.kind === 'video' && playingFor === item.id && item.preview_url}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video src={item.preview_url} controls playsinline autoplay poster={src ?? undefined}></video>
            {:else if src}
              {#if item.thumb_url && loadedFor !== item.id && src !== item.thumb_url}
                <img class="placeholder" src={item.thumb_url} alt="" aria-hidden="true" />
              {/if}
              <img
                class="main"
                {src}
                alt={item.original_name}
                decoding="async"
                draggable="false"
                onload={(e) => {
                  loadedFor = item.id;
                  measured(item, e);
                }}
              />
              {#if item.kind === 'video' && item.preview_url}
                <button class="play" onclick={() => (playingFor = item.id)} aria-label="Reproduzir vídeo">
                  <Icon name="play" size={30} fill />
                </button>
              {/if}
            {:else}
              <div class="doc"><Icon name="doc" size={56} /><span>{item.original_name}</span></div>
            {/if}

            <span class="tint {hint ?? ''}" style:opacity={hint ? strength * 0.35 : 0}></span>
            {#if hint}
              <span class="stamp {hint}" style:opacity={0.35 + strength * 0.65}>
                {hint === 'keep' ? 'Manter' : hint === 'discard' ? 'Descartar' : 'Importante'}
              </span>
            {/if}
            {#if item.important}<span class="imp"><Icon name="star" size={18} fill /></span>{/if}
            <span class="badges">
              {#if item.is_screenshot}<span class="badge">Captura de tela</span>{/if}
              {#if item.origin_app}<span class="badge">{item.origin_app}</span>{/if}
              {#if item.is_live_photo}<span class="badge">Live</span>{/if}
            </span>
          </figure>
        {/key}

        {#if ghost}
          {#key ghost.key}
            <div class="card ghost fly-{ghost.dir}" style:--r={shape(ghost.item)} aria-hidden="true">
              {#if ghost.src}<img src={ghost.src} alt="" />{/if}
            </div>
          {/key}
        {/if}
      </div>

      <div class="meta">
        <div class="meta-text">
          <span class="name">{item.original_name}</span>
          <span class="faint">
            {captureDateTime(item)} · {kindLabel[item.kind]} · {bytes(item.size_bytes)}{item.place ? ` · ${item.place}` : ''}
          </span>
        </div>
        {#if item.kind === 'photo' && item.preview_url && item.medium_url}
          <button class="btn small ghost" class:on={showHd} onclick={toggleHd} aria-pressed={showHd} title="Ver em alta resolução (H)">
            <Icon name="hd" size={16} /><span class="hide-sm">{showHd ? 'Prévia' : 'Alta'}</span>
          </button>
        {/if}
      </div>
    {:else if list.loading}
      <p class="muted">Carregando…</p>
    {:else}
      <div class="finished">
        <div class="ok"><Icon name="check" size={34} /></div>
        <h2>Entrada vazia</h2>
        <p class="muted">Você triou {num(doneCount)} {doneCount === 1 ? 'item' : 'itens'}.</p>
        <button class="btn primary" onclick={close} disabled={closing}>{closing ? 'Salvando…' : 'Concluir'}</button>
      </div>
    {/if}
  </div>

  {#if item}
    <footer>
      <button class="big discard" onclick={() => act('discard')} disabled={app.readonly}>
        <Icon name="trash" size={22} /><span>Descartar</span><kbd>←</kbd>
      </button>
      <button class="big important" class:on={item.important} onclick={() => act('important')}>
        <Icon name="star" size={22} fill={item.important} /><span>Importante</span><kbd>↑</kbd>
      </button>
      <button class="big keep" onclick={() => act('keep')}>
        <Icon name="check" size={22} /><span>Manter</span><kbd>→</kbd>
      </button>
    </footer>
  {/if}
</div>

<style>
  .quick {
    position: fixed;
    inset: 0;
    z-index: 90;
    background: var(--bg);
    display: grid;
    grid-template-rows: auto 1fr auto;
    padding: var(--sat) var(--sar) var(--sab) var(--sal);
    overscroll-behavior: contain;
  }
  header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 10px 14px;
  }
  .prog {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 5px;
    font-size: 12.5px;
    max-width: 520px;
    margin: 0 auto;
  }
  .saving {
    color: var(--faint);
  }
  .card-area {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
    padding: 6px 16px;
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
  }
  .card-area > p,
  .card-area > .finished {
    margin: auto;
  }
  /* All cards share one box; the picture is contained inside it, so nothing is ever cut. */
  .stack {
    position: relative;
    flex: 1;
    min-height: 0;
    width: 100%;
    max-width: 1100px;
    margin: 0 auto;
    container-type: size;
  }
  /* Largest box with the picture's shape (--r = width / height) that fits the stack. */
  .card {
    position: absolute;
    left: 50%;
    top: 50%;
    translate: -50% -50%;
    width: min(100cqw, 100cqh * var(--r, 1));
    height: min(100cqh, 100cqw / var(--r, 1));
    margin: 0;
    border-radius: var(--r-lg);
    overflow: hidden;
    background: var(--surface);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
  }
  .card img,
  .card video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
    -webkit-user-drag: none;
  }
  .placeholder {
    filter: blur(8px);
    transform: scale(1.02);
  }
  .top {
    transition: transform 0.22s var(--ease);
    animation: pop 0.16s var(--ease);
    will-change: transform;
  }
  .top.dragging {
    transition: none;
  }
  @keyframes pop {
    from {
      opacity: 0.4;
      transform: scale(0.96);
    }
  }
  /* The next card is always rendered (so it is decoded and ready) but only shows while the
     current one moves: the letterbox around a contained picture is transparent. */
  .behind {
    transform: scale(0.94);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.15s;
  }
  .moving .behind {
    opacity: 0.45;
  }
  .ghost {
    pointer-events: none;
    animation-duration: 0.3s;
    animation-timing-function: cubic-bezier(0.4, 0, 1, 1);
    animation-fill-mode: forwards;
  }
  .fly-keep {
    animation-name: fly-right;
  }
  .fly-discard {
    animation-name: fly-left;
  }
  @keyframes fly-right {
    to {
      transform: translateX(110%) rotate(14deg);
      opacity: 0;
    }
  }
  @keyframes fly-left {
    to {
      transform: translateX(-110%) rotate(-14deg);
      opacity: 0;
    }
  }
  .fl-important {
    animation: bump 0.26s var(--ease);
  }
  @keyframes bump {
    40% {
      transform: translateY(-14px) scale(1.01);
    }
  }
  .tint {
    position: absolute;
    inset: 0;
    pointer-events: none;
    transition: opacity 0.12s;
  }
  .tint.keep {
    background: var(--keep);
  }
  .tint.discard {
    background: var(--danger);
  }
  .tint.important {
    background: var(--accent);
  }
  .doc {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 40px;
    background: var(--surface);
    color: var(--info);
    text-align: center;
  }
  .doc span {
    color: var(--text);
    word-break: break-word;
  }
  .play {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 68px;
    height: 68px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: rgba(0, 0, 0, 0.5);
    color: #fff;
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
  }
  .stamp {
    position: absolute;
    top: 18px;
    padding: 6px 14px;
    border-radius: 8px;
    font-weight: 800;
    font-size: 20px;
    border: 3px solid;
    background: rgba(0, 0, 0, 0.45);
    pointer-events: none;
  }
  .stamp.keep {
    left: 18px;
    color: var(--keep);
    transform: rotate(-8deg);
  }
  .stamp.discard {
    right: 18px;
    color: var(--danger);
    transform: rotate(8deg);
  }
  .stamp.important {
    left: 50%;
    transform: translateX(-50%);
    color: var(--accent);
  }
  .imp {
    position: absolute;
    top: 10px;
    right: 10px;
    color: var(--accent);
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.6));
  }
  .badges {
    position: absolute;
    left: 10px;
    bottom: 10px;
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    pointer-events: none;
  }
  .badge {
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.55);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
  }
  .meta {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    max-width: 1100px;
    margin: 0 auto;
    font-size: 13.5px;
  }
  .meta-text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
  .meta-text .name {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
  }
  .meta .btn.on {
    color: var(--accent);
  }
  footer {
    display: flex;
    justify-content: center;
    gap: 12px;
    padding: 12px 16px 16px;
  }
  .big {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    min-width: 104px;
    padding: 12px 16px;
    border-radius: var(--r-lg);
    background: var(--surface);
    border: 1px solid var(--line-soft);
    font-weight: 600;
    font-size: 13.5px;
    transition: transform 0.08s;
  }
  .big:active {
    transform: scale(0.96);
  }
  .big:disabled {
    opacity: 0.6;
  }
  .big.discard {
    color: var(--danger);
  }
  .big.keep {
    color: var(--keep);
  }
  .big.important {
    color: var(--muted);
  }
  .big.important.on {
    color: var(--accent);
  }
  .big:hover {
    background: var(--raised);
  }
  .big kbd {
    font: inherit;
    font-size: 11px;
    color: var(--faint);
  }
  @media (hover: none) {
    .big kbd {
      display: none;
    }
    .big {
      min-width: 0;
      flex: 1;
    }
  }
  @media (max-width: 899px) {
    .hide-sm {
      display: none;
    }
    .card-area {
      padding: 4px 8px;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .top,
    .ghost,
    .fl-important {
      animation: none;
      transition: none;
    }
    .ghost {
      display: none;
    }
  }
  .finished {
    text-align: center;
  }
  .finished h2 {
    margin: 8px 0 4px;
  }
  .ok {
    width: 72px;
    height: 72px;
    border-radius: 50%;
    background: var(--keep-soft);
    color: var(--keep);
    display: grid;
    place-items: center;
    margin: 0 auto;
  }
</style>
