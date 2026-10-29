<script lang="ts">
  import { untrack } from 'svelte';
  import ItemBrowser from '../components/ItemBrowser.svelte';
  import KindTabs from '../components/KindTabs.svelte';
  import Scrubber from '../components/Scrubber.svelte';
  import SearchBar from '../components/SearchBar.svelte';
  import SelectionBar from '../components/SelectionBar.svelte';
  import Memories from '../components/Memories.svelte';
  import Icon from '../components/Icon.svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import { runAction } from '../lib/actions';
  import { href, router, go } from '../lib/router.svelte';
  import { pickAlbum } from '../lib/sheets.svelte';
  import type { Action } from '../lib/types';
  import { api } from '../lib/api';
  import { monthLabel, plural } from '../lib/format';
  import { ItemList } from '../lib/itemlist.svelte';
  import { trackMonth } from '../lib/scrollmonth';
  import { app } from '../lib/state.svelte';
  import { openViewer } from '../lib/viewer.svelte';
  import type { ItemQuery } from '../lib/api';
  import type { TimelineMonth } from '../lib/types';

  const list = new ItemList(200);
  const selection = new SvelteSet<number>();
  let selecting = $state(false);
  /** Exact place text from Lugares (#/acervo?place=…). */
  const place = $derived(router.route === 'acervo' ? (router.query.place ?? null) : null);
  let months = $state<TimelineMonth[]>([]);
  let currentMonth = $state<string | null>(null);

  const query = $derived<ItemQuery>({
    view: 'library',
    kind: app.kind,
    q: app.q || undefined,
    year: app.filters.year,
    important: app.filters.important,
    archived: app.filters.archived,
    place,
  });
  const filtering = $derived(
    !!app.q || !!place || app.filters.year !== null || app.filters.important || app.filters.archived !== null || app.kind !== 'all',
  );

  function stopSelecting() {
    selecting = false;
    selection.clear();
  }

  async function batch(action: Action) {
    const ids = [...selection];
    if (!ids.length) return;
    const r = await runAction(ids, action, {
      undo: action === 'discard' ? () => void runAction(ids, 'restore', { reload: true }) : undefined,
    });
    if (!r) return;
    if (action === 'discard') list.remove(r.ok);
    else for (const id of r.ok) list.patch(id, { important: action === 'important' });
    stopSelecting();
  }

  const layout = $derived(app.kind === 'document' || app.kind === 'audio' || app.kind === 'other' ? 'list' : 'grid');
  const years = $derived([...new Set(months.map((m) => m.year))]);
  // Timeline ignores year so the year chip can list every year.
  const visibleMonths = $derived(app.filters.year ? months.filter((m) => m.year === app.filters.year) : months);

  $effect(() => {
    void app.revision;
    const q = query;
    untrack(() => {
      selection.clear();
      void list.reset(q);
      window.scrollTo({ top: 0 });
      api
        .timeline({ ...q, year: null })
        .then((t) => (months = t.months))
        .catch(() => (months = []));
    });
  });

  $effect(() => trackMonth((k) => (currentMonth = k)));

  function jump(start: string) {
    void list.reset(query, start);
    window.scrollTo({ top: 0 });
  }
</script>

<div class="lib">
  <div class="top">
    <div class="search-wrap">
      <SearchBar {years} placeholder="Buscar no acervo: nome, lugar, câmera…" />
    </div>
    <div class="tabs-row">
      <KindTabs value={app.kind} tabs={app.stats?.tabs ?? null} onchange={(k) => (app.kind = k)} />
      <a class="places-link" href={href('lugares')} aria-label="Lugares"><Icon name="map" size={18} /><span>Lugares</span></a>
      <button class="btn small ghost sel-btn" onclick={() => (selecting ? stopSelecting() : (selecting = true))} aria-pressed={selecting}>
        <Icon name="select" size={16} /><span class="sel-lbl">{selecting ? 'Cancelar' : 'Selecionar'}</span>
      </button>
    </div>
  </div>

  <div class="content">
    {#if place}
      <div class="place-head">
        <Icon name="map" size={18} />
        <h1>{place}</h1>
        <span class="muted num">{plural(list.total, 'item', 'itens')}</span>
        <button class="btn small" onclick={() => go('acervo')}>Ver tudo</button>
      </div>
    {/if}
    {#if !filtering}
      <Memories />
    {/if}
    {#if app.q && !list.loading}
      <p class="result-count muted">{plural(list.total, 'resultado', 'resultados')} para “{app.q}”</p>
    {/if}
    {#if list.start}
      <div class="jumped">
        <span class="muted">Mostrando a partir de {monthLabel(list.start)}</span>
        <button class="btn small" onclick={() => list.reset(query)}>Voltar ao mais recente</button>
      </div>
    {/if}
    <ItemBrowser
      {list}
      {layout}
      {selection}
      {selecting}
      onselectstart={() => (selecting = true)}
      onopen={(i) => openViewer(list, i, 'library')}
      empty={app.q ? 'Nada encontrado' : 'Nada aqui ainda'}
      emptyHint={app.q
        ? 'Tente outra palavra ou remova filtros.'
        : 'Envie arquivos e mantenha-os na Entrada para eles aparecerem aqui.'}
    />
  </div>

  {#if selecting}
    <SelectionBar count={selection.size} onclear={stopSelecting}>
      <button class="btn small" disabled={!selection.size} onclick={() => pickAlbum([...selection], stopSelecting)}>
        <Icon name="albumAdd" size={15} /><span class="hide-sm">Adicionar ao álbum</span>
      </button>
      <button class="btn small" disabled={!selection.size} onclick={() => batch('important')} aria-label="Marcar como importante"><Icon name="star" size={15} /></button>
      {#if !app.readonly}
        <button class="btn small danger" disabled={!selection.size} onclick={() => batch('discard')} aria-label="Mover para lixeira"><Icon name="trash" size={15} /></button>
      {/if}
    </SelectionBar>
  {/if}

  {#if !app.q && !place && layout === 'grid'}
    <Scrubber months={visibleMonths} current={currentMonth} onjump={jump} />
  {/if}
</div>

<style>
  .top {
    position: sticky;
    top: 0;
    z-index: 10;
    padding: calc(var(--sat) + 14px) 24px 0;
    background: color-mix(in srgb, var(--bg) 92%, transparent);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
  }
  .search-wrap {
    max-width: 720px;
    margin-bottom: 8px;
  }
  .content {
    padding: 8px 64px 40px 24px;
  }
  .tabs-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .tabs-row > :global(.tabs) {
    flex: 1;
    min-width: 0;
  }
  .places-link {
    display: none;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 10px;
    border-radius: 999px;
    color: var(--muted);
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
    flex: none;
  }
  .sel-btn {
    flex: none;
  }
  .place-head {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin: 10px 0 4px;
    color: var(--accent);
  }
  .place-head h1 {
    font-size: 20px;
    color: var(--text);
  }
  .result-count {
    margin: 4px 0 0;
    font-size: 13.5px;
  }
  .jumped {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
    margin: 8px 0 0;
    font-size: 13.5px;
  }
  @media (max-width: 899px) {
    .top {
      padding: calc(var(--sat) + 10px) 16px 0;
    }
    .content {
      padding: 6px 16px 24px;
    }
    .places-link {
      display: inline-flex;
      background: var(--raised);
    }
    .places-link span,
    .sel-lbl,
    .hide-sm {
      display: none;
    }
    .sel-btn {
      padding: 0 9px;
    }
  }
</style>
