// Album list cache shared by the Álbuns screen and the "Adicionar ao álbum" sheet.
import { api, ApiError } from './api';
import { plural } from './format';
import { toast } from './state.svelte';
import type { Album } from './types';

class Albums {
  list = $state<Album[]>([]);
  loaded = $state(false);
  error = $state<string | null>(null);

  async load(): Promise<void> {
    try {
      this.list = (await api.albums()).albums;
      this.error = null;
    } catch (e) {
      this.error = e instanceof ApiError ? e.message : 'Não foi possível carregar os álbuns.';
    } finally {
      this.loaded = true;
    }
  }

  async create(name: string): Promise<Album | null> {
    try {
      const a = await api.createAlbum(name);
      this.list = [a, ...this.list];
      return a;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível criar o álbum.', 'error');
      return null;
    }
  }

  async add(album: Album, ids: number[]): Promise<boolean> {
    try {
      const r = await api.albumAdd(album.id, ids);
      toast(
        r.added ? `${plural(r.added, 'item adicionado', 'itens adicionados')} a “${album.name}”` : `Já estavam em “${album.name}”`,
        'ok',
      );
      void this.load();
      return true;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível adicionar.', 'error');
      return false;
    }
  }
}

export const albums = new Albums();
