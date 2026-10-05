// Service worker do app do conferente.
// • Guarda uma cópia do app (página e logo) para ele abrir mesmo quando a internet cai.
// • Sempre tenta a internet primeiro: com conexão, vem a versão mais nova e a cópia é atualizada.
// • Mostra os avisos do tablet (notificações) e abre o app ao tocar nelas.
const CACHE = 'mauer-conferente-v2';
const ARQUIVOS = ['conferente.html', 'logo-mauer-branco.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ARQUIVOS).catch(() => {})).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;   // banco (Firebase) não passa por aqui
  e.respondWith(
    fetch(req).then(resp => {
      if (resp.ok && (req.mode === 'navigate' || /\.(html|png|jpg|jpeg|js)$/.test(url.pathname))) {
        const copia = resp.clone();
        caches.open(CACHE).then(c => c.put(req.mode === 'navigate' ? url.pathname : req, copia)).catch(() => {});
      }
      return resp;
    }).catch(() => caches.match(req.mode === 'navigate' ? url.pathname : req, { ignoreSearch: true })
      .then(r => r || caches.match('conferente.html', { ignoreSearch: true })))
  );
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
    for (const c of cs) { if (c.url.includes('conferente')) return c.focus(); }
    return self.clients.openWindow('conferente.html');
  }));
});
