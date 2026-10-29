// pt-BR formatting helpers.
import type { Item, Kind, KindFilter, SuggestionKind } from './types';

const nf = new Intl.NumberFormat('pt-BR');
const nf1 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
const monthYearFmt = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' });
const monthShortFmt = new Intl.DateTimeFormat('pt-BR', { month: 'short', timeZone: 'UTC' });
const dateFmt = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const dateTimeFmt = new Intl.DateTimeFormat('pt-BR', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
});
const timeFmt = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' });
const localDateFmt = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short', year: 'numeric' });

export const num = (n: number): string => nf.format(n);

export function bytes(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  const s = i === 0 ? nf.format(v) : v >= 100 ? nf.format(Math.round(v)) : nf1.format(v);
  return `${s} ${units[i]}`;
}

/** Parse "AAAA-MM-DDTHH:MM:SS" local capture time as if it were UTC, so formatting never shifts it. */
export function parseLocal(s: string | null | undefined): Date | null {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(s);
  if (!m) return null;
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] ?? 0), +(m[5] ?? 0), +(m[6] ?? 0)));
}

export function monthKey(item: Item): string {
  const s = item.captured_at ?? item.uploaded_at;
  return s ? s.slice(0, 7) : '0000-00';
}

export function monthLabel(key: string): string {
  const [y, m] = key.split('-').map(Number);
  if (!y) return 'Sem data';
  return monthYearFmt.format(new Date(Date.UTC(y, m - 1, 1)));
}

export function monthShort(month: number): string {
  return monthShortFmt.format(new Date(Date.UTC(2000, month - 1, 1))).replace('.', '');
}

export function captureDate(item: Item): string {
  const d = parseLocal(item.captured_at);
  return d ? dateFmt.format(d) : '—';
}

export function captureDateTime(item: Item): string {
  const d = parseLocal(item.captured_at);
  return d ? dateTimeFmt.format(d) : 'Sem data';
}

/** Server UTC timestamps → user's local time. */
export function utcDate(s: string | null | undefined): string {
  if (!s) return '—';
  const d = new Date(s);
  return isNaN(+d) ? '—' : localDateFmt.format(d);
}

export function relativeDay(s: string | null | undefined): string {
  if (!s) return 'nunca';
  const d = new Date(s);
  if (isNaN(+d)) return '—';
  const now = new Date();
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(d)) / 86400000);
  const t = timeFmt.format(d);
  if (days === 0) return `hoje ${t}`;
  if (days === 1) return `ontem ${t}`;
  return `${localDateFmt.format(d)} ${t}`;
}

export function ago(s: string | null | undefined): string {
  if (!s) return 'nunca';
  const diff = Date.now() - new Date(s).getTime();
  const day = 86400000;
  if (diff < 60000) return 'agora há pouco';
  if (diff < 3600000) return plural(Math.round(diff / 60000), 'minuto', 'minutos', 'há ');
  if (diff < day) return plural(Math.round(diff / 3600000), 'hora', 'horas', 'há ');
  if (diff < 30 * day) return plural(Math.round(diff / day), 'dia', 'dias', 'há ');
  if (diff < 365 * day) return plural(Math.round(diff / (30 * day)), 'mês', 'meses', 'há ');
  return plural(Math.round(diff / (365 * day)), 'ano', 'anos', 'há ');
}

export function plural(n: number, one: string, many: string, prefix = ''): string {
  return `${prefix}${num(n)} ${n === 1 ? one : many}`;
}

export function daysUntil(s: string | null | undefined): number | null {
  if (!s) return null;
  return Math.max(0, Math.ceil((new Date(s).getTime() - Date.now()) / 86400000));
}

export function duration(ms: number | null | undefined): string {
  if (!ms) return '';
  const s = Math.round(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

export function eta(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return '';
  if (seconds < 60) return `~${Math.ceil(seconds)} s`;
  if (seconds < 3600) return `~${Math.ceil(seconds / 60)} min`;
  const h = Math.floor(seconds / 3600);
  return `~${h} h ${Math.round((seconds % 3600) / 60)} min`;
}

export function weeksText(w: number): string {
  if (w < 1) return 'faltam poucos dias para o próximo HD';
  if (w < 8) return `faltam ~${plural(Math.round(w), 'semana', 'semanas')} para o próximo HD`;
  if (w < 104) return `faltam ~${plural(Math.round(w / 4.3), 'mês', 'meses')} para o próximo HD`;
  return 'próximo HD ainda distante';
}

export const kindTabs: { key: KindFilter; label: string }[] = [
  { key: 'all', label: 'Tudo' },
  { key: 'photo', label: 'Fotos' },
  { key: 'video', label: 'Vídeos' },
  { key: 'document', label: 'Documentos' },
  { key: 'audio', label: 'Áudios' },
  { key: 'other', label: 'Outros' },
];

export const kindLabel: Record<Kind, string> = {
  photo: 'Foto',
  video: 'Vídeo',
  document: 'Documento',
  audio: 'Áudio',
  other: 'Outro',
};

export const suggestionLabel: Record<SuggestionKind, string> = {
  'near-duplicate': 'Quase-duplicados',
  screenshot: 'Capturas de tela',
  burst: 'Rajadas',
  whatsapp: 'Mídia do WhatsApp',
  'large-video': 'Vídeos grandes',
};

export const suggestionHint: Record<SuggestionKind, string> = {
  'near-duplicate': 'Versões muito parecidas. Fique com a melhor.',
  screenshot: 'Capturas costumam perder a utilidade com o tempo.',
  burst: 'Fotos em sequência. Normalmente uma basta.',
  whatsapp: 'Recebidas por conversas, muitas vezes repetidas.',
  'large-video': 'Ocupam muito espaço. Vale conferir.',
};

export const sourceLabel: Record<string, string> = {
  'iphone-daily': 'Backup diário do iPhone',
  'iphone-manual': 'iPhone (manual)',
  'iphone-empty': 'Esvaziar iPhone',
  mac: 'Mac',
  web: 'Navegador',
  webdav: 'WebDAV',
};

export function isMediaKind(k: KindFilter): boolean {
  return k === 'photo' || k === 'video';
}
