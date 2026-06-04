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
        caches.open(SHELL_CACHE)
            .then((cache) => cache.addAll(APP_SHELL_URLS))
            .then(() => self.skipWaiting())
    );
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

            // Claim clients only after cache cleanup is complete.
            await self.clients.claim();
        })()
    );
});

function isSameOrigin(url) {
    return url.origin === self.location.origin;
}

async function _shouldCache() {
    if (!navigator.storage?.estimate) return true;
    try {
        const { usage, quota } = await navigator.storage.estimate();
        return quota > 0 && usage / quota < 0.8;
    } catch (_) {
        return true;
    }
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

self.addEventListener('push', (event) => {
    let payload = {};
    try { payload = event.data?.json() ?? {}; } catch (_) {}

    const title   = payload.title  || 'MyAstroBoard';
    const options = {
        body:     payload.body  || '',
        icon:     payload.icon  || '/static/ico/android/launchericon-192x192.png',
        badge:    payload.badge || '/static/ico/android/launchericon-72x72.png',
        tag:      payload.tag   || 'mab-push',
        data:     payload.data  || {},
        renotify: true,
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    // Resolve the hash path to an absolute URL using the SW's own origin,
    // so the navigation works regardless of which domain the app is installed on.
    const rawUrl    = event.notification.data?.url || '/';
    const targetUrl = rawUrl.startsWith('http')
        ? rawUrl
        : `${self.location.origin}${rawUrl.startsWith('/') ? '' : '/'}${rawUrl}`;

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (clientList) => {
            for (const client of clientList) {
                if ('navigate' in client) {
                    try {
                        // navigate() returns the new WindowClient for the navigated page;
                        // focus that reference, not the pre-navigation one (stale on Firefox/Edge).
                        const navigated = await client.navigate(targetUrl);
                        return (navigated || client).focus();
                    } catch (_) {
                        // Client was closed between matchAll and navigate - try next one.
                    }
                }
            }
            // No existing window reachable - open a new one.
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});

// Fires when the browser silently rotates a push subscription (e.g. on expiry).
// Re-subscribes and sends the new subscription to the server so push delivery continues.
self.addEventListener('pushsubscriptionchange', (event) => {
    event.waitUntil(
        (async () => {
            try {
                // Remove the expired subscription from the server before re-subscribing.
                if (event.oldSubscription?.endpoint) {
                    await fetch('/api/push/unsubscribe', {
                        method:      'DELETE',
                        credentials: 'same-origin',
                        headers:     { 'Content-Type': 'application/json' },
                        body:        JSON.stringify({ endpoint: event.oldSubscription.endpoint }),
                    }).catch(() => {});
                }

                const resp = await fetch('/api/push/vapid-public-key', { credentials: 'same-origin' });
                if (!resp.ok) return;
                const { public_key: publicKeyB64 } = await resp.json();
                if (!publicKeyB64) return;

                const padding   = '='.repeat((4 - (publicKeyB64.length % 4)) % 4);
                const base64    = (publicKeyB64 + padding).replace(/-/g, '+').replace(/_/g, '/');
                const raw       = atob(base64);
                const publicKey = Uint8Array.from(raw, (c) => c.charCodeAt(0));

                const newSub = await self.registration.pushManager.subscribe({
                    userVisibleOnly:      true,
                    applicationServerKey: publicKey,
                });

                await fetch('/api/push/subscribe', {
                    method:      'POST',
                    credentials: 'same-origin',
                    headers:     { 'Content-Type': 'application/json' },
                    body:        JSON.stringify({ subscription: newSub.toJSON() }),
                });
            } catch (_) {}
        })()
    );
});

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
            fetchWithTimeout(request, 8000)
                .then((networkResponse) => {
                    const requestPath  = url.pathname;
                    const responsePath = new URL(networkResponse.url).pathname;
                    const isAuthRedirect = networkResponse.redirected && responsePath === '/login' && requestPath !== '/login';

                    // Do not cache auth redirects for protected routes, otherwise offline '/' becomes login.
                    if (!isAuthRedirect && networkResponse.ok) {
                        const responseClone = networkResponse.clone(); // clone synchronously before body is consumed
                        _shouldCache().then((ok) => {
                            if (!ok) return;
                            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, responseClone));
                        });
                    }
                    return networkResponse;
                })
                .catch(async () => {
                    const requestPath = url.pathname;
                    const cachedPage  = await caches.match(request);
                    if (cachedPage) {
                        const responsePath = new URL(cachedPage.url).pathname;
                        const isAuthRedirect = responsePath === '/login' && requestPath !== '/login';
                        if (!isAuthRedirect) {
                            return cachedPage;
                        }
                    }

                    // Never serve login HTML as offline fallback for protected routes.
                    const offlinePage = await caches.match('/offline.html');
                    if (requestPath === '/login') {
                        return cachedPage || offlinePage || new Response('Offline', {
                            status: 503,
                            statusText: 'Offline'
                        });
                    }
                    return offlinePage || new Response('Offline', {
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
                        const responseClone = networkResponse.clone(); // clone synchronously before body is consumed
                        _shouldCache().then((ok) => {
                            if (!ok) return;
                            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, responseClone));
                        });
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
