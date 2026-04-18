const CACHE_NAME = 'mural-v1';

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

self.addEventListener('fetch', event => {
    event.respondWith(
    caches.match(event.request)
        .then(response => {
        return response || fetch(event.request);
        })
    );
});