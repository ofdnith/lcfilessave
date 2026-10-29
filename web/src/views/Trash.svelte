<script lang="ts">
  import { untrack } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import { runAction } from '../lib/actions';
  import { bytes, daysUntil, num, plural } from '../lib/format';
  import { ItemList } from '../lib/itemlist.svelte';
  import { app } from '../lib/state.svelte';
  import { openViewer } from '../lib/viewer.svelte';

  const list = new ItemList(200);

  $effect(() => {
    void app.revision;
    untrack(() => void list.reset({ view: 'trash', kind: 'all' }));
  });

  let sentinel = $state<HTMLElement | null>(null);
  $effect(() => {
    if (!sentinel) return;
    const io = new IntersectionObserver((e) => e.some((x) => x.isIntersecting) && void list.more(), { rootMargin: '800px 0px' });
    io.observe(sentinel);
    return () => io.disconnect();
  });

  async function restore(ids: number[]) {
    const r = await runAction(ids, 'restore');
    if (r) list.remove(r.ok);
  }

  function expiry(s: string | null): string {
    const d = daysUntil(s);
    if (d === null) return '';
    if (d === 0) return 'apaga hoje';
    return `apaga em ${plural(d, 'dia', 'dias')}`;
  }
  const totalBytes = $derived(list.items.reduce((a, i) => a + i.size_bytes, 0));
</script>

<div class="page">
  <h1 class="page-title">Lixeira</h1>
  <p class="page-sub">
    Itens descartados ficam aqui por 30 dias e depois são apagados de vez, automaticamente.
    {#if list.total}<span class="num">{plural(list.total, 'item', 'itens')} · {bytes(totalBytes)}{list.done ? '' : '+'}</span>{/if}
  </p>

  {#if list.items.length > 1}
    <div class="top-actions">
      <button class="btn small" onclick={() => restore(list.items.map((i) => i.id))}>
        <Icon name="restore" size={15} /> Restaurar {list.done ? 'todos' : `os ${num(list.items.length)} carregados`}
      </button>
    </div>
  {/if}

  {#if list.error}
    <p class="error-text">{list.error} <button class="btn small" onclick={() => list.reload()}>Tentar de novo</button></p>
  {:else if !list.items.length && list.done}
    <div class="empty">
      <div class="mark"><Icon name="trash" size={30} /></div>
      <p class="title">Lixeira vazia</p>
      <p class="muted">O que você descartar aparece aqui por 30 dias, caso mude de ideia.</p>
    </div>
  {/if}

  <ul class="rows">
    {#each list.items as item, i (item.id)}
      {@const d = daysUntil(item.trash_expires_at)}
      <li class="row">
        <button class="open" onclick={() => openViewer(list, i, 'trash')} aria-label="Ver {item.original_name}">
          <span class="th">
            {#if item.thumb_url}<img src={item.thumb_url} alt="" loading="lazy" />{:else}<Icon name="file" size={20} />{/if}
          </span>
          <span class="txt">
            <span class="name">{item.original_name}</span>
            <span class="meta num"><span class:soon={d !== null && d <= 3}>{expiry(item.trash_expires_at)}</span> · {bytes(item.size_bytes)}</span>
          </span>
        </button>
        <button class="btn small keep" onclick={() => restore([item.id])}><Icon name="restore" size={15} /> Restaurar</button>
      </li>
    {/each}
  </ul>
  <div bind:this={sentinel} class="sentinel">{#if list.loading}<span class="muted">Carregando…</span>{/if}</div>
</div>

<style>
  .top-actions {
    margin-bottom: 12px;
  }
  .rows {
    list-style: none;
    padding: 0;
    margin: 0;
    border-top: 1px solid var(--line-soft);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid var(--line-soft);
    padding-right: 4px;
  }
  .open {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 4px;
    text-align: left;
  }
  .th {
    width: 48px;
    height: 48px;
    border-radius: 6px;
    background: var(--raised);
    overflow: hidden;
    display: grid;
    place-items: center;
    color: var(--faint);
    flex: none;
  }
  .th img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    filter: saturate(0.6);
  }
  .txt {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .name {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 520;
  }
  .meta {
    font-size: 12.5px;
    color: var(--muted);
  }
  .soon {
    color: var(--danger);
  }
  .sentinel {
    min-height: 40px;
    padding: 10px;
    text-align: center;
  }
  .empty {
    text-align: center;
    padding: 56px 16px;
  }
  .mark {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: var(--surface);
    color: var(--faint);
    display: grid;
    place-items: center;
    margin: 0 auto 12px;
  }
  .title {
    font-weight: 600;
    font-size: 17px;
    margin: 0 0 4px;
  }
</style>
