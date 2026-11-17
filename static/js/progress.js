/**
 * My Progress (v1.9) - the Astrodex "Progress" sub-tab: badges, next milestones, challenges.
 *
 * Everything shown is computed by the server from the user's own Observation Log and
 * Astrodex (GET /api/achievements, GET /api/achievements/challenges); nothing here invents
 * a figure. The tone is sober on purpose: a quiet "New" marker the first time a badge is
 * shown, no animation, no notification, and the whole page can be turned off in
 * My settings -> Customize.
 *
 * Also holds the label helpers the year in review (year_review.js) shares.
 */

/* global DOMUtils, i18n, fetchJSON, appUrl, createModal, openModal, openShareCard, createShareButton,
   buildWishlistButton, getConstellationDisplayName, strToTranslateKey, currentUserPreferences,
   COLLECTION_CATALOGUE_LABEL_KEYS, openYearReview */

const progressState = {
    // Incremented on every load so a slow response cannot overwrite a newer page.
    token: 0,
    listenersBound: false,
};

/** i18n with an English fallback, like every other module. */
function _prT(key, fallback, params) {
    if (typeof i18n === 'undefined' || typeof i18n.t !== 'function') return fallback;
    const translated = i18n.t(key, params);
    return translated && translated !== key ? translated : fallback;
}

/** Display name of a catalogue id ("Herschel400" -> "Herschel 400"). */
function progressCatalogueLabel(catalogue) {
    const keys = typeof COLLECTION_CATALOGUE_LABEL_KEYS !== 'undefined' ? COLLECTION_CATALOGUE_LABEL_KEYS : {};
    const key = keys[catalogue];
    return key ? _prT(key, catalogue) : String(catalogue || '');
}

/** Plural label of an object class ("galaxy" -> "Galaxies"). */
function progressClassLabel(objectClass) {
    return _prT(`progress.class_${objectClass}`, String(objectClass || ''));
}

/** Localized object type ("Emission Nebula"). */
function progressTypeLabel(type) {
    const raw = String(type || '').trim();
    if (!raw) return '';
    if (typeof strToTranslateKey === 'function') return _prT(`skytonight.type_${strToTranslateKey(raw)}`, raw);
    return raw;
}

function progressConstellationLabel(name) {
    if (typeof getConstellationDisplayName === 'function') return getConstellationDisplayName(name);
    return String(name || '');
}

/** A YYYY-MM-DD day as a long local date. */
function progressDateLabel(day, options = { day: 'numeric', month: 'long', year: 'numeric' }) {
    if (!day) return '';
    const date = new Date(`${day}T12:00:00`);
    if (Number.isNaN(date.getTime())) return String(day);
    const lang = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : undefined;
    return date.toLocaleDateString(lang, options);
}

/** "12h30" / "45 min" from minutes, through the share card helper when available. */
function progressHours(minutes) {
    if (typeof _shFormatMinutes === 'function') {
        const text = _shFormatMinutes(minutes);
        if (text) return text;
    }
    const value = Number(minutes) || 0;
    return _prT('session_analytics.minutes_short', `${Math.round(value)} min`, { minutes: Math.round(value) });
}

function progressAchievementsEnabled() {
    return typeof currentUserPreferences === 'undefined' || currentUserPreferences?.achievements_enabled !== false;
}

/** Show or hide the Progress sub-tab according to the user's preference. */
function applyProgressVisibility() {
    const enabled = progressAchievementsEnabled();
    document.querySelectorAll('.progress-nav-item').forEach((item) => item.classList.toggle('d-none', !enabled));
}

// ── Badge texts ─────────────────────────────────────────────────────────────

