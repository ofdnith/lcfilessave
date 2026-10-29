<script lang="ts">
  // Month-grouped grid (media) or list (documents & co.), with infinite scroll and optional selection.
  import type { Snippet } from 'svelte';
  import type { SvelteSet } from 'svelte/reactivity';
  import Thumb from './Thumb.svelte';
  import Icon, { type IconName } from './Icon.svelte';
  import { bytes, captureDate, monthKey, monthLabel, plural } from '../lib/format';
  import type { ItemList } from '../lib/itemlist.svelte';
  import type { Item } from '../lib/types';

  let {
    list,
    layout,
    selection = null,
    selecting = false,
    onopen,
    onselectstart,
    rowExtra,
    empty = 'Nada aqui ainda',
    emptyHint = '',
  }: {
    list: ItemList;
    layout: 'grid' | 'list';
    selection?: SvelteSet<number> | null;
    selecting?: boolean;
    onopen: (index: number) => void;
    onselectstart?: () => void;
    rowExtra?: Snippet<[Item]>;
    empty?: string;
    emptyHint?: string;
  } = $props();

  interface Group {
    key: string;
    label: string;
    entries: { item: Item; index: number }[];
  }

  const groups = $derived.by(() => {
    const out: Group[] = [];
    let cur: Group | null = null;
    list.items.forEach((item, index) => {
      const k = monthKey(item);
      if (!cur || cur.key !== k) {
        cur = { key: k, label: monthLabel(k), entries: [] };
        out.push(cur);
      }
      cur.entries.push({ item, index });
    });
    return out;
  });

  let lastClicked = -1;

  function click(e: MouseEvent, index: number, item: Item) {
    if (selection && (selecting || e.metaKey || e.ctrlKey)) {
      if (!selecting) onselectstart?.();
      if (e.shiftKey && lastClicked >= 0) {
        const [a, b] = [Math.min(lastClicked, index), Math.max(lastClicked, index)];
        for (let i = a; i <= b; i++) selection.add(list.items[i].id);
      } else if (selection.has(item.id)) selection.delete(item.id);
      else selection.add(item.id);
      lastClicked = index;
      return;
    }
    onopen(index);
  }

  function toggleCheck(e: MouseEvent, index: number, item: Item) {
    e.stopPropagation();
    if (!selection) return;
    if (!selecting) onselectstart?.();
    click({ ...e, metaKey: true, shiftKey: e.shiftKey } as MouseEvent, index, item);
  }

  function selectMonth(g: Group) {
    if (!selection) return;
    const all = g.entries.every((e) => selection.has(e.item.id));
    for (const e of g.entries) all ? selection.delete(e.item.id) : selection.add(e.item.id);
  }

  // Infinite scroll: load the next page when the sentinel approaches the viewport.
  let sentinel = $state<HTMLElement | null>(null);
  $effect(() => {
    if (!sentinel) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((en) => en.isIntersecting)) void list.more();
      },
      { rootMargin: '1200px 0px' },
    );
    io.observe(sentinel);
    return () => io.disconnect();
  });

  const rowIcon: Record<Item['kind'], IconName> = {
    photo: 'photo',
    video: 'video',
    document: 'doc',
    audio: 'audio',
    other: 'file',
  };
</script>

