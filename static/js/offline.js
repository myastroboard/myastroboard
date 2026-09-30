(function initializeOfflinePage() {
    const AUTO_RETRY_INTERVAL_SECONDS = 30;
    let retryCountdownSeconds = AUTO_RETRY_INTERVAL_SECONDS;
    let countdownTimerId = null;
    let reconnectInProgress = false;

    function t(key, params = {}) {
        return (typeof i18n !== 'undefined' && i18n && typeof i18n.t === 'function')
            ? i18n.t(key, params)
            : key;
    }

    function setTextByI18nKey(key) {
        const element = document.querySelector(`[data-i18n="${key}"]`);
        if (!element) {
            return;
        }

        if (typeof updateElementText === 'function') {
            updateElementText(element, key);
        } else {
            element.textContent = t(key);
        }
    }

    function applyTranslations() {
        setTextByI18nKey('pwa.offline_title');
        setTextByI18nKey('pwa.offline_message');
        setTextByI18nKey('pwa.retry_connection');
        document.title = t('pwa.offline_page_title');
        updateCountdownText();
    }

    function updateCountdownText() {
        const countdownNode = document.getElementById('retry-countdown');
        if (!countdownNode) {
            return;
        }

        countdownNode.textContent = t('pwa.auto_retry_in', { seconds: retryCountdownSeconds });
    }

    function resetCountdown() {
        retryCountdownSeconds = AUTO_RETRY_INTERVAL_SECONDS;
        updateCountdownText();
    }

    function navigateToApp() {
        // Relative: offline.html sits next to the app root
        window.location.replace('./');
    }

    async function tryReconnect() {
        const retryButton = document.getElementById('retry-connection-btn');
        const messageNode = document.querySelector('[data-i18n="pwa.offline_message"]');
        if (!retryButton || !messageNode) {
            navigateToApp();
            return;
        }

        if (reconnectInProgress) {
            return;
        }

        reconnectInProgress = true;
        retryButton.disabled = true;
        const previousMessage = messageNode.textContent;
        messageNode.textContent = t('pwa.checking_connection');

        try {
            const response = await fetchWithRetry('/api/auth/status', {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store'
            }, {
                maxAttempts: 1,
                timeoutMs: 2000,
                retryOnNetworkError: false
            });

            if (!response.ok) {
                navigateToApp();
                return;
            }

            navigateToApp();
        } catch (_) {
            // Do NOT fall back to navigator.onLine here. navigator.onLine only
            // indicates the device has a network interface — it returns true even
            // when the server is unreachable (e.g. WiFi connected but server down).
            // Navigating on a failed fetch causes the false-reconnect loop where the
            // app loads from cache, checkAuthStatus fails, and we're back here.
            messageNode.textContent = t('pwa.still_offline');
            retryButton.disabled = false;
            window.setTimeout(() => {
                messageNode.textContent = previousMessage;
            }, 3000);
        } finally {
            reconnectInProgress = false;
            resetCountdown();
        }
    }

    function startAutoRetryCountdown() {
        if (countdownTimerId) {
            window.clearInterval(countdownTimerId);
        }

        updateCountdownText();
        countdownTimerId = window.setInterval(async () => {
            if (reconnectInProgress) {
                return;
            }

            retryCountdownSeconds -= 1;
            if (retryCountdownSeconds <= 0) {
                resetCountdown();
                await tryReconnect();
                return;
            }

            updateCountdownText();
        }, 1000);
    }

    async function initialize() {
        if (typeof i18n !== 'undefined' && i18n && typeof i18n.loadLanguage === 'function') {
            await i18n.loadLanguage(i18n.getCurrentLanguage(), {
                activate: true,
                persistSelection: false
            });
        }

        applyTranslations();

        const retryButton = document.getElementById('retry-connection-btn');
        if (retryButton) {
            retryButton.addEventListener('click', tryReconnect);
        }

        startAutoRetryCountdown();
        window.addEventListener('i18nLanguageChanged', applyTranslations);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initialize();
        });
    } else {
        initialize();
    }
})();
