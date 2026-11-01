// Small per-device preferences (grid shape). localStorage can be missing or throw
// (private mode, some webviews), so every access is guarded and has a default.

type Fit = 'crop' | 'full';

function read(key: string, fallback: Fit): Fit {
  try {
    const v = localStorage.getItem(key);
    return v === 'crop' || v === 'full' ? v : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: Fit): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* not saved; still works for this visit */
  }
}

/** Entrada shows whole pictures by default (you are deciding on each one); the Acervo, squares. */
export const prefs = $state({
  inboxFit: read('acervo.fit.inbox', 'full'),
  libraryFit: read('acervo.fit.library', 'crop'),
});

export function toggleFit(which: 'inbox' | 'library'): void {
  if (which === 'inbox') {
    prefs.inboxFit = prefs.inboxFit === 'full' ? 'crop' : 'full';
    write('acervo.fit.inbox', prefs.inboxFit);
  } else {
    prefs.libraryFit = prefs.libraryFit === 'full' ? 'crop' : 'full';
    write('acervo.fit.library', prefs.libraryFit);
  }
}