/** Name and description of a badge, from its own keys or its rule's templated keys. */
function progressBadgeTexts(badge) {
    const catalogue = progressCatalogueLabel(badge.catalogue);
    const params = { count: badge.target, catalogue };
    if (badge.rule === 'first_class' || badge.rule === 'dark_site' || badge.rule === 'new_moon_night') {
        return {
            name: _prT(`progress.badges.${badge.id}.name`, badge.id),
            description: _prT(`progress.badges.${badge.id}.description`, ''),
        };
    }
    const rule = badge.complete_catalogue ? 'catalogue_complete' : badge.rule;
    return {
        name: _prT(`progress.rules.${rule}.name`, `${catalogue} ${badge.target}`, params),
        description: _prT(`progress.rules.${rule}.description`, '', params),
    };
}

function _prIsHours(badge) {
    return badge.rule === 'integration_hours' || badge.rule === 'single_target_hours';
}

function _prNumber(value) {
    const number = Number(value) || 0;
    return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

/** "7 / 10", or "7.5 h / 10 h" for an hours badge. */
function progressBadgeCounter(badge) {
    if (_prIsHours(badge)) {
        return _prT('progress.counter_hours', `${_prNumber(badge.current)} h / ${badge.target} h`, {
            current: _prNumber(badge.current),
            target: badge.target,
        });
    }
    return `${_prNumber(badge.current)} / ${badge.target}`;
}

/** "3 more Messier objects for the next badge" and the like. */
function progressRemainingText(badge) {
    const remaining = Math.max(0, Number(badge.target) - Number(badge.current));
    const params = {
        remaining: _prIsHours(badge) ? _prNumber(Math.round(remaining * 10) / 10) : _prNumber(remaining),
        catalogue: progressCatalogueLabel(badge.catalogue),
    };
    return _prT(`progress.remaining.${badge.rule}`, '', params);
}

// ── Rendering helpers ───────────────────────────────────────────────────────

function _prSection(container) {
    DOMUtils.clear(container);
    return container;
}

function _prEmpty(container, message, icon = 'bi bi-stars') {
    const empty = document.createElement('div');
    empty.className = 'progress-empty text-muted small';
    DOMUtils.append(empty, DOMUtils.createIcon(`${icon} icon-inline`), ` ${message}`);
    container.appendChild(empty);
}

function _prProgressBar(current, target, label) {
    const ratio = target > 0 ? Math.max(0, Math.min(1, Number(current) / Number(target))) : 0;
    const bar = document.createElement('div');
    bar.className = 'progress progress-badge-bar';
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-label', label);
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', String(target));
    bar.setAttribute('aria-valuenow', String(current));
    const fill = document.createElement('div');
    fill.className = 'progress-bar';
    // Per-instance dynamic width: the documented Bootstrap progress-bar exception.
    fill.style.width = `${Math.round(ratio * 100)}%`;
    bar.appendChild(fill);
    return bar;
}

function _prIcon(badge) {
    const wrapper = document.createElement('div');
    wrapper.className = `progress-badge-icon${badge.earned ? ' is-earned' : ''}`;
    wrapper.appendChild(DOMUtils.createIcon(`bi ${badge.icon}`));
    return wrapper;
}

// ── Header ──────────────────────────────────────────────────────────────────

function _prRenderStats(payload) {
    const container = document.getElementById('progress-stats');
    if (!container) return;
    const summary = payload.summary || { earned: 0, total: 0 };
    const figures = [
        {
            icon: 'bi-stars',
            value: String(payload.objects_captured ?? 0),
            label: _prT('progress.stat_objects', 'Objects captured'),
            hint: _prT('progress.stat_objects_hint', 'Logbook and Astrodex together'),
        },
    ];
    (payload.catalogues || []).forEach((row) => {
        if (!row.captured && row.catalogue !== 'Messier') return;
        figures.push({
            icon: 'bi-grid-3x3-gap',
            value: `${row.captured} / ${row.total}`,
            label: progressCatalogueLabel(row.catalogue),
        });
    });
    DOMUtils.buildStatPlate(container, {
        hero: {
            value: `${summary.earned} / ${summary.total}`,
            label: _prT('progress.stat_badges', 'Badges earned'),
            hint: _prT('progress.stat_badges_hint', 'Computed from what you actually logged'),
        },
        figures,
    });
}

// ── Next within reach ───────────────────────────────────────────────────────

function _prRenderNext(payload) {
    const container = document.getElementById('progress-next');
    if (!container) return;
    _prSection(container);
    const items = payload.next_within_reach || [];
    if (!items.length) {
        _prEmpty(
            container,
            payload.summary?.earned
                ? _prT('progress.next_none', 'Every badge you have started is earned. Pick a challenge below to start a new one.')
                : _prT('progress.next_start', 'Log your first night or add an object to your Astrodex: your first badges will follow.'),
            'bi bi-flag'
        );
        return;
    }
    const list = document.createElement('div');
    list.className = 'progress-next-list';
    items.forEach((badge) => {
        const texts = progressBadgeTexts(badge);
        const row = document.createElement('div');
        row.className = 'progress-next-item';

        const body = document.createElement('div');
        body.className = 'progress-next-body';
        const title = document.createElement('div');
        title.className = 'progress-next-title';
        title.textContent = texts.name;
        const counter = document.createElement('span');
        counter.className = 'progress-next-counter';
        counter.textContent = progressBadgeCounter(badge);
        title.appendChild(counter);
        const remaining = document.createElement('div');
        remaining.className = 'small text-muted';
        remaining.textContent = progressRemainingText(badge);
        DOMUtils.append(body, title, _prProgressBar(badge.current, badge.target, texts.name), remaining);

        row.appendChild(_prIcon(badge));
        row.appendChild(body);
        if (badge.rule === 'catalogue_count' && badge.catalogue) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-sm btn-outline-primary progress-next-action';
            DOMUtils.append(
                button,
                DOMUtils.createIcon('bi bi-moon-stars icon-inline'),
                ` ${_prT('progress.visible_tonight', 'Visible tonight')}`
            );
            button.addEventListener('click', () => openMissingTonight(badge.catalogue));
            row.appendChild(button);
        }
        list.appendChild(row);
    });
    container.appendChild(list);
}

