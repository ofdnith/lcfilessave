// Thin fetch wrapper around the Acervo HTTP API (docs/api.md).
import { app } from './state.svelte';
import type {
  Action,
  Album,
  ApiToken,
  InboxSummary,
  MemoryYear,
  Place,
  PushTopic,
  ActionResult,
  AuthStatus,
  Health,
  ItemDetail,
  ItemsPage,
  KindFilter,
  PlanFile,
  PrecheckEntry,
  PrecheckResult,
  SampleFile,
  Session,
  Settings,
  Source,
  Stats,
  Suggestion,
  TimelineMonth,
  UploadResult,
  View,
  Volume,
} from './types';

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function messageFor(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>;
    if (typeof b.error === 'string') return b.error;
    if (typeof b.detail === 'string') return b.detail;
  }
  if (status === 0) return 'Sem conexão com o servidor.';
  if (status === 401) return 'Sessão expirada. Entre de novo.';
  if (status === 404) return 'Não encontrado.';
  if (status === 403) return 'Não permitido fora de casa (modo seguro).';
  if (status === 423) return 'Migração em andamento: o Acervo está só para consulta.';
  if (status === 429) return 'Muitas tentativas. Espere um pouco.';
  if (status >= 500) return 'O servidor teve um problema. Tente de novo.';
  return `Erro ${status}.`;
}

async function request<T>(method: string, path: string, body?: unknown, opts: { auth401?: boolean } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, messageFor(0, null), null);
  }
  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    if (res.status === 401 && opts.auth401 !== false) app.auth = 'login';
    if (res.status === 423) app.migration = true;
    // A safe-mode refusal means we're away from home even if status said otherwise.
    if (res.status === 403 && path !== '/api/auth/app-token') app.readonly = true;
    throw new ApiError(res.status, messageFor(res.status, data), data);
  }
  return data as T;
}

