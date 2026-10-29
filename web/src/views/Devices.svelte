<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import { ago, bytes, num, plural } from '../lib/format';
  import { devices } from '../lib/devices.svelte';
  import { href } from '../lib/router.svelte';
  import { app, toast } from '../lib/state.svelte';
  import type { Disk } from '../lib/native';
  import type { Volume } from '../lib/types';

  $effect(() => devices.watch());

  let adding = $state<string | null>(null);

  async function add(d: Disk) {
    adding = d.mount_path;
    try {
      const v = await devices.addVolume(d);
      toast(`HD preparado como ${v.name}. Escreva esse nome numa etiqueta no HD.`, 'ok', undefined, 9000);
    } catch (e) {
      toast(`Não foi possível adicionar: ${(e as Error).message}`, 'error');
    } finally {
      adding = null;
    }
  }

  function checkLine(v: Volume): string {
    const full = v.last_full_check_at ? `última verificação completa ${ago(v.last_full_check_at)}` : 'nunca verificado por completo';
    const probs = v.last_check ? plural(v.last_check.problems, 'problema', 'problemas') : null;
    return probs ? `${full} · ${probs}` : full;
  }

  const t = $derived(devices.transfer);
  const c = $derived(devices.check);
  const busy = $derived(!!t && ['planning', 'copying', 'committing', 'bundle'].includes(t.phase));
  const tPct = $derived(t && t.totalBytes ? ((t.doneBytes + t.currentBytes) / t.totalBytes) * 100 : 0);
  const h = $derived(devices.health);
</script>