/** Modal listing the objects of a catalogue still missing and observable tonight. */
async function openMissingTonight(catalogue) {
    const label = progressCatalogueLabel(catalogue);
    const body = document.createElement('div');
    body.appendChild(DOMUtils.createSpinnerWrapper(_prT('common.loading', 'Loading...')));
    createModal(_prT('progress.missing_title', 'Still to capture, visible tonight: {catalogue}', { catalogue: label }), body, 'lg');
    openModal('modal_lg_close');

    let payload = null;
    try {
        payload = await fetchJSON(`/api/achievements/missing-tonight?catalogue=${encodeURIComponent(catalogue)}`);
    } catch (error) {
        console.error('Error loading the missing objects visible tonight:', error);
    }
    DOMUtils.clear(body);
    if (!payload) {
        _prEmpty(body, _prT('progress.load_error', 'Could not load your progress.'), 'bi bi-exclamation-triangle');
        return;
    }
    const intro = document.createElement('p');
    intro.className = 'small text-muted';
    intro.textContent = _prT(
        'progress.missing_intro',
        'Objects of this catalogue you have not captured yet, observable tonight within your SkyTonight constraints, longest first.'
    );
    body.appendChild(intro);
    if (!payload.targets.length) {
        _prEmpty(body, _prT('progress.missing_none', 'Nothing left in this catalogue is observable from here tonight.'), 'bi bi-cloud-moon');
        return;
    }
    const list = document.createElement('ul');
    list.className = 'list-group progress-target-list';
    payload.targets.forEach((target) => {
        const item = document.createElement('li');
        item.className = 'list-group-item d-flex flex-wrap align-items-center gap-2';
        const name = document.createElement('div');
        name.className = 'flex-grow-1';
        const strong = document.createElement('strong');
        strong.textContent = target.name;
        name.appendChild(strong);
        const details = [
            target.preferred_name !== target.name ? target.preferred_name : '',
            progressTypeLabel(target.object_type),
            progressConstellationLabel(target.constellation),
        ].filter(Boolean);
        if (details.length) {
            const small = document.createElement('div');
            small.className = 'small text-muted';
            small.textContent = details.join(' - ');
            name.appendChild(small);
        }
        const hours = document.createElement('span');
        hours.className = 'badge text-bg-secondary';
        hours.textContent = _prT('progress.hours_tonight', '{hours} h tonight', { hours: _prNumber(target.observable_hours) });
        item.appendChild(name);
        if (target.transit_local_time) {
            const transit = document.createElement('span');
            transit.className = 'small text-muted';
            transit.textContent = _prT('progress.transit_at', 'Highest at {time}', { time: target.transit_local_time });
            item.appendChild(transit);
        }
        item.appendChild(hours);
        if (typeof buildWishlistButton === 'function') {
            item.appendChild(buildWishlistButton({ name: target.name, catalogue }, false));
        }
        list.appendChild(item);
    });
    body.appendChild(list);
}

