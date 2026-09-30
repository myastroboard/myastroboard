// Admin app settings: VAPID contact email, privacy, log levels, reverse-proxy flags, container restart

async function loadAppSettings() {
    try {
        const settings = await fetchJSON('/api/admin/app-settings');
        const emailEl = document.getElementById('app-setting-vapid-email');
        const trustEl = document.getElementById('app-setting-trust-proxy');
        const secureEl = document.getElementById('app-setting-session-secure');
        const indexingEl = document.getElementById('app-setting-search-indexing');
        const externalUrlEl = document.getElementById('app-setting-external-base-url');
        if (emailEl) emailEl.value = settings.vapid_contact_email || '';
        if (trustEl) trustEl.checked = !!settings.trust_proxy_headers;
        if (secureEl) secureEl.checked = !!settings.session_cookie_secure;
        if (indexingEl) indexingEl.checked = !!settings.search_engine_indexing;
        if (externalUrlEl) externalUrlEl.value = settings.external_base_url || '';
    } catch (err) {
        console.error('Failed to load app settings:', err);
    }
}

async function saveAppSettingsNotifications() {
    const email = (document.getElementById('app-setting-vapid-email')?.value || '').trim();
    await _saveAppSettings({ vapid_contact_email: email }, 'notifications');
}

async function saveAppSettingsPrivacy() {
    const indexing = document.getElementById('app-setting-search-indexing')?.checked ?? false;
    await _saveAppSettings({ search_engine_indexing: indexing }, 'privacy');
}

// Log levels and retention (Parameters -> Log export). A LOG_LEVEL / CONSOLE_LOG_LEVEL environment
// variable overrides the saved level: its select is then disabled, with a note.
const _LOG_LEVEL_FIELDS = [
    { key: 'log_level', envKey: 'log_level_env', envVar: 'LOG_LEVEL', id: 'app-setting-log-level' },
    { key: 'console_log_level', envKey: 'console_log_level_env', envVar: 'CONSOLE_LOG_LEVEL', id: 'app-setting-console-log-level' },
];

async function loadLogLevels() {
    try {
        const settings = await fetchJSON('/api/admin/app-settings');
        const retentionEl = document.getElementById('app-setting-log-retention');
        if (retentionEl) retentionEl.value = settings.log_retention_days ?? 90;
        for (const field of _LOG_LEVEL_FIELDS) {
            const select = document.getElementById(field.id);
            const note = document.getElementById(`${field.id}-env`);
            if (!select) continue;
            const envLevel = settings[field.envKey];
            select.value = envLevel || settings[field.key];
            select.disabled = !!envLevel;
            if (note) {
                note.replaceChildren();
                if (envLevel) {
                    const icon = document.createElement('i');
                    icon.className = 'bi bi-lock-fill icon-inline';
                    icon.setAttribute('aria-hidden', 'true');
                    note.append(icon, ' ', i18n.t('settings.log_level_env_override', {
                        variable: field.envVar, level: envLevel,
                    }));
                }
                note.style.display = envLevel ? '' : 'none';
            }
        }
    } catch (err) {
        console.error('Failed to load log levels:', err);
    }
}

async function saveAppSettingsLogs() {
    const partial = {};
    for (const field of _LOG_LEVEL_FIELDS) {
        const select = document.getElementById(field.id);
        if (select && !select.disabled) partial[field.key] = select.value;
    }
    const retentionEl = document.getElementById('app-setting-log-retention');
    if (retentionEl && retentionEl.value !== '') partial.log_retention_days = Number(retentionEl.value);
    await _saveAppSettings(partial, 'logs');
    if (retentionEl) loadLogLevels(); // show the value the server kept (clamped to 0-3650)
}

async function saveAppSettingsProxy() {
    const trust = document.getElementById('app-setting-trust-proxy')?.checked ?? false;
    const secure = document.getElementById('app-setting-session-secure')?.checked ?? false;
    const externalBaseUrl = (document.getElementById('app-setting-external-base-url')?.value || '').trim();
    await _saveAppSettings(
        { trust_proxy_headers: trust, session_cookie_secure: secure, external_base_url: externalBaseUrl },
        'proxy',
    );
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

        const feedbackIds = {
            notifications: 'app-settings-notifications-feedback',
            privacy: 'app-settings-privacy-feedback',
            proxy: 'app-settings-proxy-feedback',
            logs: 'app-settings-logs-feedback',
        };
        _showFeedback(feedbackIds[section]);

        if (section === 'notifications' && typeof _refreshVapidWarning === 'function') {
            _refreshVapidWarning();
        }

        if (result.requires_restart) {
            showRestartBanner();
        }
    } catch (err) {
        console.error('Failed to save app settings:', err);
        if (err.status === 400 && section === 'proxy') {
            showMessage('error', i18n.t('settings.app_settings_external_base_url_invalid'));
        }
    }
}

function showRestartBanner() {
    const banner = document.getElementById('restart-required-banner');
    if (banner) banner.style.display = 'flex';
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

    document.getElementById('save-app-settings-privacy')
        ?.addEventListener('click', saveAppSettingsPrivacy);

    document.getElementById('save-app-settings-proxy')
        ?.addEventListener('click', saveAppSettingsProxy);

    document.getElementById('save-app-settings-logs')
        ?.addEventListener('click', saveAppSettingsLogs);

    document.getElementById('btn-restart-app')
        ?.addEventListener('click', restartApp);
});
