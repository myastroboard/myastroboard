/**
 * spaceflight.js - Spaceflight section: launches, astronauts, space events
 * Uses XSS-safe DOM APIs only (no innerHTML).
 * API data comes from the Launch Library 2 cache endpoints.
 */

'use strict';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function _sfLoading(container) {
    DOMUtils.clear(container);
    const el = document.createElement('div');
    el.className = 'alert alert-info d-flex align-items-center gap-2';
    const spinner = document.createElement('span');
    spinner.className = 'spinner-border spinner-border-sm';
    spinner.setAttribute('role', 'status');
    el.appendChild(spinner);
    const txt = document.createElement('span');
    txt.setAttribute('data-i18n', 'common.loading');
    txt.textContent = i18n.t('common.loading', 'Loading…');
    el.appendChild(txt);
    container.appendChild(el);
}

function _sfError(container, msgKey, fallback) {
    DOMUtils.clear(container);
    const el = document.createElement('div');
    el.className = 'alert alert-warning';
    el.textContent = i18n.t(msgKey, fallback);
    container.appendChild(el);
}

function _sfCacheNotReady(container) {
    _sfError(container, 'common.cache_not_ready', 'Data is being fetched. Please try again shortly.');
}

// Launch/event times are the same real-world instant for every location, but
// displaying them in the browser's own timezone made all 3 locations show
// identical hours - not helpful when planning around a launch from a specific
// site. Resolved once per page load and reused by every date formatted below.
let _sfTimezone = null;
let _sfTimezonePromise = null;

function _sfEnsureTimezone() {
    if (_sfTimezonePromise) return _sfTimezonePromise;
    _sfTimezonePromise = fetchJSON('/api/locations/mine')
        .then(data => {
            const locations = (data && data.locations) || [];
            const active = locations.find(loc => loc.id === data.active_location_id);
            _sfTimezone = active?.timezone || null;
        })
        .catch(() => { _sfTimezone = null; });
    return _sfTimezonePromise;
}

/**
 * Format an ISO-8601 date string for display using the user locale, in the
 * caller's active observing location's timezone (with a "(UTC+x)" suffix)
 * when known, falling back to the browser's local timezone otherwise.
 * Returns the original string if parsing fails.
 */
function _sfFormatDate(isoStr) {
    if (!isoStr) return '-';
    try {
        const date = new Date(isoStr);
        const opts = {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
        };
        if (_sfTimezone) opts.timeZone = _sfTimezone;
        const formatted = date.toLocaleString(undefined, opts);
        const offset = _sfTimezone ? getUtcOffsetLabel(_sfTimezone, date) : null;
        return offset ? `${formatted} (${offset})` : formatted;
    } catch (_) {
        return isoStr;
    }
}

/**
 * Build and return a countdown string ("in X days Y hours") from now to target ISO date.
 * Returns null if the target date is in the past or invalid.
 */
function _sfCountdown(isoStr) {
    if (!isoStr) return null;
    const diff = new Date(isoStr) - Date.now();
    if (diff <= 0) return null;
    const totalMins = Math.floor(diff / 60000);
    const days = Math.floor(totalMins / 1440);
    const hours = Math.floor((totalMins % 1440) / 60);
    const mins = totalMins % 60;
    let parts = [];
    if (days > 0) parts.push(`${days}${i18n.t('spaceflight.countdown_d', 'd')}`);
    if (hours > 0 || days > 0) parts.push(`${hours}${i18n.t('spaceflight.countdown_h', 'h')}`);
    parts.push(`${mins}${i18n.t('spaceflight.countdown_m', 'm')}`);
    return parts.join(' ');
}

// Live countdown ticker - updates every second for the next launch hero card
let _sfCountdownTimer = null;
const _sfTranslateCache = new Map();

function _sfCurrentLang() {
    return (typeof i18n !== 'undefined' && typeof i18n.getCurrentLanguage === 'function')
        ? i18n.getCurrentLanguage()
        : 'en';
}

function _sfShouldOfferTranslation() {
    return _sfCurrentLang() !== 'en';
}

async function _sfTranslateTextOnDemand(originalText, targetLang) {
    const text = (originalText || '').trim();
    if (!text) return null;
    const cacheKey = `${targetLang}::${text}`;
    if (_sfTranslateCache.has(cacheKey)) {
        return _sfTranslateCache.get(cacheKey);
    }

    const response = await fetch('/api/translate/on-demand', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            text,
            source_lang: 'en',
            target_lang: targetLang,
        })
    });

    if (!response.ok) {
        throw new Error('translation_http_error');
    }

    const payload = await response.json();
    const translated = (payload && typeof payload.translated_text === 'string')
        ? payload.translated_text.trim()
        : '';
    if (!translated) {
        return null;
    }
    _sfTranslateCache.set(cacheKey, translated);
    return translated;
}

