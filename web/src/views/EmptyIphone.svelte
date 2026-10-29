<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import { num, plural } from '../lib/format';
  import { emptyIphone as e } from '../lib/empty-iphone.svelte';
  import { href } from '../lib/router.svelte';

  const c = $derived(e.counts);
  const s = $derived(e.session);
  const failed = $derived(e.files.filter((f) => f.status === 'failed'));
  const pct = $derived.by(() => {
    if (!c.total) return 0;
    if (e.phase === 'hashing') return (c.hashed / c.total) * 50;
    if (e.phase === 'uploading' || e.phase === 'checking') return 50 + ((c.known + c.uploaded + c.failed) / c.total) * 50;
    return e.phase === 'done' ? 100 : 0;
  });
  const phaseText: Record<string, string> = {
    scanning: 'Lendo a pasta…',
    hashing: 'Calculando a assinatura de cada arquivo…',
    checking: 'Conferindo o que o servidor já tem…',
    uploading: 'Enviando o que falta…',
    verifying: 'Confirmando com o servidor…',
  };
</script>

<div class="page empty-iphone">
  <a class="back" href={href('dispositivos')}><Icon name="left" size={16} /> Dispositivos</a>
  <h1 class="page-title">Esvaziar iPhone</h1>
  <p class="page-sub">Envia tudo do iPhone e confere, arquivo por arquivo, antes de você apagar qualquer coisa.</p>

  {#if e.phase === 'idle'}
    <ol class="steps panel">
      <li>Conecte o iPhone ao Mac pelo cabo e desbloqueie-o.</li>
      <li>Abra o <strong>Captura de Imagem</strong>, escolha o iPhone e importe tudo para uma pasta nova. <span class="muted">Não marque “Apagar após importar”.</span></li>
      <li>Escolha essa pasta aqui. O Acervo envia o que falta e confere cada arquivo pelo conteúdo.</li>
      <li>Só quando aparecer “seguro apagar do iPhone”, apague as fotos no próprio iPhone. Essa parte é sempre manual.</li>
    </ol>
    <button class="btn primary" onclick={() => e.choose()}><Icon name="folder" size={17} /> Escolher pasta importada</button>
  {:else}
    <section class="panel">
      <p class="folder faint">{e.folder}</p>
      {#if e.busy}
        <p><strong>{phaseText[e.phase]}</strong></p>
        <div class="bar"><span style:width="{pct}%"></span></div>
        <p class="muted num small">
          {num(c.total)} arquivos · {num(c.hashed)} lidos · {num(c.known)} já estavam no servidor · {num(c.uploaded)} enviados
          {#if c.failed} · <span class="error-text">{num(c.failed)} com erro</span>{/if}
        </p>
      {:else if e.phase === 'done' && s}
        {@const expected = s.expected_count ?? c.total}
        {#if s.safe_to_delete}
          <div class="safe">
            <Icon name="shield" size={28} />
            <div>
              <p class="big num">{num(s.received_verified_count)} de {num(expected)} recebidos e verificados</p>
              <p>Seguro apagar do iPhone. Apague pelo app Fotos do iPhone quando quiser; o Acervo nunca apaga nada do iPhone.</p>
            </div>
          </div>
        {:else}
          <div class="unsafe">
            <Icon name="alert" size={26} />
            <div>
              <p class="big num">{num(s.received_verified_count)} de {num(expected)} recebidos e verificados</p>
              <p>Ainda não apague do iPhone.
                {#if expected - s.received_verified_count > 0}Faltam {plural(expected - s.received_verified_count, 'arquivo', 'arquivos')}.{/if}
                {#if c.failed}{plural(c.failed, 'arquivo falhou', 'arquivos falharam')} aqui.{/if}
                Tente de novo: o que já chegou não é reenviado.
              </p>
            </div>
          </div>
        {/if}
        <p class="muted small">{s.summary_text}</p>
      {:else if e.phase === 'failed'}
        <p class="error-text">Parou: {e.error}</p>
        <p class="muted small">Nada foi apagado. Tente de novo; o que já chegou não é reenviado.</p>
      {/if}

      {#if failed.length}
        <details class="small">
          <summary class="error-text">{plural(failed.length, 'arquivo com erro', 'arquivos com erro')}</summary>
          <ul>{#each failed as f (f.path)}<li>{f.name}: {f.error}</li>{/each}</ul>
        </details>
      {/if}

      {#if !e.busy}
        <div class="acts">
          {#if e.phase !== 'done' || !s?.safe_to_delete}
            <button class="btn primary" onclick={() => e.run()}>Tentar de novo</button>
          {/if}
          {#if s?.new_count}<a class="btn" href={href('entrada')}>Ver na Entrada</a>{/if}
          <button class="btn ghost" onclick={() => e.reset()}>Escolher outra pasta</button>
        </div>
      {/if}
    </section>
  {/if}
</div>

<style>
  .empty-iphone {
    max-width: 720px;
  }
  .back {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--muted);
    text-decoration: none;
    font-size: 14px;
    margin: var(--sat) 0 8px;
  }
  .steps {
    margin: 0 0 18px;
    padding-left: 38px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    font-size: 14.5px;
  }
  .folder {
    font-family: ui-monospace, Menlo, monospace;
    font-size: 12.5px;
    margin: 0 0 12px;
    word-break: break-all;
  }
  .panel p {
    margin: 0 0 8px;
  }
  .small {
    font-size: 13px;
  }
  .safe,
  .unsafe {
    display: flex;
    gap: 14px;
    align-items: flex-start;
    padding: 16px;
    border-radius: var(--r-md);
    margin-bottom: 10px;
  }
  .safe {
    background: var(--keep-soft);
    color: var(--keep);
  }
  .unsafe {
    background: var(--accent-soft);
    color: var(--warn);
  }
  .safe p,
  .unsafe p {
    color: var(--text);
  }
  .big {
    font-size: 19px;
    font-weight: 700;
  }
  .acts {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 12px;
  }
</style>
