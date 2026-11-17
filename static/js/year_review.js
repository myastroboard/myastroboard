/**
 * Year in review (v1.9) - "My astro year", a short sequence of screens about one year.
 *
 * The server builds every figure (GET /api/session-analytics/year-review?year=) from the
 * user's own Observation Log and Astrodex; this module only turns each non-empty part into
 * a share card model and shows them one after the other, drawn on a canvas by the share
 * card engine (share_card.js), so each screen is also the image that gets shared. A screen
 * without data is left out, never shown empty, and no figure compares the user with anyone.
 *
 * Opened from Your Sky, from the Progress page, and from the end-of-year highlight on the
 * Astrophotography tab (1 December - 15 January), which can be dismissed per year.
 */

/* global DOMUtils, i18n, fetchJSON, appUrl, openModal, closeModal, openShareCard, drawShareCard,
   loadShareCardImage, saveUserPreferences, setCurrentUserPreferences, currentUserPreferences,
   progressCatalogueLabel, progressClassLabel, progressTypeLabel, progressConstellationLabel,
   progressDateLabel, progressHours */

const YEAR_REVIEW_MODAL_ID = 'modal_full_close';
// The end-of-year highlight runs from 1 December to 15 January (month is 0-based here).
const YEAR_REVIEW_HIGHLIGHT_FROM = { month: 11, day: 1 };
const YEAR_REVIEW_HIGHLIGHT_UNTIL = { month: 0, day: 15 };

const yearReviewState = {
    payload: null,
    screens: [],
    index: 0,
    images: new Map(),
    keyHandler: null,
};

function _yrT(key, fallback, params) {
    if (typeof i18n === 'undefined' || typeof i18n.t !== 'function') return fallback;
    const translated = i18n.t(key, params);
    return translated && translated !== key ? translated : fallback;
}

function _yrNumber(value, digits = 1) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '';
    return Number.isInteger(number) ? String(number) : number.toFixed(digits);
}

// ── Screens ─────────────────────────────────────────────────────────────────

/**
 * Turn the review payload into share card models, one per screen that has data.
 * @param {Object} payload
 * @returns {Object[]}
 */
