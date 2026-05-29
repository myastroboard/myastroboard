const APP_VERSION = new URL(self.location.href).searchParams.get('v') || 'dev';
const SHELL_CACHE = `myastroboard-shell-${APP_VERSION}`;
const RUNTIME_CACHE = `myastroboard-runtime-${APP_VERSION}`;

const APP_SHELL_URLS = [
    '/login',
    '/offline.html',
    '/manifest.webmanifest',
    '/manifest.fr.webmanifest',
    '/manifest.es.webmanifest',
    '/manifest.de.webmanifest',
    '/manifest.it.webmanifest',
    '/manifest.pt.webmanifest',
    '/static/css/bs_variables.css',
    '/static/css/bs_icons_custom.css',
    '/static/css/bs_main.css',
    '/static/css/bs_login.css',
    '/static/js/theme.js',
    '/static/js/i18n.js',
    '/static/js/apiHelper.js',
    '/static/js/offline.js',
    '/static/js/notifications.js',
    '/static/i18n/en.json',
    '/static/i18n/fr.json',
    '/static/i18n/de.json',
    '/static/i18n/es.json',
    '/static/i18n/it.json',
    '/static/i18n/pt.json',
    '/static/ico/ios/16.png',
    '/static/ico/ios/32.png',
    '/static/ico/ios/180.png',
    '/static/ico/android/launchericon-48x48.png',
    '/static/ico/android/launchericon-72x72.png',
    '/static/ico/android/launchericon-96x96.png',
    '/static/ico/android/launchericon-144x144.png',
    '/static/ico/android/launchericon-192x192.png',
    '/static/ico/android/launchericon-512x512.png',
    '/static/ico/windows/Square150x150Logo.scale-100.png',
    '/static/favicon.ico',
    '/static/favicon.svg'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(SHELL_CACHE).then((cache) => cache.addAll(APP_SHELL_URLS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        (async () => {
            const keys = await caches.keys();
            await Promise.all(
                keys
                    .filter((key) =>
                        key.startsWith('myastroboard-shell-') || key.startsWith('myastroboard-runtime-')
                    )
                    .filter((key) => key !== SHELL_CACHE && key !== RUNTIME_CACHE)
                    .map((key) => caches.delete(key))
            );

            // Cleanup polluted legacy entries where protected routes were cached as redirected /login pages.
            const runtimeCache = await caches.open(RUNTIME_CACHE);
            const requests = await runtimeCache.keys();
            await Promise.all(
                requests.map(async (cachedRequest) => {
                    const requestPath = new URL(cachedRequest.url).pathname;
                    if (requestPath === '/login') {
                        return;
                    }

                    const cachedResponse = await runtimeCache.match(cachedRequest);
                    if (!cachedResponse) {
                        return;
                    }

                    const responsePath = new URL(cachedResponse.url).pathname;
                    if (responsePath === '/login') {
                        await runtimeCache.delete(cachedRequest);
                    }
                })
            );
        })()
    );
    self.clients.claim();
});

function isSameOrigin(url) {
    return url.origin === self.location.origin;
}

async function fetchWithTimeout(request, timeoutMs) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(request, { signal: controller.signal });
    } finally {
        clearTimeout(timeoutId);
    }
}

self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    if (request.method !== 'GET') {
        return;
    }

    if (!isSameOrigin(url)) {
        return;
    }

    if (url.pathname.startsWith('/api/')) {
        return;
    }

    if (request.mode === 'navigate') {
        event.respondWith(
            fetchWithTimeout(request, 2500)
                .then((networkResponse) => {
                    const requestPath = new URL(request.url).pathname;
                    const responsePath = new URL(networkResponse.url).pathname;
                    const isAuthRedirect = networkResponse.redirected && responsePath === '/login' && requestPath !== '/login';

                    // Do not cache auth redirects for protected routes, otherwise offline '/' becomes login.
                    if (!isAuthRedirect && networkResponse.ok) {
                        const responseClone = networkResponse.clone();
                        caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, responseClone));
                    }
                    return networkResponse;
                })
                .catch(async () => {
                    const requestPath = new URL(request.url).pathname;
                    const cachedPage = await caches.match(request);
                    if (cachedPage) {
                        const responsePath = new URL(cachedPage.url).pathname;
                        const isAuthRedirect = responsePath === '/login' && requestPath !== '/login';
                        if (!isAuthRedirect) {
                            return cachedPage;
                        }
                    }

                    // Never serve login HTML as offline fallback for protected routes.
                    if (requestPath === '/login') {
                        return cachedPage || caches.match('/offline.html') || new Response('Offline', {
                            status: 503,
                            statusText: 'Offline'
                        });
                    }
                    return caches.match('/offline.html') || new Response('Offline', {
                        status: 503,
                        statusText: 'Offline'
                    });
                })
        );
        return;
    }

    if (url.pathname.startsWith('/static/') || url.pathname.match(/^\/manifest(\.[a-z]+)?\.webmanifest$/)) {
        event.respondWith(
            (async () => {
                const cachedResponse = await caches.match(request);
                const fallbackCachedResponse = cachedResponse || await caches.match(url.pathname);
                try {
                    const networkResponse = await fetchWithTimeout(request, 4000);
                    if (networkResponse && networkResponse.status === 200) {
                        const responseClone = networkResponse.clone();
                        caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, responseClone));
                    }
                    return networkResponse;
                } catch (_) {
                    return fallbackCachedResponse || new Response('', {
                        status: 503,
                        statusText: 'Offline asset unavailable'
                    });
                }
            })()
        );
    }
});
