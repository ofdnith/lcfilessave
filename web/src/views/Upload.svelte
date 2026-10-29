<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import { bytes, eta, num, plural } from '../lib/format';
  import { href } from '../lib/router.svelte';
  import { uploader, type Batch, type Job } from '../lib/uploader.svelte';

  let picker = $state<HTMLInputElement | null>(null);
  let over = $state(false);

  function pick(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    if (input.files?.length) uploader.add(input.files);
    input.value = '';
  }

  function drop(e: DragEvent) {
    e.preventDefault();
    over = false;
    if (e.dataTransfer?.files.length) uploader.add(e.dataTransfer.files);
  }

  const phaseText: Record<Batch['phase'], string> = {
    preparing: 'Preparando',
    hashing: 'Calculando assinaturas',
    checking: 'Conferindo o que já existe',
    uploading: 'Enviando',
    finishing: 'Finalizando',
    done: 'Concluído',
    failed: 'Parou',
  };

  function jobLine(j: Job): string {
    switch (j.status) {
      case 'queued':
        return 'Na fila';
      case 'hashing':
        return `Lendo ${Math.round((j.progress / Math.max(1, j.size)) * 100)}%`;
      case 'checking':
        return 'Conferindo';
      case 'waiting':
        return 'Aguardando envio';
      case 'uploading':
        return `${Math.round((j.progress / Math.max(1, j.size)) * 100)}%`;
      case 'processing':
        return 'Processando no servidor';
      default:
        return j.message;
    }
  }

  function tone(j: Job): string {
    if (j.status === 'failed') return 'bad';
    if (j.result === 'new' || j.result === 'attached') return 'good';
    if (j.result === 'in_trash' || j.result === 'purged' || j.result === 'discarded') return 'warn';
    if (j.status === 'skipped' || j.result === 'duplicate') return 'dim';
    return '';
  }

  const batches = $derived([...uploader.batches].reverse());
</script>

<div
  class="page"
  role="region"
  aria-label="Enviar"
  ondragover={(e) => {
    e.preventDefault();
    over = true;
  }}
  ondragleave={(e) => {
    if (e.currentTarget === e.target) over = false;
  }}
  ondrop={drop}