function buildYearReviewScreens(payload) {
    if (!payload || !payload.has_data || !payload.totals) return [];
    const year = String(payload.year);
    const kicker = _yrT('year_review.kicker', 'My astro year {year}', { year });
    const filename = (name) => `my-astro-year-${year}-${name}`;
    const screens = [];
    const totals = payload.totals;

    const integration = Number(totals.integration_minutes) > 0 ? progressHours(totals.integration_minutes) : '';
    screens.push({
        id: 'year',
        title: _yrT('year_review.share_title', 'Share this screen'),
        filename: filename('year'),
        kicker,
        heading: year,
        subheading: _yrT('year_review.year_subheading', 'A year under the sky'),
        hero: integration
            ? { value: integration, label: _yrT('year_review.hero_integration', 'of light collected') }
            : { value: String(totals.targets), label: _yrT('year_review.hero_objects', 'objects captured') },
        facts: [
            { id: 'nights', label: _yrT('year_review.fact_nights', 'Nights out'), value: totals.nights ? String(totals.nights) : '' },
            { id: 'sessions', label: _yrT('year_review.fact_sessions', 'Sessions'), value: totals.sessions ? String(totals.sessions) : '' },
            {
                id: 'objects',
                label: _yrT('year_review.fact_objects', 'Objects'),
                value: integration && totals.targets ? String(totals.targets) : '',
            },
        ],
    });

    const favourite = payload.favourite_class;
    screens.push({
        id: 'targets',
        title: _yrT('year_review.share_title', 'Share this screen'),
        filename: filename('targets'),
        kicker,
        heading: _yrT('year_review.targets_heading', 'Your targets'),
        hero: { value: String(totals.targets), label: _yrT('year_review.hero_objects', 'objects captured') },
        facts: [
            {
                id: 'new',
                label: _yrT('year_review.fact_new', 'New this year'),
                value: totals.new_targets ? String(totals.new_targets) : '',
            },
            {
                id: 'favourite',
                label: _yrT('year_review.fact_favourite', 'Favourite kind'),
                value: favourite ? progressClassLabel(favourite.object_class) : '',
            },
        ],
    });

    const target = payload.target_of_year;
    if (target) {
        screens.push({
            id: 'target',
            title: _yrT('year_review.share_title', 'Share this screen'),
            filename: filename('target'),
            kicker: _yrT('year_review.target_kicker', 'Target of the year {year}', { year }),
            heading: target.preferred_name || target.name,
            subheading: [
                target.preferred_name && target.preferred_name !== target.name ? target.name : '',
                progressTypeLabel(target.object_type),
                progressConstellationLabel(target.constellation),
            ]
                .filter(Boolean)
                .join(' - '),
            imageUrl: target.picture ? appUrl(`/api/astrodex/images/${encodeURIComponent(target.picture.filename)}`) : '',
            hero: { value: progressHours(target.integration_minutes), label: _yrT('year_review.hero_on_target', 'on this target') },
            facts: [
                {
                    id: 'nights',
                    label: _yrT('year_review.fact_nights_on_it', 'Nights on it'),
                    value: target.nights ? String(target.nights) : '',
                },
            ],
        });
    }

    const night = payload.best_night;
    if (night) {
        screens.push({
            id: 'night',
            title: _yrT('year_review.share_title', 'Share this screen'),
            filename: filename('best-night'),
            kicker: _yrT('year_review.night_kicker', 'Best night of {year}', { year }),
            heading: progressDateLabel(night.date, { weekday: 'long', day: 'numeric', month: 'long' }),
            subheading: night.combination_name || '',
            hero: Number(night.integration_minutes) > 0
                ? { value: progressHours(night.integration_minutes), label: _yrT('year_review.hero_that_night', 'collected that night') }
                : null,
            facts: [
                {
                    id: 'rating',
                    label: _yrT('year_review.fact_rating', 'Your rating'),
                    value: night.average_rating !== null && night.average_rating !== undefined ? `${_yrNumber(night.average_rating)} / 5` : '',
                },
                { id: 'sqm', label: _yrT('share.fact_sqm', 'Sky (SQM)'), value: night.sqm ? Number(night.sqm).toFixed(2) : '' },
                {
                    id: 'moon',
                    label: _yrT('share.fact_moon', 'Moon'),
                    value: night.moon_illumination_percent !== null && night.moon_illumination_percent !== undefined
                        ? `${Math.round(Number(night.moon_illumination_percent))}%`
                        : '',
                },
            ],
            list: { title: _yrT('share.list_targets', 'Targets'), items: night.targets || [] },
        });
    }

    const equipment = payload.equipment;
    if (equipment) {
        screens.push({
            id: 'equipment',
            title: _yrT('year_review.share_title', 'Share this screen'),
            filename: filename('equipment'),
            kicker: _yrT('year_review.equipment_kicker', 'Hardest-working equipment'),
            heading: equipment.combination_name,
            hero: { value: String(equipment.share_percent), unit: '%', label: _yrT('year_review.hero_share', 'of the light of the year') },
            facts: [
                { id: 'hours', label: _yrT('year_review.fact_hours', 'Integration'), value: progressHours(equipment.integration_minutes) },
                { id: 'nights', label: _yrT('year_review.fact_nights', 'Nights out'), value: equipment.nights ? String(equipment.nights) : '' },
                {
                    id: 'combinations',
                    label: _yrT('year_review.fact_combinations', 'Setups used'),
                    value: equipment.combinations_used > 1 ? String(equipment.combinations_used) : '',
                },
            ],
        });
    }

    const catalogues = payload.catalogues || [];
    const previous = payload.previous_year;
    if (catalogues.length || previous) {
        const previousValue = previous
            ? [
                Number(previous.integration_minutes) > 0 ? progressHours(previous.integration_minutes) : '',
                _yrT('year_review.previous_objects', '{count} objects', { count: previous.targets }),
            ]
                .filter(Boolean)
                .join(', ')
            : '';
        screens.push({
            id: 'progress',
            title: _yrT('year_review.share_title', 'Share this screen'),
            filename: filename('progress'),
            kicker,
            heading: _yrT('year_review.progress_heading', 'Your progress'),
            facts: [
                {
                    id: 'previous',
                    label: previous ? _yrT('year_review.fact_previous', 'In {year}', { year: previous.year }) : '',
                    value: previousValue,
                },
            ],
            bars: {
                title: _yrT('year_review.list_catalogues', 'Catalogues'),
                items: catalogues.map((row) => ({
                    label: progressCatalogueLabel(row.catalogue),
                    value: row.captured,
                    total: row.total,
                    note: row.gained > 0 ? _yrT('year_review.gained_short', '+{count}', { count: row.gained }) : '',
                })),
            },
        });
    }

    const mosaic = payload.mosaic || [];
    if (mosaic.length) {
        screens.push({
            id: 'mosaic',
            title: _yrT('year_review.share_title', 'Share this screen'),
            filename: filename('pictures'),
            kicker,
            heading: _yrT('year_review.mosaic_heading', 'My {year} in pictures', { year }),
            mosaicUrls: mosaic.map((picture) => appUrl(`/api/astrodex/images/${encodeURIComponent(picture.filename)}`)),
            facts: [
                {
                    id: 'pictures',
                    label: _yrT('year_review.fact_pictures', 'Pictures'),
                    value: mosaic.length > 1 ? String(mosaic.length) : '',
                },
            ],
        });
    }

    // Text-only screens grow their text to fill the card; screens with a picture keep the
    // usual layout (the engine only scales a card that has no picture).
    screens.forEach((screen) => {
        screen.fill = true;
    });
    return screens;
}