function _sfAttachTranslateToggle(textEl, originalText) {
    if (!textEl || !originalText || !_sfShouldOfferTranslation()) {
        return;
    }

    const parent = textEl.parentElement;
    if (!parent) {
        return;
    }

    const targetLang = _sfCurrentLang();
    let translatedText = null;
    let showingTranslated = false;

    const controls = document.createElement('div');
    controls.className = 'mt-1';

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'btn btn-link btn-sm p-0 align-baseline';
    toggle.textContent = i18n.t('spaceflight.translate_action', 'Translate');

    const hint = document.createElement('small');
    hint.className = 'text-muted ms-2';

    toggle.addEventListener('click', async () => {
        if (showingTranslated) {
            textEl.textContent = originalText;
            toggle.textContent = i18n.t('spaceflight.translate_action', 'Translate');
            hint.textContent = '';
            showingTranslated = false;
            return;
        }

        if (!translatedText) {
            toggle.disabled = true;
            hint.textContent = i18n.t('spaceflight.translating', 'Translating...');
            try {
                translatedText = await _sfTranslateTextOnDemand(originalText, targetLang);
            } catch (_) {
                translatedText = null;
            }
            toggle.disabled = false;
        }

        if (translatedText && translatedText !== originalText) {
            textEl.textContent = translatedText;
            toggle.textContent = i18n.t('spaceflight.show_original_action', 'Show original');
            hint.textContent = i18n.t('spaceflight.translated_via_free_service', 'Machine translated');
            showingTranslated = true;
        } else {
            hint.textContent = i18n.t('spaceflight.translation_unavailable', 'Translation unavailable for this text.');
        }
    });

    controls.appendChild(toggle);
    controls.appendChild(hint);
    parent.appendChild(controls);
}

function _sfStartLiveCountdown(netIso, valueEl) {
    if (_sfCountdownTimer) clearInterval(_sfCountdownTimer);
    function tick() {
        const val = _sfCountdown(netIso);
        if (val) {
            valueEl.textContent = val;
        } else {
            valueEl.textContent = i18n.t('spaceflight.launched', 'Launched!');
            clearInterval(_sfCountdownTimer);
            _sfCountdownTimer = null;
        }
    }
    tick();
    _sfCountdownTimer = setInterval(tick, 1000);
}

// ---------------------------------------------------------------------------
// Launch detail modal
// ---------------------------------------------------------------------------

