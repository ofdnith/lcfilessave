<script lang="ts">
  // Leaflet map with OpenStreetMap tiles; loaded on demand so the main bundle stays small.
  import type * as Leaflet from 'leaflet';
  import { clusterPoints, type Cluster } from '../lib/cluster';
  import { num } from '../lib/format';

  let {
    points,
    onpick,
  }: {
    points: [number, number, number][];
    /** Called with the ids of a point (or a cluster that can't be split further). */
    onpick: (ids: number[]) => void;
  } = $props();

  const MAX_ZOOM = 18;
  let el = $state<HTMLElement | null>(null);
  let failed = $state<string | null>(null);
  let tilesDown = $state(false);
  let L: typeof Leaflet | null = null;
  let map: Leaflet.Map | null = null;
  let layer: Leaflet.LayerGroup | null = null;

  function icon(c: Cluster): Leaflet.DivIcon {
    const n = c.ids.length;
    const size = n === 1 ? 14 : n < 10 ? 30 : n < 100 ? 36 : n < 1000 ? 42 : 48;
    return L!.divIcon({
      className: 'acv-marker',
      html: n === 1 ? '<span class="acv-dot"></span>' : `<span class="acv-cl">${num(n)}</span>`,
      iconSize: [size, size],
    });
  }

  function redraw() {
    if (!map || !L || !layer) return;
    layer.clearLayers();
    const z = map.getZoom();
    const b = map.getBounds().pad(0.3);
    const visible = points.filter(([, lat, lon]) => b.contains([lat, lon]));
    for (const c of clusterPoints(visible, z)) {
      const m = L.marker([c.lat, c.lon], {
        icon: icon(c),
        keyboard: true,
        title: c.ids.length === 1 ? '1 foto' : `${c.ids.length} fotos`,
      });
      m.on('click', () => {
        const z2 = map!.getZoom();
        // Points with identical coordinates never split: show them as a list instead of zooming forever.
        const same = c.ids.length > 1 && points.filter(([id]) => c.ids.includes(id)).every(([, la, lo], _, arr) => la === arr[0][1] && lo === arr[0][2]);
        if (c.ids.length === 1 || z2 >= MAX_ZOOM - 2 || same) onpick(c.ids);
        else map!.setView([c.lat, c.lon], Math.min(MAX_ZOOM, z2 + 3));
      });
      layer.addLayer(m);
    }
  }

  $effect(() => {
    if (!el) return;
    let cancelled = false;
    (async () => {
      try {
        const mod = await import('leaflet');
        await import('leaflet/dist/leaflet.css');
        if (cancelled || !el) return;
        L = (mod.default ?? mod) as typeof Leaflet;
        map = L.map(el, { zoomControl: true, attributionControl: true, worldCopyJump: true, maxZoom: MAX_ZOOM });
        map.attributionControl.setPrefix(false);
        let tileErrors = 0;
        let tileOk = 0;
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: MAX_ZOOM,
          attribution: '© OpenStreetMap',
        })
          .on('tileerror', () => {
            tileErrors++;
            if (!tileOk && tileErrors >= 4) tilesDown = true;
          })
          .on('tileload', () => {
            tileOk++;
            tilesDown = false;
          })
          .addTo(map);
        layer = L.layerGroup().addTo(map);
        if (points.length) {
          const bounds = L.latLngBounds(points.map(([, la, lo]) => [la, lo] as [number, number]));
          map.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
        } else map.setView([-14.2, -51.9], 4);
        map.on('moveend zoomend', redraw);
        redraw();
      } catch {
        failed = 'Não foi possível abrir o mapa.';
      }
    })();
    return () => {
      cancelled = true;
      map?.remove();
      map = null;
    };
  });

  // Redraw when the point set changes.
  $effect(() => {
    void points;
    redraw();
  });
</script>

<div class="map-wrap">
  <div class="map" bind:this={el} aria-label="Mapa das fotos"></div>
  {#if failed}
    <div class="offline">
      <p><strong>O mapa precisa de internet</strong></p>
      <p class="muted">{failed} A lista de lugares abaixo funciona sem ele.</p>
    </div>
  {/if}
</div>
{#if tilesDown && !failed}
  <p class="tiles-note">
    <strong>O fundo do mapa precisa de internet.</strong> Ele vem do OpenStreetMap e não carregou agora; os pontos e a lista abaixo
    funcionam assim mesmo.
  </p>
{/if}

<style>
  .map-wrap {
    position: relative;
    height: min(56vh, 520px);
    border-radius: var(--r-lg);
    overflow: hidden;
    border: 1px solid var(--line-soft);
    background: #1a222c;
  }
  .map {
    position: absolute;
    inset: 0;
    background: #1a222c;
  }
  .offline {
    position: absolute;
    inset: 0;
    z-index: 500;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 24px;
    background: rgba(22, 29, 38, 0.94);
  }
  .offline p {
    margin: 0 0 4px;
    max-width: 360px;
    font-size: 14px;
  }
  .tiles-note {
    margin: 8px 2px 0;
    padding: 10px 12px;
    border-radius: var(--r-md);
    background: var(--surface);
    border: 1px solid var(--line-soft);
    color: var(--muted);
    font-size: 13px;
  }
  .tiles-note strong {
    color: var(--text);
  }
  /* Leaflet elements are created outside Svelte's scope. */
  .map :global(.acv-marker) {
    display: grid;
    place-items: center;
  }
  .map :global(.acv-dot) {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--accent);
    border: 2px solid #fff;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
  }
  .map :global(.acv-cl) {
    width: 100%;
    height: 100%;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--accent);
    color: var(--accent-ink);
    font: 700 12px/1 var(--font);
    border: 3px solid rgba(255, 255, 255, 0.85);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
  }
  .map :global(.leaflet-control-attribution) {
    background: rgba(16, 21, 28, 0.75);
    color: var(--muted);
    font-size: 11px;
  }
  .map :global(.leaflet-control-attribution a) {
    color: var(--info);
  }
  .map :global(.leaflet-bar a) {
    background: var(--raised);
    color: var(--text);
    border-color: var(--line);
  }
  .map :global(.leaflet-bar a:hover) {
    background: var(--raised-2);
  }
</style>
