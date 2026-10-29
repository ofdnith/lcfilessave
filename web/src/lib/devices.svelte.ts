// Mac app only: plugged disks, known volumes, verified transfer and health checks.
// Module-level so a running transfer survives navigation between screens.
import { api, ApiError } from './api';
import { native, type Disk } from './native';
import { invalidate } from './state.svelte';
import { refreshStats } from './stats.svelte';
import type { Health, PlanFile, Volume } from './types';

const VERIFIED_BATCH = 50;
/** Keep some room free on the drive so the filesystem never fills up completely. */
const DRIVE_MARGIN = 2 * 1024 ** 3;

export interface TransferState {
  volumeId: string;
  volumeName: string;
  mountPath: string;
  phase: 'planning' | 'copying' | 'committing' | 'bundle' | 'done' | 'failed' | 'cancelled';
  files: PlanFile[];
  index: number;
  totalBytes: number;
  doneBytes: number;
  currentBytes: number;
  verified: number;
  rejected: { file_id: number; error: string }[];
  copyErrors: { rel_path: string; error: string }[];
  result: { archived_items: number; freed_bytes: number } | null;
  error: string | null;
  cancelRequested: boolean;
}

export interface CheckState {
  volumeId: string;
  full: boolean;
  phase: 'running' | 'done' | 'failed';
  checked: number;
  problems: { file_id: number; error: string }[];
  error: string | null;
}

class Devices {
  disks = $state<Disk[]>([]);
  volumes = $state<Volume[]>([]);
  archiveCopies = $state(1);
  health = $state<Health | null>(null);
  healthError = $state(false);
  diskError = $state<string | null>(null);
  transfer = $state<TransferState | null>(null);
  check = $state<CheckState | null>(null);

  #seen = new Set<string>();
  #pollers = 0;
  #diskTimer: ReturnType<typeof setInterval> | null = null;
  #healthTimer: ReturnType<typeof setInterval> | null = null;

