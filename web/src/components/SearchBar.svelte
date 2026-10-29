<script lang="ts">
  // Search input + filter chips. Writes into global app state; views react to it.
  import Icon from './Icon.svelte';
  import { app } from '../lib/state.svelte';

  let { years = [], showArchived = true, placeholder = 'Buscar' }: { years?: number[]; showArchived?: boolean; placeholder?: string } =
    $props();

  let input = $state<HTMLInputElement | null>(null);
  let text = $state(app.q);
  let timer: ReturnType<typeof setTimeout> | null = null;

  function onInput() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => (app.q = text.trim()), 200);
  }
  function clear() {
    text = '';
    app.q = '';
    input?.focus();
  }

  $effect(() => {
    if (app.searchFocus && input) {
      input.focus();
      input.select();
    }
  });
  // Keep the input in sync if something else resets the query.
  $effect(() => {
    if (app.q === '' && text.trim() !== '' && document.activeElement !== input) text = '';
  });

  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
  const anyFilter = $derived(app.filters.year !== null || app.filters.important || app.filters.archived !== null);

  function cycleArchived() {
    app.filters.archived = app.filters.archived === null ? '1' : app.filters.archived === '1' ? '0' : null;
  }
</script>

<div class="search">
  <label class="box">
    <Icon name="search" size={18} />
    <span class="sr-only">Buscar</span>
    <input
      bind:this={input}
      bind:value={text}
      oninput={onInput}
      onkeydown={(e) => e.key === 'Escape' && (text ? clear() : input?.blur())}
      type="search"
      enterkeyhint="search"
      autocomplete="off"
      autocorrect="off"
      spellcheck="false"
      {placeholder}
    />
    {#if text}
      <button class="clear" onclick={clear} aria-label="Limpar busca"><Icon name="close" size={16} /></button>
    {:else}
      <kbd class="hint">{isMac ? '⌘' : 'Ctrl'} K</kbd>
    {/if}
  </label>

  <div class="chips" role="group" aria-label="Filtros">
    <label class="chip" class:on={app.filters.year !== null}>
      <select
        aria-label="Ano"
        value={app.filters.year === null ? '' : String(app.filters.year)}
        onchange={(e) => {
          const v = (e.currentTarget as HTMLSelectElement).value;
          app.filters.year = v ? Number(v) : null;
        }}
      >
        <option value="">Qualquer ano</option>
        {#each years as y (y)}<option value={String(y)}>{y}</option>{/each}
      </select>
    </label>
    <button class="chip" class:on={app.filters.important} aria-pressed={app.filters.important} onclick={() => (app.filters.important = !app.filters.important)}>
      <Icon name="star" size={14} fill={app.filters.important} /> Importante
    </button>
    {#if showArchived}
      <button class="chip" class:on={app.filters.archived !== null} onclick={cycleArchived} title="Alterna entre: todos, só no HD, só no servidor">
        <Icon name={app.filters.archived === '0' ? 'server' : 'drive'} size={14} />
        {app.filters.archived === '1' ? 'Só no HD' : app.filters.archived === '0' ? 'Só no servidor' : 'HD ou servidor'}
      </button>
    {/if}
    {#if anyFilter}
      <button class="chip reset" onclick={() => (app.filters = { year: null, important: false, archived: null })}>Limpar filtros</button>
    {/if}
  </div>
</div>

<style>
  .search {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .box {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 44px;
    padding: 0 12px 0 14px;
    border-radius: 999px;
    background: var(--raised);
    color: var(--muted);
    border: 1px solid transparent;
    transition: border-color 0.15s, background 0.15s;
  }
  .box:focus-within {
    background: var(--surface);
    border-color: var(--accent);
  }
  input {
    flex: 1;
    min-width: 0;
    border: 0;
    outline: 0;
    background: transparent;
    font-size: 16px; /* ≥16px avoids iOS zoom on focus */
    color: var(--text);
  }
  input::placeholder {
    color: var(--faint);
  }
  input::-webkit-search-cancel-button {
    display: none;
  }
  .clear {
    color: var(--muted);
    display: grid;
    place-items: center;
    width: 28px;
    height: 28px;
    border-radius: 50%;
  }
  .clear:hover {
    background: var(--raised-2);
  }
  kbd {
    font: inherit;
    font-size: 11.5px;
    padding: 2px 7px;
    border-radius: 5px;
    border: 1px solid var(--line);
    color: var(--faint);
  }
  @media (hover: none) {
    kbd {
      display: none;
    }
  }
  .chips {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    scrollbar-width: none;
    padding-bottom: 2px;
  }
  .chips::-webkit-scrollbar {
    display: none;
  }
  .chip {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex: none;
    height: 32px;
    padding: 0 12px;
    border-radius: 8px;
    border: 1px solid var(--line);
    color: var(--muted);
    font-size: 13.5px;
    font-weight: 520;
    background: transparent;
  }
  .chip:hover {
    color: var(--text);
  }
  .chip.on {
    background: var(--accent-soft);
    border-color: rgba(240, 180, 76, 0.5);
    color: var(--accent);
  }
  .chip select {
    appearance: none;
    -webkit-appearance: none;
    border: 0;
    background: transparent;
    color: inherit;
    font-size: 13.5px;
    font-weight: 520;
    outline: 0;
    cursor: pointer;
    padding-right: 2px;
  }
  .chip select option {
    background: var(--surface);
    color: var(--text);
  }
  .chip.reset {
    border-style: dashed;
  }
</style>