// ── Badges ──────────────────────────────────────────────────────────────────

function shareBadge(badge, catalogueRows) {
    const texts = progressBadgeTexts(badge);
    const pictures = badge.rule === 'catalogue_count'
        ? ((catalogueRows || []).find((row) => row.catalogue === badge.catalogue)?.pictures || [])
        : [];
    let hero = null;
    if (badge.rule === 'catalogue_count') {
        hero = { value: _prNumber(badge.current), unit: `/ ${badge.target}`, label: progressCatalogueLabel(badge.catalogue) };
    } else if (_prIsHours(badge)) {
        hero = { value: _prNumber(badge.current), unit: 'h', label: _prT('share.hero_integration', 'total integration') };
    } else if (badge.rule === 'constellations') {
        hero = { value: _prNumber(badge.current), label: _prT('progress.share_constellations', 'constellations') };
    }
    openShareCard({
        title: _prT('progress.share_title', 'Share this badge'),
        filename: `badge-${badge.id}`,
        kicker: _prT('progress.share_kicker', 'Achievement'),
        heading: texts.name,
        subheading: texts.description,
        hero,
        mosaicUrls: pictures.map((filename) => appUrl(`/api/astrodex/images/${encodeURIComponent(filename)}`)),
        facts: [
            {
                id: 'earned',
                label: _prT('progress.share_earned', 'Earned on'),
                value: badge.earned_on ? progressDateLabel(badge.earned_on) : '',
            },
        ],
    });
}

function _prBadgeCard(badge, catalogueRows) {
    const texts = progressBadgeTexts(badge);
    const card = document.createElement('div');
    card.className = `progress-badge${badge.earned ? ' is-earned' : ''}`;

    const top = document.createElement('div');
    top.className = 'progress-badge-top';
    top.appendChild(_prIcon(badge));
    const heading = document.createElement('div');
    heading.className = 'progress-badge-heading';
    const name = document.createElement('div');
    name.className = 'progress-badge-name';
    name.textContent = texts.name;
    heading.appendChild(name);
    if (badge.new) {
        const pill = document.createElement('span');
        pill.className = 'badge rounded-pill text-bg-warning progress-badge-new';
        pill.textContent = _prT('progress.new', 'New');
        heading.appendChild(pill);
    }
    top.appendChild(heading);
    card.appendChild(top);

    const description = document.createElement('div');
    description.className = 'progress-badge-description small text-muted';
    description.textContent = texts.description;
    card.appendChild(description);

    const footer = document.createElement('div');
    footer.className = 'progress-badge-footer';
    if (badge.earned) {
        const earned = document.createElement('span');
        earned.className = 'small progress-badge-earned';
        DOMUtils.append(
            earned,
            DOMUtils.createIcon('bi bi-check-circle-fill icon-inline'),
            ` ${badge.earned_on
                ? _prT('progress.earned_on', 'Earned on {date}', { date: progressDateLabel(badge.earned_on) })
                : _prT('progress.earned', 'Earned')}`
        );
        footer.appendChild(earned);
        if (typeof createShareButton === 'function') {
            footer.appendChild(createShareButton(() => shareBadge(badge, catalogueRows)));
        }
    } else {
        const counter = document.createElement('div');
        counter.className = 'small text-muted';
        counter.textContent = progressBadgeCounter(badge);
        footer.appendChild(_prProgressBar(badge.current, badge.target, texts.name));
        footer.appendChild(counter);
    }
    card.appendChild(footer);
    return card;
}