  /** Start polling while a screen that needs it is open; returns a stop function. */
  watch(): () => void {
    if (this.#pollers++ === 0) {
      void this.refreshVolumes();
      void this.pollDisks();
      void this.pollHealth();
      this.#diskTimer = setInterval(() => void this.pollDisks(), 1500);
      this.#healthTimer = setInterval(() => void this.pollHealth(), 10000);
    }
    return () => {
      if (--this.#pollers === 0) {
        if (this.#diskTimer) clearInterval(this.#diskTimer);
        if (this.#healthTimer) clearInterval(this.#healthTimer);
      }
    };
  }

  volumeFor(d: Disk): Volume | null {
    return d.volume ? (this.volumes.find((v) => v.id === d.volume!.id) ?? null) : null;
  }

  async refreshVolumes(): Promise<void> {
    try {
      const r = await api.volumes();
      this.volumes = r.volumes;
      this.archiveCopies = r.archive_copies;
    } catch {
      /* shown as unknown disks until it works */
    }
  }

  async pollDisks(): Promise<void> {
    try {
      const disks = await native.listDisks();
      this.diskError = null;
      // Report each new sighting of a known volume once per plug-in.
      const present = new Set<string>();
      for (const d of disks) {
        if (!d.volume) continue;
        const key = `${d.volume.id}@${d.mount_path}`;
        present.add(key);
        if (!this.#seen.has(key) && this.volumes.some((v) => v.id === d.volume!.id)) {
          this.#seen.add(key);
          api
            .volumeSeen(d.volume.id, d.total_bytes - d.free_bytes)
            .then((v) => this.#replaceVolume(v))
            .catch(() => this.#seen.delete(key));
        }
      }
      for (const k of this.#seen) if (!present.has(k)) this.#seen.delete(k);
      if (JSON.stringify(disks) !== JSON.stringify(this.disks)) this.disks = disks;
    } catch (e) {
      this.diskError = (e as Error).message;
    }
  }

  async pollHealth(): Promise<void> {
    try {
      this.health = await api.health();
      this.healthError = false;
    } catch {
      this.healthError = true;
    }
  }

  #replaceVolume(v: Volume): void {
    const i = this.volumes.findIndex((x) => x.id === v.id);
    if (i >= 0) this.volumes[i] = v;
    else this.volumes.push(v);
  }

  async addVolume(d: Disk): Promise<Volume> {
    const v = await api.createVolume(d.total_bytes, d.filesystem);
    await native.initVolume(d.mount_path, v.id, v.name, v.created_at);
    this.#replaceVolume(v);
    await this.pollDisks();
    return v;
  }

  async startTransfer(d: Disk, v: Volume): Promise<void> {
    if (this.transfer && !['done', 'failed', 'cancelled'].includes(this.transfer.phase)) return;
    const t: TransferState = {
      volumeId: v.id,
      volumeName: v.name,
      mountPath: d.mount_path,
      phase: 'planning',
      files: [],
      index: 0,
      totalBytes: 0,
      doneBytes: 0,
      currentBytes: 0,
      verified: 0,
      rejected: [],
      copyErrors: [],
      result: null,
      error: null,
      cancelRequested: false,
    };
    this.transfer = t;
    const tr = this.transfer; // reactive proxy
    let unlisten: (() => void) | null = null;
    try {
      const maxBytes = Math.max(0, d.free_bytes - DRIVE_MARGIN);
      const plan = await api.archivePlan(v.id, maxBytes);
      tr.files = plan.files;
      tr.totalBytes = plan.total_bytes;
      if (!plan.files.length) {
        tr.phase = 'done';
        tr.result = { archived_items: 0, freed_bytes: 0 };
        return;
      }
      tr.phase = 'copying';
      unlisten = await native.onCopyProgress((p) => {
        const f = tr.files[tr.index];
        if (f && p.rel_path === f.rel_path) tr.currentBytes = p.bytes_done;
      });

      let pending: { file_id: number; rel_path: string; sha256: string }[] = [];
      const flush = async () => {
        if (!pending.length) return;
        const batch = pending;
        pending = [];
        const r = await api.archiveVerified(v.id, batch);
        tr.verified += r.accepted.length;
        tr.rejected.push(...r.rejected);
      };

      for (let i = 0; i < tr.files.length; i++) {
        if (tr.cancelRequested) break;
        tr.index = i;
        tr.currentBytes = 0;
        const f = tr.files[i];
        try {
          const r = await native.copyToVolume(d.mount_path, f.url, f.rel_path, f.sha256, f.size_bytes);
          // Only the hash re-read from the drive is reported; the server accepts it only if it matches.
          pending.push({ file_id: f.file_id, rel_path: f.rel_path, sha256: r.sha256 });
        } catch (e) {
          tr.copyErrors.push({ rel_path: f.rel_path, error: (e as Error).message });
          if (tr.copyErrors.length >= 5 && tr.copyErrors.length === i + 1) {
            throw new Error('Os primeiros arquivos falharam. Confira se o HD está conectado e tem espaço.');
          }
        }
        tr.doneBytes += f.size_bytes;
        tr.currentBytes = 0;
        if (pending.length >= VERIFIED_BATCH) await flush();
      }
      await flush();

      tr.phase = 'committing';
      tr.result = await api.archiveCommit(v.id);

      tr.phase = 'bundle';
      const bundle = await api.volumeBundle(v.id);
      for (const b of bundle.files) await native.writeBundleFile(d.mount_path, b.path, b.url);

      tr.phase = tr.cancelRequested ? 'cancelled' : 'done';
      invalidate();
      void refreshStats();
      void this.refreshVolumes();
    } catch (e) {
      tr.phase = 'failed';
      tr.error = e instanceof ApiError ? e.message : (e as Error).message;
    } finally {
      unlisten?.();
    }
  }

  cancelTransfer(): void {
    if (this.transfer) this.transfer.cancelRequested = true;
  }

  async runCheck(d: Disk, v: Volume, full: boolean): Promise<void> {
    if (this.check?.phase === 'running') return;
    this.check = { volumeId: v.id, full, phase: 'running', checked: 0, problems: [], error: null };
    const c = this.check;
    try {
      const sample = await api.volumeSample(v.id, 50, full);
      const res = await native.verifyVolumeFiles(d.mount_path, sample.files);
      c.checked = res.length;
      c.problems = res.filter((r) => !r.ok).map((r) => ({ file_id: r.file_id, error: r.error ?? 'hash diferente' }));
      const updated = await api.volumeCheck(v.id, {
        kind: full ? 'full' : 'partial',
        files_checked: c.checked,
        problems: c.problems,
      });
      this.#replaceVolume(updated);
      c.phase = 'done';
    } catch (e) {
      c.phase = 'failed';
      c.error = e instanceof ApiError ? e.message : (e as Error).message;
    }
  }
}

export const devices = new Devices();
