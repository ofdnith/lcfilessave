<script lang="ts">
  import { untrack } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import Icon from '../components/Icon.svelte';
  import ItemBrowser from '../components/ItemBrowser.svelte';
  import SelectionBar from '../components/SelectionBar.svelte';
  import { api, ApiError } from '../lib/api';
  import { albums } from '../lib/albums.svelte';
  import { plural } from '../lib/format';
  import { ItemList } from '../lib/itemlist.svelte';
  import { go, href } from '../lib/router.svelte';
  import { confirmSheet } from '../lib/sheets.svelte';
  import { app, toast } from '../lib/state.svelte';
  import { openViewer } from '../lib/viewer.svelte';
  import type { Album } from '../lib/types';

  let { id }: { id: number } = $props();

  const list = new ItemList(200);
  const selection = new SvelteSet<number>();
  let selecting = $state(false);
  let renaming = $state(false);
  let newName = $state('');

  const album = $derived<Album | undefined>(albums.list.find((a) => a.id === id));

  $effect(() => {
    void app.revision;
    untrack(() => {
      if (!albums.loaded) void albums.load();
      // Albums mix every state; view=library covers Acervo + archived, which is where album items live.
      void list.reset({ view: 'library', kind: 'all', album_id: id });
    });
  });

  function stopSelecting() {
    selecting = false;
    selection.clear();
  }

  async function removeSelected() {
    const ids = [...selection];
    if (!ids.length) return;
    try {
      const r = await api.albumRemove(id, ids);
      list.remove(ids);
      toast(`${plural(r.removed, 'item removido', 'itens removidos')} do álbum`, 'ok');
      void albums.load();
      stopSelecting();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível remover.', 'error');
    }
  }

  async function rename(e: SubmitEvent) {
    e.preventDefault();
    const n = newName.trim();
    if (!n) return;
    try {
      await api.updateAlbum(id, { name: n });
      renaming = false;
      await albums.load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Não foi possível renomear.', 'error');
    }
  }

  async function remove() {
    const ok = await confirmSheet({
      title: `Apagar o álbum “${album?.name ?? ''}”?`,
      body: 'As fotos não são apagadas: continuam no Acervo e em outros álbuns.',
      confirm: 'Apagar álbum',
      tone: 'danger',
    });
    if (!ok) return;
    try {
      await api.deleteAlbum(id);
      toast('Álbum apagado. As fotos continuam no Acervo.', 'ok');
      await albums.load();
      go('albuns');
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível apagar.', 'error');
    }
  }

  async function setCover() {
    const [first] = selection;
    if (first === undefined) return;
    try {
      await api.updateAlbum(id, { cover_item_id: first });
      toast('Capa do álbum trocada', 'ok');
      void albums.load();
      stopSelecting();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível trocar a capa.', 'error');
    }
  }
</script>

<div class="page album-page">
  <a class="back" href={href('albuns')}><Icon name="left" size={16} /> Álbuns</a>
  {#if renaming}
    <form class="rename" onsubmit={rename}>
      <!-- svelte-ignore a11y_autofocus -->
      <input bind:value={newName} maxlength="120" autofocus aria-label="Novo nome" />
      <button class="btn primary small" type="submit" disabled={!newName.trim()}>Salvar</button>
      <button class="btn ghost small" type="button" onclick={() => (renaming = false)}>Cancelar</button>
    </form>
  {:else}
    <header class="head">
      <div>
        <h1 class="page-title">{album?.name ?? 'Álbum'}</h1>
        <p class="muted num sub">{plural(list.total, 'item', 'itens')}</p>
      </div>
      <div class="acts">
        <button class="btn small" onclick={() => (selecting ? stopSelecting() : (selecting = true))} disabled={!list.items.length}>
          <Icon name="select" size={15} /> {selecting ? 'Cancelar' : 'Selecionar'}
        </button>
        <button class="icon-btn" title="Renomear" aria-label="Renomear álbum" onclick={() => ((newName = album?.name ?? ''), (renaming = true))}>
          <Icon name="edit" size={19} />
        </button>
        <button class="icon-btn" title="Apagar álbum" aria-label="Apagar álbum" onclick={remove}>
          <Icon name="trash" size={19} />
        </button>
      </div>
    </header>
  {/if}

  <ItemBrowser
    {list}
    layout="grid"
    {selection}
    {selecting}
    onselectstart={() => (selecting = true)}
    onopen={(i) => openViewer(list, i, 'library')}
    empty="Álbum vazio"
    emptyHint="No Acervo, selecione fotos e toque em “Adicionar ao álbum”."
  />
</div>

{#if selecting}
  <SelectionBar count={selection.size} onclear={stopSelecting}>
    <button class="btn small" disabled={selection.size !== 1} onclick={setCover} title="Usar como capa">Usar como capa</button>
    <button class="btn small danger" disabled={!selection.size} onclick={removeSelected}>Remover do álbum</button>
  </SelectionBar>
{/if}

<style>
  .back {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--muted);
    text-decoration: none;
    font-size: 14px;
    margin: var(--sat) 0 6px;
  }
  .head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 8px;
  }
  .sub {
    margin: 0;
    font-size: 13.5px;
  }
  .acts {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .rename {
    display: flex;
    gap: 8px;
    align-items: center;
    margin: 4px 0 12px;
  }
  .rename input {
    flex: 1;
    min-width: 0;
    max-width: 420px;
    height: 40px;
    padding: 0 12px;
    border-radius: var(--r-md);
    border: 1px solid var(--accent);
    background: var(--surface);
    font-size: 18px;
    font-weight: 600;
    outline: 0;
  }
</style>