>
  <h1 class="page-title">Enviar</h1>
  <p class="page-sub">Os arquivos vão para a Entrada. O que já existe no acervo é pulado sem gastar internet.</p>

  <button class="drop" class:over onclick={() => picker?.click()}>
    <span class="drop-icon"><Icon name="upload" size={30} /></span>
    <span class="drop-title">Escolher fotos, vídeos e arquivos</span>
    <span class="drop-hint muted">ou arraste para qualquer lugar da janela</span>
  </button>
  <input bind:this={picker} type="file" multiple hidden onchange={pick} />

  {#each batches as b (b.id)}
    {@const t = uploader.totals(b)}
    {@const pct = t.total ? (t.sent / t.total) * 100 : b.phase === 'done' ? 100 : 0}
    {@const hashPct = (b.jobs.filter((j) => j.sha256 || j.status === 'failed').length / b.jobs.length) * 100}
    <section class="batch panel">
      <header class="b-head">
        <div>
          <h2>{plural(b.jobs.length, 'arquivo', 'arquivos')} · {bytes(b.jobs.reduce((a, j) => a + j.size, 0))}</h2>
          <p class="muted b-phase" class:bad={b.phase === 'failed'}>
            {phaseText[b.phase]}
            {#if b.phase === 'uploading'}
              · <span class="num">{bytes(t.sent)} de {bytes(t.total)}</span>
              {#if uploader.speed > 0}· <span class="num">{bytes(uploader.speed)}/s · {eta((t.total - t.sent) / uploader.speed)}</span>{/if}
            {:else if b.phase === 'hashing'}
              · <span class="num">{Math.round(hashPct)}%</span>
            {/if}
          </p>
        </div>
        {#if b.phase !== 'done' && b.phase !== 'failed'}
          <button class="btn small ghost" onclick={() => uploader.cancelAll()}>Cancelar</button>
        {/if}
      </header>

      {#if b.phase !== 'done' && b.phase !== 'failed'}
        <div class="bar"><span style:width="{b.phase === 'hashing' || b.phase === 'checking' ? hashPct : pct}%"></span></div>
      {/if}

      {#if b.phase === 'done' && b.session}
        <div class="summary">
          <Icon name="check" size={20} />
          <div>
            <p class="sum-text">{b.session.summary_text}</p>
            {#if b.session.failed_count}<p class="error-text">{plural(b.session.failed_count, 'arquivo falhou', 'arquivos falharam')}. Envie de novo para tentar.</p>{/if}
          </div>
          {#if b.session.new_count}<a class="btn small primary" href={href('entrada')}>Ver na Entrada</a>{/if}
        </div>
      {/if}
      {#if b.error}<p class="error-text">{b.error}</p>{/if}

      <ul class="jobs">
        {#each b.jobs as j (j.key)}
          <li class="job {tone(j)}">
            <span class="j-name">{j.name}</span>
            <span class="j-size num faint">{bytes(j.size)}</span>
            <span class="j-status num">
              {#if j.result === 'in_trash' && j.itemId && !j.restored}
                Está na lixeira <button class="btn small keep" onclick={() => uploader.restore(j)}>Restaurar</button>
              {:else if j.result === 'purged' || j.result === 'discarded'}
                descartado antes
              {:else}
                {jobLine(j)}
              {/if}
            </span>
            {#if j.status === 'uploading' || j.status === 'hashing'}
              <span class="j-bar" style:width="{(j.progress / Math.max(1, j.size)) * 100}%"></span>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/each}

  {#if uploader.batches.some((b) => b.phase === 'done' || b.phase === 'failed')}
    <button class="btn small ghost" onclick={() => uploader.clearFinished()}>Limpar concluídos</button>
  {/if}

  {#if !uploader.batches.length}
    <div class="tips">
      <p><strong>Pode fechar sem medo.</strong> Se a página recarregar ou a conexão cair, adicione os mesmos arquivos de novo: o envio continua de onde parou e o que já chegou é pulado.</p>
      <p class="muted">No iPhone, o seletor abre a Fototeca. Para mandar a Fototeca inteira, use o “Esvaziar iPhone” no app do Mac.</p>
    </div>
  {/if}
</div>

<style>
  .drop {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 40px 16px;
    border: 2px dashed var(--line);
    border-radius: var(--r-lg);
    background: var(--surface);
    transition: border-color 0.15s, background 0.15s;
    margin-bottom: 20px;
  }
  .drop:hover,
  .drop.over {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .drop-icon {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: var(--accent);
    color: var(--accent-ink);
    display: grid;
    place-items: center;
    margin-bottom: 6px;
  }
  .drop-title {
    font-size: 17px;
    font-weight: 600;
  }
  .drop-hint {
    font-size: 13.5px;
  }
  @media (hover: none) {
    .drop-hint {
      display: none;
    }
  }
  .batch {
    margin-bottom: 14px;
  }
  .b-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 10px;
  }
  .b-head h2 {
    font-size: 16px;
  }
  .b-phase {
    margin: 2px 0 0;
    font-size: 13.5px;
  }
  .b-phase.bad {
    color: var(--danger);
  }
  .summary {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    border-radius: var(--r-md);
    background: var(--keep-soft);
    color: var(--keep);
    margin-bottom: 8px;
  }
  .summary > div {
    flex: 1;
  }
  .sum-text {
    margin: 0;
    color: var(--text);
    font-weight: 600;
  }
  .jobs {
    list-style: none;
    margin: 10px 0 0;
    padding: 0;
    max-height: 360px;
    overflow-y: auto;
  }
  .job {
    position: relative;
    display: grid;
    grid-template-columns: 1fr auto auto;
    align-items: center;
    gap: 12px;
    padding: 7px 2px;
    border-bottom: 1px solid var(--line-soft);
    font-size: 13.5px;
  }
  .j-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .j-status {
    color: var(--muted);
    text-align: right;
    min-width: 90px;
    display: flex;
    align-items: center;
    gap: 8px;
    justify-content: flex-end;
  }
  .job.good .j-status {
    color: var(--keep);
  }
  .job.bad .j-status {
    color: var(--danger);
  }
  .job.warn .j-status {
    color: var(--warn);
  }
  .job.dim {
    opacity: 0.7;
  }
  .j-bar {
    position: absolute;
    left: 0;
    bottom: -1px;
    height: 2px;
    background: var(--accent);
    transition: width 0.3s;
  }
  .tips {
    max-width: 640px;
    font-size: 14px;
  }
  @media (max-width: 899px) {
    .job {
      grid-template-columns: 1fr auto;
    }
    .j-size {
      display: none;
    }
  }
</style>
