<script lang="ts">
  // Right-edge fast scroller. Years as ticks; dragging shows the month under the finger and jumps with `start=AAAA-MM`.
  import { monthShort } from '../lib/format';
  import type { TimelineMonth } from '../lib/types';

  let { months, current = null, onjump }: { months: TimelineMonth[]; current?: string | null; onjump: (start: string) => void } =
    $props();

  let track = $state<HTMLElement | null>(null);
  let dragging = $state(false);
  let hover = $state<{ idx: number; y: number } | null>(null);

  const total = $derived(months.reduce((s, m) => s + Math.max(1, m.count), 0));

  // Each month gets vertical space proportional to its item count (log-damped so tiny months stay reachable).
  const layout = $derived.by(() => {
    const weights = months.map((m) => Math.log2(2 + m.count));
    const sum = weights.reduce((a, b) => a + b, 0) || 1;
    let acc = 0;
    return months.map((m, i) => {
      const top = acc / sum;
      acc += weights[i];
      return { ...m, top, bottom: acc / sum, key: `${m.year}-${String(m.month).padStart(2, '0')}` };
    });
  });

  const years = $derived.by(() => {
    const out: { year: number; top: number }[] = [];
    for (const m of layout) if (!out.length || out[out.length - 1].year !== m.year) out.push({ year: m.year, top: m.top });
    // Thin out year labels that would overlap (min ~22px apart on a typical track).
    const minGap = 0.035;
    const shown: typeof out = [];
    for (const y of out) if (!shown.length || y.top - shown[shown.length - 1].top >= minGap) shown.push(y);
    return shown;
  });

  const currentTop = $derived(layout.find((m) => m.key === current)?.top ?? null);

  function indexAt(clientY: number): { idx: number; y: number } | null {
    if (!track || !layout.length) return null;
    const r = track.getBoundingClientRect();
    const f = Math.min(0.9999, Math.max(0, (clientY - r.top) / r.height));
    let idx = layout.findIndex((m) => f >= m.top && f < m.bottom);
    if (idx < 0) idx = layout.length - 1;
    return { idx, y: clientY - r.top };
  }

  let lastJump = '';
  let jumpTimer: ReturnType<typeof setTimeout> | null = null;
  function jumpTo(idx: number, immediate = false) {
    const key = layout[idx].key;
    if (key === lastJump) return;
    lastJump = key;
    if (jumpTimer) clearTimeout(jumpTimer);
    if (immediate) onjump(key);
    else jumpTimer = setTimeout(() => onjump(key), 120);
  }

  function down(e: PointerEvent) {
    if (!track) return;
    dragging = true;
    track.setPointerCapture(e.pointerId);
    const h = indexAt(e.clientY);
    hover = h;
    if (h) jumpTo(h.idx);
    e.preventDefault();
  }
  function move(e: PointerEvent) {
    const h = indexAt(e.clientY);
    hover = h;
    if (dragging && h) jumpTo(h.idx);
  }
  function up(e: PointerEvent) {
    if (!dragging) return;
    dragging = false;
    const h = indexAt(e.clientY);
    if (h) jumpTo(h.idx, true);
    lastJump = '';
    hover = null;
  }
  function key(e: KeyboardEvent) {
    const i = layout.findIndex((m) => m.key === current);
    if (e.key === 'ArrowDown' && i < layout.length - 1) {
      onjump(layout[i + 1].key);
      e.preventDefault();
    } else if (e.key === 'ArrowUp' && i > 0) {
      onjump(layout[i - 1].key);
      e.preventDefault();
    }
  }
</script>

{#if months.length > 1 && total > 0}
  <div
    class="scrubber"
    class:dragging
    bind:this={track}
    role="slider"
    tabindex="0"
    aria-label="Linha do tempo"
    aria-valuemin={0}
    aria-valuemax={layout.length - 1}
    aria-valuenow={Math.max(0, layout.findIndex((m) => m.key === current))}
    aria-valuetext={current ?? ''}
    onpointerdown={down}
    onpointermove={move}
    onpointerup={up}
    onpointercancel={up}
    onpointerleave={() => !dragging && (hover = null)}
    onkeydown={key}
  >
    {#each years as y (y.year)}
      <span class="year" style:top="{y.top * 100}%">{y.year}</span>
    {/each}
    {#if currentTop !== null && !hover}
      <span class="pos" style:top="{currentTop * 100}%"></span>
    {/if}
    {#if hover}
      {@const m = layout[hover.idx]}
      <span class="bubble" style:top="{hover.y}px">{monthShort(m.month)} {m.year}</span>
      <span class="pos live" style:top="{hover.y}px"></span>
    {/if}
  </div>
{/if}

<style>
  .scrubber {
    position: fixed;
    right: calc(var(--sar) + 2px);
    top: calc(var(--scrub-top, 150px));
    bottom: calc(var(--scrub-bottom, 16px));
    width: 52px;
    z-index: 15;
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    cursor: ns-resize;
  }
  .year {
    position: absolute;
    right: 8px;
    transform: translateY(-50%);
    font-size: 10.5px;
    font-weight: 600;
    color: var(--faint);
    font-variant-numeric: tabular-nums;
    opacity: 0;
    transition: opacity 0.2s;
  }
  .scrubber:hover .year,
  .scrubber:focus-visible .year,
  .dragging .year {
    opacity: 1;
  }
  .pos {
    position: absolute;
    right: 4px;
    width: 18px;
    height: 3px;
    border-radius: 2px;
    background: var(--accent);
    transform: translateY(-50%);
  }
  .bubble {
    position: absolute;
    right: 34px;
    transform: translateY(-50%);
    padding: 6px 12px;
    border-radius: 999px;
    background: var(--accent);
    color: var(--accent-ink);
    font-size: 13px;
    font-weight: 700;
    white-space: nowrap;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
    pointer-events: none;
  }
  @media (max-width: 899px) {
    .scrubber {
      width: 40px;
    }
    .year {
      display: none;
    }
  }
</style>
