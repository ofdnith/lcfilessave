// Tiny hash router. Hash routing keeps the server simple: it only serves "/".
// Shapes: #/route, #/route/param, #/route?key=value
export type Route =
  | 'acervo'
  | 'entrada'
  | 'lixeira'
  | 'enviar'
  | 'ajustes'
  | 'dispositivos'
  | 'esvaziar'
  | 'albuns'
  | 'album'
  | 'lugares';

const routes: Route[] = ['acervo', 'entrada', 'lixeira', 'enviar', 'ajustes', 'dispositivos', 'esvaziar', 'albuns', 'album', 'lugares'];

interface Parsed {
  route: Route;
  param: string | null;
  query: Record<string, string>;
}

function parse(): Parsed {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path, search = ''] = raw.split('?');
  const [head, param] = path.split('/');
  const route = (routes.includes(head as Route) ? head : 'acervo') as Route;
  const query: Record<string, string> = {};
  new URLSearchParams(search).forEach((v, k) => (query[k] = v));
  return { route, param: param ? decodeURIComponent(param) : null, query };
}

export const router = $state(parse());

window.addEventListener('hashchange', () => {
  const p = parse();
  router.route = p.route;
  router.param = p.param;
  router.query = p.query;
});

export function href(route: Route, param?: string | number | null, query?: Record<string, string>): string {
  let h = `#/${route}`;
  if (param !== undefined && param !== null) h += `/${encodeURIComponent(String(param))}`;
  if (query && Object.keys(query).length) h += `?${new URLSearchParams(query).toString()}`;
  return h;
}

export function go(route: Route, param?: string | number | null, query?: Record<string, string>): void {
  const h = href(route, param, query);
  if (location.hash === h) return;
  location.hash = h;
}
