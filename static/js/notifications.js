// ======================
// Notification Manager
// Phase A: Browser Notification API (tab must be open)
// Phase C: Web Push (background) - sw.js push handler required
// ======================

const NOTIF_TRIGGERS = Object.freeze({
    N1: 'N1', // Plan My Night session starts
    N2: 'N2', // Plan My Night: next target begins
    N3: 'N3', // ISS solar or lunar transit
    N4: 'N4', // Lunar eclipse totality
    N5: 'N5', // Solar eclipse maximum
    N6: 'N6', // Astronomical darkness begins
    N7: 'N7', // Aurora: Kp index ≥ threshold
    N8: 'N8', // CSS solar or lunar transit
    N9: 'N9', // Heads-up ahead of a meteor shower / comet visibility window's peak
});

const NOTIF_ICON = '/static/ico/android/launchericon-192x192.png';
const NOTIF_BADGE     = '/static/ico/android/launchericon-72x72.png';

const _NOTIF_DEFAULTS = Object.freeze({
    enabled:          true,
    permission_asked: false,
    disabled_location_ids: Object.freeze([]), // v1.2: per-location notification mutes
    triggers: Object.freeze({
        N1: Object.freeze({ enabled: true, lead_minutes: 15 }),
        N2: Object.freeze({ enabled: true, lead_minutes: 5  }),
        N3: Object.freeze({ enabled: true, lead_minutes: 10 }),
        N4: Object.freeze({ enabled: true, lead_minutes: 30 }),
        N8: Object.freeze({ enabled: true, lead_minutes: 10 }),
        N5: Object.freeze({ enabled: true, lead_minutes: 30 }),
        N6: Object.freeze({ enabled: true, lead_minutes: 20 }),
        N7: Object.freeze({ enabled: true, kp_threshold: 6  }),
        N9: Object.freeze({ enabled: true, lead_minutes: 2880 }), // 2 days, stored as day-equivalent minutes
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
     * Safe to call multiple times - skips if already granted or denied.
     * Returns true if permission is (or becomes) granted.
     */
    async requestPermission() {
        if (!this.isSupported)            return false;
        if (this.permission === 'denied') return false;
        if (this.permission === 'granted') {
            _subscribeToPush(); // ensure push sub exists for this device
            return true;
        }
        const result = await Notification.requestPermission();
        await this._patchPrefs({ permission_asked: true });
        if (result === 'granted') _subscribeToPush();
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
        return this.getPrefs().triggers?.N7?.kp_threshold ?? 6;
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
     * @param {string} triggerId  - one of NOTIF_TRIGGERS (N1–N9)
     * @param {string} title
     * @param {string} body
     * @param {object} [options]
     * @param {string} [options.url]  - hash/path to navigate on click (e.g. '#plan-my-night')
     * @param {string} [options.tag]  - explicit dedup tag; auto-generated if omitted
     * @returns {Promise<boolean>}    - true if notification was shown
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
// Web Push subscription
// ======================

function _urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64  = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw     = atob(base64);
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

async function _subscribeToPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    try {
        const resp = await fetch('/api/push/vapid-public-key', { credentials: 'same-origin' });
        if (!resp.ok) return;
        const { public_key: publicKey } = await resp.json();
        if (!publicKey) return;

        const reg = await navigator.serviceWorker.ready;
        const existing = await reg.pushManager.getSubscription();

        if (existing) {
            // Detect VAPID key rotation: compare stored applicationServerKey to server's current key.
            // If they differ the subscription is stale and will fail delivery - force re-subscribe.
            const serverKeyBytes = _urlBase64ToUint8Array(publicKey);
            const storedKeyBytes = existing.options?.applicationServerKey
                ? new Uint8Array(existing.options.applicationServerKey)
                : null;
            const keyMismatch = storedKeyBytes && (
                storedKeyBytes.length !== serverKeyBytes.length ||
                !storedKeyBytes.every((b, i) => b === serverKeyBytes[i])
            );

            if (!keyMismatch) {
                // Re-POST to server: the server may have purged this endpoint as dead (e.g. after
                // an APNs delivery failure). The subscribe endpoint deduplicates by endpoint, so
                // this is a no-op when the subscription is already stored server-side.
                await fetch('/api/push/subscribe', {
                    method:      'POST',
                    credentials: 'same-origin',
                    headers:     { 'Content-Type': 'application/json' },
                    body:        JSON.stringify({ subscription: existing.toJSON() }),
                });
                return;
            }

            // Key mismatch: unsubscribe the stale subscription before creating a fresh one.
            console.warn('Push: VAPID key changed, re-subscribing.');
            await fetch('/api/push/unsubscribe', {
                method:      'DELETE',
                credentials: 'same-origin',
                headers:     { 'Content-Type': 'application/json' },
                body:        JSON.stringify({ endpoint: existing.endpoint }),
            }).catch(() => {});
            await existing.unsubscribe();
        }

        const sub = await reg.pushManager.subscribe({
            userVisibleOnly:      true,
            applicationServerKey: _urlBase64ToUint8Array(publicKey),
        });

        await fetch('/api/push/subscribe', {
            method:      'POST',
            credentials: 'same-origin',
            headers:     { 'Content-Type': 'application/json' },
            body:        JSON.stringify({ subscription: sub.toJSON() }),
        });
    } catch (e) {
        console.warn('Push subscription failed:', e);
    }
}

async function _unsubscribeFromPush() {
    if (!('serviceWorker' in navigator)) return;
    try {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (!sub) return;
        await fetch('/api/push/unsubscribe', {
            method:      'DELETE',
            credentials: 'same-origin',
            headers:     { 'Content-Type': 'application/json' },
            body:        JSON.stringify({ endpoint: sub.endpoint }),
        });
        await sub.unsubscribe();
    } catch (e) {
        console.warn('Push unsubscription failed:', e);
    }
}

// ======================
// Background Poller
// Runs every 5 min regardless of which tab is open.
// Calls the same _check* functions defined in each feature module.
// ======================

const _NOTIF_POLL_MS_SLOW = 5 * 60 * 1000; // 5 min - default
const _NOTIF_POLL_MS_FAST = 60 * 1000;     // 1 min - during/near active observation session
let   _notifPollTimer  = null;
let   _notifFastMode   = false;             // true when inside night or ≤30 min away

async function _runNotificationChecks() {
    if (!notificationManager.canNotify()) return;

    const enabled = notificationManager.getPrefs().triggers;

    // N7 - Aurora Kp
    if (enabled?.N7?.enabled !== false) {
        try {
            const data = await fetch('/api/aurora/predictions', { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : null);
            if (data && typeof _checkAuroraN7 === 'function') _checkAuroraN7(data);
        } catch (_) {}
    }

    // N1 + N2 - Plan My Night session / next target
    if (enabled?.N1?.enabled !== false || enabled?.N2?.enabled !== false) {
        try {
            const data = await fetch('/api/plan-my-night', { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : null);
            if (data) {
                // Activate fast mode during the night or within 30 min of night start
                const isInsideNight = data?.timeline?.is_inside_night === true;
                const nightStartMs  = data?.plan?.night_start ? new Date(data.plan.night_start).getTime() : null;
                const nearStart     = nightStartMs && !isInsideNight
                    && nightStartMs - Date.now() < 30 * 60 * 1000
                    && nightStartMs - Date.now() > 0;
                _notifFastMode = isInsideNight || !!nearStart;

                if (typeof _checkPlanNotifications === 'function') _checkPlanNotifications(data);
            }
        } catch (_) {}
    }

    // N6 - Astronomical darkness
    if (enabled?.N6?.enabled !== false) {
        try {
            const data = await fetch('/api/sun/today', { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : null);
            if (data && typeof _checkSunN6 === 'function') _checkSunN6(data);
        } catch (_) {}
    }

    // N3 - ISS transit (data is cached 6 h server-side, no extra cost)
    if (enabled?.N3?.enabled !== false) {
        try {
            const data = await fetch('/api/iss/passes?days=20', { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : null);
            if (data && typeof _checkIssN3 === 'function') _checkIssN3(data);
        } catch (_) {}
    }

    // N8 - CSS transit
    if (enabled?.N8?.enabled !== false) {
        try {
            const data = await fetch('/api/css/passes?days=20', { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : null);
            if (data && typeof _checkCssN8 === 'function') _checkCssN8(data);
        } catch (_) {}
    }

    // N4 + N5 + N9 - Eclipses & solar-system event windows (events_alerts.js also polls every
    // 10 min, but only when the calendar tab is open)
    if (enabled?.N4?.enabled !== false || enabled?.N5?.enabled !== false || enabled?.N9?.enabled !== false) {
        try {
            const lang = (typeof i18n !== 'undefined') ? i18n.getCurrentLanguage() : 'en';
            const data = await fetch(`/api/events/upcoming?lang=${encodeURIComponent(lang)}`, { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : null);
            if (data) {
                if (typeof _checkEclipseNotifications === 'function') _checkEclipseNotifications(data);
                if (typeof _checkSolsysWindowNotifications === 'function') _checkSolsysWindowNotifications(data);
            }
        } catch (_) {}
    }
}

function _scheduleNextPoll() {
    const delay = _notifFastMode ? _NOTIF_POLL_MS_FAST : _NOTIF_POLL_MS_SLOW;
    _notifPollTimer = setTimeout(async () => {
        await _runNotificationChecks();
        _scheduleNextPoll();
    }, delay);
}

function startNotificationPoller() {
    if (_notifPollTimer !== null) return;
    _runNotificationChecks().then(_scheduleNextPoll);
}

// ======================
// Settings UI
// ======================

function _notifPermissionBannerState() {
    // The Notification API silently denies permission requests on insecure origins (plain
    // HTTP, not localhost) - flag this distinctly so it doesn't look like a generic "not
    // enabled yet" state that a click on Enable would fix.
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
        return { cls: 'alert-warning', i18n: 'settings.notifications_insecure_context', fallback: 'Notifications require a secure connection (HTTPS). They cannot be enabled while using plain HTTP.' };
    }
    if (!notificationManager.isSupported) {
        return { cls: 'alert-warning', i18n: 'settings.notifications_unsupported', fallback: 'Your browser does not support notifications.' };
    }
    switch (notificationManager.permission) {
        case 'granted':  return { cls: 'alert-success', i18n: 'settings.notifications_permission_granted',  fallback: 'Browser notifications are enabled. To revoke, open your browser site settings.' };
        case 'denied':   return { cls: 'alert-danger',  i18n: 'settings.notifications_permission_denied',   fallback: 'Browser notifications are blocked. Enable them in your browser settings.' };
        default:         return { cls: 'alert-warning', i18n: 'settings.notifications_permission_default',  fallback: 'Browser notifications are not yet enabled.' };
    }
}

async function _getPushStatusSuffix() {
    const t = (key, fallback) => {
        if (typeof i18n === 'undefined') return fallback;
        const v = i18n.t(key);
        return (v && v !== key) ? v : fallback;
    };

    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        return t('settings.notifications_push_inapp_only', ' - In-app only (tab must be open)');
    }
    try {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        return sub
            ? t('settings.notifications_push_active',     ' - Background push active')
            : t('settings.notifications_push_inapp_only', ' - In-app only (tab must be open)');
    } catch (_) {
        return '';
    }
}

async function _refreshVapidWarning() {
    const el = document.getElementById('notif-vapid-warning');
    if (!el) return;
    try {
        const resp = await fetch('/api/push/vapid-config-status', { credentials: 'same-origin' });
        if (!resp.ok) return;
        const status = await resp.json();
        el.style.display = status.ok ? 'none' : '';
    } catch (_) {}
}

async function _refreshPermissionBanner() {
    const banner    = document.getElementById('notif-permission-banner');
    const enableBtn = document.getElementById('notif-enable-btn');
    if (!banner) return;

    const state = _notifPermissionBannerState();
    banner.className = `alert ${state.cls} mb-3`;

    const t = (typeof i18n !== 'undefined') ? i18n.t(state.i18n) : null;
    const mainText = (t && t !== state.i18n) ? t : state.fallback;

    while (banner.firstChild) banner.removeChild(banner.firstChild);

    const mainSpan = document.createElement('span');
    mainSpan.textContent = mainText;
    banner.appendChild(mainSpan);

    if (notificationManager.permission === 'granted') {
        const suffix = await _getPushStatusSuffix();
        if (suffix) {
            banner.appendChild(document.createElement('br'));
            const statusEl = document.createElement('small');
            statusEl.className = 'opacity-75';
            statusEl.textContent = suffix;
            banner.appendChild(statusEl);
        }
    }

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

    _renderNotifLocationMutes();
}

// Per-location mute list (v1.2): checked = notifications ON for that location.
// The block only appears when the user has more than one attributed location.
async function _renderNotifLocationMutes() {
    const block = document.getElementById('notif-locations-block');
    const list = document.getElementById('notif-locations-list');
    if (!block || !list || typeof fetchMyLocations !== 'function') return;

    let data;
    try {
        data = await fetchMyLocations();
    } catch (_) {
        block.style.display = 'none';
        return;
    }
    const locations = (data && data.locations) || [];
    if (locations.length <= 1) {
        block.style.display = 'none';
        return;
    }

    const prefs = notificationManager.getPrefs();
    const disabled = new Set(prefs.disabled_location_ids || []);

    block.style.display = '';
    DOMUtils.clear(list);
    locations.forEach(loc => {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check form-switch';

        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'form-check-input notif-location-toggle';
        input.id = `notif-location-${loc.id}`;
        input.value = loc.id;
        input.setAttribute('role', 'switch');
        input.checked = !disabled.has(loc.id);

        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.setAttribute('for', input.id);
        label.textContent = loc.name || '?';

        wrapper.appendChild(input);
        wrapper.appendChild(label);
        list.appendChild(wrapper);
    });
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

    // Per-location mutes (v1.2): unchecked toggle = muted location
    const locToggles = document.querySelectorAll('.notif-location-toggle');
    if (locToggles.length > 0) {
        prefs.disabled_location_ids = Array.from(locToggles)
            .filter(cb => !cb.checked)
            .map(cb => cb.value);
    }

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

const _PROVIDER_ICONS = {
    apple:   'bi-apple',
    google:  'bi-google',
    mozilla: 'bi-firefox',
    other:   'bi-browser-chrome',
};

async function _loadSubscriptionList() {
    const list    = document.getElementById('notif-sub-list');
    const countEl = document.getElementById('notif-sub-count');
    const allBtn  = document.getElementById('notif-unsub-all-btn');
    if (!list) return;

    try {
        const data = await fetchJSON('/api/push/subscriptions');
        const subs = data.subscriptions || [];

        DOMUtils.clear(list);
        if (countEl) {
            countEl.textContent = subs.length;
            countEl.style.display = subs.length ? '' : 'none';
        }
        if (allBtn) allBtn.style.display = subs.length ? '' : 'none';

        if (subs.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'text-muted small mb-0';
            empty.setAttribute('data-i18n', 'settings.notif_no_subscriptions');
            empty.textContent = i18n?.t('settings.notif_no_subscriptions') || 'No active subscriptions.';
            list.appendChild(empty);
            return;
        }

        subs.forEach(sub => {
            const icon     = _PROVIDER_ICONS[sub.provider] || _PROVIDER_ICONS.other;
            const date     = sub.created_at ? new Date(sub.created_at).toLocaleDateString() : '-';
            const provider = sub.provider.charAt(0).toUpperCase() + sub.provider.slice(1);

            const item = document.createElement('div');
            item.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center px-0 py-1 bg-transparent border-0';

            // Build left side using DOM API so endpoint_tail never touches innerHTML
            const leftSpan = document.createElement('span');
            leftSpan.className = 'text-muted';
            const iconEl = document.createElement('i');
            iconEl.className = `bi ${icon} me-1`;
            iconEl.setAttribute('aria-hidden', 'true');
            const tailSpan = document.createElement('span');
            tailSpan.className = 'font-monospace ms-1 opacity-50';
            tailSpan.textContent = `…${sub.endpoint_tail}`;
            leftSpan.appendChild(iconEl);
            leftSpan.appendChild(document.createTextNode(` ${provider} `));
            leftSpan.appendChild(tailSpan);

            // Build right side (date + remove button)
            const rightSpan = document.createElement('span');
            rightSpan.className = 'd-flex align-items-center gap-2';
            const dateSpan = document.createElement('span');
            dateSpan.className = 'text-muted';
            dateSpan.textContent = date;
            const btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-outline-danger py-0 px-1';
            btn.dataset.index = sub.index;
            btn.title = i18n?.t('settings.notif_remove_subscription') || 'Remove';
            const btnIcon = document.createElement('i');
            btnIcon.className = 'bi bi-x';
            btnIcon.setAttribute('aria-hidden', 'true');
            btn.appendChild(btnIcon);
            rightSpan.appendChild(dateSpan);
            rightSpan.appendChild(btn);

            item.appendChild(leftSpan);
            item.appendChild(rightSpan);

            btn.addEventListener('click', async (e) => {
                const clickedBtn = e.currentTarget;
                clickedBtn.disabled = true;
                await fetch('/api/push/subscriptions', {
                    method: 'DELETE',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ index: Number(clickedBtn.dataset.index) }),
                });
                await _subscribeToPush();
                _loadSubscriptionList();
            });
            list.appendChild(item);
        });
    } catch (e) {
        console.warn('Could not load subscriptions:', e);
    }
}

function initNotificationSettingsUI() {
    notificationManager._prefs = null; // refresh from server state on each open
    _refreshPermissionBanner();
    _refreshVapidWarning();
    _loadPrefsIntoUI();
    _loadSubscriptionList();

    // Enable button - requests permission then refreshes
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

    // Test button - uses server-side push so it works on iOS PWA too
    const testBtn = document.getElementById('notif-test-btn');
    if (testBtn && !testBtn._notifBound) {
        testBtn._notifBound = true;
        testBtn.addEventListener('click', async () => {
            const granted = await notificationManager.requestPermission();
            _refreshPermissionBanner();
            if (!granted) return;

            try {
                const res  = await fetch('/api/push/test', { method: 'POST', credentials: 'same-origin' });
                const data = await res.json();
                if (!res.ok) {
                    _showNotifMessage(data.error || 'Push test failed.', 'danger');
                    return;
                }
                if (data.delivered === 0) {
                    _showNotifMessage('Push sent but delivery failed - check server logs.', 'warning');
                    return;
                }
                // On iOS, the app must be backgrounded to display the notification.
                const hint = /iPhone|iPad|iPod/.test(navigator.userAgent)
                    ? ' Background or lock the app to see it.'
                    : '';
                const msg = (typeof i18n !== 'undefined') ? i18n.t('settings.notifications_test_body') : 'Notifications are working correctly.';
                _showNotifMessage(((msg && msg !== 'settings.notifications_test_body') ? msg : 'Push sent!') + hint);
            } catch (e) {
                _showNotifMessage('Push test error: ' + e.message, 'danger');
            }
        });
    }

    // Remove all subscriptions button
    const unsubAllBtn = document.getElementById('notif-unsub-all-btn');
    if (unsubAllBtn && !unsubAllBtn._notifBound) {
        unsubAllBtn._notifBound = true;
        unsubAllBtn.addEventListener('click', async () => {
            unsubAllBtn.disabled = true;
            try {
                // Remove all from server
                await fetch('/api/push/subscriptions', { method: 'DELETE', credentials: 'same-origin' });
                // Also unsubscribe the browser subscription on this device
                await _unsubscribeFromPush();
                _loadSubscriptionList();
                _refreshPermissionBanner();
                _showNotifMessage(i18n?.t('settings.notif_unsubscribed_all') || 'All subscriptions removed.');
            } catch (e) {
                _showNotifMessage('Error: ' + e.message, 'danger');
            } finally {
                unsubAllBtn.disabled = false;
            }
        });
    }
}
