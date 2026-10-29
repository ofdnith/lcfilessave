<script lang="ts">
  import { untrack } from 'svelte';
  // One item at a time: ← discard, → keep, ↑ important. Only discards can be undone (restore).
  import Icon from './Icon.svelte';
  import { api, ApiError } from '../lib/api';
  import { bytes, captureDateTime, kindLabel, num } from '../lib/format';
  import { refreshStats } from '../lib/stats.svelte';
  import { invalidate, toast } from '../lib/state.svelte';
  import type { ItemList } from '../lib/itemlist.svelte';
  import type { Item } from '../lib/types';

  let { list, onclose }: { list: ItemList; onclose: () => void } = $props();

  let doneCount = $state(0);
  // Total at the start of the session; set once the first page arrives.
  let startTotal = $state(0);
  $effect(() => {
    if (!startTotal && list.total) startTotal = list.total + untrack(() => doneCount);
  });
  let lastDiscard = $state<Item | null>(null);
  let busy = $state(false);
  let flash = $state<'keep' | 'discard' | 'important' | null>(null);
  let dx = $state(0);
  let dy = $state(0);

  const item = $derived(list.items[0] ?? null);
  const next = $derived(list.items[1] ?? null);
  const progress = $derived(startTotal ? Math.min(100, (doneCount / startTotal) * 100) : 0);

  $effect(() => {
    if (list.items.length < 6 && !list.done && !list.loading) void list.more();
  });
  $effect(() => {
    if (next?.preview_url && next.kind === 'photo') new Image().src = next.preview_url;
  });

  async function act(action: 'keep' | 'discard' | 'important') {
    if (!item || busy) return;
    busy = true;
    const it = item;
    flash = action;
    try {
      if (action === 'important') {
        const target = !it.important;
        const r = await api.actions([it.id], target ? 'important' : 'unimportant');
        if (r.ok.includes(it.id)) list.patch(it.id, { important: target });
      } else {
        const r = await api.actions([it.id], action);
        if (r.ok.includes(it.id)) {
          list.remove([it.id]);
          doneCount++;
          lastDiscard = action === 'discard' ? it : null;
          void refreshStats();
        } else toast(r.failed[0]?.error ?? 'Ação não concluída.', 'error');
      }
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Ação não concluída.', 'error');
    } finally {
      busy = false;
      setTimeout(() => (flash = null), 220);
    }
  }

  async function undo() {
    const it = lastDiscard;
    if (!it || busy) return;
    busy = true;
    try {
      const r = await api.actions([it.id], 'restore');
      if (r.ok.includes(it.id)) {
        list.items.unshift({ ...it, state: 'inbox' });
        list.total++;
        doneCount = Math.max(0, doneCount - 1);
        lastDiscard = null;
        void refreshStats();
      } else toast(r.failed[0]?.error ?? 'Não foi possível desfazer.', 'error');
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível desfazer.', 'error');
    } finally {
      busy = false;
    }
  }

  function close() {
    invalidate();
    onclose();
  }

  function onKey(e: KeyboardEvent) {
    if ((e.target as HTMLElement).tagName === 'INPUT') return;
    if (e.key === 'ArrowLeft') act('discard');
    else if (e.key === 'ArrowRight') act('keep');
    else if (e.key === 'ArrowUp') act('important');
    else if ((e.key === 'z' && (e.metaKey || e.ctrlKey)) || e.key === 'Backspace') undo();
    else if (e.key === 'Escape') close();
    else return;
    e.preventDefault();
  }

  let sx = 0;
  let sy = 0;
  let touching = false;
  function ts(e: TouchEvent) {
    sx = e.touches[0].clientX;
    sy = e.touches[0].clientY;
    touching = true;
  }
  function tm(e: TouchEvent) {
    if (!touching) return;
    dx = e.touches[0].clientX - sx;
    dy = Math.min(0, e.touches[0].clientY - sy);
  }
  function te() {
    touching = false;
    const x = dx;
    const y = dy;
    dx = 0;
    dy = 0;
    if (x < -90 && Math.abs(x) > Math.abs(y)) act('discard');
    else if (x > 90 && Math.abs(x) > Math.abs(y)) act('keep');
    else if (y < -110) act('important');
  }

  const hint = $derived(dx < -40 ? 'discard' : dx > 40 ? 'keep' : dy < -60 ? 'important' : null);
