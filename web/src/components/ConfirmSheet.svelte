<script lang="ts">
  import Sheet from './Sheet.svelte';
  import { sheets } from '../lib/sheets.svelte';

  function close(ok: boolean) {
    const c = sheets.confirm;
    sheets.confirm = null;
    c?.resolve(ok);
  }
</script>

{#if sheets.confirm}
  {@const c = sheets.confirm}
  <Sheet label={c.title} onclose={() => close(false)}>
    <h2>{c.title}</h2>
    {#if c.body}<p class="muted">{c.body}</p>{/if}
    <div class="acts">
      <button class="btn ghost" onclick={() => close(false)}>Cancelar</button>
      <button class="btn {c.tone === 'danger' ? 'danger' : 'primary'}" onclick={() => close(true)}>{c.confirm}</button>
    </div>
  </Sheet>
{/if}

<style>
  h2 {
    font-size: 18px;
    margin-bottom: 6px;
  }
  p {
    margin: 0 0 18px;
    font-size: 14.5px;
  }
  .acts {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }
  @media (max-width: 899px) {
    .acts {
      flex-direction: column-reverse;
    }
    .acts .btn {
      min-height: 46px;
    }
  }
</style>