const get = <T>(path: string) => request<T>('GET', path);
const del = <T>(path: string) => request<T>('DELETE', path);
const patch = <T>(path: string, body: unknown) => request<T>('PATCH', path, body);
const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, body);

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '' || v === false) continue;
    sp.set(k, v === true ? '1' : String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export interface ItemQuery {
  view?: View;
  kind?: KindFilter;
  q?: string;
  year?: number | null;
  month?: number | null;
  start?: string | null;
  important?: boolean;
  archived?: '0' | '1' | null;
  place?: string | null;
  album_id?: number | null;
  cursor?: string | null;
  limit?: number;
}

export const api = {
  authStatus: () => request<AuthStatus>('GET', '/api/auth/status', undefined, { auth401: false }),
  login: (password: string) =>
    request<{ token: string }>('POST', '/api/auth/login', { password, client: 'web' }, { auth401: false }),
  logout: () => post<{ ok: boolean }>('/api/auth/logout'),
  appToken: () => post<{ token: string }>('/api/auth/app-token'),

  items: (q: ItemQuery) => get<ItemsPage>(`/api/items${qs({ ...q })}`),
  timeline: (q: ItemQuery) =>
    get<{ months: TimelineMonth[] }>(
      `/api/timeline${qs({ view: q.view, kind: q.kind, q: q.q, important: q.important, archived: q.archived, place: q.place, album_id: q.album_id })}`,
    ),
  item: (id: number) => get<ItemDetail>(`/api/items/${id}`),
  itemsByIds: (ids: number[]) => get<ItemsPage>(`/api/items?ids=${ids.join(',')}&limit=500`),
  stats: () => get<Stats>('/api/stats'),
  actions: (ids: number[], action: Action) => post<ActionResult>('/api/items/actions', { ids, action }),

  suggestions: () => get<{ suggestions: Suggestion[] }>('/api/suggestions?status=open'),
  dismissSuggestion: (id: number) => post<{ ok: boolean }>(`/api/suggestions/${id}/dismiss`),

  createSession: (source: Source, expected_count?: number) =>
    post<Session>('/api/sessions', { source, expected_count, client_label: navigator.userAgent.slice(0, 80) }),
  session: (id: number) => get<Session>(`/api/sessions/${id}`),
  finishSession: (id: number) => post<Session>(`/api/sessions/${id}/finish`),
  precheck: (entries: PrecheckEntry[], session_id?: number) =>
    post<{ results: PrecheckResult[] }>('/api/precheck', { session_id, entries }),
  uploadResult: (id: string) => get<UploadResult>(`/api/uploads/${encodeURIComponent(id)}/result`),

  volumes: () => get<{ volumes: Volume[]; archive_copies: number }>('/api/volumes'),
  createVolume: (capacity_bytes: number, filesystem: string) => post<Volume>('/api/volumes', { capacity_bytes, filesystem }),
  volumeSeen: (id: string, used_bytes?: number) => post<Volume>(`/api/volumes/${id}/seen`, { used_bytes }),
  archivePlan: (volume_id: string, max_bytes?: number) =>
    get<{ files: PlanFile[]; total_bytes: number }>(`/api/archive/plan${qs({ volume_id, max_bytes })}`),
  archiveVerified: (volume_id: string, copies: { file_id: number; rel_path: string; sha256: string }[]) =>
    post<{ accepted: number[]; rejected: { file_id: number; error: string }[] }>('/api/archive/verified', {
      volume_id,
      copies,
    }),
  archiveCommit: (volume_id: string) =>
    post<{ archived_items: number; freed_bytes: number }>('/api/archive/commit', { volume_id }),
  volumeBundle: (id: string) => get<{ files: { path: string; url: string }[] }>(`/api/volumes/${id}/bundle`),
  volumeSample: (id: string, n: number, full: boolean) =>
    get<{ files: SampleFile[] }>(`/api/volumes/${id}/sample${qs({ n, full: full ? 1 : 0 })}`),
  volumeCheck: (id: string, body: { kind: 'partial' | 'full'; files_checked: number; problems: { file_id: number; error: string }[] }) =>
    post<Volume>(`/api/volumes/${id}/checks`, body),

  settings: () => get<Settings>('/api/settings'),

  // v0.2
  inboxSummary: () => get<InboxSummary>('/api/inbox/summary'),
  keepClean: () => post<{ kept: number; flagged_left: number }>('/api/inbox/keep-clean'),
  memories: (date?: string) => get<{ date: string; years: MemoryYear[] }>(`/api/memories${qs({ date })}`),
  places: () => get<{ places: Place[] }>('/api/places'),
  mapPoints: () => get<{ points: [number, number, number][] }>('/api/map/points'),
  albums: () => get<{ albums: Album[] }>('/api/albums'),
  createAlbum: (name: string) => post<Album>('/api/albums', { name }),
  updateAlbum: (id: number, body: { name?: string; cover_item_id?: number }) => patch<Album>(`/api/albums/${id}`, body),
  deleteAlbum: (id: number) => del<{ ok: boolean }>(`/api/albums/${id}`),
  albumAdd: (id: number, ids: number[]) => post<{ added: number }>(`/api/albums/${id}/items`, { ids }),
  albumRemove: (id: number, ids: number[]) => post<{ removed: number }>(`/api/albums/${id}/items/remove`, { ids }),
  tokens: () => get<{ tokens: ApiToken[] }>('/api/tokens'),
  createToken: (label: string) => post<{ id: number; token: string }>('/api/tokens', { label }),
  revokeToken: (id: number) => del<{ ok: boolean }>(`/api/tokens/${id}`),
  shortcuts: () => get<{ links: { manual: string | null; daily: string | null } }>('/api/shortcuts'),
  pushKey: () => get<{ public_key: string }>('/api/push/key'),
  pushSubscribe: (subscription: PushSubscriptionJSON, topics: PushTopic[]) =>
    post<{ ok: boolean }>('/api/push/subscribe', { subscription, topics }),
  pushUnsubscribe: (endpoint: string) => post<{ ok: boolean }>('/api/push/unsubscribe', { endpoint }),
  pushStatus: (endpoint: string) => get<{ subscribed: boolean; topics: PushTopic[] }>(`/api/push/status${qs({ endpoint })}`),
  pushTest: (endpoint: string) => post<{ ok: boolean }>('/api/push/test', { endpoint }),
  health: async (): Promise<Health> => {
    // /api/health answers 503 with a full body when degraded; we still want the body.
    const res = await fetch('/api/health', { credentials: 'same-origin' });
    return (await res.json()) as Health;
  },
};
