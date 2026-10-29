// Tiny hash router. Hash routing keeps the server simple: it only serves "/".
export type Route = 'acervo' | 'entrada' | 'lixeira' | 'enviar' | 'ajustes' | 'dispositivos' | 'esvaziar';

const routes: Route[] = ['acervo', 'entrada', 'lixeira', 'enviar', 'ajustes', 'dispositivos', 'esvaziar'];

function parse(): Route {
  const h = location.hash.replace(/^#\/?/, '').split(/[?/]/)[0] as Route;
  return routes.includes(h) ? h : 'acervo';
}

export const router = $state({ route: parse() });

window.addEventListener('hashchange', () => {
  router.route = parse();
});

export function go(route: Route): void {
  if (router.route === route && location.hash) return;
  location.hash = `#/${route}`;
}

export function href(route: Route): string {
  return `#/${route}`;
}
