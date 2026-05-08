const CACHE_NAME = 'mural-v2';

// Arquivos que o app vai salvar para abrir rápido
const urlsToCache = [
    '/',
    '/static/logo.png'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                return cache.addAll(urlsToCache);
            })
    );
});

// ESTRATÉGIA ATUALIZADA: Tenta a rede, se cair, usa o cache
self.addEventListener('fetch', event => {
    // Só entra na estratégia de cache para pedidos normais (GET)
    if (event.request.method !== 'GET') return;

    event.respondWith(
        fetch(event.request)
            .then(response => {
                // REMOVIDO: response.type !== 'basic' para permitir salvar os anúncios e fotos
                if (!response || response.status !== 200) {
                    return response;
                }

                const responseClone = response.clone();
                caches.open(CACHE_NAME).then(cache => {
                    cache.put(event.request, responseClone);
                });
                return response;
            })
            .catch(() => {
                // Se a internet falhar em Ivinhema, entrega o que está salvo
                return caches.match(event.request);
            })
    );
});