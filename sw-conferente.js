// Service worker mínimo: permite instalar o app na tela inicial.
// Não guarda nada em cache — tudo vem sempre da rede, para nunca mostrar versão antiga.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
