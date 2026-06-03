// Admin app settings: VAPID contact email, reverse-proxy flags, container restart

async function loadAppSettings() {
    try {
        const settings = await fetchJSON('/api/admin/app-settings');
        const emailEl = document.getElementById('app-setting-vapid-email');
        const trustEl = document.getElementById('app-setting-trust-proxy');
        const secureEl = document.getElementById('app-setting-session-secure');
        if (emailEl) emailEl.value = settings.vapid_contact_email || '';
        if (trustEl) trustEl.checked = !!settings.trust_proxy_headers;
        if (secureEl) secureEl.checked = !!settings.session_cookie_secure;
    } catch (err) {
        console.error('Failed to load app settings:', err);
    }
}

async function saveAppSettingsNotifications() {
    const email = (document.getElementById('app-setting-vapid-email')?.value || '').trim();
    await _saveAppSettings({ vapid_contact_email: email }, 'notifications');
}

async function saveAppSettingsProxy() {
    const trust = document.getElementById('app-setting-trust-proxy')?.checked ?? false;
    const secure = document.getElementById('app-setting-session-secure')?.checked ?? false;
    await _saveAppSettings({ trust_proxy_headers: trust, session_cookie_secure: secure }, 'proxy');
}

async function _saveAppSettings(partial, section) {
    try {
        const current = await fetchJSON('/api/admin/app-settings');
        const payload = { ...current, ...partial };
        const result = await fetchJSON('/api/admin/app-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        const feedbackId = section === 'notifications'
            ? 'app-settings-notifications-feedback'
            : 'app-settings-proxy-feedback';
        _showFeedback(feedbackId);

        if (section === 'notifications' && typeof _refreshVapidWarning === 'function') {
            _refreshVapidWarning();
        }

        if (result.requires_restart) {
            showRestartBanner();
        }
    } catch (err) {
        console.error('Failed to save app settings:', err);
    }
}

function showRestartBanner() {
    const banner = document.getElementById('restart-required-banner');
    if (banner) banner.style.display = 'flex';
}

function hideRestartBanner() {
    const banner = document.getElementById('restart-required-banner');
    if (banner) banner.style.display = 'none';
}

function _showFeedback(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.style.display = 'inline';
    setTimeout(() => { el.style.display = 'none'; }, 3000);
}

async function restartApp() {
    const overlay = document.getElementById('restarting-overlay');
    if (overlay) overlay.style.setProperty('display', 'flex', 'important');

    try {
        await fetch('/api/admin/restart', { method: 'POST' });
    } catch (_) {
        // expected — server may drop the connection immediately
    }

    // Poll /health every 2s until the app is back up, then reload
    const poll = setInterval(async () => {
        try {
            const r = await fetch('/health', { cache: 'no-store' });
            if (r.ok) {
                clearInterval(poll);
                window.location.reload();
            }
        } catch (_) {
            // still restarting — keep polling
        }
    }, 2000);
}

// Wire up event listeners once DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('save-app-settings-notifications')
        ?.addEventListener('click', saveAppSettingsNotifications);

    document.getElementById('save-app-settings-proxy')
        ?.addEventListener('click', saveAppSettingsProxy);

    document.getElementById('btn-restart-app')
        ?.addEventListener('click', restartApp);
});
