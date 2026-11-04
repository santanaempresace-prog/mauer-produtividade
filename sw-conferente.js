// Endereco antigo desativado: limpa o cache offline e envia o tablet para o novo site.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const chaves = await caches.keys();
    await Promise.all(chaves.map((k) => caches.delete(k)));
    await self.registration.unregister();
    const abas = await self.clients.matchAll({ type: 'window' });
    abas.forEach((c) => c.navigate('https://mauer-produtividade.web.app/conferente.html'));
  })());
});
