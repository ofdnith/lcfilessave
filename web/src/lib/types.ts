// Types mirroring docs/api.md. Keep in sync with the server contract.

export type Kind = 'photo' | 'video' | 'document' | 'audio' | 'other';
export type KindFilter = 'all' | Kind;
export type View = 'library' | 'inbox' | 'trash';
export type ItemState = 'inbox' | 'library' | 'trash' | 'archived';

export interface VolumeRef {
  id: string;
  name: string;
}

export interface Item {
  id: number;
  sha256: string;
  kind: Kind;
  mime: string;
  size_bytes: number;
  original_name: string;
  standard_name: string;
  captured_at: string | null;
  captured_tz: string | null;
  date_uncertain: boolean;
  uploaded_at: string;
  source: string;
  state: ItemState;
  important: boolean;
  volume: VolumeRef | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  gps: { lat: number; lon: number } | null;
  place: string | null;
  camera: string | null;
  is_live_photo: boolean;
  is_screenshot: boolean;
  origin_app: string | null;
  on_server: boolean;
  thumb_url: string | null;
  preview_url: string | null;
  original_url: string | null;
  live_video_url: string | null;
  trashed_at: string | null;
  trash_expires_at: string | null;
}

export interface ItemFile {
  id: number;
  role: string;
  size_bytes: number;
  mime: string;
  on_server: boolean;
  volumes: string[];
  /** Not in docs/api.md yet; requested so the Mac app can open the original on a drive. */
  rel_path?: string;
}

export interface ItemDetail extends Item {
  files: ItemFile[];
  suggestions: { id: number; kind: SuggestionKind }[];
}

export interface ItemsPage {
  items: Item[];
  next_cursor: string | null;
  total: number;
}

export interface TimelineMonth {
  year: number;
  month: number;
  count: number;
}

export interface TabStat {
  count: number;
  bytes: number;
}
export type Tabs = Record<KindFilter, TabStat>;

export interface Stats {
  inbox_count: number;
  trash_count: number;
  archived_count: number;
  suggestions_open: number;
  tabs: Tabs;
  inbox_tabs: Tabs;
  storage: {
    server_bytes: number;
    budget_bytes: number;
    disk_total_bytes: number;
    disk_free_bytes: number;
    used_pct: number;
    alert: boolean;
    weeks_to_next_drive: number | null;
  };
  daily_backup: { last_at: string | null; overdue: boolean };
}

export type Action = 'keep' | 'discard' | 'restore' | 'important' | 'unimportant';

export interface ActionResult {
  ok: number[];
  failed: { id: number; error: string }[];
}

export type SuggestionKind = 'near-duplicate' | 'screenshot' | 'burst' | 'whatsapp' | 'large-video';

export interface Suggestion {
  id: number;
  kind: SuggestionKind;
  created_at: string;
  items: Item[];
}

export type Source = 'iphone-daily' | 'iphone-manual' | 'iphone-empty' | 'mac' | 'web' | 'webdav';

export interface Session {
  id: number;
  source: Source;
  status: string;
  expected_count: number | null;
  received_verified_count: number;
  new_count: number;
  existing_count: number;
  near_dup_count: number;
  failed_count: number;
  summary_text: string;
  safe_to_delete: boolean;
  /** files the owner had discarded before (counted, but shown apart) */
  discarded_count?: number;
}

export interface PrecheckEntry {
  key: string;
  name?: string;
  created_at?: string;
  size?: number;
  sha256?: string;
}

export interface PrecheckResult {
  key: string;
  known: boolean;
  by: 'hash' | 'fingerprint' | null;
  state: string | null;
  item_id: number | null;
  verified: boolean;
}

export type UploadStatus =
  | 'receiving'
  | 'new'
  | 'duplicate'
  | 'in_trash'
  | 'discarded'
  | 'attached'
  | 'restored'
  | 'processing'
  | 'failed';

export interface UploadResult {
  status: UploadStatus;
  item_id: number | null;
  message: string;
}

export interface Volume {
  id: string;
  name: string;
  capacity_bytes: number;
  used_bytes: number;
  status: string;
  created_at: string;
  last_seen_at: string | null;
  item_count: number;
  last_full_check_at: string | null;
  last_check: {
    kind: 'partial' | 'full';
    finished_at: string;
    files_checked: number;
    problems: number;
  } | null;
}

export interface PlanFile {
  file_id: number;
  item_id: number;
  sha256: string;
  size_bytes: number;
  rel_path: string;
  url: string;
}

export interface SampleFile {
  file_id: number;
  rel_path: string;
  sha256: string;
}

export interface Settings {
  archive_batch_gb: number;
  trash_days: number;
  archive_copies: number;
  server_name: string;
  version: string;
}

export interface Health {
  status: 'ok' | 'degraded';
  version: string;
  time: string;
  catalog: { ok: boolean; schema_version: number | null; expected_version: number };
  storage: {
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    used_pct: number;
    alert_pct: number;
    alert: boolean;
  };
  problems: string[];
}

export interface AuthStatus {
  password_set: boolean;
  authenticated: boolean;
  method: 'cookie' | 'token' | 'local' | null;
}