function _sfShowLaunchModal(launch) {
    const titleEl = document.getElementById('sf-launch-modal-title');
    const bodyEl  = document.getElementById('sf-launch-modal-body');
    if (!titleEl || !bodyEl) return;

    titleEl.textContent = launch.name || '-';
    DOMUtils.clear(bodyEl);

    // ---- Helper: extract YouTube video ID from any YT URL variant ----
    function _ytId(url) {
        if (!url) return null;
        const m = url.match(/(?:youtube\.com\/(?:watch\?v=|live\/)|youtu\.be\/)([\w-]{11})/);
        return m ? m[1] : null;
    }

    // ---- Helper: build a YouTube embed iframe ----
    function _buildYtIframe(ytId) {
        const iframe = document.createElement('iframe');
        iframe.src = `https://www.youtube.com/embed/${ytId}?autoplay=0`;
        iframe.className = 'sf-modal-iframe w-100';
        iframe.setAttribute('allowfullscreen', '');
        iframe.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture';
        iframe.referrerPolicy = 'strict-origin-when-cross-origin';
        return iframe;
    }

    // ---- Helper: build the static image (with optional LIVE badge) ----
    function _buildStaticImage(showLiveBadge) {
        if (!launch.image_url) return null;
        const wrap = document.createElement('div');
        wrap.style.position = 'relative';
        const img = document.createElement('img');
        img.src = launch.image_url;
        img.alt = '';
        img.className = 'sf-modal-img w-100';
        img.loading = 'lazy';
        img.decoding = 'async';
        img.addEventListener('error', () => { wrap.style.display = 'none'; });
        wrap.appendChild(img);
        if (showLiveBadge) {
            const badge = document.createElement('span');
            badge.className = 'badge bg-danger sf-webcast-badge position-absolute top-0 end-0 m-2';
            const icon = document.createElement('i');
            icon.className = 'bi bi-broadcast me-1';
            badge.appendChild(icon);
            badge.appendChild(document.createTextNode(i18n.t('spaceflight.webcast_live', 'Webcast Live')));
            wrap.appendChild(badge);
        }
        return wrap;
    }

    // ---- Top media block ----
    const mediaSlot = document.createElement('div');
    bodyEl.appendChild(mediaSlot);

    if (launch.webcast_live) {
        // Show image with LIVE badge immediately, then replace with YouTube embed if found
        const imgEl = _buildStaticImage(true);
        if (imgEl) mediaSlot.appendChild(imgEl);

        fetch(`/api/spaceflight/launch/${encodeURIComponent(launch.id)}/vidurls`)
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                const urls = (data && data.vidURLs) || [];
                const ytUrl = urls.map(v => v.url).find(u => _ytId(u));
                if (ytUrl) {
                    DOMUtils.clear(mediaSlot);
                    mediaSlot.appendChild(_buildYtIframe(_ytId(ytUrl)));
                }
                // If no YouTube URL found, keep the image with LIVE badge
            })
            .catch(() => { /* keep static image on error */ });
    } else {
        // Not live - just show the static image
        const imgEl = _buildStaticImage(false);
        if (imgEl) mediaSlot.appendChild(imgEl);
    }

    const contentCard = document.createElement('div');
    contentCard.className = 'card m-3';
    const content = document.createElement('div');
    content.className = 'card-body';
    contentCard.appendChild(content);

    // English-only notice for non-EN users (mission descriptions are in English)
    const _modalLang = (typeof i18n !== 'undefined' && typeof i18n.getCurrentLanguage === 'function')
        ? i18n.getCurrentLanguage() : 'en';
    if (_modalLang !== 'en') {
        const notice = document.createElement('div');
        notice.className = 'alert alert-info d-flex align-items-center gap-2 py-2 mb-3';
        const noticeIcon = document.createElement('i');
        noticeIcon.className = 'bi bi-translate flex-shrink-0';
        notice.appendChild(noticeIcon);
        const noticeMsg = document.createElement('span');
        noticeMsg.textContent = i18n.t('spaceflight.english_only_notice', 'This content is only available in English.');
        notice.appendChild(noticeMsg);
        content.appendChild(notice);
    }

    // Status + badges row
    const badges = document.createElement('div');
    badges.className = 'd-flex flex-wrap gap-2 align-items-center mb-3';
    badges.appendChild(_sfStatusBadge(launch.status_abbrev));
    if (launch.webcast_live) {
        const wc = document.createElement('span');
        wc.className = 'badge bg-danger sf-webcast-badge';
        const icon = document.createElement('i');
        icon.className = 'bi bi-broadcast me-1';
        wc.appendChild(icon);
        wc.appendChild(document.createTextNode(i18n.t('spaceflight.webcast_live', 'Webcast Live')));
        badges.appendChild(wc);
    }
    if (launch.rocket_name) {
        const rkt = document.createElement('span');
        rkt.className = 'badge bg-dark';
        rkt.textContent = launch.rocket_name;
        badges.appendChild(rkt);
    }
    if (launch.orbit) {
        const orb = document.createElement('span');
        orb.className = 'badge bg-info text-dark';
        orb.textContent = launch.orbit;
        badges.appendChild(orb);
    }
    content.appendChild(badges);

    // Info grid
    function _row(labelKey, labelFallback, value) {
        if (!value) return;
        const row = document.createElement('div');
        row.className = 'row mb-2';
        const lc = document.createElement('div');
        lc.className = 'col-4 col-sm-3 text-muted small fw-semibold';
        lc.textContent = i18n.t(labelKey, labelFallback);
        const vc = document.createElement('div');
        vc.className = 'col-8 col-sm-9 small';
        vc.textContent = value;
        row.appendChild(lc);
        row.appendChild(vc);
        content.appendChild(row);
    }

    _row('spaceflight.agency',       'Agency',        launch.agency_name + (launch.agency_abbrev ? ` (${launch.agency_abbrev})` : ''));
    _row('spaceflight.pad',          'Launch pad',    launch.pad_name ? (launch.pad_name + (launch.pad_location_name ? `, ${launch.pad_location_name}` : '')) : null);
    _row('spaceflight.window',       'Launch Window', launch.window_start ? (_sfFormatDate(launch.window_start) + (launch.window_end && launch.window_end !== launch.window_start ? ` → ${_sfFormatDate(launch.window_end)}` : '')) : null);
    _row('spaceflight.mission',      'Mission',       launch.mission_name);
    _row('spaceflight.mission_type', 'Mission type',  launch.mission_type);
    _row('spaceflight.orbit',        'Orbit',         launch.orbit);

    if (launch.mission_description) {
        const desc = document.createElement('p');
        desc.className = 'small text-muted mt-2';
        desc.textContent = launch.mission_description;
        content.appendChild(desc);
        _sfAttachTranslateToggle(desc, launch.mission_description);
    }

    // Action buttons
    if (launch.video_url || launch.info_url) {
        const btns = document.createElement('div');
        btns.className = 'd-flex gap-2 mt-3 flex-wrap';
        if (launch.video_url) {
            const a = document.createElement('a');
            a.href = launch.video_url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.className = 'btn btn-sm btn-danger';
            const icon = document.createElement('i');
            icon.className = 'bi bi-play-circle me-1';
            a.appendChild(icon);
            a.appendChild(document.createTextNode(i18n.t('spaceflight.watch_live', 'Watch Live')));
            btns.appendChild(a);
        }
        if (launch.info_url) {
            const a = document.createElement('a');
            a.href = launch.info_url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.className = 'btn btn-sm btn-outline-secondary';
            const icon = document.createElement('i');
            icon.className = 'bi bi-info-circle me-1';
            a.appendChild(icon);
            a.appendChild(document.createTextNode(i18n.t('spaceflight.more_info', 'More info')));
            btns.appendChild(a);
        }
        content.appendChild(btns);
    }

    bodyEl.appendChild(contentCard);
    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('sf-launch-modal'));
    modal.show();
}

