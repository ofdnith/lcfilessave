// Global sheets (bottom sheet on phone, centered dialog on desktop): confirm and album picker.
export interface ConfirmRequest {
  title: string;
  body?: string;
  confirm: string;
  tone?: 'primary' | 'danger';
  resolve: (ok: boolean) => void;
}

export const sheets = $state({
  confirm: null as ConfirmRequest | null,
  /** Item ids waiting for an album choice. */
  albumFor: null as number[] | null,
  /** Called after items were added (album id). */
  albumDone: null as ((albumId: number) => void) | null,
});

export function confirmSheet(opts: Omit<ConfirmRequest, 'resolve'>): Promise<boolean> {
  return new Promise((resolve) => {
    sheets.confirm?.resolve(false);
    sheets.confirm = { ...opts, resolve };
  });
}

export function pickAlbum(ids: number[], done?: (albumId: number) => void): void {
  sheets.albumFor = ids;
  sheets.albumDone = done ?? null;
}