// ── Download or share every screen at once ──────────────────────────────────

const _YR_CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n += 1) {
        let c = n;
        for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
        table[n] = c >>> 0;
    }
    return table;
})();

function _yrCrc32(bytes) {
    let crc = 0xffffffff;
    for (let index = 0; index < bytes.length; index += 1) {
        crc = _YR_CRC_TABLE[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8);
    }
    return (crc ^ 0xffffffff) >>> 0;
}

/**
 * A ZIP archive of already-compressed files, stored without compression (method 0): PNGs
 * do not shrink further, and this avoids a dependency for one button.
 * @param {Array<{name: string, bytes: Uint8Array}>} files - ASCII names
 * @returns {Blob}
 */
function _yrZip(files) {
    const now = new Date();
    const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2);
    const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    const encoder = new TextEncoder();
    const parts = [];
    const central = [];
    let offset = 0;

    files.forEach((file) => {
        const name = encoder.encode(file.name);
        const crc = _yrCrc32(file.bytes);
        const local = new DataView(new ArrayBuffer(30));
        local.setUint32(0, 0x04034b50, true);
        local.setUint16(4, 20, true);
        local.setUint16(10, dosTime, true);
        local.setUint16(12, dosDate, true);
        local.setUint32(14, crc, true);
        local.setUint32(18, file.bytes.length, true);
        local.setUint32(22, file.bytes.length, true);
        local.setUint16(26, name.length, true);
        parts.push(local.buffer, name, file.bytes);

        const entry = new DataView(new ArrayBuffer(46));
        entry.setUint32(0, 0x02014b50, true);
        entry.setUint16(4, 20, true);
        entry.setUint16(6, 20, true);
        entry.setUint16(12, dosTime, true);
        entry.setUint16(14, dosDate, true);
        entry.setUint32(16, crc, true);
        entry.setUint32(20, file.bytes.length, true);
        entry.setUint32(24, file.bytes.length, true);
        entry.setUint16(28, name.length, true);
        entry.setUint32(42, offset, true);
        central.push(entry.buffer, name);
        offset += 30 + name.length + file.bytes.length;
    });

    const centralSize = central.reduce((total, part) => total + part.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, files.length, true);
    end.setUint16(10, files.length, true);
    end.setUint32(12, centralSize, true);
    end.setUint32(16, offset, true);
    return new Blob([...parts, ...central, end.buffer], { type: 'application/zip' });
}

