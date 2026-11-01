<script lang="ts">
  // Banners for what the owner should act on (GET /api/stats → alerts). The
  // server writes the texts; the same ones go out as iPhone notifications.
  import Icon from './Icon.svelte';
  import { isNative } from '../lib/native';
  import { router } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';
  import type { Alert } from '../lib/types';

  const HIDE_MS = 24 * 3600 * 1000;
  const KEY = 'acervo.alerts.hidden';

  function load(): Record<string, number> {
    try {
      return JSON.parse(localStorage.getItem(KEY) || '{}');
    } catch {
      return {};
    }
  }
  let hidden = $state<Record<string, number>>(load());

  function hide(a: Alert) {
    hidden = { ...hidden, [a.id]: Date.now() };
    try {
      localStorage.setItem(KEY, JSON.stringify(hidden));
    } catch {
      /* private mode: hidden for this visit only */
    }
  }

  /** Dispositivos only exists in the computer app: elsewhere, explain how to do it. */
  function target(a: Alert): string {
    const h = a.href.replace(/^\//, '');
    if (h.startsWith('#/dispositivos') && !isNative()) return '#/ajuda/transferir-lote';
    return h;
  }

  // Not on the screen the alert points to (you are already there).
  const here: Partial<Record<Alert['id'], string[]>> = { entrada: ['entrada'], lote: ['dispositivos'] };

  const list = $derived(
    (app.stats?.alerts ?? []).filter(
      (a) =>
        !here[a.id]?.includes(router.route) &&
        // Urgent ones cannot be snoozed.
        (a.level === 'danger' || !hidden[a.id] || Date.now() - hidden[a.id] > HIDE_MS),
    ),
  );
  let expanded = $state(false);
  const shown = $derived(expanded ? list : list.slice(0, 2));
</script>

{#if list.length}
  <div class="alerts" role="status">
    {#each shown as a (a.id)}
      <div class="alert {a.level}">
        <a class="body" href={target(a)}>
          <Icon name={a.level === 'info' ? 'info' : a.id === 'lote' || a.id === 'espaco' ? 'drive' : 'alert'} size={18} />
          <span class="txt">
            <strong>{a.title}</strong>
            <span class="desc">{a.text}</span>
          </span>
          <Icon name="right" size={16} />
        </a>
        {#if a.level !== 'danger'}
          <button class="x" onclick={() => hide(a)} aria-label="Esconder este aviso por um dia" title="Esconder por um dia">
            <Icon name="close" size={14} />
          </button>
        {/if}
      </div>
    {/each}
    {#if list.length > 2}
      <button class="more" onclick={() => (expanded = !expanded)}>
        {expanded ? 'Mostrar menos' : `Mais ${list.length - 2} ${list.length - 2 === 1 ? 'aviso' : 'avisos'}`}
      </button>
    {/if}
  </div>
{/if}

<style>
  .alerts {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .alert {
    position: relative;
    display: flex;
    border-radius: var(--r-md);
    background: var(--accent-soft);
    color: var(--warn);
  }
  .alert.danger {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .alert.info {
    background: rgba(143, 185, 255, 0.1);
    color: var(--info);
  }
  .body {
    flex: 1;
    min-width: 0;
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 10px 12px;
    color: inherit;
    text-decoration: none;
  }
  .alert:has(.x) .body {
    padding-right: 4px;
  }
  .txt {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
    font-size: 13.5px;
  }
  strong {
    font-weight: 650;
  }
  .desc {
    color: var(--muted);
    font-size: 13px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .x {
    flex: none;
    display: grid;
    place-items: center;
    width: 38px;
    color: var(--faint);
  }
  .x:hover {
    color: var(--text);
  }
  .more {
    align-self: flex-start;
    font-size: 13px;
    color: var(--muted);
    padding: 2px 4px;
  }
</style>
