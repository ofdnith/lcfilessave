<script lang="ts">
  import { app } from '../lib/state.svelte';
  import { relativeDay, weeksText } from '../lib/format';

  let { compact = false }: { compact?: boolean } = $props();

  const s = $derived(app.stats?.storage);
  const daily = $derived(app.stats?.daily_backup);
  const pct = $derived(s && s.budget_bytes ? Math.min(100, (s.server_bytes / s.budget_bytes) * 100) : 0);

  function gb(n: number): string {
    return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: n >= 10e9 ? 0 : 1 }).format(n / 1e9);
  }
</script>

{#if s}
  <div class="status" class:compact class:alert={s.alert}>
    <div class="line">
      <span class="num"><strong>{gb(s.server_bytes)}</strong> de {gb(s.budget_bytes)} GB</span>
      {#if s.weeks_to_next_drive != null}<span class="eta">{weeksText(s.weeks_to_next_drive)}</span>{/if}
    </div>
    <div class="bar"><span style:width="{pct}%"></span></div>
    {#if daily}
      <p class="daily" class:late={daily.overdue}>
        Último backup diário: {daily.last_at ? relativeDay(daily.last_at) : 'nunca'}
      </p>
    {/if}
  </div>
{/if}

<style>
  .status {
    font-size: 12.5px;
    color: var(--muted);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .line {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .compact .line {
    flex-direction: column;
  }
  strong {
    color: var(--text);
    font-weight: 650;
  }
  .eta {
    color: var(--faint);
  }
  .alert .bar > span {
    background: var(--danger);
  }
  .alert strong,
  .alert .eta {
    color: var(--danger);
  }
  .daily {
    margin: 2px 0 0;
    color: var(--faint);
  }
  .daily.late {
    color: var(--warn);
  }
</style>