// Launch status → Bootstrap badge classes
const _STATUS_BADGE = {
    'Go':       'badge bg-success',
    'TBC':      'badge bg-secondary',
    'TBD':      'badge bg-secondary',
    'Hold':     'badge bg-warning text-dark',
    'In Flight':'badge bg-primary',
    'Success':  'badge bg-success',
    'Partial Failure': 'badge bg-warning text-dark',
    'Failure':  'badge bg-danger',
};

/**
 * Build a "data source" attribution footer element for the bottom of each spaceflight page.
 * Uses a safe anchor built via DOM APIs; the translated string may contain an <a> tag
 * for the link so we parse it manually rather than using innerHTML.
 */
function _sfSourceAttribution() {
    const footer = document.createElement('p');
    footer.className = 'sf-data-source text-muted small mt-4 text-center';

    const icon = document.createElement('i');
    icon.className = 'bi bi-database me-1';
    footer.appendChild(icon);

    // Parse the translation: text before <a>, link text, text after </a>
    const raw = i18n.t('spaceflight.data_source', 'Data and images provided by The Space Devs via Launch Library 2');
    const aMatch = raw.match(/^(.*?)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)<\/a>(.*)$/i);
    if (aMatch) {
        if (aMatch[1]) footer.appendChild(document.createTextNode(aMatch[1]));
        const link = document.createElement('a');
        link.href = aMatch[2];
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = aMatch[3];
        footer.appendChild(link);
        if (aMatch[4]) footer.appendChild(document.createTextNode(aMatch[4]));
    } else {
        footer.appendChild(document.createTextNode(raw));
    }

    return footer;
}

function _sfStatusBadge(abbrev) {
    const cls = _STATUS_BADGE[abbrev] || 'badge bg-secondary';
    const badge = document.createElement('span');
    badge.className = cls + ' sf-status-badge';
    badge.textContent = abbrev || '?';
    return badge;
}

// ---------------------------------------------------------------------------
// Launch Timeline
// ---------------------------------------------------------------------------

function loadSpaceflightLaunches() {
    const container = document.getElementById('spaceflight-launches-display');
    if (!container) return;
    _sfLoading(container);

    Promise.all([
        fetch('/api/spaceflight/launches').then(r => {
            if (r.status === 503) return Promise.reject('cache_not_ready');
            if (!r.ok) return Promise.reject('http_error');
            return r.json();
        }),
        _sfEnsureTimezone()
    ])
        .then(([data]) => _renderLaunches(container, data))
        .catch(err => {
            if (err === 'cache_not_ready') _sfCacheNotReady(container);
            else _sfError(container, 'spaceflight.launches_error', 'Failed to load launch data.');
        });
}

