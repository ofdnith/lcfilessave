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
  import ConfirmSheet from './components/ConfirmSheet.svelte';
  import AlbumSheet from './components/AlbumSheet.svelte';
  import Albums from './views/Albums.svelte';
  import AlbumPage from './views/AlbumPage.svelte';
  import Places from './views/Places.svelte';
  import Help from './views/Help.svelte';
  import Alerts from './components/Alerts.svelte';
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
  // When opened by IP (or the old Tailscale name), point to the trusted address:
  // only it works in Safari and the Mac app without installing a certificate.
  let safeUrl = $state<string | null>(null);
  async function checkHealth() {
    try {
      const h = await api.health();
      app.migration = !!h.migration?.active;
      const trusted = [h.addresses?.home, h.addresses?.away].filter((u): u is string => !!u);
      const onTrusted = trusted.some((u) => new URL(u).host === location.host);
      // The Mac app picks the address itself (and only navigates to that one).
      const inApp = '__TAURI__' in window;
      const target = h.remote ? h.addresses?.away : h.addresses?.home;
      safeUrl = target && !onTrusted && !inApp ? target + '/' + location.hash : null;
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

  // Banners on top take the status-bar inset themselves; the page below must not add it again.
  const alertsShown = $derived(
    (app.stats?.alerts ?? []).length > 0 && router.route !== 'ajuda',
  );
  const hasTop = $derived(app.migration || !!safeUrl || alertsShown);
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
  <main class="main" class:has-top={hasTop}>
    {#if hasTop}
      <div class="top-stack">
        {#if app.migration}
          <div class="banner danger" role="status">
            <Icon name="lock" size={18} /> Migração em andamento — o Acervo está só para consulta
          </div>
        {/if}
        {#if safeUrl}
          <a class="banner" href={safeUrl}>
            <Icon name="shield" size={18} />
            <span>Há um endereço seguro para o Acervo. Abra por ele e salve na Tela de Início: funciona no Safari sem instalar certificado.</span>
          </a>
        {/if}
        {#if alertsShown}<Alerts />{/if}
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
    {:else if router.route === 'ajuda'}
      {#key router.param}<Help slug={router.param} />{/key}
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
    /* Top inset for the page header: the status bar / notch, unless banners already took it. */
    --page-top: var(--sat);
    margin-left: var(--sidebar);
    min-height: 100%;
    min-height: 100dvh;
    padding-right: var(--sar);
  }
  .main.has-top {
    --page-top: 0px;
  }
  .top-stack {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: calc(var(--sat) + 12px) 24px 0;
    max-width: 1148px;
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
    .top-stack {
      padding: calc(var(--sat) + 10px) 16px 0;
    }
  }
</style>