/** Every screen rendered as a PNG file, in order, with the viewer's format and theme. */
async function _yrRenderAll() {
    const files = [];
    for (let index = 0; index < yearReviewState.screens.length; index += 1) {
        const screen = yearReviewState.screens[index];
        const canvas = document.createElement('canvas');
        drawShareCard(canvas, screen, YEAR_REVIEW_OPTIONS, await _yrImageFor(screen));
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
        if (!blob) continue;
        const name = `${String(index + 1).padStart(2, '0')}-${screen.filename || screen.id}.png`;
        files.push(new File([blob], name, { type: 'image/png' }));
    }
    return files;
}

function _yrCanShareFiles() {
    if (typeof File !== 'function' || typeof navigator.canShare !== 'function') return false;
    const probe = () => new File([new Blob()], 'probe.png', { type: 'image/png' });
    try {
        return navigator.canShare({ files: [probe(), probe()] });
    } catch (_error) {
        return false;
    }
}

/** Run *task* with the button disabled and showing that the images are being prepared. */
async function _yrBusy(button, task) {
    const label = Array.from(button.childNodes);
    button.disabled = true;
    DOMUtils.clear(button);
    button.appendChild(DOMUtils.createSpinnerWrapper(_yrT('year_review.preparing', 'Preparing the images...'), ''));
    try {
        await task();
    } catch (error) {
        // The user closing the share sheet is not an error.
        if (error && error.name !== 'AbortError') console.error('Year in review export failed:', error);
    } finally {
        DOMUtils.clear(button);
        DOMUtils.append(button, ...label);
        button.disabled = false;
    }
}

