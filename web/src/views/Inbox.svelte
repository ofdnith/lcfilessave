<script lang="ts">
  import { untrack } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import Icon from '../components/Icon.svelte';
  import ItemBrowser from '../components/ItemBrowser.svelte';
  import KindTabs from '../components/KindTabs.svelte';
  import QuickTriage from '../components/QuickTriage.svelte';
  import SearchBar from '../components/SearchBar.svelte';
  import SelectionBar from '../components/SelectionBar.svelte';
  import Suggestions from '../components/Suggestions.svelte';
  import { runAction } from '../lib/actions';
  import { api, ApiError } from '../lib/api';
  import { refreshStats } from '../lib/stats.svelte';
  import { confirmSheet, pickAlbum } from '../lib/sheets.svelte';
  import { invalidate, toast } from '../lib/state.svelte';
  import { plural } from '../lib/format';
  import type { InboxSummary } from '../lib/types';
  import { href } from '../lib/router.svelte';
  import { num } from '../lib/format';
  import { ItemList } from '../lib/itemlist.svelte';
  import { app } from '../lib/state.svelte';
  import { openViewer } from '../lib/viewer.svelte';
  import type { ItemQuery } from '../lib/api';
  import type { Action } from '../lib/types';

  const list = new ItemList(200);
  const quickList = new ItemList(60);
  const selection = new SvelteSet<number>();
  let selecting = $state(false);
  let quick = $state(false);

  const query = $derived<ItemQuery>({
    view: 'inbox',
    kind: app.kind,
    q: app.q || undefined,
    year: app.filters.year,
    important: app.filters.important,
  });
  const layout = $derived(app.kind === 'document' || app.kind === 'audio' || app.kind === 'other' ? 'list' : 'grid');
  const count = $derived(app.stats?.inbox_count ?? list.total);
  let summary = $state<InboxSummary | null>(null);
  let keeping = $state(false);

  $effect(() => {
    void app.revision;
    void app.stats?.inbox_count;
    api
      .inboxSummary()
      .then((s) => (summary = s))
      .catch(() => (summary = null));
  });

  async function keepClean() {
    const s = summary;
    if (!s || !s.clean || keeping) return;
    const ok = await confirmSheet({
      title: `Manter ${plural(s.clean, 'item', 'itens')} no Acervo?`,
      body: s.flagged
        ? `${s.flagged === 1 ? 'O 1 sinalizado continua' : `Os ${num(s.flagged)} sinalizados continuam`} na Entrada para você decidir.`
        : 'Nenhum item está em sugestões; a Entrada fica vazia.',
      confirm: `Manter ${num(s.clean)}`,
    });
    if (!ok) return;
    keeping = true;
    try {
      const r = await api.keepClean();
      toast(
        `${plural(r.kept, 'item mantido', 'itens mantidos')}${r.flagged_left ? ` · ${plural(r.flagged_left, 'sinalizado continua', 'sinalizados continuam')} na Entrada` : ''}`,
        'ok',
      );
      await refreshStats();
      invalidate();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível manter.', 'error');
    } finally {
      keeping = false;
    }
  }

  $effect(() => {
    void app.revision;
    const q = query;
    untrack(() => {
      void list.reset(q);
      selection.clear();
    });
  });

  function startQuick() {
    void quickList.reset(query);
    quick = true;
  }

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
    if (action === 'keep' || action === 'discard') list.remove(r.ok);
    else for (const id of r.ok) list.patch(id, { important: action === 'important' });
    stopSelecting();
  }

  function onKey(e: KeyboardEvent) {
    if (quick || (e.target as HTMLElement).tagName === 'INPUT') return;
    if ((e.metaKey || e.ctrlKey) && e.key === 'a' && selecting) {
      list.items.forEach((i) => selection.add(i.id));
      e.preventDefault();
    } else if (e.key === 'Escape' && selecting) stopSelecting();
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="page inbox">
  <header class="hero">
    <div class="counter">
      <span class="big num">{num(count)}</span>
      <span class="label">{count === 1 ? 'item aguardando triagem' : 'itens aguardando triagem'}</span>
    </div>
    <div class="hero-actions">
      {#if summary && summary.clean > 0}
        <button class="btn keep-all" onclick={keepClean} disabled={keeping}>
          <Icon name="check" size={17} />
          {summary.flagged ? `Manter tudo, menos as sugestões (${num(summary.clean)})` : `Manter tudo (${num(summary.clean)})`}
        </button>
      {/if}
      <button class="btn primary" onclick={startQuick} disabled={!count}><Icon name="zap" size={17} /> Modo rápido</button>
      <button class="btn" onclick={() => (selecting ? stopSelecting() : (selecting = true))} aria-pressed={selecting} disabled={!list.items.length}>
        <Icon name="select" size={17} /> {selecting ? 'Cancelar seleção' : 'Selecionar'}
      </button>
    </div>
  </header>

  <Suggestions />

  <div class="filters">
    <SearchBar showArchived={false} placeholder="Buscar na Entrada" />
    <KindTabs value={app.kind} tabs={app.stats?.inbox_tabs ?? null} onchange={(k) => (app.kind = k)} />
  </div>

  <ItemBrowser
    {list}
    {layout}
    {selection}
    {selecting}
    onselectstart={() => (selecting = true)}
    onopen={(i) => openViewer(list, i, 'inbox')}
    empty={app.q ? 'Nada encontrado' : 'Entrada em dia'}
    emptyHint={app.q ? 'Tente outra palavra.' : 'Tudo que chegar pelo backup ou pelo envio aparece aqui para você decidir.'}
  />
  {#if !list.items.length && list.done && !app.q}
    <p class="center"><a class="btn" href={href('enviar')}><Icon name="upload" size={16} /> Enviar arquivos</a></p>
  {/if}
</div>

{#if selecting}
  <SelectionBar count={selection.size} onclear={stopSelecting}>
    <button class="btn small keep" disabled={!selection.size} onclick={() => batch('keep')}><Icon name="check" size={15} /> Manter</button>
    {#if !app.readonly}
      <button class="btn small danger" disabled={!selection.size} onclick={() => batch('discard')}><Icon name="trash" size={15} /> Descartar</button>
    {/if}
    <button class="btn small" disabled={!selection.size} onclick={() => pickAlbum([...selection], stopSelecting)} aria-label="Adicionar ao álbum"><Icon name="albumAdd" size={15} /></button>
    <button class="btn small" disabled={!selection.size} onclick={() => batch('important')} aria-label="Marcar como importante"><Icon name="star" size={15} /><span class="hide-sm">Importante</span></button>
  </SelectionBar>
{/if}

{#if quick}
  <QuickTriage list={quickList} onclose={() => (quick = false)} />
{/if}

<style>
  .hero {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 16px;
    padding: calc(var(--sat) + 12px) 0 20px;
  }
  .counter {
    display: flex;
    align-items: baseline;
    gap: 12px;
    flex-wrap: wrap;
  }
  .big {
    font-size: 56px;
    font-weight: 700;
    letter-spacing: -0.03em;
    line-height: 1;
    color: var(--accent);
  }
  .label {
    font-size: 19px;
    color: var(--text);
    font-weight: 500;
  }
  .keep-all {
    background: var(--keep-soft);
    color: var(--keep);
    border-color: rgba(107, 212, 155, 0.35);
  }
  .keep-all:hover {
    background: rgba(107, 212, 155, 0.22);
  }
  .hero-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .filters {
    position: sticky;
    top: 0;
    z-index: 10;
    padding: calc(var(--sat) + 8px) 0 0;
    margin: 0 -24px 6px;
    padding-left: 24px;
    padding-right: 24px;
    background: color-mix(in srgb, var(--bg) 92%, transparent);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .center {
    text-align: center;
  }
  @media (max-width: 899px) {
    .big {
      font-size: 44px;
    }
    .label {
      font-size: 16px;
    }
    .filters {
      margin: 0 -16px 6px;
      padding-left: 16px;
      padding-right: 16px;
    }
    .hide-sm {
      display: none;
    }
  }
</style>