<div class="page devices">
  <h1 class="page-title">Dispositivos</h1>
  <p class="page-sub">O servidor e os HDs conectados a este Mac. Atualiza sozinho.</p>

  <section class="card server" class:bad={devices.healthError || h?.status === 'degraded'}>
    <span class="dev-icon"><Icon name="server" size={26} /></span>
    <div class="dev-main">
      <h2>Servidor</h2>
      {#if devices.healthError}
        <p class="error-text">Sem resposta. Confira se o celular está ligado e na mesma rede.</p>
      {:else if h}
        <p class="muted num">
          {h.status === 'ok' ? 'Funcionando' : 'Com problemas'} · versão {h.version} ·
          {bytes(h.storage.free_bytes)} livres de {bytes(h.storage.total_bytes)}
        </p>
        {#if h.problems.length}<ul class="problems">{#each h.problems as p}<li>{p}</li>{/each}</ul>{/if}
      {:else}
        <p class="muted">Conectando…</p>
      {/if}
    </div>
    <span class="dot" class:ok={h?.status === 'ok' && !devices.healthError}></span>
  </section>

  <h2 class="sec">HDs conectados</h2>
  {#if devices.diskError}<p class="error-text">{devices.diskError}</p>{/if}
  {#if !devices.disks.length}
    <div class="empty panel">
      <Icon name="drive" size={28} />
      <p>Conecte um HD externo para transferir um lote ou verificar a saúde dele.</p>
    </div>
  {/if}

  {#each devices.disks as d (d.mount_path)}
    {@const v = devices.volumeFor(d)}
    <section class="card disk" class:known={!!v}>
      <span class="dev-icon"><Icon name="drive" size={26} /></span>
      <div class="dev-main">
        {#if v}
          <h2><span class="label-tag">{v.name}</span></h2>
          <p class="muted num">{bytes(d.free_bytes)} livres de {bytes(d.total_bytes)} · {plural(v.item_count, 'item', 'itens')}</p>
          <p class="faint small">{checkLine(v)}</p>
          {#if app.readonly}
            <p class="lock small"><Icon name="lock" size={14} /> Fora de casa, transferir e verificar HDs ficam bloqueados.</p>
          {:else}
          <div class="acts">
            <button class="btn small primary" disabled={busy} onclick={() => devices.startTransfer(d, v)}>
              <Icon name="download" size={15} /> Transferir lote para cá
            </button>
            <button class="btn small" disabled={c?.phase === 'running' || busy} onclick={() => devices.runCheck(d, v, false)}>
              <Icon name="shield" size={15} /> Verificar saúde
            </button>
            <button class="btn small ghost" disabled={c?.phase === 'running' || busy} onclick={() => devices.runCheck(d, v, true)}>
              Verificação completa
            </button>
          </div>
          {/if}
        {:else if d.volume}
          <h2>{d.label || d.mount_path}</h2>
          <p class="muted">Tem um {d.volume.name}, mas o servidor não conhece este volume. Ele pode ser de outro Acervo.</p>
        {:else}
          <h2>{d.label || d.mount_path}</h2>
          <p class="muted num">{bytes(d.total_bytes)} · {d.filesystem || 'formato desconhecido'} · ainda não faz parte do acervo</p>
          {#if app.readonly}
            <p class="lock small"><Icon name="lock" size={14} /> Adicione HDs novos quando estiver em casa.</p>
          {:else if d.filesystem.toLowerCase() === 'exfat'}
            <div class="acts">
              <button class="btn small" disabled={adding === d.mount_path} onclick={() => add(d)}>
                <Icon name="plus" size={15} /> {adding === d.mount_path ? 'Preparando…' : 'Adicionar como novo volume'}
              </button>
            </div>
          {:else}
            <p class="warn small">
              Precisa estar em exFAT para abrir em qualquer computador. Formate pelo Utilitário de Disco (isso apaga o HD) e conecte de novo.
            </p>
          {/if}
        {/if}
      </div>
    </section>

    {#if v && t && t.volumeId === v.id}
      <section class="panel job">
        {#if t.phase === 'planning'}
          <p>Montando o lote…</p>
        {:else if t.phase === 'copying'}
          <div class="job-head">
            <p><strong class="num">{num(t.index + 1)} de {num(t.files.length)}</strong> · <span class="num">{bytes(t.doneBytes + t.currentBytes)} de {bytes(t.totalBytes)}</span></p>
            <button class="btn small ghost" disabled={t.cancelRequested} onclick={() => devices.cancelTransfer()}>
              {t.cancelRequested ? 'Parando depois deste arquivo…' : 'Parar'}
            </button>
          </div>
          <div class="bar"><span style:width="{tPct}%"></span></div>
          <p class="faint small path">{t.files[t.index]?.rel_path}</p>
          <p class="faint small">Cada arquivo é copiado, relido do HD e conferido por SHA-256 antes de contar.</p>
        {:else if t.phase === 'committing'}
          <p>Confirmando com o servidor…</p>
        {:else if t.phase === 'bundle'}
          <p>Gravando catálogo, miniaturas e ABRIR-ACERVO.html no HD…</p>
        {:else if t.phase === 'done' || t.phase === 'cancelled'}
          <p class="ok-line">
            <Icon name="check" size={18} />
            {#if t.result && t.result.archived_items}
              <span class="num">{plural(t.result.archived_items, 'item transferido', 'itens transferidos')} · {bytes(t.result.freed_bytes)} liberados no servidor</span>
            {:else if t.files.length === 0}
              Nada para transferir agora.
            {:else}
              <span class="num">{plural(t.verified, 'arquivo copiado e conferido', 'arquivos copiados e conferidos')}. {devices.archiveCopies > 1 ? `Os itens saem do servidor quando estiverem em ${devices.archiveCopies} HDs.` : ''}</span>
            {/if}
          </p>
          {#if t.phase === 'cancelled'}<p class="muted small">Parado antes do fim. Transfira de novo para continuar; o que já foi conferido não é copiado outra vez.</p>{/if}
        {:else if t.phase === 'failed'}
          <p class="error-text">A transferência parou: {t.error}</p>
          <p class="muted small">Nada foi apagado do servidor sem conferência. Conecte o HD e transfira de novo para continuar.</p>
        {/if}
        {#if t.rejected.length || t.copyErrors.length}
          <details class="small">
            <summary class="warn">{plural(t.rejected.length + t.copyErrors.length, 'arquivo não conferiu', 'arquivos não conferiram')} e continuam no servidor</summary>
            <ul>
              {#each t.copyErrors as e}<li>{e.rel_path}: {e.error}</li>{/each}
              {#each t.rejected as e}<li>arquivo {e.file_id}: {e.error}</li>{/each}
            </ul>
          </details>
        {/if}
      </section>
    {/if}

    {#if v && c && c.volumeId === v.id}
      <section class="panel job">
        {#if c.phase === 'running'}
          <p>Relendo {c.full ? 'todos os arquivos' : 'uma amostra'} do {v.name}…</p>
        {:else if c.phase === 'done'}
          <p class:ok-line={!c.problems.length} class:error-text={!!c.problems.length}>
            {#if !c.problems.length}<Icon name="check" size={18} />{/if}
            <span class="num">{plural(c.checked, 'arquivo conferido', 'arquivos conferidos')} · {plural(c.problems.length, 'problema', 'problemas')}</span>
          </p>
          {#if c.problems.length}
            <ul class="small">{#each c.problems as p}<li>arquivo {p.file_id}: {p.error}</li>{/each}</ul>
            <p class="muted small">Se os originais ainda estão no servidor ou em outro HD, transfira de novo para refazer as cópias.</p>
          {/if}
        {:else}
          <p class="error-text">A verificação parou: {c.error}</p>
        {/if}
      </section>
    {/if}
  {/each}

  <section class="panel promo">
    <span class="dev-icon"><Icon name="phone" size={24} /></span>
    <div>
      <h2>Esvaziar iPhone</h2>
      <p class="muted">Mande a Fototeca inteira pelo cabo e saiba exatamente quando é seguro apagar do iPhone.</p>
    </div>
    <a class="btn small" href={href('esvaziar')}>Começar</a>
  </section>
</div>

<style>
  .devices {
    max-width: 820px;
  }
  .page-title {
    padding-top: var(--sat);
  }
  .sec {
    font-size: 15px;
    margin: 24px 0 10px;
    color: var(--muted);
    font-weight: 600;
  }
  .card {
    display: flex;
    gap: 14px;
    align-items: flex-start;
    padding: 16px;
    border-radius: var(--r-lg);
    background: var(--surface);
    border: 1px solid var(--line-soft);
    margin-bottom: 10px;
  }
  .card.known {
    border-color: rgba(240, 180, 76, 0.35);
  }
  .card.bad {
    border-color: rgba(255, 138, 128, 0.4);
  }
  .dev-icon {
    width: 46px;
    height: 46px;
    border-radius: 12px;
    background: var(--raised);
    color: var(--muted);
    display: grid;
    place-items: center;
    flex: none;
  }
  .known .dev-icon {
    color: var(--accent);
  }
  .dev-main {
    flex: 1;
    min-width: 0;
  }
  .dev-main h2 {
    font-size: 16px;
    margin-bottom: 2px;
  }
  .dev-main p {
    margin: 0;
    font-size: 13.5px;
  }
  .label-tag {
    display: inline-block;
    padding: 2px 9px 2px 7px;
    border-radius: 4px;
    background: #f3e7c9;
    color: #3b2c0c;
    border-left: 4px solid var(--accent);
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 0.02em;
  }
  .acts {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
  }
  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--danger);
    margin-top: 6px;
  }
  .dot.ok {
    background: var(--keep);
    box-shadow: 0 0 0 4px var(--keep-soft);
  }
  .problems {
    margin: 6px 0 0;
    padding-left: 18px;
    color: var(--warn);
    font-size: 13px;
  }
  .small {
    font-size: 12.5px;
  }
  .lock {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 10px !important;
    color: var(--info);
  }
  .warn {
    color: var(--warn);
  }
  .empty {
    display: flex;
    align-items: center;
    gap: 14px;
    color: var(--muted);
  }
  .empty p {
    margin: 0;
  }
  .job {
    margin: -4px 0 12px 60px;
    font-size: 14px;
  }
  .job p {
    margin: 0 0 6px;
  }
  .job-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  .path {
    margin-top: 6px !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-family: ui-monospace, Menlo, monospace;
  }
  .ok-line {
    display: flex;
    gap: 8px;
    align-items: center;
    color: var(--keep);
    font-weight: 600;
  }
  .promo {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-top: 28px;
  }
  .promo h2 {
    font-size: 16px;
  }
  .promo p {
    margin: 2px 0 0;
    font-size: 13.5px;
  }
  .promo > div {
    flex: 1;
  }
  @media (max-width: 899px) {
    .job {
      margin-left: 0;
    }
  }
</style>
