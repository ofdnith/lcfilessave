<script lang="ts">
  // "Sugestões": groups proposed by the server. Never discards anything on its own;
  // the user picks items and decides.
  import { SvelteSet } from 'svelte/reactivity';
  import Icon from './Icon.svelte';
  import Thumb from './Thumb.svelte';
  import { api, ApiError } from '../lib/api';
  import { runAction } from '../lib/actions';
  import { bytes, num, plural, suggestionHint, suggestionLabel } from '../lib/format';
  import { ItemList } from '../lib/itemlist.svelte';
  import { app, invalidate, toast } from '../lib/state.svelte';
  import { refreshStats } from '../lib/stats.svelte';
  import { openViewer } from '../lib/viewer.svelte';
  import type { Action, Suggestion } from '../lib/types';

  let suggestions = $state<Suggestion[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let open = $state<number | null>(null);
  const picked = new SvelteSet<number>();

  async function load() {
    loading = true;
    error = null;
    try {
      suggestions = (await api.suggestions()).suggestions.filter((s) => s.items.length);
    } catch (e) {
      error = e instanceof ApiError ? e.message : 'Não foi possível carregar as sugestões.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void app.revision;
    void load();
  });

  function toggle(id: number) {
    picked.has(id) ? picked.delete(id) : picked.add(id);
  }

  async function apply(s: Suggestion, action: Action, ids: number[]) {
    const r = await runAction(ids, action, {
      undo: action === 'discard' ? () => void runAction(ids, 'restore', { reload: true }) : undefined,
    });
    if (!r) return;
    for (const id of r.ok) picked.delete(id);
    if (action === 'keep' || action === 'discard') {
      s.items = s.items.filter((i) => !r.ok.includes(i.id));
      if (s.items.length === 0) suggestions = suggestions.filter((x) => x.id !== s.id);
      invalidate();
    } else {
      for (const i of s.items) if (r.ok.includes(i.id)) i.important = action === 'important';
    }
  }

  async function dismiss(s: Suggestion) {
    try {
      await api.dismissSuggestion(s.id);
      suggestions = suggestions.filter((x) => x.id !== s.id);
      void refreshStats();
      toast('Sugestão ignorada', 'info', undefined, 2500);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível ignorar.', 'error');
    }
  }

  function view(s: Suggestion, index: number) {
    const l = new ItemList();
    l.items = s.items;
    l.total = s.items.length;
    l.done = true;
    openViewer(l, index, 'inbox');
  }

  const groupBytes = (s: Suggestion) => s.items.reduce((a, i) => a + i.size_bytes, 0);
</script>

{#if loading && !suggestions.length}
  <!-- quiet while loading; the section appears when there is something to show -->
{:else if error}
  <p class="error-text">{error} <button class="btn small" onclick={load}>Tentar de novo</button></p>
{:else if suggestions.length}
  <section class="sugg" aria-labelledby="sugg-title">
    <h2 id="sugg-title">Sugestões <span class="count num">{num(suggestions.length)}</span></h2>
    <p class="muted lead">Agrupamos o que talvez você queira revisar junto. Nada é descartado sem você escolher.</p>
    <div class="groups">
      {#each suggestions as s (s.id)}
        {@const sel = s.items.filter((i) => picked.has(i.id)).map((i) => i.id)}
        <article class="group" class:open={open === s.id}>
          <button class="group-head" onclick={() => (open = open === s.id ? null : s.id)} aria-expanded={open === s.id}>
            <div class="peek">
              {#each s.items.slice(0, 3) as it (it.id)}
                <span class="peek-i">{#if it.thumb_url}<img src={it.thumb_url} alt="" loading="lazy" />{/if}</span>
              {/each}
            </div>
            <div class="g-text">
              <span class="g-title">{suggestionLabel[s.kind]}</span>
              <span class="faint">{plural(s.items.length, 'item', 'itens')} · {bytes(groupBytes(s))}</span>
            </div>
            <span class="chev"><Icon name={open === s.id ? 'up' : 'right'} size={18} /></span>
          </button>

          {#if open === s.id}
            <div class="g-body">
              <p class="muted hint">{suggestionHint[s.kind]} Toque para ver; marque para agir em lote.</p>
              <div class="g-grid">
                {#each s.items as it, i (it.id)}
                  <div class="g-cell">
                    <button class="g-tile" onclick={() => view(s, i)} aria-label="Ver {it.original_name}">
                      <Thumb item={it} selecting selected={picked.has(it.id)} />
                    </button>
                    <button class="g-pick" class:on={picked.has(it.id)} onclick={() => toggle(it.id)} aria-pressed={picked.has(it.id)} aria-label="Selecionar {it.original_name}">
                      {#if picked.has(it.id)}<Icon name="check" size={14} />{/if}
                    </button>
                  </div>
                {/each}
              </div>
              <div class="g-actions">
                {#if sel.length}
                  <span class="muted num">{plural(sel.length, 'selecionado', 'selecionados')}</span>
                  <button class="btn small keep" onclick={() => apply(s, 'keep', sel)}><Icon name="check" size={15} /> Manter</button>
                  {#if !app.readonly}
                    <button class="btn small danger" onclick={() => apply(s, 'discard', sel)}><Icon name="trash" size={15} /> Descartar</button>
                  {/if}
                  <button class="btn small" onclick={() => apply(s, 'important', sel)}><Icon name="star" size={15} /> Importante</button>
                {:else}
                  <button class="btn small keep" onclick={() => apply(s, 'keep', s.items.map((i) => i.id))}>Manter todos</button>
                  <button class="btn small" onclick={() => s.items.forEach((i) => picked.add(i.id))}>Selecionar todos</button>
                {/if}
                <span class="spacer"></span>
                <button class="btn small ghost" onclick={() => dismiss(s)}>Ignorar sugestão</button>
              </div>
            </div>
          {/if}
        </article>
      {/each}
    </div>
  </section>
{/if}

<style>
  .sugg {
    margin: 8px 0 28px;
  }
  h2 {
    font-size: 18px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .count {
    font-size: 12px;
    padding: 1px 8px;
    border-radius: 999px;
    background: var(--raised);
    color: var(--muted);
  }
  .lead {
    margin: 4px 0 12px;
    font-size: 13.5px;
  }
  .groups {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .group {
    background: var(--surface);
    border: 1px solid var(--line-soft);
    border-radius: var(--r-md);
    overflow: hidden;
  }
  .group.open {
    border-color: var(--line);
  }
  .group-head {
    display: flex;
    align-items: center;
    gap: 14px;
    width: 100%;
    padding: 10px 14px 10px 10px;
    text-align: left;
  }
  .group-head:hover {
    background: var(--raised);
  }
  .peek {
    display: flex;
    flex: none;
  }
  .peek-i {
    width: 40px;
    height: 40px;
    border-radius: 6px;
    background: var(--raised-2);
    overflow: hidden;
    border: 2px solid var(--surface);
    margin-left: -14px;
  }
  .peek-i:first-child {
    margin-left: 0;
  }
  .peek-i img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    font-size: 13px;
  }
  .g-title {
    font-weight: 600;
    font-size: 15px;
  }
  .chev {
    color: var(--faint);
  }
  .g-body {
    padding: 0 14px 14px;
  }
  .hint {
    font-size: 13px;
    margin: 0 0 10px;
  }
  .g-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 4px;
  }
  .g-cell {
    position: relative;
    border-radius: 6px;
    overflow: hidden;
  }
  .g-tile {
    display: block;
    width: 100%;
  }
  .g-pick {
    position: absolute;
    top: 0;
    left: 0;
    width: 40px;
    height: 40px;
    display: grid;
    place-items: center;
    color: transparent;
  }
  .g-cell :global(.check) {
    pointer-events: none;
  }
  .g-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    font-size: 13px;
  }
  .spacer {
    flex: 1;
  }
</style>
