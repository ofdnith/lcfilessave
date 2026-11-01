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
    {#if s.inbox_max_bytes}
      <p class="extra" class:warn={s.inbox_alert}>
        Entrada: {gb(s.inbox_bytes)} de {gb(s.inbox_max_bytes)} GB
      </p>
    {/if}
    {#if s.sd}
      {#if !s.sd.present}
        <p class="extra danger">Cartão microSD não encontrado</p>
      {:else}
        <p class="extra" class:warn={s.sd.alert}>
          Cartão: {gb(s.sd.free_bytes ?? 0)} GB livres{#if s.sd.alert} · hora de passar um lote para o HD{/if}
        </p>
        {#if s.sd.pending_bytes > 0}
          <p class="extra faint">Copiando {gb(s.sd.pending_bytes)} GB para o cartão…</p>
        {/if}
      {/if}
    {/if}
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
  .extra {
    margin: 0;
  }
  .extra.warn {
    color: var(--warn);
  }
  .extra.danger {
    color: var(--danger);
  }
  .extra.faint {
    color: var(--faint);
  }
  .daily {
    margin: 2px 0 0;
    color: var(--faint);
  }
  .daily.late {
    color: var(--warn);
  }
</style>
