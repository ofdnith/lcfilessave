<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import StorageStatus from '../components/StorageStatus.svelte';
  import IphoneSetup from '../components/IphoneSetup.svelte';
  import PushSettings from '../components/PushSettings.svelte';
  import { api } from '../lib/api';
  import { bytes, num } from '../lib/format';
  import { isNative } from '../lib/native';
  import { href } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';
  import type { Settings } from '../lib/types';

  let settings = $state<Settings | null>(null);
  let settingsError = $state(false);
  let authMethod = $state<string | null>(null);

  $effect(() => {
    api.settings().then((s) => (settings = s)).catch(() => (settingsError = true));
    api.authStatus().then((a) => (authMethod = a.method)).catch(() => {});
  });

  const standalone =
    typeof window !== 'undefined' &&
    (window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true);
  const isIOS = typeof navigator !== 'undefined' && /iPhone|iPad|iPod/.test(navigator.userAgent);

  async function logout() {
    try {
      await api.logout();
    } finally {
      app.auth = 'login';
    }
  }

  const st = $derived(app.stats);
</script>

<div class="page settings">
  <h1 class="page-title">Ajustes</h1>

  <section class="panel">
    <h2>Espaço no servidor</h2>
    <StorageStatus />
    {#if st}
      <dl class="grid">
        <div><dt>No acervo</dt><dd class="num">{num(st.tabs.all.count)} itens · {bytes(st.tabs.all.bytes)}</dd></div>
        <div><dt>Na Entrada</dt><dd class="num">{num(st.inbox_count)}</dd></div>
        <div><dt>Arquivados em HD</dt><dd class="num">{num(st.archived_count)}</dd></div>
        <div><dt>Na lixeira</dt><dd class="num">{num(st.trash_count)}</dd></div>
        <div><dt>Disco do celular</dt><dd class="num">{bytes(st.storage.disk_free_bytes)} livres de {bytes(st.storage.disk_total_bytes)}</dd></div>
        {#if settings}
          <div><dt>Lote por HD</dt><dd class="num">{num(settings.archive_batch_gb)} GB · {settings.archive_copies} {settings.archive_copies === 1 ? 'cópia' : 'cópias'}</dd></div>
        {/if}
      </dl>
    {/if}
  </section>

  <nav class="shortcuts" aria-label="Atalhos">
    <a class="sc" href={href('lixeira')}>
      <Icon name="trash" size={19} /><span>Lixeira</span>
      {#if st?.trash_count}<span class="faint num">{num(st.trash_count)}</span>{/if}
      <Icon name="right" size={16} />
    </a>
    <a class="sc" href={href('lugares')}>
      <Icon name="map" size={19} /><span>Lugares</span><Icon name="right" size={16} />
    </a>
  </nav>

  {#if !isNative()}
    <IphoneSetup />
    <PushSettings />
  {/if}

  {#if isNative()}
    <section class="panel">
      <h2>App do Mac</h2>
      <p class="muted">HDs, transferências e o Esvaziar iPhone ficam em <a href={href('dispositivos')}>Dispositivos</a>.</p>
    </section>
  {/if}

  {#if !standalone && !isNative()}
    <section class="panel">
      <h2>Instalar no iPhone</h2>
      <ol class="steps">
        <li>Abra este endereço no <strong>Safari</strong>.</li>
        <li>Toque em <strong>Compartilhar</strong> <span class="inline-icon"><Icon name="share" size={16} /></span>.</li>
        <li>Escolha <strong>Adicionar à Tela de Início</strong> e confirme.</li>
      </ol>
      <p class="muted small">O Acervo abre em tela cheia, como um app. {isIOS ? '' : 'No Mac, use o app próprio ou o navegador.'}</p>
    </section>
  {/if}

  <section class="panel">
    <h2>Certificado de segurança</h2>
    <p class="muted">
      Se o servidor usa HTTPS próprio, o iPhone e o Mac precisam confiar no certificado dele uma vez.
      Baixe, instale e, no iPhone, ative em Ajustes → Geral → Sobre → Ajustes de Confiança de Certificados.
    </p>
    <a class="btn small" href="/ca.crt" download="acervo-ca.crt"><Icon name="shield" size={16} /> Baixar certificado</a>
  </section>

  <section class="panel">
    <h2>Sobre</h2>
    <dl class="grid">
      <div><dt>Servidor</dt><dd>{settings?.server_name ?? (settingsError ? 'indisponível' : '…')}</dd></div>
      <div><dt>Versão</dt><dd class="num">{settings?.version ?? '…'}</dd></div>
      <div><dt>Lixeira</dt><dd class="num">{settings ? `${settings.trash_days} dias` : '…'}</dd></div>
    </dl>
  </section>

  {#if authMethod !== 'local'}
    <button class="btn danger" onclick={logout}><Icon name="logout" size={16} /> Sair</button>
  {/if}
</div>

<style>
  .settings {
    max-width: 720px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    align-items: stretch;
  }
  .settings > .btn {
    align-self: flex-start;
  }
  .page-title {
    padding-top: var(--sat);
  }
  h2 {
    font-size: 16px;
    margin-bottom: 10px;
  }
  .panel p {
    margin: 0 0 12px;
    font-size: 14px;
  }
  .shortcuts {
    display: none;
    flex-direction: column;
    background: var(--surface);
    border: 1px solid var(--line-soft);
    border-radius: var(--r-lg);
    overflow: hidden;
  }
  .sc {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 13px 16px;
    color: var(--text);
    text-decoration: none;
    font-weight: 560;
  }
  .sc + .sc {
    border-top: 1px solid var(--line-soft);
  }
  .sc span:first-of-type {
    flex: 1;
  }
  .sc :global(svg:last-child) {
    color: var(--faint);
  }
  @media (max-width: 899px) {
    .shortcuts {
      display: flex;
    }
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 12px 16px;
    margin: 16px 0 0;
  }
  dt {
    font-size: 12px;
    color: var(--faint);
  }
  dd {
    margin: 0;
    font-size: 14px;
  }
  .steps {
    margin: 0 0 10px;
    padding-left: 20px;
    font-size: 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .inline-icon {
    display: inline-flex;
    vertical-align: -3px;
    color: var(--info);
  }
  .small {
    font-size: 13px;
  }
</style>
