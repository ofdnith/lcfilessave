// Mac app only: "Esvaziar iPhone" — send a folder imported via Image Capture and confirm,
// by SHA-256, that every file reached the server before the user deletes anything from the phone.
import { api, ApiError } from './api';
import { native, type ScannedFile } from './native';
import { invalidate } from './state.svelte';
import { refreshStats } from './stats.svelte';
import type { Session } from './types';

const PRECHECK_BATCH = 200;
const UPLOAD_PARALLEL = 2;

export interface EmptyFile extends ScannedFile {
  sha256: string | null;
  status: 'pending' | 'hashing' | 'known' | 'uploading' | 'done' | 'failed';
  error: string | null;
}

class EmptyIphone {
  folder = $state<string | null>(null);
  files = $state<EmptyFile[]>([]);
  phase = $state<'idle' | 'scanning' | 'hashing' | 'checking' | 'uploading' | 'verifying' | 'done' | 'failed'>('idle');
  session = $state<Session | null>(null);
  error = $state<string | null>(null);

  get counts() {
    let hashed = 0;
    let known = 0;
    let uploaded = 0;
    let failed = 0;
    for (const f of this.files) {
      if (f.sha256) hashed++;
      if (f.status === 'known') known++;
      if (f.status === 'done') uploaded++;
      if (f.status === 'failed') failed++;
    }
    return { hashed, known, uploaded, failed, total: this.files.length };
  }

  get busy(): boolean {
    return ['scanning', 'hashing', 'checking', 'uploading', 'verifying'].includes(this.phase);
  }

  reset(): void {
    if (this.busy) return;
    this.folder = null;
    this.files = [];
    this.phase = 'idle';
    this.session = null;
    this.error = null;
  }

  async choose(): Promise<void> {
    if (this.busy) return;
    const folder = await native.pickFolder();
    if (!folder) return;
    this.reset();
    this.folder = folder;
    await this.run();
  }

  /** Run (or re-run) the whole flow for the chosen folder. Safe to repeat: known files are skipped by hash. */
  async run(): Promise<void> {
    if (!this.folder || this.busy) return;
    this.error = null;
    try {
      this.phase = 'scanning';
      const scanned = await native.scanFolder(this.folder);
      const isVideo = (n: string) => /\.(mov|mp4|m4v|3gp|avi)$/i.test(n);
      scanned.sort((a, b) => Number(isVideo(a.name)) - Number(isVideo(b.name)));
      this.files = scanned.map((f) => ({ ...f, sha256: null, status: 'pending', error: null }));
      if (!this.files.length) throw new Error('A pasta está vazia.');

      this.session = await api.createSession('iphone-empty', this.files.length);
      const sid = this.session.id;

      this.phase = 'hashing';
      for (const f of this.files) {
        f.status = 'hashing';
        try {
          f.sha256 = await native.hashFile(f.path);
          f.status = 'pending';
        } catch (e) {
          f.status = 'failed';
          f.error = (e as Error).message;
        }
      }

      this.phase = 'checking';
      const hashed = this.files.filter((f) => f.sha256);
      for (let i = 0; i < hashed.length; i += PRECHECK_BATCH) {
        const slice = hashed.slice(i, i + PRECHECK_BATCH);
        // key = client_key = the file path, so each file counts exactly once in the session.
        const r = await api.precheck(
          slice.map((f) => ({ key: f.path, sha256: f.sha256!, name: f.name, size: f.size })),
          sid,
        );
        const byPath = new Map(slice.map((f) => [f.path, f]));
        for (const res of r.results) {
          const f = byPath.get(res.key);
          if (f && res.known && res.verified) f.status = 'known';
        }
      }

      this.phase = 'uploading';
      const todo = this.files.filter((f) => f.status === 'pending' && f.sha256);
      let next = 0;
      await Promise.all(
        Array.from({ length: Math.min(UPLOAD_PARALLEL, todo.length) }, async () => {
          while (next < todo.length) {
            const f = todo[next++];
            f.status = 'uploading';
            try {
              const r = await native.uploadFile(f.path, 'iphone-empty', sid, f.sha256!, f.modified_ms, f.path);
              if (r.status === 'failed') {
                f.status = 'failed';
                f.error = r.message || 'falhou';
              } else f.status = 'done';
            } catch (e) {
              f.status = 'failed';
              f.error = (e as Error).message;
            }
          }
        }),
      );

      this.phase = 'verifying';
      await api.finishSession(sid);
      this.session = await api.session(sid);
      this.phase = 'done';
      invalidate();
      void refreshStats();
    } catch (e) {
      this.phase = 'failed';
      this.error = e instanceof ApiError ? e.message : (e as Error).message;
    }
  }
}

export const emptyIphone = new EmptyIphone();
