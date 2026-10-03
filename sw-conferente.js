// Service worker mínimo: permite instalar o app na tela inicial e mostrar os avisos do tablet.
// Não guarda nada em cache — tudo vem sempre da rede, para nunca mostrar versão antiga.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
// Tocar na notificação traz o app do conferente para a frente (ou abre de novo)
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
    for (const c of cs) { if (c.url.includes('conferente')) return c.focus(); }
    return self.clients.openWindow('conferente.html');
  }));
});
