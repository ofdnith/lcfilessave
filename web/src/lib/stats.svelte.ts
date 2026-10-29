import { api } from './api';
import { app } from './state.svelte';

let pending: Promise<void> | null = null;

export function refreshStats(): Promise<void> {
  if (pending) return pending;
  pending = api
    .stats()
    .then((s) => {
      app.stats = s;
    })
    .catch(() => {
      /* stats are decorative; keep the last known value */
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}
