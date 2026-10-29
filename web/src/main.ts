import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

const app = mount(App, { target: document.getElementById('app')! });

// Service worker: production only, secure contexts only (https or localhost).
// Skipped inside the Mac app, which always loads fresh from the server.
if (import.meta.env.PROD && 'serviceWorker' in navigator && window.isSecureContext && !window.__TAURI__) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* offline shell is a nicety; ignore failures */
    });
  });
}

export default app;