function _renderLaunches(container, data) {
    DOMUtils.clear(container);

    const upcoming = (data.upcoming && data.upcoming.results) || [];
    const past     = (data.past && data.past.results) || [];

    if (upcoming.length === 0 && past.length === 0) {
        _sfError(container, 'spaceflight.no_data', 'No data available.');
        return;
    }

    // ---- Next launch hero card ----
    if (upcoming.length > 0) {
        const next = upcoming[0];
        const hero = document.createElement('div');
        hero.className = 'sf-next-launch card mb-4 d-flex flex-row overflow-hidden';
        hero.style.cursor = 'pointer';
        hero.addEventListener('click', () => _sfShowLaunchModal(next));

        // Hero image
        if (next.image_url) {
            const img = document.createElement('img');
            img.src = next.image_url;
            img.alt = '';
            img.className = 'sf-hero-img';
            img.loading = 'lazy';
            img.decoding = 'async';
            img.addEventListener('error', () => { img.style.display = 'none'; });
            hero.appendChild(img);
        }

        const body = document.createElement('div');
        body.className = 'card-body';

        const label = document.createElement('p');
        label.className = 'text-muted small mb-1 sf-next-label';
        label.textContent = i18n.t('spaceflight.next_launch', 'Next Launch');
        body.appendChild(label);

        const title = document.createElement('h3');
        title.className = 'card-title';
        title.textContent = next.name || '-';
        body.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'd-flex flex-wrap gap-2 align-items-center mb-2';
        meta.appendChild(_sfStatusBadge(next.status_abbrev));
        if (next.webcast_live) {
            const wc = document.createElement('span');
            wc.className = 'badge bg-danger sf-webcast-badge';
            const wcIcon = document.createElement('i');
            wcIcon.className = 'bi bi-broadcast me-1';
            wc.appendChild(wcIcon);
            wc.appendChild(document.createTextNode(i18n.t('spaceflight.webcast_live', 'Webcast Live')));
            meta.appendChild(wc);
        }
        if (next.rocket_name) {
            const rkt = document.createElement('span');
            rkt.className = 'badge bg-dark';
            rkt.textContent = next.rocket_name;
            meta.appendChild(rkt);
        }
        body.appendChild(meta);

        // Live countdown
        const cdWrap = document.createElement('p');
        cdWrap.className = 'sf-countdown';
        const cdLabel = document.createElement('span');
        cdLabel.className = 'text-muted small me-1';
        cdLabel.textContent = i18n.t('spaceflight.t_minus', 'T-');
        cdWrap.appendChild(cdLabel);
        const cdValue = document.createElement('strong');
        cdWrap.appendChild(cdValue);
        body.appendChild(cdWrap);
        _sfStartLiveCountdown(next.net, cdValue);

        const date = document.createElement('p');
        date.className = 'text-muted small mb-0';
        date.textContent = _sfFormatDate(next.net);
        body.appendChild(date);

        if (next.pad_name) {
            const pad = document.createElement('p');
            pad.className = 'text-muted small mb-0';
            const icon = document.createElement('i');
            icon.className = 'bi bi-geo-alt me-1';
            pad.appendChild(icon);
            pad.appendChild(document.createTextNode(next.pad_name + (next.pad_location_name ? `, ${next.pad_location_name}` : '')));
            body.appendChild(pad);
        }

        if (next.agency_name) {
            const ag = document.createElement('p');
            ag.className = 'text-muted small mb-0';
            const agIcon = document.createElement('i');
            agIcon.className = 'bi bi-building me-1';
            ag.appendChild(agIcon);
            ag.appendChild(document.createTextNode(next.agency_name + (next.agency_abbrev ? ` (${next.agency_abbrev})` : '')));
            body.appendChild(ag);
        }

        hero.appendChild(body);
        container.appendChild(hero);
    }

    // ---- Upcoming launches list ----
    if (upcoming.length > 1) {
        const upcomingTitle = document.createElement('h5');
        upcomingTitle.className = 'mt-3 mb-2';
        const icon = document.createElement('i');
        icon.className = 'bi bi-rocket-takeoff me-2 text-danger';
        upcomingTitle.appendChild(icon);
        upcomingTitle.appendChild(document.createTextNode(i18n.t('spaceflight.upcoming_title', 'Upcoming Launches')));
        container.appendChild(upcomingTitle);

        const grid = document.createElement('div');
        grid.className = 'row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3 mb-4';
        upcoming.slice(1).forEach(launch => grid.appendChild(_makeLaunchCard(launch, false)));
        container.appendChild(grid);
    }

    // ---- Past launches ----
    if (past.length > 0) {
        const pastTitle = document.createElement('h5');
        pastTitle.className = 'mt-3 mb-2 text-muted';
        const icon = document.createElement('i');
        icon.className = 'bi bi-clock-history me-2';
        pastTitle.appendChild(icon);
        pastTitle.appendChild(document.createTextNode(i18n.t('spaceflight.past_title', 'Recent Launches')));
        container.appendChild(pastTitle);

        const grid = document.createElement('div');
        grid.className = 'row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3';
        past.forEach(launch => grid.appendChild(_makeLaunchCard(launch, true)));
        container.appendChild(grid);
    }

    container.appendChild(_sfSourceAttribution());
}

function _makeLaunchCard(launch, isPast) {
    const col = document.createElement('div');
    col.className = 'col';

    const card = document.createElement('div');
    card.className = 'card h-100 sf-launch-card d-flex flex-row overflow-hidden' + (isPast ? ' sf-launch-past' : '');
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => _sfShowLaunchModal(launch));

    // Card image - left side, full card height
    if (launch.image_url) {
        const img = document.createElement('img');
        img.src = launch.image_url;
        img.alt = '';
        img.className = 'sf-launch-card-img';
        img.loading = 'eager';
        img.decoding = 'async';
        img.addEventListener('error', () => { img.style.display = 'none'; });
        card.appendChild(img);
    }

    const body = document.createElement('div');
    body.className = 'card-body';

    // Title row
    const title = document.createElement('h6');
    title.className = 'card-title';
    title.textContent = launch.name || '-';
    body.appendChild(title);

    // Status + rocket + webcast badges
    const meta = document.createElement('div');
    meta.className = 'd-flex flex-wrap gap-1 align-items-center mb-2';
    meta.appendChild(_sfStatusBadge(launch.status_abbrev));
    if (launch.webcast_live) {
        const wc = document.createElement('span');
        wc.className = 'badge bg-danger sf-webcast-badge';
        const icon = document.createElement('i');
        icon.className = 'bi bi-broadcast';
        wc.appendChild(icon);
        meta.appendChild(wc);
    }
    if (launch.rocket_name) {
        const rkt = document.createElement('span');
        rkt.className = 'badge bg-secondary';
        rkt.textContent = launch.rocket_name;
        meta.appendChild(rkt);
    }
    if (launch.orbit) {
        const orb = document.createElement('span');
        orb.className = 'badge bg-info text-dark';
        orb.textContent = launch.orbit;
        meta.appendChild(orb);
    }
    body.appendChild(meta);

    // Date
    if (launch.net) {
        const date = document.createElement('p');
        date.className = 'text-muted small mb-1';
        const icon = document.createElement('i');
        icon.className = 'bi bi-calendar3 me-1';
        date.appendChild(icon);
        date.appendChild(document.createTextNode(_sfFormatDate(launch.net)));
        body.appendChild(date);
    }

    // Pad
    if (launch.pad_name) {
        const pad = document.createElement('p');
        pad.className = 'text-muted small mb-1';
        const icon = document.createElement('i');
        icon.className = 'bi bi-geo-alt me-1';
        pad.appendChild(icon);
        pad.appendChild(document.createTextNode(launch.pad_name));
        body.appendChild(pad);
    }

    // Agency label
    if (launch.agency_name) {
        const ag = document.createElement('p');
        ag.className = 'text-muted small mb-0 mt-auto';
        const icon = document.createElement('i');
        icon.className = 'bi bi-building me-1';
        ag.appendChild(icon);
        ag.appendChild(document.createTextNode(launch.agency_name + (launch.agency_abbrev ? ` (${launch.agency_abbrev})` : '')));
        body.appendChild(ag);
    }

    card.appendChild(body);
    col.appendChild(card);
    return col;
}

