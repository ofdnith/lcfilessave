<script lang="ts">
  import Icon from './Icon.svelte';
  import Sheet from './Sheet.svelte';
  import { albums } from '../lib/albums.svelte';
  import { plural } from '../lib/format';
  import { sheets } from '../lib/sheets.svelte';
  import type { Album } from '../lib/types';

  let creating = $state(false);
  let name = $state('');
  let busy = $state(false);

  $effect(() => {
    if (sheets.albumFor) {
      creating = false;
      name = '';
      void albums.load();
    }
  });

  function close() {
    sheets.albumFor = null;
    sheets.albumDone = null;
  }

  async function choose(a: Album) {
    const ids = sheets.albumFor;
    if (!ids || busy) return;
    busy = true;
    const ok = await albums.add(a, ids);
    busy = false;
    if (ok) {
      sheets.albumDone?.(a.id);
      close();
    }
  }

  async function create(e: SubmitEvent) {
    e.preventDefault();
    const n = name.trim();
    if (!n || busy) return;
    busy = true;
    const a = await albums.create(n);
    busy = false;
    if (a) await choose(a);
  }
</script>

{#if sheets.albumFor}
  <Sheet label="Adicionar ao álbum" onclose={close}>
    <h2>Adicionar ao álbum</h2>
    <p class="muted sub">{plural(sheets.albumFor.length, 'item', 'itens')}</p>

    {#if creating}
      <form onsubmit={create} class="new">
        <!-- svelte-ignore a11y_autofocus -->
        <input bind:value={name} placeholder="Nome do álbum" maxlength="120" autofocus aria-label="Nome do novo álbum" />
        <button class="btn primary" type="submit" disabled={!name.trim() || busy}>Criar e adicionar</button>
      </form>
    {:else}
      <button class="row new-row" onclick={() => (creating = true)}>
        <span class="cover add"><Icon name="plus" size={20} /></span>
        <span class="name">Novo álbum…</span>
      </button>
    {/if}

    {#if !albums.loaded}
      <p class="muted">Carregando…</p>
    {:else if albums.error}
      <p class="error-text">{albums.error}</p>
    {/if}
    <ul>
      {#each albums.list as a (a.id)}
        <li>
          <button class="row" onclick={() => choose(a)} disabled={busy}>
            <span class="cover">
              {#if a.cover?.thumb_url}<img src={a.cover.thumb_url} alt="" loading="lazy" />{:else}<Icon name="album" size={18} />{/if}
            </span>
            <span class="name">{a.name}</span>
            <span class="faint num">{a.count}</span>
          </button>
        </li>
      {/each}
    </ul>
  </Sheet>
{/if}

<style>
  h2 {
    font-size: 18px;
  }
  .sub {
    margin: 2px 0 14px;
    font-size: 13.5px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 8px 6px;
    border-radius: var(--r-md);
    text-align: left;
  }
  .row:hover {
    background: var(--raised);
  }
  .cover {
    width: 44px;
    height: 44px;
    border-radius: 8px;
    background: var(--raised);
    display: grid;
    place-items: center;
    overflow: hidden;
    color: var(--faint);
    flex: none;
  }
  .cover.add {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .cover img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .name {
    flex: 1;
    font-weight: 560;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .new {
    display: flex;
    gap: 8px;
    margin-bottom: 10px;
  }
  .new input {
    flex: 1;
    min-width: 0;
    height: 40px;
    padding: 0 12px;
    border-radius: var(--r-md);
    border: 1px solid var(--line);
    background: var(--bg);
    font-size: 16px;
    outline: 0;
  }
  .new input:focus {
    border-color: var(--accent);
  }
</style>