function _prRenderBadges(payload) {
    const container = document.getElementById('progress-badges');
    if (!container) return;
    _prSection(container);
    const badges = payload.badges || [];
    (payload.groups || []).forEach((group) => {
        const members = badges.filter((badge) => badge.group === group);
        if (!members.length) return;
        const title = document.createElement('h4');
        title.className = 'progress-group-title';
        title.textContent = _prT(`progress.group_${group}`, group);
        const grid = document.createElement('div');
        grid.className = 'progress-badge-grid';
        members.forEach((badge) => grid.appendChild(_prBadgeCard(badge, payload.catalogues)));
        DOMUtils.append(container, title, grid);
    });
}

// ── Challenges ──────────────────────────────────────────────────────────────

function _prTargetRow(target, catalogue) {
    const row = document.createElement('li');
    row.className = `list-group-item progress-target${target.captured ? ' is-captured' : ''}`;
    const mark = DOMUtils.createIcon(target.captured ? 'bi bi-check-circle-fill progress-target-mark' : 'bi bi-circle progress-target-mark');
    mark.setAttribute('aria-label', target.captured ? _prT('progress.captured', 'Captured') : _prT('progress.not_captured', 'Not captured yet'));
    mark.setAttribute('role', 'img');
    const text = document.createElement('div');
    text.className = 'progress-target-text';
    const name = document.createElement('strong');
    name.textContent = target.name;
    text.appendChild(name);
    const details = [
        target.preferred_name && target.preferred_name !== target.name ? target.preferred_name : '',
        progressTypeLabel(target.object_type),
        target.magnitude !== null && target.magnitude !== undefined ? `mag ${Number(target.magnitude).toFixed(1)}` : '',
    ].filter(Boolean);
    if (details.length) {
        const small = document.createElement('div');
        small.className = 'small text-muted';
        small.textContent = details.join(' - ');
        text.appendChild(small);
    }
    DOMUtils.append(row, mark, text);
    if (!target.captured && typeof buildWishlistButton === 'function') {
        row.appendChild(buildWishlistButton({ name: target.name, catalogue: catalogue || target.catalogue }, false));
    }
    return row;
}

function _prRenderSeasonal(container, seasonal, locationName) {
    if (!seasonal || !seasonal.challenges || !seasonal.challenges.length) return;
    const season = _prT(`progress.season_${seasonal.season}`, seasonal.season);
    const intro = document.createElement('p');
    intro.className = 'small text-muted mb-2';
    intro.textContent = _prT(
        'progress.season_intro',
        '{season}: the brightest Messier and Caldwell objects well placed from {location} this season, at your SkyTonight altitude limits.',
        { season, location: locationName || '' }
    );
    container.appendChild(intro);

    const grid = document.createElement('div');
    grid.className = 'progress-challenge-grid';
    seasonal.challenges.forEach((challenge) => {
        const card = document.createElement('div');
        card.className = 'progress-challenge';
        const header = document.createElement('div');
        header.className = 'progress-challenge-header';
        const title = document.createElement('div');
        title.className = 'progress-challenge-title';
        title.textContent = _prT(`progress.challenge_${challenge.object_class}`, progressClassLabel(challenge.object_class));
        const counter = document.createElement('span');
        counter.className = 'progress-next-counter';
        counter.textContent = `${challenge.captured} / ${challenge.total}`;
        DOMUtils.append(header, title, counter);
        const list = document.createElement('ul');
        list.className = 'list-group list-group-flush progress-target-list';
        challenge.targets.forEach((target) => list.appendChild(_prTargetRow(target)));
        DOMUtils.append(card, header, _prProgressBar(challenge.captured, challenge.total, title.textContent), list);
        grid.appendChild(card);
    });
    container.appendChild(grid);
}

