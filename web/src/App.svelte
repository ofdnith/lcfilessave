<script lang="ts">
  import Nav from './components/Nav.svelte';
  import Toasts from './components/Toasts.svelte';
  import Viewer from './components/Viewer.svelte';
  import Icon from './components/Icon.svelte';
  import Library from './views/Library.svelte';
  import Inbox from './views/Inbox.svelte';
  import Trash from './views/Trash.svelte';
  import Upload from './views/Upload.svelte';
  import Settings from './views/Settings.svelte';
  import Devices from './views/Devices.svelte';
  import EmptyIphone from './views/EmptyIphone.svelte';
  import Login from './views/Login.svelte';
  import StorageStatus from './components/StorageStatus.svelte';
  import ConfirmSheet from './components/ConfirmSheet.svelte';
  import AlbumSheet from './components/AlbumSheet.svelte';
  import Albums from './views/Albums.svelte';
  import AlbumPage from './views/AlbumPage.svelte';
  import Places from './views/Places.svelte';
  import { api, ApiError } from './lib/api';
  import { isNative } from './lib/native';
  import { go, router } from './lib/router.svelte';
  import { app } from './lib/state.svelte';
  import { refreshStats } from './lib/stats.svelte';
  import { uploader } from './lib/uploader.svelte';

  async function checkAuth() {
    try {
      const s = await api.authStatus();
      app.remote = !!s.remote;
      app.readonly = !!s.readonly;
      app.auth = s.password_set && !s.authenticated ? 'login' : 'ok';
      if (app.auth === 'ok') void refreshStats();
    } catch (e) {
      app.auth = e instanceof ApiError && e.status === 401 ? 'login' : 'offline';
    }
  }
  void checkAuth();

  // Keep counters fresh: on focus and every 60 s while visible.
  $effect(() => {
    if (app.auth !== 'ok') return;
    const t = setInterval(() => document.visibilityState === 'visible' && void refreshStats(), 60000);
    const onVis = () => document.visibilityState === 'visible' && void refreshStats();
    document.addEventListener('visibilitychange', onVis);
    return () => {
      clearInterval(t);
      document.removeEventListener('visibilitychange', onVis);
    };
  });

  // Migration state lives in /api/health; check it on load and every 30 s.
  async function checkHealth() {
    try {
      app.migration = !!(await api.health()).migration?.active;
    } catch {
      /* the offline screen covers a dead server */
    }
  }
  $effect(() => {
    if (app.auth !== 'ok') return;
    void checkHealth();
    const t = setInterval(() => document.visibilityState === 'visible' && void checkHealth(), 30000);
    return () => clearInterval(t);
  });

  // Mac-only routes are hidden elsewhere.
  $effect(() => {
    if ((router.route === 'dispositivos' || router.route === 'esvaziar') && !isNative()) go('acervo');
  });

  // Reset type/search when switching between Acervo and Entrada so filters don't leak confusingly.
  let lastRoute = router.route;
  $effect(() => {
    const r = router.route;
    if (r !== lastRoute) {
      lastRoute = r;
      app.q = '';
      app.filters = { year: null, important: false, archived: null };
      window.scrollTo({ top: 0 });
    }
  });

  function onKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (router.route !== 'acervo' && router.route !== 'entrada') go('acervo');
      requestAnimationFrame(() => app.searchFocus++);
    }
  }

  // Whole-window drop target on desktop: dropping files anywhere starts an upload.
  let dragDepth = $state(0);
  const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files');
  function dragEnter(e: DragEvent) {
    if (!hasFiles(e) || app.auth !== 'ok') return;
    dragDepth++;
  }
  function dragLeave(e: DragEvent) {
    if (!hasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
  }
  function dragOver(e: DragEvent) {
    if (hasFiles(e) && app.auth === 'ok') e.preventDefault();
  }
  function drop(e: DragEvent) {
    dragDepth = 0;
    if (!hasFiles(e) || app.auth !== 'ok') return;
    e.preventDefault();
    if (router.route === 'enviar') return; // the Upload view handles its own drop
    if (e.dataTransfer?.files.length) {
      uploader.add(e.dataTransfer.files);
      go('enviar');
    }
  }

  // Warn before closing while an upload runs (tus resumes anyway, but hashing restarts).
  $effect(() => {
    const h = (e: BeforeUnloadEvent) => {
      if (uploader.running) e.preventDefault();
    };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  });

  const overdue = $derived(app.stats?.daily_backup.overdue ?? false);
</script>

<svelte:window onkeydown={onKey} ondragenter={dragEnter} ondragleave={dragLeave} ondragover={dragOver} ondrop={drop} />

{#if app.auth === 'checking'}
  <div class="splash" aria-label="Carregando"><img src="/icons/icon-192.png" alt="" width="64" height="64" /></div>
{:else if app.auth === 'offline'}
  <div class="splash col">
    <Icon name="server" size={36} />
    <h1>Servidor fora do ar</h1>
    <p class="muted">Confira se o celular do Acervo está ligado e na mesma rede (ou no Tailscale).</p>
    <button class="btn primary" onclick={() => ((app.auth = 'checking'), checkAuth())}>Tentar de novo</button>
  </div>
{:else if app.auth === 'login'}
  <Login />
{:else}
  <Nav />
  <main class="main">
    {#if app.migration}
      <div class="banner danger top-banner" role="status">
        <Icon name="lock" size={18} /> Migração em andamento — o Acervo está só para consulta
      </div>
    {/if}
    {#if app.readonly}
      <div class="slim" role="status">
        <Icon name="shield" size={15} /> Fora de casa · modo seguro (não dá para apagar nem mexer em HDs)
      </div>
    {/if}
    {#if overdue}
      <div class="banner top-banner" role="status"><Icon name="alert" size={18} /> Backup diário atrasado: mais de 48 h</div>
    {/if}
    {#if app.stats?.storage.alert}
      <div class="banner danger top-banner" role="status">
        <Icon name="drive" size={18} /> Servidor quase cheio. Transfira um lote para um HD pelo app do Mac.
      </div>
    {/if}
    {#if router.route === 'acervo'}
      <Library />
    {:else if router.route === 'entrada'}
      <Inbox />
    {:else if router.route === 'lixeira'}
      <Trash />
    {:else if router.route === 'enviar'}
      <Upload />
    {:else if router.route === 'ajustes'}
      <div class="mobile-status"><StorageStatus /></div>
      <Settings />
    {:else if router.route === 'dispositivos'}
      <Devices />
    {:else if router.route === 'esvaziar'}
      <EmptyIphone />
    {:else if router.route === 'albuns'}
      <Albums />
    {:else if router.route === 'album'}
      {#key router.param}<AlbumPage id={Number(router.param)} />{/key}
    {:else if router.route === 'lugares'}
      <Places />
    {/if}
  </main>
  <Viewer />
  <AlbumSheet />
  {#if dragDepth > 0 && router.route !== 'enviar'}
    <div class="dropzone" aria-hidden="true">
      <div><Icon name="upload" size={40} /><p>Solte para enviar ao Acervo</p></div>
    </div>
  {/if}
{/if}
<ConfirmSheet />
<Toasts />

<style>
  .main {
    margin-left: var(--sidebar);
    min-height: 100%;
    padding-right: var(--sar);
  }
  .top-banner {
    margin: calc(var(--sat) + 12px) 24px 0;
  }
  .top-banner + .top-banner {
    margin-top: 8px;
  }
  .slim {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: calc(var(--sat) + 6px) 16px 6px;
    background: rgba(143, 185, 255, 0.12);
    color: var(--info);
    font-size: 12.5px;
    font-weight: 560;
    text-align: center;
  }
  .slim + .top-banner {
    margin-top: 10px;
  }
  .mobile-status {
    display: none;
  }
  .splash {
    height: 100%;
    display: grid;
    place-items: center;
  }
  .splash.col {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    gap: 10px;
    text-align: center;
    padding: 24px;
    color: var(--muted);
  }
  .splash.col h1 {
    color: var(--text);
    font-size: 22px;
  }
  .splash.col p {
    margin: 0 0 8px;
    max-width: 360px;
  }
  .splash img {
    border-radius: 16px;
    animation: breathe 1.6s ease-in-out infinite;
  }
  @keyframes breathe {
    50% {
      opacity: 0.5;
    }
  }
  .dropzone {
    position: fixed;
    inset: 0;
    z-index: 150;
    background: rgba(16, 21, 28, 0.82);
    display: grid;
    place-items: center;
    pointer-events: none;
  }
  .dropzone > div {
    padding: 48px 64px;
    border: 2px dashed var(--accent);
    border-radius: 24px;
    text-align: center;
    color: var(--accent);
    font-size: 18px;
    font-weight: 600;
  }
  @media (max-width: 899px) {
    .main {
      margin-left: 0;
      padding-left: var(--sal);
      padding-bottom: calc(var(--tabbar) + var(--sab));
    }
    .top-banner {
      margin: calc(var(--sat) + 10px) 16px 0;
    }
    .mobile-status {
      display: block;
      padding: calc(var(--sat) + 16px) 16px 0;
    }
    .mobile-status + :global(.page .page-title) {
      padding-top: 0;
    }
  }
</style>
