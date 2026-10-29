<script lang="ts">
  // "Neste dia": one card per past year with photos taken on today's date.
  import { api } from '../lib/api';
  import { ItemList } from '../lib/itemlist.svelte';
  import { app } from '../lib/state.svelte';
  import { openViewer } from '../lib/viewer.svelte';
  import type { MemoryYear } from '../lib/types';

  let years = $state<MemoryYear[]>([]);

  $effect(() => {
    void app.revision;
    api
      .memories()
      .then((r) => (years = r.years.filter((y) => y.items.length)))
      .catch(() => (years = []));
  });

  function open(y: MemoryYear) {
    const l = new ItemList();
    l.items = y.items;
    l.total = y.items.length;
    l.done = true;
    openViewer(l, 0, 'library');
  }

  const ago = (n: number) => (n === 1 ? 'Há 1 ano' : `Há ${n} anos`);
</script>

{#if years.length}
  <section class="mem" aria-labelledby="mem-title">
    <h2 id="mem-title">Neste dia</h2>
    <div class="strip">
      {#each years as y (y.year)}
        {@const cover = y.items[0]}
        <button class="card" onclick={() => open(y)} aria-label="{ago(y.years_ago)}, {y.year}: {y.count} itens">
          {#if cover.medium_url || cover.thumb_url}
            <img src={cover.medium_url ?? cover.thumb_url} alt="" loading="lazy" />
          {/if}
          <span class="shade"></span>
          <span class="txt">
            <strong>{ago(y.years_ago)}</strong>
            <span>{y.year}</span>
          </span>
        </button>
      {/each}
    </div>
  </section>
{/if}

<style>
  .mem {
    margin: 6px 0 14px;
  }
  h2 {
    font-size: 15px;
    font-weight: 620;
    margin-bottom: 8px;
  }
  .strip {
    display: flex;
    gap: 10px;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    scrollbar-width: none;
    padding-bottom: 2px;
  }
  .strip::-webkit-scrollbar {
    display: none;
  }
  .card {
    position: relative;
    flex: none;
    width: 168px;
    aspect-ratio: 3 / 4;
    border-radius: var(--r-lg);
    overflow: hidden;
    background: var(--raised);
    scroll-snap-align: start;
    text-align: left;
  }
  .card img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.3s var(--ease);
  }
  .card:hover img {
    transform: scale(1.03);
  }
  .shade {
    position: absolute;
    inset: 0;
    background: linear-gradient(to top, rgba(5, 7, 10, 0.8), transparent 55%);
  }
  .txt {
    position: absolute;
    left: 12px;
    right: 12px;
    bottom: 10px;
    display: flex;
    flex-direction: column;
    color: #fff;
    line-height: 1.2;
  }
  .txt strong {
    font-size: 16px;
  }
  .txt span {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.75);
  }
  @media (max-width: 899px) {
    .card {
      width: 132px;
    }
    .strip {
      margin: 0 -16px;
      padding: 0 16px 2px;
      scroll-padding: 0 16px;
    }
  }
</style>
