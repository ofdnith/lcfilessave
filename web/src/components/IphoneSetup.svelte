<script lang="ts">
  // Ajustes → Configurar iPhone: server address, Shortcuts tokens and install links.
  import Icon from './Icon.svelte';
  import { api, ApiError } from '../lib/api';
  import { ago, utcDate } from '../lib/format';
  import { confirmSheet } from '../lib/sheets.svelte';
  import { app, toast } from '../lib/state.svelte';
  import type { ApiToken } from '../lib/types';

  let tokens = $state<ApiToken[]>([]);
  let tokensError = $state<string | null>(null);
  let links = $state<{ manual: string | null; daily: string | null } | null>(null);
  let fresh = $state<string | null>(null);
  let busy = $state(false);

  const origin = location.origin;
  let passwordSet = $state(true);

  function loadTokens() {
    api
      .tokens()
      .then((r) => {
        tokens = r.tokens;
        tokensError = null;
      })
      .catch((e) => (tokensError = e instanceof ApiError ? e.message : 'Não foi possível listar os tokens.'));
  }

  $effect(() => {
    api
      .authStatus()
      .then((a) => (passwordSet = a.password_set))
      .catch(() => {});
    loadTokens();
    api
      .shortcuts()
      .then((r) => (links = r.links))
      .catch(() => (links = null));
  });

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${what} copiado`, 'ok', undefined, 2000);
    } catch {
      toast('Não deu para copiar. Toque e segure no texto para copiar.', 'error');
    }
  }

  async function create() {
    busy = true;
    try {
      const r = await api.createToken('iPhone');
      fresh = r.token;
      loadTokens();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível criar o token.', 'error');
    } finally {
      busy = false;
    }
  }

  async function revoke(t: ApiToken) {
    const ok = await confirmSheet({
      title: `Revogar “${t.label}”?`,
      body: 'Os atalhos que usam esse token param de funcionar até receberem um novo.',
      confirm: 'Revogar',
      tone: 'danger',
    });
    if (!ok) return;
    try {
      await api.revokeToken(t.id);
      tokens = tokens.filter((x) => x.id !== t.id);
      toast('Token revogado', 'ok');
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível revogar.', 'error');
    }
  }
</script>

<section class="panel">
  <h2>Configurar iPhone</h2>
  <p class="muted">Os atalhos do app Atalhos precisam do endereço do servidor e de um token.</p>

  <div class="field">
    <span class="lbl">Endereço do servidor</span>
    <div class="copyrow">
      <code>{origin}</code>
      <button class="btn small" onclick={() => copy(origin, 'Endereço')}><Icon name="copy" size={15} /> Copiar</button>
    </div>
  </div>

  {#if fresh}
    <div class="fresh">
      <p><strong>Token novo.</strong> Copie agora e cole no atalho: ele não aparece de novo.</p>
      <div class="copyrow">
        <code class="tok">{fresh}</code>
        <button class="btn small primary" onclick={() => copy(fresh!, 'Token')}><Icon name="copy" size={15} /> Copiar</button>
      </div>
      <button class="btn small ghost" onclick={() => (fresh = null)}>Já copiei</button>
    </div>
  {:else if !passwordSet}
    <p class="lockline"><Icon name="lock" size={14} /> Defina uma senha no servidor antes (comando <code>acervo senha</code>); os tokens só existem com senha.</p>
  {:else if !app.readonly}
    <button class="btn small" onclick={create} disabled={busy}><Icon name="key" size={15} /> Criar token para os Atalhos</button>
  {:else}
    <p class="lockline"><Icon name="lock" size={14} /> Crie e revogue tokens quando estiver em casa.</p>
  {/if}

  {#if links && (links.manual || links.daily)}
    <div class="links">
      {#if links.manual}<a class="btn small" href={links.manual} target="_blank" rel="noopener"><Icon name="share" size={15} /> Instalar atalho Mandar pro backup</a>{/if}
      {#if links.daily}<a class="btn small" href={links.daily} target="_blank" rel="noopener"><Icon name="calendar" size={15} /> Instalar atalho Backup diário</a>{/if}
    </div>
  {:else}
    <p class="muted small">Os atalhos prontos ainda não foram configurados no servidor. O passo a passo para montá-los está em <code>docs/iphone.md</code>.</p>
  {/if}

  {#if tokensError}
    <p class="error-text small">{tokensError}</p>
  {:else if tokens.length}
    <h3>Tokens em uso</h3>
    <ul class="tokens">
      {#each tokens as t (t.id)}
        <li>
          <span class="tinfo">
            <span class="tname">{t.label}</span>
            <span class="faint small">criado em {utcDate(t.created_at)} · {t.last_used_at ? `usado ${ago(t.last_used_at)}` : 'nunca usado'}</span>
          </span>
          {#if !app.readonly}<button class="btn small ghost" onclick={() => revoke(t)}>Revogar</button>{/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  h2 {
    font-size: 16px;
    margin-bottom: 6px;
  }
  h3 {
    font-size: 13.5px;
    color: var(--muted);
    font-weight: 600;
    margin: 18px 0 6px;
  }
  p {
    margin: 0 0 12px;
    font-size: 14px;
  }
  .small {
    font-size: 12.5px;
  }
  .field {
    margin-bottom: 14px;
  }
  .lbl {
    display: block;
    font-size: 12px;
    color: var(--faint);
    margin-bottom: 4px;
  }
  .copyrow {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  code {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 13px;
    padding: 6px 10px;
    border-radius: 8px;
    background: var(--bg);
    border: 1px solid var(--line-soft);
    word-break: break-all;
  }
  p code {
    padding: 1px 6px;
    font-size: 12px;
    white-space: nowrap;
    word-break: normal;
  }
  .tok {
    flex: 1;
    min-width: 0;
    user-select: all;
    -webkit-user-select: all;
  }
  .fresh {
    padding: 12px;
    border-radius: var(--r-md);
    background: var(--accent-soft);
    border: 1px solid rgba(240, 180, 76, 0.35);
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: flex-start;
  }
  .fresh p {
    margin: 0;
  }
  .fresh .copyrow {
    width: 100%;
  }
  .links {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 14px 0 4px;
  }
  .links + p,
  .fresh + p,
  .btn + p {
    margin-top: 12px;
  }
  .lockline {
    display: flex;
    gap: 6px;
    align-items: center;
    color: var(--info);
  }
  .tokens {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .tokens li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
    border-top: 1px solid var(--line-soft);
  }
  .tinfo {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .tname {
    font-weight: 560;
    font-size: 14px;
  }
</style>
