<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import MapView from '../components/MapView.svelte';
  import { api, ApiError } from '../lib/api';
  import { num, plural } from '../lib/format';
  import { ItemList } from '../lib/itemlist.svelte';
  import { href } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';
  import { openViewer } from '../lib/viewer.svelte';
  import type { Item, Place } from '../lib/types';

  const PICK_LIMIT = 60;

  let places = $state<Place[]>([]);
  let points = $state<[number, number, number][]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let filter = $state('');

  let picked = $state<Item[]>([]);
  let pickedTotal = $state(0);
  let picking = $state(false);

  $effect(() => {
    void app.revision;
    loading = true;
    Promise.all([api.places(), api.mapPoints()])
      .then(([p, m]) => {
        places = p.places;
        points = m.points;
        error = null;
      })
      .catch((e) => (error = e instanceof ApiError ? e.message : 'Não foi possível carregar os lugares.'))
      .finally(() => (loading = false));
  });

  async function pick(ids: number[]) {
    picking = true;
    pickedTotal = ids.length;
    picked = [];
    const want = ids.slice(0, PICK_LIMIT);
    const got = await Promise.allSettled(want.map((id) => api.item(id)));
    picked = got.flatMap((r) => (r.status === 'fulfilled' ? [r.value as Item] : []));
    picking = false;
    requestAnimationFrame(() => document.getElementById('picked')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }

  function openPicked(i: number) {
    const l = new ItemList();
    l.items = picked;
    l.total = picked.length;
    l.done = true;
    openViewer(l, i, 'library');
  }

  const fold = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const shown = $derived(filter.trim() ? places.filter((p) => fold(p.place).includes(fold(filter.trim()))) : places);
</script>

<div class="page places">
  <a class="back" href={href('acervo')}><Icon name="left" size={16} /> Acervo</a>
  <h1 class="page-title">Lugares</h1>
  <p class="page-sub">Fotos com localização, no mapa e por cidade.</p>

  {#if error}
    <p class="error-text">{error}</p>
  {:else if !loading && !points.length && !places.length}
    <div class="empty panel">
      <Icon name="map" size={28} />
      <p>Nenhuma foto com localização ainda. Fotos do iPhone costumam trazer o lugar; ele aparece aqui depois do envio.</p>
    </div>
  {:else}
    {#if points.length}
      <MapView {points} onpick={pick} />
      <p class="faint small num">{plural(points.length, 'foto no mapa', 'fotos no mapa')} · toque num grupo para aproximar</p>
    {/if}

    {#if picking || picked.length}
      <section id="picked" class="picked">
        <header>
          <h2>Neste ponto</h2>
          <span class="muted num">{pickedTotal > PICK_LIMIT ? `${num(PICK_LIMIT)} de ${num(pickedTotal)}` : plural(pickedTotal, 'item', 'itens')}</span>
          <button class="icon-btn" aria-label="Fechar" onclick={() => ((picked = []), (picking = false))}><Icon name="close" size={18} /></button>
        </header>
        {#if picking}
          <p class="muted">Carregando…</p>
        {:else}
          <div class="pgrid">
            {#each picked as it, i (it.id)}
              <button class="pcell" onclick={() => openPicked(i)} aria-label={it.original_name}>
                {#if it.thumb_url}<img src={it.thumb_url} alt="" loading="lazy" />{/if}
              </button>
            {/each}
          </div>
        {/if}
      </section>
    {/if}

    {#if places.length}
      <section class="list">
        <header class="list-head">
          <h2>Por lugar</h2>
          {#if places.length > 8}
            <input type="search" bind:value={filter} placeholder="Filtrar cidades" aria-label="Filtrar cidades" />
          {/if}
        </header>
        <ul>
          {#each shown as p (p.place)}
            <li>
              <a class="row" href={href('acervo', null, { place: p.place })}>
                <span class="cover">
                  {#if p.cover?.thumb_url}<img src={p.cover.thumb_url} alt="" loading="lazy" />{:else}<Icon name="map" size={18} />{/if}
                </span>
                <span class="txt">
                  <span class="name">{p.place}</span>
                  <span class="faint num">{plural(p.count, 'foto', 'fotos')}</span>
                </span>
                <Icon name="right" size={18} />
              </a>
            </li>
          {/each}
        </ul>
        {#if filter && !shown.length}<p class="muted">Nenhum lugar com “{filter}”.</p>{/if}
      </section>
    {/if}
  {/if}
</div>

<style>
  .places {
    max-width: 980px;
  }
  .back {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--muted);
    text-decoration: none;
    font-size: 14px;
    margin: var(--sat) 0 6px;
  }
  .small {
    font-size: 12.5px;
    margin: 6px 2px 0;
  }
  .empty {
    display: flex;
    align-items: center;
    gap: 14px;
    color: var(--muted);
  }
  .empty p {
    margin: 0;
  }
  .picked {
    margin-top: 18px;
    scroll-margin-top: 16px;
  }
  .picked header,
  .list-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }
  .picked h2,
  .list h2 {
    font-size: 16px;
  }
  .picked header .icon-btn {
    margin-left: auto;
  }
  .pgrid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 3px;
  }
  .pcell {
    aspect-ratio: 1;
    background: var(--raised);
    overflow: hidden;
  }
  .pcell img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .list {
    margin-top: 26px;
  }
  .list-head input {
    margin-left: auto;
    height: 34px;
    padding: 0 12px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 16px;
    outline: 0;
    width: min(220px, 50%);
  }
  .list-head input:focus {
    border-color: var(--accent);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--line-soft);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 4px;
    border-bottom: 1px solid var(--line-soft);
    color: var(--muted);
    text-decoration: none;
  }
  .row:hover {
    background: var(--surface);
  }
  .cover {
    width: 52px;
    height: 52px;
    border-radius: 8px;
    background: var(--raised);
    overflow: hidden;
    display: grid;
    place-items: center;
    flex: none;
    color: var(--faint);
  }
  .cover img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .txt {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    font-size: 13px;
  }
  .name {
    color: var(--text);
    font-weight: 560;
    font-size: 14.5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
