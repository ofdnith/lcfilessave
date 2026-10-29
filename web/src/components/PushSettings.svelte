<script lang="ts">
  // Ajustes → Avisos (Web Push), only meaningful in the installed PWA.
  import Icon from './Icon.svelte';
  import { api, ApiError } from '../lib/api';
  import { allTopics, currentSubscription, isStandalone, pushSupported, subscribe, topicLabels, unsubscribe } from '../lib/push';
  import { toast } from '../lib/state.svelte';
  import type { PushTopic } from '../lib/types';

  const standalone = isStandalone();
  const supported = pushSupported();

  let key = $state<string | null>(null);
  let serverSupport = $state<boolean | null>(null);
  let sub = $state<PushSubscription | null>(null);
  let topics = $state<PushTopic[]>([...allTopics]);
  let busy = $state(false);

  $effect(() => {
    if (!standalone || !supported) return;
    api
      .pushKey()
      .then((r) => {
        key = r.public_key;
        serverSupport = true;
      })
      .catch(() => (serverSupport = false));
    currentSubscription()
      .then(async (s) => {
        sub = s;
        if (s) {
          const st = await api.pushStatus(s.endpoint).catch(() => null);
          if (st?.subscribed) topics = st.topics;
          else sub = null;
        }
      })
      .catch(() => {});
  });

  async function toggle() {
    if (busy || !key) return;
    busy = true;
    try {
      if (sub) {
        await unsubscribe(sub);
        sub = null;
        toast('Avisos desligados', 'info', undefined, 2500);
      } else {
        sub = await subscribe(key, topics);
        toast('Avisos ligados', 'ok', undefined, 2500);
      }
    } catch (e) {
      toast(e instanceof ApiError ? e.message : (e as Error).message, 'error');
    } finally {
      busy = false;
    }
  }

  async function setTopic(t: PushTopic, on: boolean) {
    topics = on ? [...new Set([...topics, t])] : topics.filter((x) => x !== t);
    if (!sub) return;
    try {
      await api.pushSubscribe(sub.toJSON(), topics);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível salvar.', 'error');
    }
  }

  async function test() {
    if (!sub) return;
    try {
      await api.pushTest(sub.endpoint);
      toast('Aviso de teste enviado', 'ok', undefined, 2500);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível enviar.', 'error');
    }
  }
</script>

<section class="panel">
  <h2>Avisos</h2>
  {#if !standalone}
    <p class="muted">Adicione à Tela de Início para receber avisos: backup atrasado, servidor ficando cheio, problema num HD.</p>
  {:else if !supported}
    <p class="muted">Este aparelho não recebe avisos de web apps. No iPhone, precisa do iOS 16.4 ou mais novo e do endereço com HTTPS.</p>
  {:else if serverSupport === false}
    <p class="muted">O servidor ainda não está configurado para mandar avisos.</p>
  {:else if serverSupport === null}
    <p class="muted">Conferindo…</p>
  {:else}
    <label class="switch">
      <span>
        <strong>Receber avisos</strong>
        <span class="faint small">{sub ? 'Ligado neste aparelho' : 'Desligado'}</span>
      </span>
      <input type="checkbox" role="switch" checked={!!sub} disabled={busy} onchange={toggle} />
    </label>
    <fieldset disabled={!sub}>
      <legend class="sr-only">Quais avisos</legend>
      {#each allTopics as t (t)}
        <label class="topic">
          <input type="checkbox" checked={topics.includes(t)} onchange={(e) => setTopic(t, (e.currentTarget as HTMLInputElement).checked)} />
          {topicLabels[t]}
        </label>
      {/each}
    </fieldset>
    {#if sub}<button class="btn small" onclick={test}><Icon name="bell" size={15} /> Enviar aviso de teste</button>{/if}
  {/if}
</section>

<style>
  h2 {
    font-size: 16px;
    margin-bottom: 8px;
  }
  p {
    margin: 0;
    font-size: 14px;
  }
  .small {
    font-size: 12.5px;
  }
  .switch {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 4px 0 10px;
    cursor: pointer;
  }
  .switch > span {
    display: flex;
    flex-direction: column;
  }
  input[type='checkbox'][role='switch'] {
    appearance: none;
    -webkit-appearance: none;
    width: 46px;
    height: 28px;
    border-radius: 14px;
    background: var(--raised-2);
    position: relative;
    cursor: pointer;
    transition: background 0.18s;
    flex: none;
  }
  input[role='switch']::after {
    content: '';
    position: absolute;
    top: 3px;
    left: 3px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #fff;
    transition: transform 0.18s var(--ease);
  }
  input[role='switch']:checked {
    background: var(--keep);
  }
  input[role='switch']:checked::after {
    transform: translateX(18px);
  }
  fieldset {
    border: 0;
    margin: 0 0 12px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  fieldset:disabled {
    opacity: 0.45;
  }
  .topic {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 6px 0;
    font-size: 14px;
  }
  .topic input {
    width: 18px;
    height: 18px;
    accent-color: var(--accent);
  }
</style>
