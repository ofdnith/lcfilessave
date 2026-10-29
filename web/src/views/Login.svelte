<script lang="ts">
  import { api, ApiError } from '../lib/api';
  import { app } from '../lib/state.svelte';
  import { refreshStats } from '../lib/stats.svelte';

  let password = $state('');
  let error = $state<string | null>(null);
  let busy = $state(false);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!password || busy) return;
    busy = true;
    error = null;
    try {
      await api.login(password);
      password = '';
      app.auth = 'ok';
      void refreshStats();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) error = 'Senha errada. Tente de novo.';
      else if (err instanceof ApiError && err.status === 429) error = 'Muitas tentativas. Espere alguns minutos e tente de novo.';
      else error = err instanceof ApiError ? err.message : 'Não foi possível entrar.';
    } finally {
      busy = false;
    }
  }
</script>

<main class="login">
  <form onsubmit={submit} class="card">
    <img src="/icons/icon-192.png" alt="" width="72" height="72" class="logo" />
    <h1>Acervo</h1>
    <p class="muted">Digite a senha do servidor para continuar.</p>
    <label class="sr-only" for="pw">Senha</label>
    <!-- svelte-ignore a11y_autofocus -->
    <input id="pw" type="password" bind:value={password} autocomplete="current-password" placeholder="Senha" autofocus aria-invalid={!!error} />
    {#if error}<p class="error-text" role="alert">{error}</p>{/if}
    <button class="btn primary" type="submit" disabled={busy || !password}>{busy ? 'Entrando…' : 'Entrar'}</button>
  </form>
</main>

<style>
  .login {
    min-height: 100%;
    display: grid;
    place-items: center;
    padding: calc(var(--sat) + 24px) 16px calc(var(--sab) + 24px);
  }
  .card {
    width: 100%;
    max-width: 340px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    text-align: center;
  }
  .logo {
    margin: 0 auto 4px;
    border-radius: 18px;
  }
  h1 {
    font-size: 28px;
  }
  p {
    margin: 0;
  }
  input {
    height: 48px;
    padding: 0 16px;
    border-radius: var(--r-md);
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 16px;
    outline: 0;
  }
  input:focus {
    border-color: var(--accent);
  }
  .btn {
    min-height: 46px;
  }
</style>
