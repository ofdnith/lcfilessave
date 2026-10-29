<script lang="ts">
  import { untrack } from 'svelte';
  import ItemBrowser from '../components/ItemBrowser.svelte';
  import KindTabs from '../components/KindTabs.svelte';
  import Scrubber from '../components/Scrubber.svelte';
  import SearchBar from '../components/SearchBar.svelte';
  import { api } from '../lib/api';
  import { monthLabel, plural } from '../lib/format';
  import { ItemList } from '../lib/itemlist.svelte';
  import { trackMonth } from '../lib/scrollmonth';
  import { app } from '../lib/state.svelte';
  import { openViewer } from '../lib/viewer.svelte';
  import type { ItemQuery } from '../lib/api';
  import type { TimelineMonth } from '../lib/types';

  const list = new ItemList(200);
  let months = $state<TimelineMonth[]>([]);
  let currentMonth = $state<string | null>(null);

  const query = $derived<ItemQuery>({
    view: 'library',
    kind: app.kind,
    q: app.q || undefined,
    year: app.filters.year,
    important: app.filters.important,
    archived: app.filters.archived,
  });

  const layout = $derived(app.kind === 'document' || app.kind === 'audio' || app.kind === 'other' ? 'list' : 'grid');
  const years = $derived([...new Set(months.map((m) => m.year))]);
  // Timeline ignores year so the year chip can list every year.
  const visibleMonths = $derived(app.filters.year ? months.filter((m) => m.year === app.filters.year) : months);

  $effect(() => {
    void app.revision;
    const q = query;
    untrack(() => {
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
    <KindTabs value={app.kind} tabs={app.stats?.tabs ?? null} onchange={(k) => (app.kind = k)} />
  </div>

  <div class="content">
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
      onopen={(i) => openViewer(list, i, 'library')}
      empty={app.q ? 'Nada encontrado' : 'Nada aqui ainda'}
      emptyHint={app.q
        ? 'Tente outra palavra ou remova filtros.'
        : 'Envie arquivos e mantenha-os na Entrada para eles aparecerem aqui.'}
    />
  </div>

  {#if !app.q && layout === 'grid'}
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
  }
</style>
