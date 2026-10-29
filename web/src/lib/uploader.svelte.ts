// Upload pipeline for the browser: session → hash → precheck → tus upload → result → finish.
// Lives at module level so it keeps running while the user navigates between screens.
import * as tus from 'tus-js-client';
import { api, ApiError } from './api';
import { sha256File, pool } from './hash';
import { invalidate, toast } from './state.svelte';
import { refreshStats } from './stats.svelte';
import type { PrecheckResult, Session, UploadStatus } from './types';

export type JobStatus =
  | 'queued'
  | 'hashing'
  | 'checking'
  | 'waiting'
  | 'uploading'
  | 'processing'
  | 'done'
  | 'skipped'
  | 'failed';

export interface Job {
  /** client_key: stable per-file id (name|size|lastModified); also the precheck `key`. */
  key: string;
  file: File;
  name: string;
  size: number;
  isVideo: boolean;
  status: JobStatus;
  /** Bytes hashed or uploaded, depending on phase. */
  progress: number;
  sha256: string | null;
  result: UploadStatus | 'known' | 'purged' | null;
  itemId: number | null;
  message: string;
  restored: boolean;
}

export interface Batch {
  id: number;
  jobs: Job[];
  session: Session | null;
  phase: 'preparing' | 'hashing' | 'checking' | 'uploading' | 'finishing' | 'done' | 'failed';
  error: string | null;
  startedAt: number;
}

const CHUNK_SIZE = 8 * 1024 * 1024;
const PARALLEL_UPLOADS = 3;
const PARALLEL_HASH = 2;
const PRECHECK_BATCH = 200;

/** cancelAll() may flip a batch to "failed" while an await is pending. */
function stopped(b: Batch): boolean {
  return b.phase === 'failed';
}

export function clientKey(f: File): string {
  return `${f.name}|${f.size}|${f.lastModified}`;
}

function isVideoFile(f: File): boolean {
  return f.type.startsWith('video/') || /\.(mov|mp4|m4v|avi|mkv|3gp|webm)$/i.test(f.name);
}

class Uploader {
  batches = $state<Batch[]>([]);
  running = $state(false);
  speed = $state(0); // bytes/s, smoothed

  #seq = 0;
  #lastBytes = 0;
  #lastT = 0;
  #timer: ReturnType<typeof setInterval> | null = null;
  #active = new Set<tus.Upload>();

  get current(): Batch | null {
    return this.batches.find((b) => b.phase !== 'done' && b.phase !== 'failed') ?? null;
  }

  /** Bytes that still need sending in the running batch, and bytes sent so far. */
  totals(b: Batch): { total: number; sent: number; files: number; finished: number } {
    let total = 0;
    let sent = 0;
    let finished = 0;
    for (const j of b.jobs) {
      if (j.status === 'skipped') {
        finished++;
        continue;
      }
      if (j.status === 'done' || j.status === 'failed') finished++;
      if (j.result === 'known' || j.result === 'purged') continue;
      total += j.size;
      sent += j.status === 'uploading' || j.status === 'processing' || j.status === 'done' ? j.progress : 0;
    }
    return { total, sent, files: b.jobs.length, finished };
  }

  add(files: FileList | File[]): void {
    // One job per client_key: the same file dropped twice counts once.
    const byKey = new Map<string, File>();
    for (const f of Array.from(files)) byKey.set(clientKey(f), f);
    if (!byKey.size) return;
    const id = ++this.#seq;
    const jobs: Job[] = [...byKey].map(([key, file]) => ({
      key,
      file,
      name: file.name,
      size: file.size,
      isVideo: isVideoFile(file),
      status: 'queued',
      progress: 0,
      sha256: null,
      result: null,
      itemId: null,
      message: '',
      restored: false,
    }));
    // Photos before videos so a Live Photo's video finds its photo.
    jobs.sort((a, b) => Number(a.isVideo) - Number(b.isVideo));
    this.batches.push({ id, jobs, session: null, phase: 'preparing', error: null, startedAt: Date.now() });
    if (!this.running) void this.#loop();
  }

