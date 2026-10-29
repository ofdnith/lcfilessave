// Web Push helpers. Works only in the installed PWA (iOS 16.4+) over HTTPS.
import { api } from './api';
import type { PushTopic } from './types';

export const topicLabels: Record<PushTopic, string> = {
  backup_atrasado: 'Backup diário atrasado',
  espaco: 'Servidor ficando cheio',
  hd_problema: 'Problema num HD',
  backup_concluido: 'Resumo do backup diário',
};
export const allTopics = Object.keys(topicLabels) as PushTopic[];

export function isStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window && window.isSecureContext;
}

function urlB64ToUint8Array(b64: string): Uint8Array<ArrayBuffer> {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function registration(): Promise<ServiceWorkerRegistration> {
  // The SW registers on load in production; make sure one exists before subscribing.
  const existing = await navigator.serviceWorker.getRegistration();
  if (!existing) await navigator.serviceWorker.register('/sw.js');
  return navigator.serviceWorker.ready;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return reg ? reg.pushManager.getSubscription() : null;
}

/** Asks permission (must run from a tap), subscribes and registers with the server. */
export async function subscribe(publicKey: string, topics: PushTopic[]): Promise<PushSubscription> {
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') throw new Error('Permissão negada. Libere em Ajustes → Notificações → Acervo.');
  const reg = await registration();
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(publicKey) });
  }
  await api.pushSubscribe(sub.toJSON(), topics);
  return sub;
}

export async function unsubscribe(sub: PushSubscription): Promise<void> {
  try {
    await api.pushUnsubscribe(sub.endpoint);
  } finally {
    await sub.unsubscribe();
  }
}
