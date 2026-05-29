// ======================
// Notification Manager
// Phase A: Browser Notification API (tab must be open)
// Phase C: Web Push (background) — sw.js push handler required
// ======================

const NOTIF_TRIGGERS = Object.freeze({
    N1: 'N1', // Plan My Night session starts
    N2: 'N2', // Plan My Night: next target begins
    N3: 'N3', // ISS solar or lunar transit
    N4: 'N4', // Lunar eclipse totality
    N5: 'N5', // Solar eclipse maximum
    N6: 'N6', // Astronomical darkness begins
    N7: 'N7', // Aurora: Kp index ≥ threshold
});

const NOTIF_ICON = '/static/ico/android/launchericon-192x192.png';
const NOTIF_BADGE     = '/static/ico/android/launchericon-72x72.png';

const _NOTIF_DEFAULTS = Object.freeze({
    enabled:          true,
    permission_asked: false,
    triggers: Object.freeze({
        N1: Object.freeze({ enabled: true, lead_minutes: 15 }),
        N2: Object.freeze({ enabled: true, lead_minutes: 5  }),
        N3: Object.freeze({ enabled: true, lead_minutes: 10 }),
        N4: Object.freeze({ enabled: true, lead_minutes: 30 }),
        N5: Object.freeze({ enabled: true, lead_minutes: 30 }),
        N6: Object.freeze({ enabled: true, lead_minutes: 20 }),
        N7: Object.freeze({ enabled: true, kp_threshold: 5  }),
    }),
});

class NotificationManager {
    constructor() {
        this._prefs        = null; // lazy-loaded from localStorage
        this._lastNotified = {};   // triggerId → ms timestamp, in-memory dedup
    }

    // ── Support & permission ─────────────────────────────────────────────

    get isSupported() {
        return typeof Notification !== 'undefined';
    }

    get permission() {
        return this.isSupported ? Notification.permission : 'unsupported';
    }

    canNotify() {
        return this.isSupported
            && this.permission === 'granted'
            && this.getPrefs().enabled;
    }

    /**
     * Ask the browser for notification permission.
     * Safe to call multiple times — skips if already granted or denied.
     * Returns true if permission is (or becomes) granted.
     */
    async requestPermission() {
        if (!this.isSupported)            return false;
        if (this.permission === 'denied') return false;
        if (this.permission === 'granted') return true;
        const result = await Notification.requestPermission();
        await this._patchPrefs({ permission_asked: true });
        return result === 'granted';
    }

    // ── Preferences (localStorage) ───────────────────────────────────────

    getPrefs() {
        if (!this._prefs) {
            const serverPrefs = window.myastroboardUserPreferences?.notifications;
            this._prefs = this._mergeWithDefaults(serverPrefs || {});
        }
        return this._prefs;
    }

    async savePrefs(prefs) {
        this._prefs = prefs;
        if (typeof saveUserPreferences === 'function' && window.myastroboardUserPreferences) {
            const full = { ...window.myastroboardUserPreferences, notifications: prefs };
            const updated = await saveUserPreferences(full);
            if (updated && typeof updated === 'object') {
                window.myastroboardUserPreferences = updated;
            }
        }
    }

    async _patchPrefs(partial) {
        await this.savePrefs({ ...this.getPrefs(), ...partial });
    }

    _mergeWithDefaults(stored) {
        const merged = { ..._NOTIF_DEFAULTS, ...stored };
        merged.triggers = {};
        for (const id of Object.keys(_NOTIF_DEFAULTS.triggers)) {
            merged.triggers[id] = {
                ..._NOTIF_DEFAULTS.triggers[id],
                ...(stored.triggers?.[id] ?? {}),
            };
        }
        return merged;
    }

    // ── Per-trigger accessors ────────────────────────────────────────────

    isTriggerEnabled(triggerId) {
        return this.getPrefs().triggers?.[triggerId]?.enabled ?? true;
    }

