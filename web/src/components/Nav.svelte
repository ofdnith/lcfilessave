<script lang="ts">
  import Icon, { type IconName } from './Icon.svelte';
  import StorageStatus from './StorageStatus.svelte';
  import { num } from '../lib/format';
  import { isNative } from '../lib/native';
  import { href, router, type Route } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';
  import { uploader } from '../lib/uploader.svelte';

  interface NavItem {
    route: Route;
    label: string;
    icon: IconName;
    badge?: number;
    mobile: boolean;
  }

  const native = isNative();
  const items = $derived<NavItem[]>([
    { route: 'acervo', label: 'Acervo', icon: 'library', mobile: true },
    { route: 'entrada', label: 'Entrada', icon: 'inbox', badge: app.stats?.inbox_count, mobile: true },
    { route: 'enviar', label: 'Enviar', icon: 'upload', mobile: true },
    { route: 'lixeira', label: 'Lixeira', icon: 'trash', mobile: true },
    ...(native ? [{ route: 'dispositivos' as Route, label: 'Dispositivos', icon: 'drive' as IconName, mobile: false }] : []),
    { route: 'ajustes', label: 'Ajustes', icon: 'settings', mobile: true },
  ]);

  const active = (r: Route) => router.route === r || (r === 'dispositivos' && router.route === 'esvaziar');
  const uploading = $derived(uploader.running);
</script>

<nav class="sidebar" aria-label="Principal">
  <a class="brand" href={href('acervo')}>
    <img src="/icons/icon-192.png" alt="" width="30" height="30" />
    <span>Acervo</span>
  </a>
  <ul>
    {#each items as it (it.route)}
      <li>
        <a href={href(it.route)} class:active={active(it.route)} aria-current={active(it.route) ? 'page' : undefined}>
          <Icon name={it.icon} size={20} />
          <span class="lbl">{it.label}</span>
          {#if it.route === 'enviar' && uploading}<span class="pulse" aria-label="Enviando"></span>{/if}
          {#if it.badge}<span class="badge num">{num(it.badge)}</span>{/if}
        </a>
      </li>
    {/each}
  </ul>
  <div class="foot">
    <StorageStatus />
  </div>
</nav>

<nav class="tabbar" aria-label="Principal">
  {#each items.filter((i) => i.mobile) as it (it.route)}
    <a href={href(it.route)} class:active={active(it.route)} aria-current={active(it.route) ? 'page' : undefined}>
      <span class="ti">
        <Icon name={it.icon} size={23} />
        {#if it.badge}<span class="tbadge num">{it.badge > 999 ? '999+' : num(it.badge)}</span>{/if}
        {#if it.route === 'enviar' && uploading}<span class="pulse dot"></span>{/if}
      </span>
      <span class="tl">{it.label}</span>
    </a>
  {/each}
</nav>

<style>
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    width: var(--sidebar);
    padding: calc(var(--sat) + 18px) 12px calc(var(--sab) + 16px) calc(var(--sal) + 12px);
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border-right: 1px solid var(--line-soft);
    z-index: 20;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 10px 18px;
    color: var(--text);
    text-decoration: none;
    font-weight: 700;
    font-size: 18px;
    letter-spacing: -0.01em;
  }
  .brand img {
    border-radius: 8px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .sidebar a:not(.brand) {
    display: flex;
    align-items: center;
    gap: 14px;
    height: 42px;
    padding: 0 14px;
    border-radius: 999px;
    color: var(--muted);
    text-decoration: none;
    font-weight: 560;
    font-size: 14.5px;
  }
  .sidebar a:not(.brand):hover {
    background: var(--raised);
    color: var(--text);
  }
  .sidebar a.active {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .lbl {
    flex: 1;
  }
  .badge {
    font-size: 12px;
    font-weight: 700;
    padding: 1px 8px;
    border-radius: 999px;
    background: var(--accent);
    color: var(--accent-ink);
  }
  .pulse {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--keep);
    animation: pulse 1.4s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }
  .foot {
    margin-top: auto;
    padding: 14px 10px 0;
    border-top: 1px solid var(--line-soft);
  }
  .tabbar {
    display: none;
  }

  @media (max-width: 899px) {
    .sidebar {
      display: none;
    }
    .tabbar {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: 30;
      display: flex;
      height: calc(var(--tabbar) + var(--sab));
      padding: 0 var(--sar) var(--sab) var(--sal);
      background: color-mix(in srgb, var(--surface) 90%, transparent);
      backdrop-filter: blur(18px) saturate(1.4);
      -webkit-backdrop-filter: blur(18px) saturate(1.4);
      border-top: 1px solid var(--line-soft);
    }
    .tabbar a {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2px;
      color: var(--faint);
      text-decoration: none;
      font-size: 10.5px;
      font-weight: 600;
    }
    .tabbar a.active {
      color: var(--accent);
    }
    .ti {
      position: relative;
      display: grid;
      place-items: center;
      width: 52px;
      height: 28px;
      border-radius: 999px;
    }
    .active .ti {
      background: var(--accent-soft);
    }
    .tbadge {
      position: absolute;
      top: -4px;
      left: 30px;
      min-width: 18px;
      padding: 0 5px;
      height: 17px;
      border-radius: 9px;
      background: var(--accent);
      color: var(--accent-ink);
      font-size: 10.5px;
      font-weight: 800;
      line-height: 17px;
      text-align: center;
    }
    .pulse.dot {
      position: absolute;
      top: 0;
      right: 10px;
    }
  }
</style>
