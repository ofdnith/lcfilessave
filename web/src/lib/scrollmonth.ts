// Tracks which month header is at the top of the viewport (for the scrubber position).
export function trackMonth(onchange: (key: string | null) => void): () => void {
  let raf = 0;
  let last: string | null = null;
  const check = () => {
    raf = 0;
    const sections = document.querySelectorAll<HTMLElement>('section[data-month]');
    let key: string | null = null;
    for (const s of sections) {
      const r = s.getBoundingClientRect();
      if (r.bottom > 140) {
        key = s.dataset.month ?? null;
        break;
      }
    }
    if (key !== last) {
      last = key;
      onchange(key);
    }
  };
  const onScroll = () => {
    if (!raf) raf = requestAnimationFrame(check);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
  return () => {
    window.removeEventListener('scroll', onScroll);
    if (raf) cancelAnimationFrame(raf);
  };
}
