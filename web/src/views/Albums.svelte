<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import { albums } from '../lib/albums.svelte';
  import { num } from '../lib/format';
  import { go, href } from '../lib/router.svelte';
  import { app } from '../lib/state.svelte';

  let creating = $state(false);
  let name = $state('');

  $effect(() => {
    void app.revision;
    void albums.load();
  });

  async function create(e: SubmitEvent) {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    const a = await albums.create(n);
    if (a) {
      name = '';
      creating = false;
      go('album', a.id);
    }
  }
</script>

<div class="page albums">
  <header class="head">
    <h1 class="page-title">Álbuns</h1>
    <button class="btn primary small" onclick={() => (creating = !creating)} aria-expanded={creating}>
      <Icon name="plus" size={16} /> Novo álbum
    </button>
  </header>
  <p class="page-sub">Junte fotos de vários meses e lugares. Um item pode estar em vários álbuns.</p>

  {#if creating}
    <form class="new panel" onsubmit={create}>
      <!-- svelte-ignore a11y_autofocus -->
      <input bind:value={name} placeholder="Nome do álbum, ex.: Viagem a Salvador" maxlength="120" autofocus aria-label="Nome do álbum" />
      <button class="btn primary" type="submit" disabled={!name.trim()}>Criar</button>
    </form>
  {/if}

  {#if albums.error}
    <p class="error-text">{albums.error} <button class="btn small" onclick={() => albums.load()}>Tentar de novo</button></p>
  {:else if albums.loaded && !albums.list.length}
    <div class="empty">
      <div class="mark"><Icon name="album" size={30} /></div>
      <p class="title">Nenhum álbum ainda</p>
      <p class="muted">Crie um aqui, ou selecione fotos no Acervo e toque em “Adicionar ao álbum”.</p>
    </div>
  {/if}

  <div class="grid">
    {#each albums.list as a (a.id)}
      <a class="album" href={href('album', a.id)}>
        <span class="cover">
          {#if a.cover && (a.cover.medium_url || a.cover.thumb_url)}
            <img src={a.cover.medium_url ?? a.cover.thumb_url} alt="" loading="lazy" />
          {:else}
            <Icon name="album" size={32} />
          {/if}
        </span>
        <span class="name">{a.name}</span>
        <span class="faint num">{num(a.count)} {a.count === 1 ? 'item' : 'itens'}</span>
      </a>
    {/each}
  </div>
</div>

<style>
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-top: var(--sat);
  }
  .new {
    display: flex;
    gap: 8px;
    margin-bottom: 18px;
    padding: 12px;
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
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 18px 14px;
  }
  .album {
    display: flex;
    flex-direction: column;
    gap: 2px;
    color: var(--text);
    text-decoration: none;
    font-size: 13px;
  }
  .cover {
    aspect-ratio: 1;
    border-radius: var(--r-lg);
    background: var(--surface);
    border: 1px solid var(--line-soft);
    overflow: hidden;
    display: grid;
    place-items: center;
    color: var(--faint);
    margin-bottom: 6px;
  }
  .cover img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.25s var(--ease);
  }
  .album:hover img {
    transform: scale(1.03);
  }
  .name {
    font-weight: 600;
    font-size: 14.5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .empty {
    text-align: center;
    padding: 48px 16px;
  }
  .mark {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: var(--surface);
    color: var(--faint);
    display: grid;
    place-items: center;
    margin: 0 auto 12px;
  }
  .title {
    font-weight: 600;
    font-size: 17px;
    margin: 0 0 4px;
  }
  @media (max-width: 899px) {
    .grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 14px 10px;
    }
  }
</style>