  clearFinished(): void {
    this.batches = this.batches.filter((b) => b.phase !== 'done' && b.phase !== 'failed');
  }

  cancelAll(): void {
    for (const u of this.#active) void u.abort(false);
    for (const b of this.batches) {
      if (b.phase === 'done' || b.phase === 'failed') continue;
      b.phase = 'failed';
      b.error = 'Envio cancelado. Adicione os arquivos de novo para continuar de onde parou.';
      for (const j of b.jobs) if (j.status !== 'done' && j.status !== 'skipped') j.status = 'failed';
    }
  }

  async restore(job: Job): Promise<void> {
    if (!job.itemId) return;
    try {
      const r = await api.actions([job.itemId], 'restore');
      if (r.ok.length) {
        job.restored = true;
        job.message = 'Restaurado da lixeira';
        toast('Item restaurado da lixeira', 'ok');
        invalidate();
        void refreshStats();
      } else toast(r.failed[0]?.error ?? 'Não foi possível restaurar.', 'error');
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Não foi possível restaurar.', 'error');
    }
  }

  async #loop(): Promise<void> {
    this.running = true;
    this.#startMeter();
    try {
      let b: Batch | null;
      while ((b = this.batches.find((x) => x.phase === 'preparing') ?? null)) {
        await this.#run(b);
      }
    } finally {
      this.running = false;
      this.#stopMeter();
    }
  }

  async #run(b: Batch): Promise<void> {
    try {
      b.session = await api.createSession('web', b.jobs.length);

      b.phase = 'hashing';
      await pool(b.jobs, PARALLEL_HASH, async (j) => {
        if (stopped(b)) return;
        j.status = 'hashing';
        j.progress = 0;
        try {
          j.sha256 = await sha256File(j.file, (d) => (j.progress = d));
          j.status = 'checking';
        } catch {
          j.status = 'failed';
          j.message = 'Não foi possível ler o arquivo';
        }
      });
      if (stopped(b)) return;

      b.phase = 'checking';
      const toCheck = b.jobs.filter((j) => j.sha256);
      for (let i = 0; i < toCheck.length; i += PRECHECK_BATCH) {
        const slice = toCheck.slice(i, i + PRECHECK_BATCH);
        const res = await api.precheck(
          slice.map((j) => ({
            key: j.key,
            name: j.name,
            created_at: new Date(j.file.lastModified || Date.now()).toISOString(),
            size: j.size,
            sha256: j.sha256!,
          })),
          b.session.id,
        );
        const byKey = new Map<string, PrecheckResult>(res.results.map((r) => [r.key, r]));
        for (const j of slice) this.#applyPrecheck(j, byKey.get(j.key));
      }
      if (stopped(b)) return;

      b.phase = 'uploading';
      const pending = b.jobs.filter((j) => j.status === 'waiting');
      await pool(pending, PARALLEL_UPLOADS, (j) => (stopped(b) ? Promise.resolve() : this.#upload(b, j)));
      if (stopped(b)) return;

      b.phase = 'finishing';
      b.session = await api.finishSession(b.session.id);
      b.phase = 'done';
      invalidate();
      void refreshStats();
    } catch (e) {
      if (!stopped(b)) {
        b.phase = 'failed';
        b.error = e instanceof ApiError ? e.message : 'O envio parou. Adicione os arquivos de novo para continuar.';
      }
    }
  }

  #applyPrecheck(j: Job, r: PrecheckResult | undefined): void {
    if (!r || !r.known) {
      j.status = 'waiting';
      j.progress = 0;
      return;
    }
    j.itemId = r.item_id;
    j.status = 'skipped';
    if (r.state === 'purged') {
      j.result = 'purged';
      j.message = 'Descartado antes';
    } else if (r.state === 'trash') {
      j.result = 'in_trash';
      j.message = 'Está na lixeira';
    } else {
      j.result = 'known';
      j.message = r.state === 'archived' ? 'Já existia (no HD)' : 'Já existia';
    }
  }