function _prRenderMarathon(container, marathon) {
    if (!marathon || !marathon.date) return;
    const card = document.createElement('div');
    card.className = `progress-marathon${marathon.in_season ? ' is-in-season' : ''}`;

    const header = document.createElement('div');
    header.className = 'progress-challenge-header';
    const title = document.createElement('div');
    title.className = 'progress-challenge-title';
    DOMUtils.append(
        title,
        DOMUtils.createIcon('bi bi-person-walking icon-inline'),
        ` ${_prT('progress.marathon_title', 'Messier marathon {year}', { year: marathon.year })}`
    );
    const counter = document.createElement('span');
    counter.className = 'progress-next-counter';
    counter.textContent = `${marathon.reachable} / ${marathon.total}`;
    DOMUtils.append(header, title, counter);
    card.appendChild(header);

    const when = document.createElement('p');
    when.className = 'mb-1';
    const days = Number(marathon.days_until);
    when.textContent = _prT(
        days === 0 ? 'progress.marathon_tonight' : days > 0 ? 'progress.marathon_when' : 'progress.marathon_past',
        'Night of {date}, Moon {moon}%.',
        {
            date: progressDateLabel(marathon.date, { weekday: 'long', day: 'numeric', month: 'long' }),
            moon: Math.round(Number(marathon.moon_illumination_percent) || 0),
            days,
        }
    );
    const reach = document.createElement('p');
    reach.className = 'small text-muted mb-2';
    reach.textContent = _prT(
        'progress.marathon_reach',
        'From your site, {reachable} of the {total} Messier objects can be caught that night, down to {altitude} degrees, between {start} and {end}. {captured} of them are already in your log.',
        {
            reachable: marathon.reachable,
            total: marathon.total,
            altitude: marathon.minimum_altitude,
            start: marathon.dark_start || '-',
            end: marathon.dark_end || '-',
            captured: marathon.captured || 0,
        }
    );
    DOMUtils.append(card, when, reach);

    if (marathon.sequence && marathon.sequence.length) {
        const details = document.createElement('details');
        details.className = 'progress-marathon-details';
        const summary = document.createElement('summary');
        summary.textContent = _prT('progress.marathon_order', 'Suggested order for your latitude');
        details.appendChild(summary);
        const list = document.createElement('ol');
        list.className = 'progress-marathon-list';
        marathon.sequence.forEach((row) => {
            const item = document.createElement('li');
            item.className = row.captured ? 'is-captured' : '';
            const time = document.createElement('span');
            time.className = 'progress-marathon-time';
            time.textContent = row.best_time;
            const name = document.createElement('strong');
            name.textContent = ` ${row.name}`;
            const extra = document.createElement('span');
            extra.className = 'text-muted small';
            const label = row.preferred_name && row.preferred_name !== row.name ? ` - ${row.preferred_name}` : '';
            extra.textContent = label;
            DOMUtils.append(item, time, name, extra);
            if (row.captured) {
                const mark = DOMUtils.createIcon('bi bi-check-circle-fill progress-target-mark ms-1');
                mark.setAttribute('role', 'img');
                mark.setAttribute('aria-label', _prT('progress.captured', 'Captured'));
                item.appendChild(mark);
            }
            list.appendChild(item);
        });
        details.appendChild(list);
        card.appendChild(details);
    }
    if (marathon.unreachable && marathon.unreachable.length) {
        const out = document.createElement('p');
        out.className = 'small text-muted mt-2 mb-0';
        out.textContent = _prT('progress.marathon_unreachable', 'Out of reach from here that night: {names}.', {
            names: marathon.unreachable.map((row) => row.name).join(', '),
        });
        card.appendChild(out);
    }
    container.appendChild(card);
}