// ---------------------------------------------------------------------------
// Astronauts & Human Spaceflight
// ---------------------------------------------------------------------------

function loadSpaceflightAstronauts() {
    const container = document.getElementById('spaceflight-astronauts-display');
    if (!container) return;
    _sfLoading(container);

    fetch('/api/spaceflight/astronauts')
        .then(r => {
            if (r.status === 503) return Promise.reject('cache_not_ready');
            if (!r.ok) return Promise.reject('http_error');
            return r.json();
        })
        .then(data => _renderAstronauts(container, data))
        .catch(err => {
            if (err === 'cache_not_ready') _sfCacheNotReady(container);
            else _sfError(container, 'spaceflight.astronauts_error', 'Failed to load astronaut data.');
        });
}

function _renderAstronauts(container, data) {
    DOMUtils.clear(container);

    // Warn non-English users that bios are English-only
    const _astLang = (typeof i18n !== 'undefined' && typeof i18n.getCurrentLanguage === 'function')
        ? i18n.getCurrentLanguage() : 'en';
    if (_astLang !== 'en') {
        const notice = document.createElement('div');
        notice.className = 'alert alert-info d-flex align-items-center gap-2 py-2 mb-3';
        const noticeIcon = document.createElement('i');
        noticeIcon.className = 'bi bi-translate flex-shrink-0';
        notice.appendChild(noticeIcon);
        const noticeMsg = document.createElement('span');
        noticeMsg.textContent = i18n.t('spaceflight.english_only_notice', 'This content is only available in English.');
        notice.appendChild(noticeMsg);
        container.appendChild(notice);
    }

    // Active station expedition blocks (ISS, CSS, etc.)
    const expeditions = (data.iss_crew && data.iss_crew.expeditions) || [];
    const hasExpeditionCrew = expeditions.some(e => e.crew && e.crew.length > 0);
    expeditions.forEach(expedition => {
        if (!expedition.crew || expedition.crew.length === 0) return;
        const section = document.createElement('div');
        section.className = 'mb-4';

        const header = document.createElement('h5');
        header.className = 'mb-3';
        const icon = document.createElement('i');
        icon.className = (expedition.station_abbrev === 'ISS' ? 'bi bi-iss' : 'bi bi-stars') + ' me-2';
        header.appendChild(icon);
        header.appendChild(document.createTextNode(
            expedition.name || expedition.station_name || i18n.t('spaceflight.station_crew_title', 'Current Station Crew')
        ));
        section.appendChild(header);

        const grid = document.createElement('div');
        grid.className = 'row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-6 g-3 mb-2';
        expedition.crew.forEach(member => grid.appendChild(_makeCrewCard(member)));
        section.appendChild(grid);
        container.appendChild(section);

        const hr = document.createElement('hr');
        container.appendChild(hr);
    });

    // All astronauts in space
    const astronauts = (data.astronauts_in_space && data.astronauts_in_space.results) || [];

    if (astronauts.length === 0 && !hasExpeditionCrew) {
        const noData = document.createElement('div');
        noData.className = 'alert alert-info d-flex align-items-center gap-2';
        const noDataIcon = document.createElement('i');
        noDataIcon.className = 'bi bi-info-circle flex-shrink-0';
        noData.appendChild(noDataIcon);
        const noDataMsg = document.createElement('span');
        noDataMsg.textContent = i18n.t('spaceflight.no_data', 'No astronaut data available at this time.');
        noData.appendChild(noDataMsg);
        container.appendChild(noData);
        container.appendChild(_sfSourceAttribution());
        return;
    }

    if (astronauts.length > 0) {
        const allTitle = document.createElement('h5');
        allTitle.className = 'mb-3';
        const icon2 = document.createElement('i');
        icon2.className = 'bi bi-people me-2 text-info';
        allTitle.appendChild(icon2);
        allTitle.appendChild(document.createTextNode(
            i18n.t('spaceflight.all_in_space', 'People Currently in Space') +
            ` (${data.astronauts_in_space.count || astronauts.length})`
        ));
        container.appendChild(allTitle);

        const grid = document.createElement('div');
        grid.className = 'row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 row-cols-xl-6 g-3';
        astronauts.forEach(ast => grid.appendChild(_makeAstronautCard(ast)));
        container.appendChild(grid);
    }

    container.appendChild(_sfSourceAttribution());
}

