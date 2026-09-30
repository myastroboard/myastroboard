(function registerPWA() {
    // No service worker under a sub-path (HA ingress panel): sw.js and its cache list are
    // root-scoped, and the panel is a frame inside Home Assistant that cannot be installed.
    if (!('serviceWorker' in navigator) || APP_BASE_PATH) {
        return;
    }

    let deferredInstallPrompt = null;

    const PWA_FALLBACK_MESSAGES = {
        'pwa.install_prompt_unavailable': 'Install prompt is not currently available in this browser.',
        'pwa.install_dismissed': 'Install dismissed. You can install later from the browser menu.',
        'pwa.install_ready': 'Install MyAstroBoard for faster launch and offline access.',
        'pwa.install_success': 'MyAstroBoard installed successfully.',
        'pwa.running_installed': 'MyAstroBoard is running as an installed app.',
        'pwa.ios_add_to_home': 'On iOS, use Share -> Add to Home Screen to install this app.',
        'pwa.offline_support_unavailable': 'Background offline support is unavailable right now.',
    };

    function getInstallButtons() {
        return Array.from(document.querySelectorAll('[data-pwa-install]'));
    }

    function getInstallStatusNodes() {
        return Array.from(document.querySelectorAll('[data-pwa-install-status]'));
    }

    function setInstallButtonsVisible(visible) {
        getInstallButtons().forEach((button) => {
            button.hidden = !visible;
            button.disabled = !visible;
        });
    }

    function setInstallStatus(message) {
        getInstallStatusNodes().forEach((statusNode) => {
            const hasMessage = Boolean(message);
            statusNode.hidden = !hasMessage;
            statusNode.textContent = message || '';
        });
    }

    function t(key) {
        if (typeof i18n !== 'undefined' && i18n && typeof i18n.t === 'function') {
            try {
                if (typeof i18n.has === 'function' && i18n.has(key)) {
                    return i18n.t(key);
                }
                return PWA_FALLBACK_MESSAGES[key] || key;
            } catch (_) {
                return PWA_FALLBACK_MESSAGES[key] || key;
            }
        }
        return PWA_FALLBACK_MESSAGES[key] || key;
    }

    function setInstallStatusKey(key) {
        setInstallStatus(t(key));
    }

    function isStandaloneMode() {
        return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    }

    function isIOSMobile() {
        return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
    }

    async function onInstallButtonClick() {
        if (!deferredInstallPrompt) {
            setInstallStatusKey('pwa.install_prompt_unavailable');
            return;
        }

        deferredInstallPrompt.prompt();
        const choiceResult = await deferredInstallPrompt.userChoice;

        if (choiceResult.outcome !== 'accepted') {
            setInstallStatusKey('pwa.install_dismissed');
            setInstallButtonsVisible(true);
        }

        deferredInstallPrompt = null;
    }

    window.addEventListener('beforeinstallprompt', (event) => {
        deferredInstallPrompt = event;
        setInstallButtonsVisible(true);
        setInstallStatusKey('pwa.install_ready');
    });

    window.addEventListener('appinstalled', () => {
        deferredInstallPrompt = null;
        setInstallButtonsVisible(false);
        setInstallStatusKey('pwa.install_success');
    });

    window.addEventListener('load', async () => {
        if (isStandaloneMode()) {
            setInstallButtonsVisible(false);
            setInstallStatusKey('pwa.running_installed');
        } else if (isIOSMobile()) {
            setInstallButtonsVisible(false);
            setInstallStatusKey('pwa.ios_add_to_home');
        }

        getInstallButtons().forEach((button) => {
            button.addEventListener('click', onInstallButtonClick);
        });

        try {
            const appVersionMeta = document.querySelector('meta[name="app-version"]');
            let appVersion = appVersionMeta ? String(appVersionMeta.content || '').trim() : '';

            if (!appVersion) {
                appVersion = String(localStorage.getItem('myastroboard_app_version') || '').trim();
            }

            if (!appVersion) {
                try {
                    const response = await fetch('/api/version', { cache: 'no-store' });
                    if (response.ok) {
                        const payload = await response.json();
                        appVersion = String(payload?.version || '').trim();
                        if (appVersion) {
                            localStorage.setItem('myastroboard_app_version', appVersion);
                        }
                    }
                } catch (_) {
                    // Keep fallback below if version endpoint is unavailable.
                }
            }

            const serviceWorkerUrl = appVersion
                ? appUrl(`/sw.js?v=${encodeURIComponent(appVersion)}`)
                : appUrl('/sw.js');

            await navigator.serviceWorker.register(serviceWorkerUrl, {
                scope: '/',
                updateViaCache: 'none'
            });
        } catch (error) {
            console.warn('PWA service worker registration failed:', error);
            setInstallStatusKey('pwa.offline_support_unavailable');
        }
    });

    window.addEventListener('i18nLanguageChanged', () => {
        if (deferredInstallPrompt) {
            setInstallStatusKey('pwa.install_ready');
        }
    });
})();
