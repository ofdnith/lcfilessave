<script lang="ts">
  import { bytes, kindTabs, num } from '../lib/format';
  import type { KindFilter, Tabs } from '../lib/types';

  let { value, tabs = null, onchange }: { value: KindFilter; tabs?: Tabs | null; onchange: (k: KindFilter) => void } = $props();

  function key(e: KeyboardEvent, i: number) {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    const next = kindTabs[(i + d + kindTabs.length) % kindTabs.length];
    onchange(next.key);
    (e.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLElement>('[role=tab]')[(i + d + kindTabs.length) % kindTabs.length]?.focus();
    e.preventDefault();
  }
</script>

<div class="tabs" role="tablist" aria-label="Tipo">
  {#each kindTabs as t, i (t.key)}
    {@const st = tabs?.[t.key]}
    <button
      role="tab"
      aria-selected={value === t.key}
      tabindex={value === t.key ? 0 : -1}
      class="tab"
      class:on={value === t.key}
      onclick={() => onchange(t.key)}
      onkeydown={(e) => key(e, i)}
    >
      <span class="label">{t.label}</span>
      {#if st}
        <span class="stat num">{`${num(st.count)} · ${bytes(st.bytes)}`}</span>
      {/if}
    </button>
  {/each}
</div>

<style>
  .tabs {
    display: flex;
    gap: 2px;
    overflow-x: auto;
    scrollbar-width: none;
    border-bottom: 1px solid var(--line-soft);
  }
  .tabs::-webkit-scrollbar {
    display: none;
  }
  .tab {
    flex: none;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    padding: 8px 14px 9px;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    color: var(--muted);
    border-radius: 8px 8px 0 0;
  }
  .tab:hover {
    color: var(--text);
    background: var(--surface);
  }
  .tab.on {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  .label {
    font-weight: 600;
    font-size: 14.5px;
  }
  .stat {
    font-size: 11.5px;
    color: var(--faint);
    white-space: nowrap;
  }
  .on .stat {
    color: var(--muted);
  }
  @media (max-width: 899px) {
    .tab {
      padding: 6px 11px 7px;
    }
    .label {
      font-size: 14px;
    }
  }
</style>