// Always renders a square image slot: real photo or person placeholder.
function _sfCrewImg(src, eager) {
    if (src) {
        const img = document.createElement('img');
        img.src = src;
        img.alt = '';
        img.className = 'card-img-top sf-crew-img';
        img.loading = eager ? 'eager' : 'lazy';
        img.decoding = 'async';
        img.addEventListener('load', () => img.classList.add('sf-img-loaded'));
        img.addEventListener('error', () => img.replaceWith(_sfCrewImg(null)));
        return img;
    }
    const ph = document.createElement('div');
    ph.className = 'sf-crew-placeholder';
    const icon = document.createElement('i');
    icon.className = 'bi bi-person-fill';
    ph.appendChild(icon);
    return ph;
}

function _makeCrewCard(member) {
    const col = document.createElement('div');
    col.className = 'col';

    const card = document.createElement('div');
    card.className = 'card h-100 text-center sf-crew-card';

    card.appendChild(_sfCrewImg(member.profile_image, true));

    const body = document.createElement('div');
    body.className = 'card-body p-2';

    const name = document.createElement('p');
    name.className = 'card-title small fw-semibold mb-1';
    name.textContent = member.name || '-';
    body.appendChild(name);

    if (member.role) {
        const role = document.createElement('p');
        role.className = 'text-muted small mb-0';
        role.textContent = member.role;
        body.appendChild(role);
    }

    if (member.agency_abbrev) {
        const agency = document.createElement('span');
        agency.className = 'badge bg-secondary';
        agency.textContent = member.agency_abbrev;
        body.appendChild(agency);
    }

    card.appendChild(body);
    col.appendChild(card);
    return col;
}

function _makeAstronautCard(ast) {
    const col = document.createElement('div');
    col.className = 'col';

    const card = document.createElement('div');
    card.className = 'card h-100 text-center sf-astronaut-card';

    card.appendChild(_sfCrewImg(ast.profile_image, false));

    const body = document.createElement('div');
    body.className = 'card-body p-2';

    const name = document.createElement('p');
    name.className = 'card-title small fw-semibold mb-1';
    name.textContent = ast.name || '-';
    body.appendChild(name);

    if (ast.nationality) {
        const nat = document.createElement('p');
        nat.className = 'text-muted small mb-1';
        nat.textContent = ast.nationality;
        body.appendChild(nat);
    }

    if (ast.agency_abbrev || ast.station_abbrev) {
        const badges = document.createElement('div');
        badges.className = 'mb-1';
        if (ast.agency_abbrev) {
            const agency = document.createElement('span');
            agency.className = 'badge bg-secondary me-1';
            agency.textContent = ast.agency_abbrev;
            badges.appendChild(agency);
        }
        if (ast.station_abbrev) {
            const station = document.createElement('span');
            const stationClass = ast.station_abbrev === 'ISS' ? 'bg-info text-dark'
                               : ast.station_abbrev === 'CSS' ? 'bg-warning text-dark'
                               : 'bg-secondary';
            station.className = `badge ${stationClass}`;
            station.textContent = ast.station_abbrev;
            badges.appendChild(station);
        }
        body.appendChild(badges);
    }

    if (ast.bio) {
        const bio = document.createElement('p');
        bio.className = 'text-muted small mt-2 mb-0 sf-astronaut-bio';
        bio.textContent = ast.bio;
        body.appendChild(bio);
        _sfAttachTranslateToggle(bio, ast.bio);
    }

    card.appendChild(body);
    col.appendChild(card);
    return col;
}

// ---------------------------------------------------------------------------
// Space Events
// ---------------------------------------------------------------------------

function loadSpaceflightEvents() {
    const container = document.getElementById('spaceflight-events-display');
    if (!container) return;
    _sfLoading(container);

    Promise.all([
        fetch('/api/spaceflight/events').then(r => {
            if (r.status === 503) return Promise.reject('cache_not_ready');
            if (!r.ok) return Promise.reject('http_error');
            return r.json();
        }),
        _sfEnsureTimezone()
    ])
        .then(([data]) => _renderSpaceEvents(container, data))
        .catch(err => {
            if (err === 'cache_not_ready') _sfCacheNotReady(container);
            else _sfError(container, 'spaceflight.events_error', 'Failed to load space events.');
        });
}

function _renderSpaceEvents(container, data) {
    DOMUtils.clear(container);

    // Warn non-English users that event descriptions are English-only
    const lang = (typeof i18n !== 'undefined' && typeof i18n.getCurrentLanguage === 'function')
        ? i18n.getCurrentLanguage() : 'en';
    if (lang !== 'en') {
        const notice = document.createElement('div');
        notice.className = 'alert alert-info d-flex align-items-center gap-2 py-2';
        const icon = document.createElement('i');
        icon.className = 'bi bi-translate flex-shrink-0';
        notice.appendChild(icon);
        const msg = document.createElement('span');
        msg.textContent = i18n.t('spaceflight.english_only_notice', 'This content is only available in English.');
        notice.appendChild(msg);
        container.appendChild(notice);
    }

    const events = (data && data.results) || [];
    if (events.length === 0) {
        _sfError(container, 'spaceflight.no_events', 'No upcoming space events found.');
        return;
    }

    const list = document.createElement('div');
    list.className = 'sf-events-list';
    events.forEach(ev => list.appendChild(_makeEventCard(ev)));
    container.appendChild(list);

    container.appendChild(_sfSourceAttribution());
}

