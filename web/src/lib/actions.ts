// Batch item actions with Portuguese feedback.
import { api, ApiError } from './api';
import { invalidate, toast } from './state.svelte';
import { refreshStats } from './stats.svelte';
import { plural } from './format';
import type { Action, ActionResult } from './types';

const done: Record<Action, [string, string]> = {
  keep: ['item mantido', 'itens mantidos'],
  discard: ['item na lixeira', 'itens na lixeira'],
  restore: ['item restaurado', 'itens restaurados'],
  important: ['item marcado como importante', 'itens marcados como importantes'],
  unimportant: ['item desmarcado', 'itens desmarcados'],
};

export async function runAction(
  ids: number[],
  action: Action,
  opts: { quiet?: boolean; undo?: () => void; reload?: boolean } = {},
): Promise<ActionResult | null> {
  if (!ids.length) return null;
  try {
    const res = await api.actions(ids, action);
    if (!opts.quiet) {
      const [one, many] = done[action];
      if (res.ok.length) {
        toast(
          `${plural(res.ok.length, one, many)}`,
          'ok',
          opts.undo ? { label: 'Desfazer', run: opts.undo } : undefined,
        );
      }
      if (res.failed.length) {
        toast(`${plural(res.failed.length, 'item falhou', 'itens falharam')}: ${res.failed[0].error}`, 'error');
      }
    }
    void refreshStats();
    if (opts.reload) invalidate();
    return res;
  } catch (e) {
    toast(e instanceof ApiError ? e.message : 'Ação não concluída.', 'error');
    return null;
  }
}