  #upload(b: Batch, j: Job): Promise<void> {
    return new Promise<void>((resolve) => {
      j.status = 'uploading';
      j.progress = 0;
      const upload = new tus.Upload(j.file, {
        endpoint: '/api/uploads',
        chunkSize: CHUNK_SIZE,
        retryDelays: [0, 1000, 3000, 5000, 10000],
        storeFingerprintForResuming: true,
        removeFingerprintOnSuccess: true,
        metadata: {
          filename: j.name,
          filetype: j.file.type || 'application/octet-stream',
          lastModified: String(j.file.lastModified || Date.now()),
          source: 'web',
          session_id: String(b.session!.id),
          sha256: j.sha256!,
          client_key: j.key,
        },
        onProgress: (sent) => {
          j.progress = sent;
        },
        onError: (err) => {
          this.#active.delete(upload);
          if (b.phase === 'failed') return resolve();
          j.status = 'failed';
          j.message = describeTusError(err);
          resolve();
        },
        onSuccess: async () => {
          this.#active.delete(upload);
          j.progress = j.size;
          j.status = 'processing';
          const id = (upload.url ?? '').split('/').filter(Boolean).pop() ?? '';
          await this.#fetchResult(j, id);
          resolve();
        },
      });
      this.#active.add(upload);
      upload
        .findPreviousUploads()
        .then((prev) => {
          if (prev.length) upload.resumeFromPreviousUpload(prev[0]);
          upload.start();
        })
        .catch(() => upload.start());
    });
  }

  async #fetchResult(j: Job, id: string): Promise<void> {
    // The server processes the file after the last PATCH; poll briefly while it says "receiving".
    for (let attempt = 0; attempt < 30; attempt++) {
      try {
        const r = await api.uploadResult(id);
        if (r.status !== 'receiving') {
          j.result = r.status;
          j.itemId = r.item_id;
          j.message = r.message || statusText[r.status];
          j.status = r.status === 'failed' ? 'failed' : 'done';
          return;
        }
      } catch (e) {
        if (e instanceof ApiError && e.status !== 404 && e.status < 500) {
          j.status = 'failed';
          j.message = e.message;
          return;
        }
      }
      await new Promise((r) => setTimeout(r, Math.min(500 + attempt * 300, 3000)));
    }
    j.status = 'done';
    j.message = 'Recebido; processando no servidor';
  }

  #startMeter(): void {
    this.#lastBytes = this.#sentNow();
    this.#lastT = performance.now();
    this.#timer = setInterval(() => {
      const now = performance.now();
      const bytes = this.#sentNow();
      const inst = ((bytes - this.#lastBytes) * 1000) / Math.max(1, now - this.#lastT);
      this.speed = this.speed ? this.speed * 0.7 + Math.max(0, inst) * 0.3 : Math.max(0, inst);
      this.#lastBytes = bytes;
      this.#lastT = now;
    }, 1000);
  }

  #stopMeter(): void {
    if (this.#timer) clearInterval(this.#timer);
    this.#timer = null;
    this.speed = 0;
  }

  #sentNow(): number {
    const b = this.current;
    return b ? this.totals(b).sent : 0;
  }
}

export const statusText: Record<UploadStatus, string> = {
  receiving: 'Recebendo',
  new: 'Novo',
  duplicate: 'Já existia',
  in_trash: 'Está na lixeira',
  discarded: 'Descartado antes',
  attached: 'Juntado à Live Photo',
  restored: 'Recuperado',
  processing: 'Processando',
  failed: 'Falhou',
};

function describeTusError(err: Error): string {
  const anyErr = err as Error & { originalResponse?: { getStatus(): number } | null };
  const status = anyErr.originalResponse?.getStatus?.();
  if (status === 401) return 'Sessão expirada. Entre de novo e reenvie.';
  if (status === 413) return 'Arquivo grande demais para o servidor.';
  if (status === 507) return 'Servidor sem espaço.';
  if (!navigator.onLine) return 'Sem conexão. Reenvie para continuar de onde parou.';
  return 'Falhou depois de várias tentativas. Reenvie para continuar de onde parou.';
}

export const uploader = new Uploader();