function _makeEventCard(ev) {
    const card = document.createElement('div');
    card.className = 'card mb-3 sf-event-card d-flex flex-row overflow-hidden';

    // Left thumbnail, same visual system as launch cards.
    if (ev.image_url) {
        const img = document.createElement('img');
        img.src = ev.image_url;
        img.alt = '';
        img.className = 'sf-events-card-img';
        img.loading = 'lazy';
        img.decoding = 'async';
        img.addEventListener('error', () => { img.style.display = 'none'; });
        card.appendChild(img);
    }

    const body = document.createElement('div');
    body.className = 'card-body';

    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-start gap-2 flex-wrap';

    const titleWrap = document.createElement('div');
    const title = document.createElement('h6');
    title.className = 'card-title mb-1';
    title.textContent = ev.name || '-';
    titleWrap.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'd-flex flex-wrap gap-1 align-items-center';
    if (ev.type_name) {
        const type = document.createElement('span');
        type.className = 'badge bg-info text-dark';
        type.textContent = ev.type_name;
        meta.appendChild(type);
    }
    if (ev.webcast_live) {
        const live = document.createElement('span');
        live.className = 'badge bg-danger sf-webcast-badge';
        const liveIcon = document.createElement('i');
        liveIcon.className = 'bi bi-broadcast me-1';
        live.appendChild(liveIcon);
        live.appendChild(document.createTextNode(i18n.t('spaceflight.webcast_live', 'Webcast Live')));
        meta.appendChild(live);
    }
    if (meta.childElementCount > 0) {
        titleWrap.appendChild(meta);
    }
    header.appendChild(titleWrap);

    if (ev.date) {
        const date = document.createElement('div');
        date.className = 'text-muted small text-end flex-shrink-0';
        const icon = document.createElement('i');
        icon.className = 'bi bi-calendar3 me-1';
        date.appendChild(icon);
        date.appendChild(document.createTextNode(_sfFormatDate(ev.date)));
        const countdown = _sfCountdown(ev.date);
        if (countdown) {
            const cd = document.createElement('div');
            cd.className = 'sf-event-countdown small';
            cd.textContent = countdown;
            date.appendChild(cd);
        }
        header.appendChild(date);
    }
    body.appendChild(header);

    if (ev.description) {
        const desc = document.createElement('p');
        desc.className = 'card-text text-muted small mt-2 mb-1';
        desc.textContent = ev.description;
        body.appendChild(desc);
        _sfAttachTranslateToggle(desc, ev.description);
    }

    if (ev.location) {
        const loc = document.createElement('p');
        loc.className = 'text-muted small mb-0';
        const icon = document.createElement('i');
        icon.className = 'bi bi-geo-alt me-1';
        loc.appendChild(icon);
        loc.appendChild(document.createTextNode(ev.location));
        body.appendChild(loc);
    }

    if (ev.programs && ev.programs.length > 0) {
        const progs = document.createElement('div');
        progs.className = 'd-flex flex-wrap gap-1 mt-2';
        ev.programs.forEach(p => {
            const badge = document.createElement('span');
            badge.className = 'badge bg-dark';
            badge.textContent = p;
            progs.appendChild(badge);
        });
        body.appendChild(progs);
    }

    if (ev.video_url || ev.news_url) {
        const actions = document.createElement('div');
        actions.className = 'd-flex gap-2 mt-3 flex-wrap';

        if (ev.video_url) {
            const videoLink = document.createElement('a');
            videoLink.href = ev.video_url;
            videoLink.target = '_blank';
            videoLink.rel = 'noopener noreferrer';
            videoLink.className = ev.webcast_live ? 'btn btn-sm btn-danger' : 'btn btn-sm btn-outline-danger';

            const videoIcon = document.createElement('i');
            videoIcon.className = 'bi bi-play-circle me-1';
            videoLink.appendChild(videoIcon);
            videoLink.appendChild(document.createTextNode(i18n.t('spaceflight.watch_live', 'Watch Live')));
            actions.appendChild(videoLink);
        }

        if (ev.news_url) {
            const infoLink = document.createElement('a');
            infoLink.href = ev.news_url;
            infoLink.target = '_blank';
            infoLink.rel = 'noopener noreferrer';
            infoLink.className = 'btn btn-sm btn-outline-secondary';

            const infoIcon = document.createElement('i');
            infoIcon.className = 'bi bi-info-circle me-1';
            infoLink.appendChild(infoIcon);
            infoLink.appendChild(document.createTextNode(i18n.t('spaceflight.more_info', 'More info')));
            actions.appendChild(infoLink);
        }

        body.appendChild(actions);
    }

    card.appendChild(body);
    return card;
}