</script>

<svelte:window onkeydown={onKey} />

<div class="quick" role="dialog" aria-modal="true" aria-label="Modo rápido">
  <header>
    <button class="icon-btn" onclick={close} aria-label="Sair do modo rápido"><Icon name="close" /></button>
    <div class="prog">
      <div class="bar keep"><span style:width="{progress}%"></span></div>
      <span class="num muted">{num(doneCount)} triados · {num(list.total)} restantes</span>
    </div>
    <button class="btn small" disabled={!lastDiscard || busy} onclick={undo} title="Desfazer descarte">
      <Icon name="undo" size={16} /> Desfazer
    </button>
  </header>

  <div class="card-area" ontouchstart={ts} ontouchmove={tm} ontouchend={te} role="presentation">
    {#if item}
      {#key item.id}
        <figure
          class="card"
          class:fl-keep={flash === 'keep'}
          class:fl-discard={flash === 'discard'}
          style:transform={dx || dy ? `translate(${dx}px, ${dy}px) rotate(${dx / 30}deg)` : undefined}
        >
          {#if item.kind === 'video' && item.preview_url}
            <!-- svelte-ignore a11y_media_has_caption -->
            <video src={item.preview_url} controls playsinline autoplay muted loop poster={item.thumb_url ?? undefined}></video>
          {:else if item.kind === 'photo' && (item.preview_url || item.thumb_url)}
            <img src={item.preview_url ?? item.thumb_url} alt={item.original_name} />
          {:else}
            <div class="doc"><Icon name="doc" size={56} /><span>{item.original_name}</span></div>
          {/if}
          {#if hint}
            <span class="stamp {hint}">{hint === 'keep' ? 'Manter' : hint === 'discard' ? 'Descartar' : 'Importante'}</span>
          {/if}
          {#if item.important}<span class="imp"><Icon name="star" size={16} fill /></span>{/if}
        </figure>
      {/key}
      <p class="meta">
        <span>{captureDateTime(item)}</span>
        <span class="faint">{kindLabel[item.kind]} · {bytes(item.size_bytes)}{item.place ? ` · ${item.place}` : ''}</span>
      </p>
    {:else if list.loading}
      <p class="muted">Carregando…</p>
    {:else}
      <div class="finished">
        <div class="ok"><Icon name="check" size={34} /></div>
        <h2>Entrada vazia</h2>
        <p class="muted">Você triou {num(doneCount)} {doneCount === 1 ? 'item' : 'itens'}.</p>
        <button class="btn primary" onclick={close}>Concluir</button>
      </div>
    {/if}
  </div>

  {#if item}
    <footer>
      <button class="big discard" onclick={() => act('discard')} disabled={busy}>
        <Icon name="trash" size={22} /><span>Descartar</span><kbd>←</kbd>
      </button>
      <button class="big important" class:on={item.important} onclick={() => act('important')} disabled={busy}>
        <Icon name="star" size={22} fill={item.important} /><span>Importante</span><kbd>↑</kbd>
      </button>
      <button class="big keep" onclick={() => act('keep')} disabled={busy}>
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
  .card-area {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    min-height: 0;
    padding: 6px 16px;
    touch-action: none;
  }
  .card {
    position: relative;
    margin: 0;
    flex: 1;
    min-height: 0;
    max-width: 100%;
    display: grid;
    place-items: center;
    border-radius: var(--r-lg);
    overflow: hidden;
    transition: box-shadow 0.2s, opacity 0.2s;
    animation: pop 0.18s var(--ease);
  }
  @keyframes pop {
    from {
      opacity: 0;
      transform: scale(0.97);
    }
  }
  .card img,
  .card video {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: var(--r-lg);
    display: block;
  }
  .fl-keep {
    box-shadow: 0 0 0 4px var(--keep);
  }
  .fl-discard {
    box-shadow: 0 0 0 4px var(--danger);
  }
  .doc {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 40px;
    background: var(--surface);
    border-radius: var(--r-lg);
    color: var(--info);
  }
  .doc span {
    color: var(--text);
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
  .meta {
    margin: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    font-size: 14px;
    text-align: center;
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