{#if list.items.length === 0 && !list.loading}
  {#if list.error}
    <div class="state">
      <p class="error-text">{list.error}</p>
      <button class="btn" onclick={() => list.reload()}>Tentar de novo</button>
    </div>
  {:else if list.done}
    <div class="state">
      <div class="empty-mark"><Icon name="library" size={30} /></div>
      <p class="empty-title">{empty}</p>
      {#if emptyHint}<p class="muted">{emptyHint}</p>{/if}
    </div>
  {/if}
{/if}

{#each groups as g (g.key)}
  <section class="month" data-month={g.key}>
    <header class="month-head">
      <h2>{g.label}</h2>
      {#if selection && selecting}
        <button class="btn ghost small" onclick={() => selectMonth(g)}>
          {g.entries.every((e) => selection.has(e.item.id)) ? 'Desmarcar mês' : 'Selecionar tudo do mês'}
        </button>
      {/if}
    </header>

    {#if layout === 'grid'}
      <div class="grid">
        {#each g.entries as { item, index } (item.id)}
          <div class="cell">
            <button
              class="tile"
              aria-label="{item.original_name}, {captureDate(item)}"
              aria-pressed={selection && selecting ? selection.has(item.id) : undefined}
              onclick={(e) => click(e, index, item)}
            >
              <Thumb {item} selecting={!!selection && selecting} selected={!!selection?.has(item.id)} />
            </button>
            {#if selection && !selecting}
              <button class="hover-check" aria-label="Selecionar" onclick={(e) => toggleCheck(e, index, item)}>
                <Icon name="check" size={14} />
              </button>
            {/if}
          </div>
        {/each}
      </div>
    {:else}
      <ul class="rows">
        {#each g.entries as { item, index } (item.id)}
          <li class="row" class:sel={selection?.has(item.id)}>
            <button class="row-main" onclick={(e) => click(e, index, item)}>
              {#if selection && selecting}
                <span class="row-check" class:on={selection.has(item.id)}>
                  {#if selection.has(item.id)}<Icon name="check" size={13} />{/if}
                </span>
              {/if}
              <span class="row-icon" data-kind={item.kind}>
                {#if item.thumb_url}
                  <img src={item.thumb_url} alt="" loading="lazy" />
                {:else}
                  <Icon name={rowIcon[item.kind]} size={20} />
                {/if}
              </span>
              <span class="row-name">
                <span class="name">{item.original_name}</span>
                <span class="meta">
                  {captureDate(item)}{#if item.date_uncertain}<em>(data incerta)</em>{/if}
                  {#if item.volume && !item.on_server}<span class="vol">{item.volume.name}</span>{/if}
                  {#if item.important}<span class="imp"><Icon name="star" size={11} fill /></span>{/if}
                </span>
              </span>
              <span class="row-size num">{bytes(item.size_bytes)}</span>
            </button>
            {#if rowExtra}<div class="row-extra">{@render rowExtra(item)}</div>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>
{/each}

<div bind:this={sentinel} class="sentinel">
  {#if list.loading}
    <span class="spinner" aria-label="Carregando"></span>
  {:else if list.error && list.items.length}
    <span class="error-text">{list.error}</span>
    <button class="btn small" onclick={() => list.more()}>Tentar de novo</button>
  {:else if list.done && list.items.length > 40}
    <span class="faint">{plural(list.total, 'item', 'itens')} · fim da lista</span>
  {/if}
</div>

<style>
  .month {
    content-visibility: auto;
    contain-intrinsic-size: auto 600px;
    margin-bottom: 18px;
  }
  .month-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-height: 40px;
    padding: 6px 2px;
  }
  .month-head h2 {
    font-size: 15px;
    font-weight: 620;
    color: var(--text);
  }
  .month-head h2::first-letter {
    text-transform: uppercase;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
    gap: 3px;
  }
  .cell {
    position: relative;
  }
  .tile {
    display: block;
    width: 100%;
  }
  .tile:focus-visible {
    outline-offset: -2px;
    border-radius: 0;
  }
  .hover-check {
    position: absolute;
    top: 6px;
    left: 6px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.9);
    background: rgba(0, 0, 0, 0.3);
    color: transparent;
    display: grid;
    place-items: center;
    opacity: 0;
    transition: opacity 0.12s;
  }
  .cell:hover .hover-check,
  .hover-check:focus-visible {
    opacity: 1;
  }
  .hover-check:hover {
    color: #fff;
  }
  @media (hover: none) {
    .hover-check {
      display: none;
    }
  }
  /* Full-bleed on phones: the section itself bleeds, because content-visibility
     clips anything a child draws outside the section box. */
  @media (max-width: 899px) {
    .month {
      margin: 0 -16px 18px;
    }
    .month-head {
      padding: 6px 16px;
    }
    .grid {
      grid-template-columns: repeat(auto-fill, minmax(92px, 1fr));
      gap: 2px;
    }
    .rows {
      padding: 0 10px;
    }
  }

  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--line-soft);
  }
  .row {
    display: flex;
    align-items: center;
    border-bottom: 1px solid var(--line-soft);
  }
  .row.sel {
    background: var(--accent-soft);
  }
  .row-main {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 9px 6px;
    text-align: left;
  }
  .row-main:hover {
    background: var(--surface);
  }
  .row-check {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 2px solid var(--faint);
    display: grid;
    place-items: center;
    flex: none;
    color: var(--accent-ink);
  }
  .row-check.on {
    background: var(--accent);
    border-color: var(--accent);
  }
  .row-icon {
    width: 40px;
    height: 40px;
    flex: none;
    border-radius: var(--r-sm);
    background: var(--raised);
    display: grid;
    place-items: center;
    overflow: hidden;
    color: var(--info);
  }
  .row-icon[data-kind='audio'] {
    color: #c7a6ff;
  }
  .row-icon[data-kind='other'] {
    color: var(--muted);
  }
  .row-icon img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .row-name {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 520;
  }
  .meta {
    font-size: 12.5px;
    color: var(--muted);
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .meta em {
    font-style: normal;
    color: var(--warn);
  }
  .vol {
    padding: 0 5px;
    border-radius: 3px;
    background: #f3e7c9;
    color: #3b2c0c;
    font-size: 10px;
    font-weight: 750;
    border-left: 3px solid var(--accent);
  }
  .imp {
    color: var(--accent);
    display: inline-flex;
  }
  .row-size {
    color: var(--muted);
    font-size: 13px;
    flex: none;
  }
  .row-extra {
    padding-right: 6px;
    flex: none;
  }

  .sentinel {
    min-height: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    font-size: 13px;
  }
  .spinner {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 2.5px solid var(--line);
    border-top-color: var(--accent);
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .state {
    padding: 64px 16px;
    text-align: center;
  }
  .empty-mark {
    width: 64px;
    height: 64px;
    margin: 0 auto 14px;
    border-radius: 50%;
    background: var(--surface);
    display: grid;
    place-items: center;
    color: var(--faint);
  }
  .empty-title {
    font-size: 17px;
    font-weight: 600;
    margin: 0 0 4px;
  }
</style>
