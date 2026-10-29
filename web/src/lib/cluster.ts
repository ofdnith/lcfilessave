// Simple screen-space grid clustering: points that fall into the same cell at the
// current zoom become one cluster, placed at the average of its members.
export interface Cluster {
  lat: number;
  lon: number;
  ids: number[];
}

/** Web-Mercator world pixel coordinates at zoom z (256 px tiles). */
function project(lat: number, lon: number, z: number): [number, number] {
  const scale = 256 * 2 ** z;
  const s = Math.sin((Math.max(-85.0511, Math.min(85.0511, lat)) * Math.PI) / 180);
  return [((lon + 180) / 360) * scale, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * scale];
}

export function clusterPoints(points: [number, number, number][], zoom: number, cellPx = 64): Cluster[] {
  const cells = new Map<string, { lat: number; lon: number; ids: number[] }>();
  for (const [id, lat, lon] of points) {
    const [x, y] = project(lat, lon, zoom);
    const key = `${Math.floor(x / cellPx)}:${Math.floor(y / cellPx)}`;
    const c = cells.get(key);
    if (c) {
      c.lat += lat;
      c.lon += lon;
      c.ids.push(id);
    } else cells.set(key, { lat, lon, ids: [id] });
  }
  return [...cells.values()].map((c) => ({ lat: c.lat / c.ids.length, lon: c.lon / c.ids.length, ids: c.ids }));
}
