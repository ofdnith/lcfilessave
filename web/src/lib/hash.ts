// Streaming SHA-256 of a File, chunk by chunk via file.slice, so large videos never sit in memory.
import { createSHA256, type IHasher } from 'hash-wasm';

const CHUNK = 4 * 1024 * 1024;

export async function sha256File(file: File, onProgress?: (done: number) => void, signal?: AbortSignal): Promise<string> {
  const hasher: IHasher = await createSHA256();
  hasher.init();
  for (let off = 0; off < file.size; off += CHUNK) {
    if (signal?.aborted) throw new DOMException('Cancelado', 'AbortError');
    const buf = await file.slice(off, Math.min(off + CHUNK, file.size)).arrayBuffer();
    hasher.update(new Uint8Array(buf));
    onProgress?.(Math.min(off + CHUNK, file.size));
  }
  return hasher.digest('hex');
}

/** Run `fn` over items with at most `limit` in flight. */
export async function pool<T>(items: T[], limit: number, fn: (item: T, index: number) => Promise<void>): Promise<void> {
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      await fn(items[i], i);
    }
  });
  await Promise.all(workers);
}
