// Global reactive app state (Svelte 5 runes in a module).
import type { KindFilter, Stats } from './types';

export type AuthPhase = 'checking' | 'login' | 'ok' | 'offline';

export interface Filters {
  year: number | null;
  important: boolean;
  archived: '0' | '1' | null;
}

export interface Toast {
  id: number;
  text: string;
  tone: 'info' | 'error' | 'ok';
  action?: { label: string; run: () => void };
}

export const app = $state({
  auth: 'checking' as AuthPhase,
  stats: null as Stats | null,
  kind: 'all' as KindFilter,
  q: '',
  filters: { year: null, important: false, archived: null } as Filters,
  toasts: [] as Toast[],
  /** Bumped whenever item lists must reload (after actions, uploads, …). */
  revision: 0,
  /** Focus request counter for the search input (⌘K). */
  searchFocus: 0,
  /** Away from home over Tailscale (from /api/auth/status). */
  remote: false,
  /** Safe mode: destructive actions are refused by the server; hide them. */
  readonly: false,
  /** Server is being migrated: everything that changes data answers 423. */
  migration: false,
});

let toastSeq = 0;
export function toast(text: string, tone: Toast['tone'] = 'info', action?: Toast['action'], ms = 5000): void {
  const id = ++toastSeq;
  app.toasts = [...app.toasts.slice(-3), { id, text, tone, action }];
  setTimeout(() => dismissToast(id), ms);
}
export function dismissToast(id: number): void {
  app.toasts = app.toasts.filter((t) => t.id !== id);
}

export function invalidate(): void {
  app.revision++;
}
