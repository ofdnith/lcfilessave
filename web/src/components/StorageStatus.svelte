<script lang="ts">
  import { app } from '../lib/state.svelte';
  import { relativeDay, weeksText } from '../lib/format';

  // Since the microSD was retired (01/11/2026), the phone's own storage holds
  // the Entrada and the Acervo until a batch goes to an external storage.
  const s = $derived(app.stats?.storage);
  const daily = $derived(app.stats?.daily_backup);
  const batch = $derived(s?.batch.bytes ?? 0);
  const pct = $derived(s && s.budget_bytes ? Math.min(100, (batch / s.budget_bytes) * 100) : 0);
  const full = $derived(!!s && batch >= s.budget_bytes);
  const diskWarn = $derived(!!app.stats?.alerts.some((a) => a.id === 'espaco'));

  function gb(n: number): string {
    return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: n >= 10e9 ? 0 : 1 }).format(n / 1e9);
  }
</script>

{#if s}
  <div class="status" class:full>
    <div class="line">
      <span class="num"><strong>{gb(batch)}</strong> de {gb(s.budget_bytes)} GB no próximo lote</span>
      {#if full}
        <span class="eta">pronto para ir a um armazenamento</span>
      {:else if s.weeks_to_next_drive != null}
        <span class="eta">{weeksText(s.weeks_to_next_drive)}</span>
      {/if}
    </div>
    <div class="bar"><span style:width="{pct}%"></span></div>
    {#if s.inbox_bytes > 0}
      <p class="extra" class:warn={!!s.inbox_reminder}>
        Entrada: {gb(s.inbox_bytes)} GB esperando triagem{#if s.inbox_max_bytes} (limite {gb(s.inbox_max_bytes)} GB){/if}
      </p>
    {/if}
    <p class="extra num" class:warn={diskWarn}>
      Celular: {gb(s.disk_free_bytes)} GB livres de {gb(s.disk_total_bytes)} GB
    </p>
    {#if s.card && s.card.library_bytes > 0}
      <p class="extra" class:danger={!s.card.present}>
        {s.card.present
          ? `Cartão antigo: ${gb(s.card.library_bytes)} GB voltando para o celular`
          : `Cartão antigo fora do celular (${gb(s.card.library_bytes)} GB ainda nele)`}
      </p>
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
  strong {
    color: var(--text);
    font-weight: 650;
  }
  .eta {
    color: var(--faint);
  }
  .full .bar > span {
    background: var(--warn);
  }
  .full .eta {
    color: var(--warn);
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
  .daily {
    margin: 2px 0 0;
    color: var(--faint);
  }
  .daily.late {
    color: var(--warn);
  }
</style>
