// Typed wrapper over the Mac app's native commands (Tauri 2, injected as window.__TAURI__).
// The Rust side is implemented separately; names and argument shapes must match exactly.
import { api } from './api';
import type { UploadResult } from './types';

interface TauriGlobal {
  core: { invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> };
  event: {
    listen<T>(event: string, handler: (e: { payload: T }) => void): Promise<() => void>;
  };
}

declare global {
  interface Window {
    __TAURI__?: TauriGlobal;
  }
}

export const isNative = (): boolean => typeof window !== 'undefined' && !!window.__TAURI__;

function tauri(): TauriGlobal {
  if (!window.__TAURI__) throw new Error('Disponível só no app do Mac.');
  return window.__TAURI__;
}

function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  return tauri()
    .core.invoke<T>(cmd, args)
    .catch((e: unknown) => {
      throw new Error(typeof e === 'string' ? e : e instanceof Error ? e.message : String(e));
    });
}

export interface VolumeJson {
  id: string;
  name: string;
  created_at: string;
}

export interface Disk {
  mount_path: string;
  label: string;
  filesystem: string;
  total_bytes: number;
  free_bytes: number;
  volume: VolumeJson | null;
}

export interface ScannedFile {
  path: string;
  name: string;
  size: number;
  modified_ms: number;
}

export interface CopyProgress {
  rel_path: string;
  bytes_done: number;
  bytes_total: number;
}

const serverUrl = (): string => window.location.origin;

let tokenPromise: Promise<string> | null = null;
/** Bearer token for native commands that talk to the server themselves. Fetched once, kept in memory. */
export function appToken(): Promise<string> {
  if (!tokenPromise) {
    tokenPromise = api
      .appToken()
      .then((r) => r.token)
      .catch((e) => {
        tokenPromise = null;
        throw e;
      });
  }
  return tokenPromise;
}

export const native = {
  listDisks: () => invoke<Disk[]>('list_disks'),
  initVolume: (mountPath: string, id: string, name: string, createdAt: string) =>
    invoke<VolumeJson>('init_volume', { mountPath, id, name, createdAt }),
  copyToVolume: async (mountPath: string, url: string, relPath: string, sha256: string, sizeBytes: number) =>
    invoke<{ sha256: string }>('copy_to_volume', {
      serverUrl: serverUrl(),
      token: await appToken(),
      mountPath,
      url,
      relPath,
      sha256,
      sizeBytes,
    }),
  writeBundleFile: async (mountPath: string, path: string, url: string) =>
    invoke<null>('write_bundle_file', { serverUrl: serverUrl(), token: await appToken(), mountPath, path, url }),
  verifyVolumeFiles: (mountPath: string, files: { file_id: number; rel_path: string; sha256: string }[]) =>
    invoke<{ file_id: number; ok: boolean; error: string | null }[]>('verify_volume_files', { mountPath, files }),
  openOnVolume: (mountPath: string, relPath: string) => invoke<null>('open_on_volume', { mountPath, relPath }),
  pickFolder: () => invoke<string | null>('pick_folder'),
  scanFolder: (path: string) => invoke<ScannedFile[]>('scan_folder', { path }),
  hashFile: (path: string) => invoke<string>('hash_file', { path }),
  /** `clientKey` (the file path) must be forwarded by Rust as the `client_key` param of POST /api/upload. */
  uploadFile: async (path: string, source: string, sessionId: number, sha256: string, createdMs: number, clientKey: string = path) =>
    invoke<UploadResult>('upload_file', {
      serverUrl: serverUrl(),
      token: await appToken(),
      path,
      source,
      sessionId,
      sha256,
      createdMs,
      clientKey,
    }),
  onCopyProgress: (handler: (p: CopyProgress) => void) =>
    tauri().event.listen<CopyProgress>('copy-progress', (e) => handler(e.payload)),
};

/** Mount path of a plugged drive holding the given volume, or null. */
export async function findMountedVolume(volumeId: string): Promise<string | null> {
  try {
    const disks = await native.listDisks();
    return disks.find((d) => d.volume?.id === volumeId)?.mount_path ?? null;
  } catch {
    return null;
  }
}

const kindFolder: Record<string, string> = {
  photo: 'fotos',
  video: 'videos',
  document: 'docs',
  audio: 'audios',
  other: 'outros',
};

/** Fallback path on a drive (AAAA/MM/tipo/nome-padrão) when the server does not send rel_path. */
export function guessRelPath(item: { captured_at: string | null; uploaded_at: string; kind: string; standard_name: string }): string {
  const d = (item.captured_at ?? item.uploaded_at ?? '').slice(0, 7).split('-');
  return `${d[0]}/${d[1]}/${kindFolder[item.kind] ?? 'outros'}/${item.standard_name}`;
}