function _prRenderChallenges(payload) {
    const container = document.getElementById('progress-challenges');
    if (!container) return;
    _prSection(container);
    if (!payload) {
        _prEmpty(container, _prT('progress.challenges_error', 'The challenges could not be computed for your location.'), 'bi bi-exclamation-triangle');
        return;
    }
    // The marathon goes first while it is in season: it is the one with a date.
    if (payload.marathon?.in_season) _prRenderMarathon(container, payload.marathon);
    _prRenderSeasonal(container, payload.seasonal, payload.location_name);
    if (payload.marathon && !payload.marathon.in_season) _prRenderMarathon(container, payload.marathon);
    if (!container.childNodes.length) {
        _prEmpty(container, _prT('progress.challenges_none', 'No challenge can be computed for your location right now.'), 'bi bi-cloud-moon');
    }
}

// ── Entry point ─────────────────────────────────────────────────────────────

function _prBindListeners() {
    if (progressState.listenersBound) return;
    progressState.listenersBound = true;
    document.getElementById('progress-year-review-btn')?.addEventListener('click', () => {
        if (typeof openYearReview === 'function') openYearReview();
    });
    window.addEventListener('i18nLanguageChanged', () => {
        if (document.getElementById('progress-subtab')?.classList.contains('active')) loadProgress();
    });
}

/** Mark the badges just shown as seen, so "New" appears once. */
function _prMarkSeen(ids) {
    if (!ids || !ids.length) return;
    fetchJSON('/api/achievements/seen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
    }).catch((error) => console.error('Error saving the badges seen:', error));
}

/**
 * Load and render the Progress sub-tab. Called by app.js when the sub-tab opens.
 */
async function loadProgress() {
    _prBindListeners();
    const token = ++progressState.token;
    const disabled = document.getElementById('progress-disabled');
    const content = document.getElementById('progress-content');
    const enabled = progressAchievementsEnabled();
    disabled?.classList.toggle('d-none', enabled);
    content?.classList.toggle('d-none', !enabled);
    if (!enabled) return;

    ['progress-stats', 'progress-next', 'progress-badges', 'progress-challenges'].forEach((id) => {
        const element = document.getElementById(id);
        if (element) DOMUtils.setLoading(element, _prT('common.loading', 'Loading...'));
    });

    const challengesRequest = fetchJSON('/api/achievements/challenges').catch((error) => {
        console.error('Error loading the challenges:', error);
        return null;
    });

    let payload = null;
    try {
        payload = await fetchJSON('/api/achievements');
    } catch (error) {
        console.error('Error loading the badges:', error);
    }
    if (token !== progressState.token) return;
    if (!payload) {
        ['progress-stats', 'progress-next', 'progress-badges'].forEach((id) => {
            const element = document.getElementById(id);
            if (element) {
                DOMUtils.clear(element);
                _prEmpty(element, _prT('progress.load_error', 'Could not load your progress.'), 'bi bi-exclamation-triangle');
            }
        });
    } else {
        _prRenderStats(payload);
        _prRenderNext(payload);
        _prRenderBadges(payload);
        _prMarkSeen(payload.summary?.new_ids || []);
    }

    const challenges = await challengesRequest;
    if (token !== progressState.token) return;
    _prRenderChallenges(challenges);
}

window.loadProgress = loadProgress;
window.applyProgressVisibility = applyProgressVisibility;