async function _yrDownloadAll() {
    const files = await _yrRenderAll();
    if (!files.length) return;
    const entries = await Promise.all(
        files.map(async (file) => ({ name: file.name, bytes: new Uint8Array(await file.arrayBuffer()) }))
    );
    const url = URL.createObjectURL(_yrZip(entries));
    const link = document.createElement('a');
    link.href = url;
    link.download = `my-astro-year-${yearReviewState.payload.year}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function _yrShareAll() {
    const files = await _yrRenderAll();
    if (!files.length) return;
    await navigator.share({
        files,
        title: _yrT('year_review.title', 'My astro year {year}', { year: yearReviewState.payload.year }),
    });
}

// ── Viewer ──────────────────────────────────────────────────────────────────

const YEAR_REVIEW_OPTIONS = { format: '4x5', theme: 'dark', brand: true, facts: {} };

async function _yrImageFor(screen) {
    if (!yearReviewState.images.has(screen.id)) {
        yearReviewState.images.set(screen.id, loadShareCardImage(screen));
    }
    return yearReviewState.images.get(screen.id);
}

async function _yrDraw(canvas, counter, dots) {
    const screen = yearReviewState.screens[yearReviewState.index];
    if (!screen) return;
    counter.textContent = _yrT('year_review.counter', '{index} / {total}', {
        index: yearReviewState.index + 1,
        total: yearReviewState.screens.length,
    });
    dots.forEach((dot, position) => dot.classList.toggle('is-active', position === yearReviewState.index));
    canvas.setAttribute('aria-label', [screen.kicker, screen.heading].filter(Boolean).join(' - '));
    const index = yearReviewState.index;
    const image = await _yrImageFor(screen);
    if (index !== yearReviewState.index) return;
    drawShareCard(canvas, screen, YEAR_REVIEW_OPTIONS, image);
}

function _yrYearSelect(payload, onChange) {
    const years = payload?.available_years || [];
    if (years.length < 2 && years.includes(payload?.year)) return null;
    const select = document.createElement('select');
    select.className = 'form-select form-select-sm year-review-year';
    select.setAttribute('aria-label', _yrT('year_review.year_label', 'Year'));
    const options = years.includes(payload.year) ? years : [payload.year, ...years];
    options.forEach((year) => {
        const option = document.createElement('option');
        option.value = String(year);
        option.textContent = String(year);
        option.selected = year === payload.year;
        select.appendChild(option);
    });
    select.addEventListener('change', () => onChange(Number(select.value)));
    return select;
}

function _yrRender(bodyEl) {
    const payload = yearReviewState.payload;
    DOMUtils.clear(bodyEl);
    const root = document.createElement('div');
    root.className = 'year-review';

    const toolbar = document.createElement('div');
    toolbar.className = 'year-review-toolbar';
    const yearSelect = _yrYearSelect(payload, (year) => openYearReview(year));
    if (yearSelect) toolbar.appendChild(yearSelect);
    root.appendChild(toolbar);

    if (!yearReviewState.screens.length) {
        const empty = document.createElement('div');
        empty.className = 'year-review-empty text-center';
        empty.appendChild(DOMUtils.createIcon('bi bi-calendar-heart year-review-empty-icon'));
        const text = document.createElement('p');
        text.textContent = _yrT(
            'year_review.empty',
            'Nothing in your logbook or your Astrodex for {year} yet. Log a night or add a picture, and your review will build itself.',
            { year: payload?.year ?? '' }
        );
        empty.appendChild(text);
        root.appendChild(empty);
        bodyEl.appendChild(root);
        return;
    }

    const counter = document.createElement('div');
    counter.className = 'year-review-counter small text-muted';
    toolbar.appendChild(counter);

    const stage = document.createElement('div');
    stage.className = 'year-review-stage';
    const canvas = document.createElement('canvas');
    canvas.className = 'year-review-canvas';
    canvas.setAttribute('role', 'img');
    stage.appendChild(canvas);
    root.appendChild(stage);

    const navigation = document.createElement('div');
    navigation.className = 'year-review-nav';
    const previous = document.createElement('button');
    previous.type = 'button';
    previous.className = 'btn btn-outline-secondary';
    previous.setAttribute('aria-label', _yrT('year_review.previous', 'Previous screen'));
    previous.appendChild(DOMUtils.createIcon('bi bi-chevron-left'));
    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'btn btn-outline-secondary';
    next.setAttribute('aria-label', _yrT('year_review.next', 'Next screen'));
    next.appendChild(DOMUtils.createIcon('bi bi-chevron-right'));
    const dotsWrapper = document.createElement('div');
    dotsWrapper.className = 'year-review-dots';
    const dots = yearReviewState.screens.map((screen, position) => {
        const dot = document.createElement('button');
        dot.type = 'button';
        dot.className = 'year-review-dot';
        dot.setAttribute('aria-label', _yrT('year_review.go_to', 'Screen {index}', { index: position + 1 }));
        dot.addEventListener('click', () => go(position));
        dotsWrapper.appendChild(dot);
        return dot;
    });
    DOMUtils.append(navigation, previous, dotsWrapper, next);
    root.appendChild(navigation);

    const actions = document.createElement('div');
    actions.className = 'year-review-actions';
    const share = document.createElement('button');
    share.type = 'button';
    share.className = 'btn btn-primary';
    DOMUtils.append(share, DOMUtils.createIcon('bi bi-share icon-inline'), ` ${_yrT('year_review.share', 'Share this screen')}`);
    share.addEventListener('click', () => {
        const index = yearReviewState.index;
        const screen = yearReviewState.screens[index];
        // The share modal replaces this one (Bootstrap cannot stack modals); closing it
        // brings the review back on the same screen.
        openShareCard({ ...screen, onClose: () => _yrShow(index) });
    });
    actions.appendChild(share);
    const downloadAll = document.createElement('button');
    downloadAll.type = 'button';
    downloadAll.className = 'btn btn-outline-primary';
    DOMUtils.append(
        downloadAll,
        DOMUtils.createIcon('bi bi-file-earmark-zip icon-inline'),
        ` ${_yrT('year_review.download_all', 'Download all (ZIP)')}`
    );
    downloadAll.addEventListener('click', () => _yrBusy(downloadAll, _yrDownloadAll));
    actions.appendChild(downloadAll);
    // The system share sheet takes several pictures at once on most phones, which posts
    // the whole review as one carousel.
    if (_yrCanShareFiles()) {
        const shareAll = document.createElement('button');
        shareAll.type = 'button';
        shareAll.className = 'btn btn-outline-primary';
        DOMUtils.append(shareAll, DOMUtils.createIcon('bi bi-images icon-inline'), ` ${_yrT('year_review.share_all', 'Share all')}`);
        shareAll.addEventListener('click', () => _yrBusy(shareAll, _yrShareAll));
        actions.appendChild(shareAll);
    }
    const privacy = document.createElement('p');
    privacy.className = 'small text-muted mb-0';
    privacy.textContent = _yrT(
        'year_review.privacy',
        'Only you can see your review. It is drawn in your browser from your own log, and never shows your location.'
    );
    root.appendChild(actions);
    root.appendChild(privacy);
    bodyEl.appendChild(root);

    function go(position) {
        const total = yearReviewState.screens.length;
        yearReviewState.index = ((position % total) + total) % total;
        previous.disabled = yearReviewState.index === 0;
        next.disabled = yearReviewState.index === total - 1;
        _yrDraw(canvas, counter, dots);
    }
    previous.addEventListener('click', () => go(yearReviewState.index - 1));
    next.addEventListener('click', () => go(yearReviewState.index + 1));
    yearReviewState.go = go;
    go(yearReviewState.index);
}

function _yrBindKeys() {
    if (yearReviewState.keyHandler) return;
    yearReviewState.keyHandler = (event) => {
        if (!document.getElementById(YEAR_REVIEW_MODAL_ID)?.classList.contains('show')) return;
        if (!document.querySelector('.year-review-canvas') || typeof yearReviewState.go !== 'function') return;
        if (event.target instanceof HTMLSelectElement) return;
        if (event.key === 'ArrowRight' && yearReviewState.index < yearReviewState.screens.length - 1) {
            yearReviewState.go(yearReviewState.index + 1);
        } else if (event.key === 'ArrowLeft' && yearReviewState.index > 0) {
            yearReviewState.go(yearReviewState.index - 1);
        }
    };
    document.addEventListener('keydown', yearReviewState.keyHandler);
}

function _yrUnbindKeys() {
    if (!yearReviewState.keyHandler) return;
    document.removeEventListener('keydown', yearReviewState.keyHandler);
    yearReviewState.keyHandler = null;
}

/** Show the already loaded review, on *index*. */
function _yrShow(index = 0) {
    const modalEl = document.getElementById(YEAR_REVIEW_MODAL_ID);
    const titleEl = document.getElementById(`${YEAR_REVIEW_MODAL_ID}_title`);
    const bodyEl = document.getElementById(`${YEAR_REVIEW_MODAL_ID}_body`);
    if (!modalEl || !titleEl || !bodyEl || !yearReviewState.payload) return;
    titleEl.textContent = _yrT('year_review.title', 'My astro year {year}', { year: yearReviewState.payload.year });
    yearReviewState.index = Math.min(index, Math.max(0, yearReviewState.screens.length - 1));
    _yrRender(bodyEl);
    _yrBindKeys();
    openModal(modalEl, { backdrop: true, onHidden: _yrUnbindKeys });
}

/**
 * Open the review for *year* (default: the server's choice - the year just ending, or the
 * latest year with data).
 * @param {number} [year]
 */
async function openYearReview(year) {
    const modalEl = document.getElementById(YEAR_REVIEW_MODAL_ID);
    const titleEl = document.getElementById(`${YEAR_REVIEW_MODAL_ID}_title`);
    const bodyEl = document.getElementById(`${YEAR_REVIEW_MODAL_ID}_body`);
    if (!modalEl || !titleEl || !bodyEl) return;

    if (!modalEl.classList.contains('show')) {
        titleEl.textContent = _yrT('year_review.open', 'My astro year');
        DOMUtils.clear(bodyEl);
        bodyEl.appendChild(DOMUtils.createSpinnerWrapper(_yrT('common.loading', 'Loading...')));
        _yrBindKeys();
        openModal(modalEl, { backdrop: true, onHidden: _yrUnbindKeys });
    }

    const query = year ? `?year=${encodeURIComponent(year)}` : '';
    let payload = null;
    try {
        payload = await fetchJSON(`/api/session-analytics/year-review${query}`);
    } catch (error) {
        console.error('Error loading the year in review:', error);
    }
    if (!payload) {
        DOMUtils.clear(bodyEl);
        const error = document.createElement('p');
        error.className = 'text-muted';
        error.textContent = _yrT('year_review.load_error', 'Could not load your year in review.');
        bodyEl.appendChild(error);
        return;
    }
    yearReviewState.payload = payload;
    yearReviewState.screens = buildYearReviewScreens(payload);
    yearReviewState.images = new Map();
    titleEl.textContent = _yrT('year_review.title', 'My astro year {year}', { year: payload.year });
    yearReviewState.index = 0;
    _yrRender(bodyEl);
}

// ── End-of-year highlight on the Astrophotography tab ───────────────────────

/** The year the highlight is for on *date*, or null outside 1 December - 15 January. */
function yearReviewHighlightYear(date = new Date()) {
    const month = date.getMonth();
    const day = date.getDate();
    if (month === YEAR_REVIEW_HIGHLIGHT_FROM.month && day >= YEAR_REVIEW_HIGHLIGHT_FROM.day) return date.getFullYear();
    if (month === YEAR_REVIEW_HIGHLIGHT_UNTIL.month && day <= YEAR_REVIEW_HIGHLIGHT_UNTIL.day) return date.getFullYear() - 1;
    return null;
}

async function _yrDismissHighlight(year, container) {
    container.classList.add('d-none');
    if (typeof saveUserPreferences !== 'function') return;
    try {
        const updated = await saveUserPreferences({ year_review_dismissed: year });
        if (typeof setCurrentUserPreferences === 'function') setCurrentUserPreferences(updated);
    } catch (error) {
        console.error('Error saving the dismissed year in review:', error);
    }
}

/**
 * Show the "your year is ready" highlight when it is the season for it, the user has data
 * for that year and has not dismissed it. Called once the app is initialized.
 */
async function initYearReviewHighlight() {
    const container = document.getElementById('year-review-highlight');
    if (!container) return;
    const year = yearReviewHighlightYear();
    if (!year || currentUserPreferences?.year_review_dismissed === year) {
        container.classList.add('d-none');
        return;
    }
    let payload = null;
    try {
        payload = await fetchJSON(`/api/session-analytics/year-review?year=${year}`);
    } catch (error) {
        console.error('Error checking the year in review:', error);
        return;
    }
    if (!payload || !payload.has_data) return;

    DOMUtils.clear(container);
    const icon = DOMUtils.createIcon('bi bi-calendar-heart year-review-highlight-icon');
    const text = document.createElement('div');
    text.className = 'flex-grow-1';
    const title = document.createElement('strong');
    title.textContent = _yrT('year_review.highlight_title', 'Your astro year {year} is ready', { year });
    const detail = document.createElement('div');
    detail.className = 'small';
    detail.textContent = _yrT('year_review.highlight_text', 'A few screens about your year under the sky, each one ready to share.');
    DOMUtils.append(text, title, detail);
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'btn btn-sm btn-primary';
    open.textContent = _yrT('year_review.highlight_open', 'See it');
    open.addEventListener('click', () => openYearReview(year));
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'btn-close';
    close.setAttribute('aria-label', _yrT('year_review.highlight_dismiss', 'Hide until next year'));
    close.title = close.getAttribute('aria-label');
    close.addEventListener('click', () => _yrDismissHighlight(year, container));
    DOMUtils.append(container, icon, text, open, close);
    container.classList.remove('d-none');
}

// Any "My astro year" button (Your Sky header) opens the review.
document.addEventListener('click', (event) => {
    const trigger = event.target instanceof Element ? event.target.closest('[data-action="open-year-review"]') : null;
    if (!trigger) return;
    event.preventDefault();
    openYearReview();
});

window.openYearReview = openYearReview;
window.initYearReviewHighlight = initYearReviewHighlight;