    getLeadMinutes(triggerId) {
        return this.getPrefs().triggers?.[triggerId]?.lead_minutes
            ?? _NOTIF_DEFAULTS.triggers[triggerId]?.lead_minutes
            ?? 15;
    }

    getKpThreshold() {
        return this.getPrefs().triggers?.N7?.kp_threshold ?? 5;
    }

    // ── Deduplication (in-memory, resets on page reload) ─────────────────

    markNotified(triggerId) {
        this._lastNotified[triggerId] = Date.now();
    }

    /**
     * Returns true if this trigger fired a notification within the last cooldownMs.
     * Prevents repeated notifications when a polling loop re-evaluates a condition.
     */
    wasRecentlyNotified(triggerId, cooldownMs) {
        const last = this._lastNotified[triggerId];
        return last != null && (Date.now() - last) < cooldownMs;
    }

    // ── Fire notification ─────────────────────────────────────────────────

    /**
     * Show a native browser notification for the given trigger.
     *
     * @param {string} triggerId  — one of NOTIF_TRIGGERS (N1–N7)
     * @param {string} title
     * @param {string} body
     * @param {object} [options]
     * @param {string} [options.url]  — hash/path to navigate on click (e.g. '#plan-my-night')
     * @param {string} [options.tag]  — explicit dedup tag; auto-generated if omitted
     * @returns {Promise<boolean>}    — true if notification was shown
     */
    async notify(triggerId, title, body, { url = '/', tag = null } = {}) {
        if (!this.canNotify())              return false;
        if (!this.isTriggerEnabled(triggerId)) return false;

        // Request permission lazily on first call if not yet asked
        if (this.permission !== 'granted') {
            const granted = await this.requestPermission();
            if (!granted) return false;
        }

        const notifTag = tag ?? `mab-${triggerId}-${Date.now()}`;

        const notification = new Notification(title, {
            body,
            icon:  NOTIF_ICON,
            badge: NOTIF_BADGE,
            tag:   notifTag,
        });

        notification.onclick = () => {
            window.focus();
            notification.close();
            if (url) {
                const hash = url.replace(/^[/#]+/, '');
                if (hash) window.location.hash = hash;
            }
        };

        this.markNotified(triggerId);
        return true;
    }
}

const notificationManager = new NotificationManager();

// ======================
// Settings UI
// ======================

function _notifPermissionBannerState() {
    if (!notificationManager.isSupported) {
        return { cls: 'alert-warning', i18n: 'settings.notifications_unsupported', fallback: 'Your browser does not support notifications.' };
    }
    switch (notificationManager.permission) {
        case 'granted':  return { cls: 'alert-success', i18n: 'settings.notifications_permission_granted',  fallback: 'Browser notifications are enabled.' };
        case 'denied':   return { cls: 'alert-danger',  i18n: 'settings.notifications_permission_denied',   fallback: 'Browser notifications are blocked. Enable them in your browser settings.' };
        default:         return { cls: 'alert-warning', i18n: 'settings.notifications_permission_default',  fallback: 'Browser notifications are not yet enabled.' };
    }
}

function _refreshPermissionBanner() {
    const banner    = document.getElementById('notif-permission-banner');
    const enableBtn = document.getElementById('notif-enable-btn');
    if (!banner) return;

    const state = _notifPermissionBannerState();
    banner.className = `alert ${state.cls} mb-3`;
    const t = (typeof i18n !== 'undefined') ? i18n.t(state.i18n) : null;
    banner.textContent = (t && t !== state.i18n) ? t : state.fallback;
    banner.style.display = '';

    if (enableBtn) {
        enableBtn.style.display = notificationManager.permission === 'default' ? '' : 'none';
    }
}

function _loadPrefsIntoUI() {
    const prefs = notificationManager.getPrefs();

    const master = document.getElementById('notif-master-toggle');
    if (master) master.checked = prefs.enabled;

    for (const id of Object.keys(NOTIF_TRIGGERS)) {
        const toggle = document.getElementById(`notif-trigger-${id}`);
        if (toggle) toggle.checked = prefs.triggers?.[id]?.enabled ?? true;

        const lead = document.getElementById(`notif-lead-${id}`);
        if (lead) {
            const val = String(prefs.triggers?.[id]?.lead_minutes ?? _NOTIF_DEFAULTS.triggers[id]?.lead_minutes ?? 15);
            const opt = lead.querySelector(`option[value="${val}"]`);
            if (opt) lead.value = val;
        }
    }

    const kp = document.getElementById('notif-kp-threshold');
    if (kp) kp.value = String(notificationManager.getKpThreshold());
}

function _collectPrefsFromUI() {
    const prefs = notificationManager._mergeWithDefaults(notificationManager.getPrefs());

    const master = document.getElementById('notif-master-toggle');
    if (master) prefs.enabled = master.checked;

    for (const id of Object.keys(NOTIF_TRIGGERS)) {
        const toggle = document.getElementById(`notif-trigger-${id}`);
        if (toggle) prefs.triggers[id].enabled = toggle.checked;

        const lead = document.getElementById(`notif-lead-${id}`);
        if (lead && prefs.triggers[id].lead_minutes !== undefined) {
            prefs.triggers[id].lead_minutes = parseInt(lead.value, 10);
        }
    }

    const kp = document.getElementById('notif-kp-threshold');
    if (kp) prefs.triggers.N7.kp_threshold = parseInt(kp.value, 10);

    return prefs;
}

function _showNotifMessage(text, type = 'success') {
    const el = document.getElementById('notif-save-message');
    if (!el) return;
    el.className = `alert alert-${type} mt-3`;
    el.textContent = text;
    el.style.display = '';
    setTimeout(() => { el.style.display = 'none'; }, 3000);
}

function initNotificationSettingsUI() {
    notificationManager._prefs = null; // refresh from server state on each open
    _refreshPermissionBanner();
    _loadPrefsIntoUI();

    // Enable button — requests permission then refreshes
    const enableBtn = document.getElementById('notif-enable-btn');
    if (enableBtn && !enableBtn._notifBound) {
        enableBtn._notifBound = true;
        enableBtn.addEventListener('click', async () => {
            await notificationManager.requestPermission();
            _refreshPermissionBanner();
        });
    }

    // Save button
    const saveBtn = document.getElementById('notif-save-btn');
    if (saveBtn && !saveBtn._notifBound) {
        saveBtn._notifBound = true;
        saveBtn.addEventListener('click', async () => {
            try {
                await notificationManager.savePrefs(_collectPrefsFromUI());
                const msg = (typeof i18n !== 'undefined') ? i18n.t('settings.notifications_saved') : 'Preferences saved.';
                _showNotifMessage((msg && msg !== 'settings.notifications_saved') ? msg : 'Preferences saved.');
            } catch {
                _showNotifMessage(i18n?.t('common.error') || 'Failed to save preferences.', 'danger');
            }
        });
    }

    // Test button
    const testBtn = document.getElementById('notif-test-btn');
    if (testBtn && !testBtn._notifBound) {
        testBtn._notifBound = true;
        testBtn.addEventListener('click', async () => {
            const granted = await notificationManager.requestPermission();
            _refreshPermissionBanner();
            if (!granted) return;

            const title = (typeof i18n !== 'undefined') ? i18n.t('settings.notifications_test_title') : 'MyAstroBoard';
            const body  = (typeof i18n !== 'undefined') ? i18n.t('settings.notifications_test_body')  : 'Notifications are working correctly.';
            const n = new Notification(
                (title && title !== 'settings.notifications_test_title') ? title : 'MyAstroBoard',
                {
                    body:  (body  && body  !== 'settings.notifications_test_body')  ? body  : 'Notifications are working correctly.',
                    icon:  NOTIF_ICON,
                    badge: NOTIF_BADGE,
                    tag:   'mab-test',
                }
            );
            n.onclick = () => { window.focus(); n.close(); };
        });
    }
}
