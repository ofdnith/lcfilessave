// Paged, reactive item list backed by GET /api/items with cursor pagination.
import { api, ApiError, type ItemQuery } from './api';
import type { Item } from './types';

export class ItemList {
  items = $state<Item[]>([]);
  total = $state(0);
  cursor = $state<string | null>(null);
  loading = $state(false);
  done = $state(false);
  error = $state<string | null>(null);
  /** `start` param in effect (AAAA-MM) when the user jumped with the scrubber. */
  start = $state<string | null>(null);

  #query: ItemQuery = {};
  #gen = 0;
  #pageSize: number;

  constructor(pageSize = 200) {
    this.#pageSize = pageSize;
  }

  /** Replace the query and load the first page. */
  async reset(query: ItemQuery, start: string | null = null): Promise<void> {
    this.#query = query;
    this.start = start;
    this.items = [];
    this.cursor = null;
    this.done = false;
    this.error = null;
    this.loading = false;
    this.#gen++;
    await this.more();
  }

  /** Reload with the current query and jump point (e.g. after an error or an action). */
  reload(): Promise<void> {
    return this.reset(this.#query, this.start);
  }

  async more(): Promise<void> {
    if (this.loading || this.done) return;
    const gen = this.#gen;
    this.loading = true;
    this.error = null;
    try {
      const page = await api.items({
        ...this.#query,
        start: this.cursor ? null : this.start,
        cursor: this.cursor,
        limit: this.#pageSize,
      });
      if (gen !== this.#gen) return;
      // Guard against overlap if the server returns an item twice across pages.
      const seen = new Set(this.items.map((i) => i.id));
      this.items.push(...page.items.filter((i) => !seen.has(i.id)));
      this.total = page.total;
      this.cursor = page.next_cursor;
      this.done = !page.next_cursor;
    } catch (e) {
      if (gen !== this.#gen) return;
      this.error = e instanceof ApiError ? e.message : 'Não foi possível carregar.';
    } finally {
      if (gen === this.#gen) this.loading = false;
    }
  }

  remove(ids: number[]): void {
    const set = new Set(ids);
    const before = this.items.length;
    this.items = this.items.filter((i) => !set.has(i.id));
    this.total = Math.max(0, this.total - (before - this.items.length));
  }

  patch(id: number, fields: Partial<Item>): void {
    const it = this.items.find((i) => i.id === id);
    if (it) Object.assign(it, fields);
  }
}
