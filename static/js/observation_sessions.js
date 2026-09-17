/* =====================================================
   Observation Log (v1.3) - static/js/observation_sessions.js

   The "Log" step of the Plan -> Observe -> Log -> Astrodex loop: a private,
   chronological record of what was actually captured on each night.

   Rendered entirely with explicit DOM APIs (no innerHTML, no
   DOMUtils.setTrustedHTML) per the project's XSS rules - this is a new file, so
   no legacy HTML-template exception applies.
   ===================================================== */

const OBSERVATION_LOG_API = '/api/observation-sessions';
const _OBS_CUSTOM_LOCATION_VALUE = '__other__';
const _OBS_NO_COMBINATION_VALUE = '';

// 7Timer's ASTRO scales, shared with the backend: seeing 1=best..8=worst,
// transparency 1=worst..8=best.
const _OBS_SKY_SCALE = [1, 2, 3, 4, 5, 6, 7, 8];

let observationLogData = {
    sessions: [],
    stats: {},
    canEdit: false,
};

let observationLogFilters = {
    search: '',
    locationId: '',
    combinationId: '',
    minRating: '',
    fromDate: '',
    toDate: '',
    sort: 'date',
    order: 'desc',
};

// Which session's detail view is open, or null while the list is showing.
let observationLogOpenSessionId = null;

// Reference data loaded alongside the session list (locations, equipment, plans).
let observationLogLocations = [];
let observationLogActiveLocationId = null;
let observationLogCombinations = [];
let observationLogPlans = [];

let _observationLocationMap = null;
let _observationCoordinatesDebounce = null;

// ============================================
// Small shared helpers
// ============================================

/** Bootstrap icon class for star `i` (1-5) of a 0-5, 0.5-step rating `value`.
 *
 * NOTE: intentionally duplicated from astrodex.js's `_starIconClass` /
 * `_buildRatingWidget` / `_buildStarRatingDisplay` trio so the two feature files stay
 * independently deployable. If you fix a rounding/threshold bug here, apply the same fix
 * in static/js/astrodex.js. */
function _obsStarIconClass(value, i) {
    if (value >= i) return 'bi bi-star-fill text-warning';
    if (value >= i - 0.5) return 'bi bi-star-half text-warning';
    return 'bi bi-star text-warning';
}

/** Read-only star display for an entry row. Returns a <span> node. */
function _obsBuildStarRatingDisplay(rating) {
    const wrap = document.createElement('span');
    wrap.className = 'observation-log-star-rating';
    const value = Number(rating) || 0;
    for (let i = 1; i <= 5; i++) {
        wrap.appendChild(DOMUtils.createIcon(_obsStarIconClass(value, i)));
    }
    const label = document.createElement('span');
    label.className = 'ms-1';
    label.textContent = value.toFixed(1);
    wrap.appendChild(label);
    return wrap;
}

/** Interactive 0-5 (half-star step) rating widget - see _obsStarIconClass's duplication note. */
function _obsBuildRatingWidget(prefix, currentRating) {
    const wrap = document.createElement('div');
    wrap.className = 'd-flex align-items-center gap-1';
    wrap.id = `${prefix}-rating-widget`;
    wrap.dataset.rating = currentRating != null ? String(currentRating) : '';

    const renderStars = () => {
        DOMUtils.clear(wrap);
        const value = parseFloat(wrap.dataset.rating) || 0;
        for (let i = 1; i <= 5; i++) {
            const starWrap = document.createElement('span');
            starWrap.className = 'd-inline-flex align-items-center justify-content-center observation-log-rating-star';
            starWrap.title = i18n.t('observation_log.rating');
            starWrap.appendChild(DOMUtils.createIcon(_obsStarIconClass(value, i)));
            starWrap.addEventListener('click', (event) => {
                const rect = starWrap.getBoundingClientRect();
                const clickedHalf = (event.clientX - rect.left) < (rect.width / 2);
                const newValue = clickedHalf ? i - 0.5 : i;
                wrap.dataset.rating = (value === newValue) ? '' : String(newValue);
                renderStars();
            });
            wrap.appendChild(starWrap);
        }
        const label = document.createElement('span');
        label.className = 'text-muted small ms-1';
        label.textContent = value > 0 ? value.toFixed(1) : i18n.t('observation_log.not_rated');
        wrap.appendChild(label);
    };

    renderStars();
    return wrap;
}

/** Read a widget built by _obsBuildRatingWidget(), or null when unrated. */
function _obsGetRatingWidgetValue(prefix) {
    const raw = document.getElementById(`${prefix}-rating-widget`)?.dataset.rating;
    return raw ? parseFloat(raw) : null;
}

/** Build a labelled Bootstrap column wrapping one form control. */
function _obsField(columnClass, labelText, control, controlId) {
    const col = document.createElement('div');
    col.className = columnClass;
    const label = document.createElement('label');
    label.className = 'form-label';
    label.textContent = labelText;
    if (controlId) label.htmlFor = controlId;
    col.appendChild(label);
    col.appendChild(control);
    return col;
}

function _obsInput(id, type, value, extra = {}) {
    const input = document.createElement('input');
    input.type = type;
    input.className = 'form-control';
    input.id = id;
    input.value = value == null ? '' : String(value);
    Object.entries(extra).forEach(([key, val]) => input.setAttribute(key, val));
    return input;
}

function _obsSelect(id, options, selectedValue) {
    const select = document.createElement('select');
    select.className = 'form-select';
    select.id = id;
    options.forEach(({ value, label }) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        if (String(value) === String(selectedValue ?? '')) option.selected = true;
        select.appendChild(option);
    });
    return select;
}

function _obsSectionHeader(text) {
    const col = document.createElement('div');
    col.className = 'col-12';
    const heading = document.createElement('h6');
    heading.className = 'text-muted border-bottom pb-1 mb-0 mt-2';
    heading.textContent = text;
    col.appendChild(heading);
    return col;
}

function _obsNumberOrNull(elementId) {
    const raw = document.getElementById(elementId)?.value;
    if (raw === undefined || raw === null || String(raw).trim() === '') return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
}

function _obsTodayIso() {
    return new Date().toISOString().split('T')[0];
}

/** Format an entry's integration time as a compact "1h30" / "45 min" label. */
function _obsFormatIntegration(minutes) {
    const value = Number(minutes);
    if (!Number.isFinite(value) || value <= 0) return '';
    const hours = Math.floor(value / 60);
    const rest = Math.round(value % 60);
    return hours > 0 ? `${hours}h${String(rest).padStart(2, '0')}` : i18n.t('observation_log.minutes_short', { minutes: rest });
}

/** Best-effort name of a session's combination, falling back to its frozen snapshot. */
function _obsCombinationLabel(session) {
    const live = observationLogCombinations.find(combo => combo.id === session.combination_id);
    return live?.name || session.combination_name || '';
}

/** Best-effort name of an entry's own equipment override, or '' when it has none (in
 * which case it inherits the session's equipment - see _obsCombinationLabel above). */
function _obsEntryCombinationLabel(entry) {
    if (!entry.combination_id) return '';
    const live = observationLogCombinations.find(combo => combo.id === entry.combination_id);
    return live?.name || entry.combination_name || '';
}

/** The equipment name to actually show for one entry: its own override if it has one,
 * else the session's own default - so every target displays *some* equipment label
 * (when there is one to show), not just the exceptions. */
function _obsEntryEffectiveCombinationLabel(session, entry) {
    return _obsEntryCombinationLabel(entry) || _obsCombinationLabel(session);
}

/** A session's nights, chronologically - mirrors the backend's _sorted_nights(). */
function _obsSortedNights(session) {
    return [...(session.nights || [])].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')));
}

/** The session's earliest night's date - "the session's date" for display/sort,
 * matching the backend's session_date_range()[0] / _primary_night(). */
function _obsSessionDate(session) {
    const nights = _obsSortedNights(session);
    return nights.length ? (nights[0].date || '') : '';
}

/** [earliest, latest] night date - equal for a single-night session, the still
 * overwhelmingly common case. */
function _obsSessionDateRange(session) {
    const nights = _obsSortedNights(session);
    if (!nights.length) return ['', ''];
    return [nights[0].date || '', nights[nights.length - 1].date || ''];
}

/** "2026-07-14" for a single-night session, "2026-07-14 - 2026-07-16" for a multi-night one. */
function _obsFormatSessionDateLabel(session) {
    const [start, end] = _obsSessionDateRange(session);
    if (!start) return '';
    return start === end ? start : `${start} - ${end}`;
}

/** True when any of the session's nights falls within [fromDate, toDate] (either bound
 * blank = open-ended) - mirrors the backend's _session_overlaps_date_range(). */
function _obsSessionOverlapsDateRange(session, fromDate, toDate) {
    if (!fromDate && !toDate) return true;
    return (session.nights || []).some(night => {
        const date = String(night.date || '');
        if (fromDate && date < fromDate) return false;
        if (toDate && date > toDate) return false;
        return true;
    });
}

// ============================================
// Data loading
// ============================================

async function loadObservationSessions() {
    const container = document.getElementById('observation-log-display');
    if (!container) return;

    DOMUtils.setLoading(container, i18n.t('common.loading'));

    try {
        // currentUser is already populated by checkAuthStatus() before any tab is
        // reachable - reading it here avoids an extra /api/auth/status round trip
        // (via getUserRole()) on every single Observation Log visit.
        const role = typeof currentUser !== 'undefined' && currentUser
            ? currentUser.role
            : (typeof getUserRole === 'function' ? await getUserRole() : 'user');
        observationLogData.canEdit = role === 'user' || role === 'admin';

        const [payload] = await Promise.all([
            fetchJSON(OBSERVATION_LOG_API),
            _obsLoadLocations(),
            _obsLoadCombinations(),
            _obsLoadPlans(),
        ]);
        observationLogData.sessions = payload.sessions || [];
        observationLogData.stats = payload.stats || {};

        renderObservationLogStats();
        if (observationLogOpenSessionId
            && observationLogData.sessions.some(session => session.id === observationLogOpenSessionId)) {
            renderObservationSessionDetail(observationLogOpenSessionId);
        } else {
            observationLogOpenSessionId = null;
            renderObservationSessionsList();
        }
    } catch (error) {
        console.error('Error loading observation sessions:', error);
        showMessage('error', i18n.t('observation_log.failed_to_load'));
        DOMUtils.clear(container);
    }
}

async function _obsLoadLocations() {
    if (typeof fetchMyLocations !== 'function') return;
    try {
        const data = await fetchMyLocations();
        observationLogLocations = data?.locations || [];
        observationLogActiveLocationId = data?.active_location_id ?? null;
    } catch (error) {
        console.warn('Observation Log: location presets unavailable', error);
        observationLogLocations = [];
    }
}

async function _obsLoadCombinations() {
    try {
        const response = await fetchJSON('/api/equipment/combinations');
        const own = response.data || [];
        const shared = (response.shared_from_others || []).map(combo => ({ ...combo, is_own: false }));
        observationLogCombinations = [...own, ...shared];
    } catch (error) {
        console.warn('Observation Log: equipment combinations unavailable', error);
        observationLogCombinations = [];
    }
}

/** Plans available to import from. Both 'current' and 'previous' count: a plan flips to
 * 'previous' the moment the night ends, which is exactly when logging happens. */
async function _obsLoadPlans() {
    try {
        const response = await fetchJSON('/api/plan-my-night/list');
        observationLogPlans = (response.plans || []).filter(
            plan => (plan.state === 'current' || plan.state === 'previous') && (plan.entries_count || 0) > 0
        );
    } catch (error) {
        console.warn('Observation Log: plan list unavailable', error);
        observationLogPlans = [];
    }
}

// ============================================
// Stats header
// ============================================

function renderObservationLogStats() {
    const container = document.getElementById('observation-log-stats');
    if (!container) return;

    const stats = observationLogData.stats || {};
    DOMUtils.buildStatPlate(container, {
        hero: {
            // An empty log still reads as a duration - see _saHours() for the same call.
            value: _obsFormatIntegration(stats.total_integration_minutes)
                || i18n.t('observation_log.minutes_short', { minutes: 0 }),
            label: i18n.t('observation_log.stat_integration'),
        },
        figures: [
            {
                icon: 'bi-moon-stars',
                value: String(stats.total_sessions ?? 0),
                label: i18n.t('observation_log.stat_sessions'),
            },
            {
                icon: 'bi-stars',
                value: String(stats.total_entries ?? 0),
                label: i18n.t('observation_log.stat_targets'),
            },
            {
                icon: 'bi-star-fill',
                value: stats.average_rating != null ? _obsBuildStarRatingDisplay(stats.average_rating) : '-',
                label: i18n.t('observation_log.stat_rating'),
            },
        ],
    });
}

// ============================================
// Session list view
// ============================================

/** Apply the client-side filter/sort state. Session counts are personal and modest, so
 * everything is filtered in the browser - no server-side paging needed. */
function _obsFilteredSessions() {
    const { search, locationId, combinationId, minRating, fromDate, toDate, sort, order } = observationLogFilters;
    const needle = search.trim().toLowerCase();

    const matches = observationLogData.sessions.filter(session => {
        if (locationId && session.location_id !== locationId) return false;
        // Matches either the session's own default equipment or any entry's per-target
        // override - a combination used for just one target during the night is still
        // "equipment used in this session" from the filter's point of view.
        if (combinationId
            && session.combination_id !== combinationId
            && !(session.entries || []).some(entry => entry.combination_id === combinationId)) {
            return false;
        }
        if (!_obsSessionOverlapsDateRange(session, fromDate, toDate)) return false;
        if (minRating && (_obsSessionAverageRating(session) ?? -1) < Number(minRating)) return false;
        if (!needle) return true;

        const haystack = [
            ...(session.nights || []).map(night => night.date),
            session.location_name,
            session.combination_name,
            session.notes,
            ...(session.entries || []).map(entry => entry.name),
            ...(session.entries || []).map(entry => entry.combination_name),
        ].filter(Boolean).join(' ').toLowerCase();
        return haystack.includes(needle);
    });

    const direction = order === 'asc' ? 1 : -1;
    return matches.sort((a, b) => {
        let result = 0;
        if (sort === 'entries') {
            result = (a.entries?.length || 0) - (b.entries?.length || 0);
        } else if (sort === 'integration') {
            result = _obsSessionIntegration(a) - _obsSessionIntegration(b);
        } else if (sort === 'rating') {
            result = (_obsSessionAverageRating(a) ?? -1) - (_obsSessionAverageRating(b) ?? -1);
        } else {
            result = _obsSessionDate(a).localeCompare(_obsSessionDate(b));
        }
        return result * direction;
    });
}

function _obsSessionIntegration(session) {
    return (session.entries || []).reduce((total, entry) => total + (Number(entry.integration_minutes) || 0), 0);
}

function _obsSessionFrames(session) {
    return (session.entries || []).reduce((total, entry) => total + (Number(entry.frame_count) || 0), 0);
}

/** Mean of the *rated* entries only - unrated targets are excluded rather than counted as zero. */
function _obsSessionAverageRating(session) {
    const ratings = (session.entries || [])
        .map(entry => Number(entry.rating))
        .filter(value => Number.isFinite(value));
    if (!ratings.length) return null;
    return ratings.reduce((total, value) => total + value, 0) / ratings.length;
}

function renderObservationSessionsList() {
    const container = document.getElementById('observation-log-display');
    if (!container) return;

    observationLogOpenSessionId = null;
    DOMUtils.clear(container);
    container.appendChild(_obsBuildListToolbar());
    container.appendChild(_obsBuildFilterBar());

    // Results live in their own container so a filter change can refresh just the cards -
    // rebuilding the whole view on every keystroke would blow away the search input's focus
    // and caret position.
    const results = document.createElement('div');
    results.id = 'observation-log-results';
    container.appendChild(results);
    _obsRenderSessionGrid();
}

function _obsRenderSessionGrid() {
    const results = document.getElementById('observation-log-results');
    if (!results) return;
    DOMUtils.clear(results);

    const sessions = _obsFilteredSessions();
    if (!sessions.length) {
        const empty = document.createElement('div');
        empty.className = 'observation-log-empty';
        empty.textContent = observationLogData.sessions.length
            ? i18n.t('observation_log.no_match')
            : i18n.t('observation_log.empty');
        results.appendChild(empty);
        return;
    }

    const grid = document.createElement('div');
    grid.className = 'row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3 mt-1';
    sessions.forEach(session => grid.appendChild(_obsBuildSessionCard(session)));
    results.appendChild(grid);
}

function _obsBuildListToolbar() {
    const toolbar = document.createElement('div');
    toolbar.className = 'd-flex flex-wrap gap-2 align-items-center mb-2';

    const title = document.createElement('h3');
    title.className = 'h5 mb-0 me-auto';
    title.textContent = i18n.t('observation_log.my_sessions');
    toolbar.appendChild(title);

    // A read action, offered to every logged-in role - not gated on canEdit below.
    if (observationLogData.sessions.length) {
        const exportAllButton = document.createElement('button');
        exportAllButton.type = 'button';
        exportAllButton.id = 'observation-log-export-all';
        exportAllButton.className = 'btn btn-outline-secondary btn-sm';
        DOMUtils.append(
            exportAllButton,
            DOMUtils.createIcon('bi bi-filetype-pdf icon-inline'),
            i18n.t('observation_log.export_pdf_all')
        );
        exportAllButton.addEventListener('click', () => showObservationExportRangeModal());
        toolbar.appendChild(exportAllButton);
    }

    if (!observationLogData.canEdit) return toolbar;

    const newButton = document.createElement('button');
    newButton.type = 'button';
    newButton.id = 'observation-log-new-session';
    newButton.className = 'btn btn-success btn-sm';
    DOMUtils.append(
        newButton,
        DOMUtils.createIcon('bi bi-plus-circle icon-inline'),
        i18n.t('observation_log.new_session')
    );
    newButton.addEventListener('click', () => showObservationSessionForm(null));
    toolbar.appendChild(newButton);

    // Only offered when there is actually something importable (a current or previous
    // plan that has targets) - otherwise the button is a dead end.
    if (observationLogPlans.length) {
        const importButton = document.createElement('button');
        importButton.type = 'button';
        importButton.id = 'observation-log-import-plan';
        importButton.className = 'btn btn-info btn-sm';
        DOMUtils.append(
            importButton,
            DOMUtils.createIcon('bi bi-box-arrow-in-down icon-inline'),
            i18n.t('observation_log.import_from_plan')
        );
        importButton.addEventListener('click', () => showObservationImportFromPlanModal());
        toolbar.appendChild(importButton);
    }

    return toolbar;
}

function _obsBuildFilterBar() {
    const row = document.createElement('div');
    row.className = 'row g-2 mb-2';

    const search = _obsInput('observation-log-search', 'search', observationLogFilters.search, {
        placeholder: i18n.t('observation_log.search_placeholder'),
    });
    search.addEventListener('input', () => {
        observationLogFilters.search = search.value;
        _obsRenderSessionGrid();
    });
    row.appendChild(_obsField('col-6 col-lg-3', i18n.t('observation_log.filter_search'), search, search.id));

    const fromDate = _obsInput('observation-log-from', 'date', observationLogFilters.fromDate);
    fromDate.addEventListener('change', () => {
        observationLogFilters.fromDate = fromDate.value;
        _obsRenderSessionGrid();
    });
    row.appendChild(_obsField('col-6 col-lg-2', i18n.t('observation_log.filter_from'), fromDate, fromDate.id));

    const toDate = _obsInput('observation-log-to', 'date', observationLogFilters.toDate);
    toDate.addEventListener('change', () => {
        observationLogFilters.toDate = toDate.value;
        _obsRenderSessionGrid();
    });
    row.appendChild(_obsField('col-6 col-lg-2', i18n.t('observation_log.filter_to'), toDate, toDate.id));

    const locationOptions = [{ value: '', label: i18n.t('observation_log.filter_all_locations') }];
    observationLogLocations.forEach(loc => locationOptions.push({ value: loc.id, label: loc.name || '?' }));
    const locationSelect = _obsSelect('observation-log-location-filter', locationOptions, observationLogFilters.locationId);
    locationSelect.addEventListener('change', () => {
        observationLogFilters.locationId = locationSelect.value;
        _obsRenderSessionGrid();
    });
    row.appendChild(_obsField('col-6 col-lg-2', i18n.t('observation_log.location'), locationSelect, locationSelect.id));

    const comboOptions = [{ value: '', label: i18n.t('observation_log.filter_all_combinations') }];
    observationLogCombinations.forEach(combo => comboOptions.push({ value: combo.id, label: combo.name || '?' }));
    const comboSelect = _obsSelect('observation-log-combination-filter', comboOptions, observationLogFilters.combinationId);
    comboSelect.addEventListener('change', () => {
        observationLogFilters.combinationId = comboSelect.value;
        _obsRenderSessionGrid();
    });
    row.appendChild(_obsField('col-6 col-lg-2', i18n.t('observation_log.equipment'), comboSelect, comboSelect.id));

    const ratingOptions = [{ value: '', label: i18n.t('observation_log.filter_any_rating') }];
    [1, 2, 3, 4, 5].forEach(value => ratingOptions.push({
        value: String(value),
        label: i18n.t('observation_log.filter_min_rating', { rating: value }),
    }));
    const ratingSelect = _obsSelect('observation-log-rating-filter', ratingOptions, observationLogFilters.minRating);
    ratingSelect.addEventListener('change', () => {
        observationLogFilters.minRating = ratingSelect.value;
        _obsRenderSessionGrid();
    });
    row.appendChild(_obsField('col-6 col-lg-2', i18n.t('observation_log.rating'), ratingSelect, ratingSelect.id));

    const sortGroup = document.createElement('div');
    sortGroup.className = 'input-group';
    const sortSelect = _obsSelect('observation-log-sort', [
        { value: 'date', label: i18n.t('observation_log.sort_by_date') },
        { value: 'entries', label: i18n.t('observation_log.sort_by_targets') },
        { value: 'integration', label: i18n.t('observation_log.sort_by_integration') },
        { value: 'rating', label: i18n.t('observation_log.sort_by_rating') },
    ], observationLogFilters.sort);
    sortSelect.addEventListener('change', () => {
        observationLogFilters.sort = sortSelect.value;
        _obsRenderSessionGrid();
    });
    const orderButton = document.createElement('button');
    orderButton.type = 'button';
    orderButton.className = 'btn btn-primary';
    orderButton.title = i18n.t('observation_log.toggle_sort_order');
    orderButton.appendChild(DOMUtils.createIcon(
        observationLogFilters.order === 'asc' ? 'bi bi-sort-down-alt' : 'bi bi-sort-up-alt'
    ));
    orderButton.addEventListener('click', () => {
        observationLogFilters.order = observationLogFilters.order === 'asc' ? 'desc' : 'asc';
        DOMUtils.clear(orderButton);
        orderButton.appendChild(DOMUtils.createIcon(
            observationLogFilters.order === 'asc' ? 'bi bi-sort-down-alt' : 'bi bi-sort-up-alt'
        ));
        _obsRenderSessionGrid();
    });
    sortGroup.appendChild(sortSelect);
    sortGroup.appendChild(orderButton);
    row.appendChild(_obsField('col-12 col-lg-3', i18n.t('observation_log.sort'), sortGroup, sortSelect.id));

    return row;
}

function _obsBuildSessionCard(session) {
    const col = document.createElement('div');
    col.className = 'col';

    const card = document.createElement('div');
    card.className = 'card h-100 observation-log-session-card';
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    const open = () => renderObservationSessionDetail(session.id);
    card.addEventListener('click', open);
    card.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            open();
        }
    });

    const body = document.createElement('div');
    body.className = 'card-body';

    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-start gap-2';
    const date = document.createElement('span');
    date.className = 'observation-log-session-date';
    date.textContent = _obsFormatSessionDateLabel(session);
    header.appendChild(date);

    const entryCount = document.createElement('span');
    entryCount.className = 'badge bg-primary';
    entryCount.textContent = i18n.t('observation_log.target_count', { count: (session.entries || []).length });
    header.appendChild(entryCount);
    body.appendChild(header);

    const metaParts = [session.location_name, _obsCombinationLabel(session)].filter(Boolean);
    if (metaParts.length) {
        const meta = document.createElement('div');
        meta.className = 'observation-log-meta mt-1';
        meta.textContent = metaParts.join(' · ');
        body.appendChild(meta);
    }

    const summary = document.createElement('div');
    summary.className = 'observation-log-meta mt-2 d-flex flex-wrap gap-2 align-items-center';
    const integration = _obsFormatIntegration(_obsSessionIntegration(session));
    if (integration) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-secondary';
        badge.textContent = i18n.t('observation_log.integration_badge', { value: integration });
        summary.appendChild(badge);
    }
    const frames = _obsSessionFrames(session);
    if (frames > 0) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-secondary';
        badge.textContent = i18n.t('observation_log.frames_badge', { count: frames });
        summary.appendChild(badge);
    }
    const average = _obsSessionAverageRating(session);
    if (average != null) summary.appendChild(_obsBuildStarRatingDisplay(average));
    if (summary.childNodes.length) body.appendChild(summary);

    if (session.notes) {
        const notes = document.createElement('p');
        notes.className = 'observation-log-meta mt-2 mb-0';
        notes.textContent = session.notes;
        body.appendChild(notes);
    }

    card.appendChild(body);
    col.appendChild(card);
    return col;
}

// ============================================
// Session detail view
// ============================================

function renderObservationSessionDetail(sessionId) {
    const container = document.getElementById('observation-log-display');
    const session = observationLogData.sessions.find(item => item.id === sessionId);
    if (!container || !session) {
        renderObservationSessionsList();
        return;
    }

    observationLogOpenSessionId = sessionId;
    DOMUtils.clear(container);

    const toolbar = document.createElement('div');
    toolbar.className = 'd-flex flex-wrap gap-2 align-items-center mb-3';

    const backButton = document.createElement('button');
    backButton.type = 'button';
    backButton.id = 'observation-log-back';
    backButton.className = 'btn btn-dark btn-sm';
    DOMUtils.append(backButton, DOMUtils.createIcon('bi bi-arrow-left icon-inline'), i18n.t('observation_log.back_to_list'));
    backButton.addEventListener('click', () => renderObservationSessionsList());
    toolbar.appendChild(backButton);

    const heading = document.createElement('h3');
    heading.className = 'h5 mb-0 me-auto';
    heading.textContent = i18n.t('observation_log.session_of', { date: _obsFormatSessionDateLabel(session) });
    toolbar.appendChild(heading);

    const sessionPictures = _obsCollectSessionPictures(session);
    if (sessionPictures.length) {
        const galleryButton = document.createElement('button');
        galleryButton.type = 'button';
        galleryButton.id = 'observation-log-session-photos';
        galleryButton.className = 'btn btn-outline-primary btn-sm';
        DOMUtils.append(
            galleryButton,
            DOMUtils.createIcon('bi bi-images icon-inline'),
            i18n.t('observation_log.session_photos', { count: sessionPictures.length })
        );
        galleryButton.addEventListener('click', () => showPictureSlideshowFromPictures(sessionPictures, {
            title: i18n.t('observation_log.session_photos_title', { date: _obsFormatSessionDateLabel(session) }),
        }));
        toolbar.appendChild(galleryButton);
    }

    const exportPdfButton = document.createElement('button');
    exportPdfButton.type = 'button';
    exportPdfButton.id = 'observation-log-export-pdf';
    exportPdfButton.className = 'btn btn-outline-secondary btn-sm';
    DOMUtils.append(exportPdfButton, DOMUtils.createIcon('bi bi-filetype-pdf icon-inline'), i18n.t('observation_log.export_pdf'));
    exportPdfButton.addEventListener('click', () => {
        const lang = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : 'en';
        _obsTriggerPdfDownload(`${OBSERVATION_LOG_API}/${session.id}/export.pdf?lang=${encodeURIComponent(lang)}`);
    });
    toolbar.appendChild(exportPdfButton);

    if (observationLogData.canEdit) {
        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'btn btn-primary btn-sm';
        DOMUtils.append(editButton, DOMUtils.createIcon('bi bi-pencil icon-inline'), i18n.t('observation_log.edit_session'));
        editButton.addEventListener('click', () => showObservationSessionForm(session));
        toolbar.appendChild(editButton);

        const addEntryButton = document.createElement('button');
        addEntryButton.type = 'button';
        addEntryButton.id = 'observation-log-add-target';
        addEntryButton.className = 'btn btn-success btn-sm';
        DOMUtils.append(addEntryButton, DOMUtils.createIcon('bi bi-plus-circle icon-inline'), i18n.t('observation_log.add_target'));
        addEntryButton.addEventListener('click', () => showObservationEntryForm(session.id, null));
        toolbar.appendChild(addEntryButton);

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'btn btn-danger btn-sm';
        DOMUtils.append(deleteButton, DOMUtils.createIcon('bi bi-trash icon-inline'), i18n.t('observation_log.delete_session'));
        deleteButton.addEventListener('click', () => deleteObservationSession(session.id));
        toolbar.appendChild(deleteButton);
    }

    container.appendChild(toolbar);
    container.appendChild(_obsBuildSessionSummaryCard(session));
    container.appendChild(_obsBuildNightsSection(session));
    container.appendChild(_obsBuildEntriesList(session));
    container.appendChild(_obsBuildAttachmentsSection(session));
}

/** Trip-level card: location/equipment (fixed for the whole session) + total
 * integration across every night, plus the trip-level notes. Per-night conditions
 * (date/sqm/seeing/...) live in _obsBuildNightsSection() below, one card per night. */
function _obsBuildSessionSummaryCard(session) {
    const card = document.createElement('div');
    card.className = 'card mb-3';
    const body = document.createElement('div');
    body.className = 'card-body';

    const grid = document.createElement('div');
    grid.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-4 g-2';

    const rows = [
        [i18n.t('observation_log.location'), session.location_name || i18n.t('observation_log.no_location')],
        [i18n.t('observation_log.default_equipment'), _obsCombinationLabel(session) || i18n.t('observation_log.no_equipment')],
        [i18n.t('observation_log.total_integration'), _obsFormatIntegration(_obsSessionIntegration(session)) || '—'],
        [i18n.t('observation_log.stat_targets'), String((session.entries || []).length)],
    ];

    rows.forEach(([label, value]) => {
        const col = document.createElement('div');
        col.className = 'col';
        const labelEl = document.createElement('div');
        labelEl.className = 'text-muted small';
        labelEl.textContent = label;
        const valueEl = document.createElement('div');
        valueEl.className = 'observation-log-summary-value';
        valueEl.textContent = value;
        col.appendChild(labelEl);
        col.appendChild(valueEl);
        grid.appendChild(col);
    });

    body.appendChild(grid);

    if (session.notes) {
        const notes = document.createElement('p');
        notes.className = 'mt-3 mb-0';
        notes.textContent = session.notes;
        body.appendChild(notes);
    }

    card.appendChild(body);
    return card;
}

/** One card per night: its own date/start-end/SQM/seeing/transparency/moon/notes, plus
 * add/edit/delete controls. A session always has >=1 night. */
function _obsBuildNightsSection(session) {
    const wrap = document.createElement('div');
    wrap.className = 'mb-3';

    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-center mb-2';
    const title = document.createElement('h6');
    title.className = 'text-muted mb-0';
    title.textContent = i18n.t('observation_log.nights_section');
    header.appendChild(title);

    if (observationLogData.canEdit) {
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.id = 'observation-log-add-night';
        addButton.className = 'btn btn-outline-success btn-sm';
        DOMUtils.append(addButton, DOMUtils.createIcon('bi bi-plus-circle icon-inline'), i18n.t('observation_log.add_night'));
        addButton.addEventListener('click', () => showObservationNightForm(session.id, null));
        header.appendChild(addButton);
    }
    wrap.appendChild(header);

    const grid = document.createElement('div');
    grid.className = 'row row-cols-1 row-cols-lg-2 g-2';
    _obsSortedNights(session).forEach(night => grid.appendChild(_obsBuildNightCard(session, night)));
    wrap.appendChild(grid);

    return wrap;
}

function _obsBuildNightCard(session, night) {
    const col = document.createElement('div');
    col.className = 'col';
    const card = document.createElement('div');
    card.className = 'card h-100 observation-log-night-card';
    card.dataset.nightId = night.id;
    const body = document.createElement('div');
    body.className = 'card-body py-2';

    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-start gap-2';
    const date = document.createElement('div');
    date.className = 'fw-bold observation-log-night-date';
    date.textContent = night.date || '';
    header.appendChild(date);

    if (observationLogData.canEdit) {
        const actions = document.createElement('div');
        actions.className = 'd-flex gap-1';

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'btn btn-outline-primary btn-sm';
        editButton.title = i18n.t('observation_log.edit_night');
        editButton.appendChild(DOMUtils.createIcon('bi bi-pencil'));
        editButton.addEventListener('click', () => showObservationNightForm(session.id, night));
        actions.appendChild(editButton);

        if ((session.nights || []).length > 1) {
            const deleteButton = document.createElement('button');
            deleteButton.type = 'button';
            deleteButton.className = 'btn btn-outline-danger btn-sm';
            deleteButton.title = i18n.t('observation_log.delete_night');
            deleteButton.appendChild(DOMUtils.createIcon('bi bi-trash'));
            deleteButton.addEventListener('click', () => deleteObservationNight(session.id, night.id));
            actions.appendChild(deleteButton);
        }
        header.appendChild(actions);
    }
    body.appendChild(header);

    const conditionsGrid = document.createElement('div');
    conditionsGrid.className = 'row row-cols-2 row-cols-md-3 g-1 mt-1';
    const conditionRows = [
        [i18n.t('observation_log.start_time'), night.start_time ? formatTimeThenDate(night.start_time) : '—'],
        [i18n.t('observation_log.end_time'), night.end_time ? formatTimeThenDate(night.end_time) : '—'],
        [i18n.t('observation_log.sqm'), night.sqm != null ? String(night.sqm) : '—'],
        [
            i18n.t('observation_log.seeing'),
            night.seeing != null ? i18n.t('observation_log.seeing_value', { value: night.seeing }) : '—',
        ],
        [
            i18n.t('observation_log.transparency'),
            night.transparency != null
                ? i18n.t('observation_log.transparency_value', { value: night.transparency })
                : '—',
        ],
        [
            i18n.t('observation_log.moon_illumination'),
            night.moon_illumination_percent != null
                ? i18n.t('observation_log.moon_illumination_value', { value: Math.round(night.moon_illumination_percent) })
                : '—',
        ],
    ];
    conditionRows.forEach(([label, value]) => {
        const cell = document.createElement('div');
        cell.className = 'col';
        const labelEl = document.createElement('div');
        labelEl.className = 'text-muted small';
        labelEl.textContent = label;
        const valueEl = document.createElement('div');
        valueEl.className = 'small';
        valueEl.textContent = value;
        cell.appendChild(labelEl);
        cell.appendChild(valueEl);
        conditionsGrid.appendChild(cell);
    });
    body.appendChild(conditionsGrid);

    if (night.notes) {
        const notes = document.createElement('div');
        notes.className = 'observation-log-meta small mt-2';
        notes.textContent = night.notes;
        body.appendChild(notes);
    }

    card.appendChild(body);
    col.appendChild(card);
    return col;
}

/** Flat list for a single-night session (the common case); grouped by night, with a
 * date divider per group, once there's more than one - the "day-by-day" breakdown a
 * multi-night trip needs. */
function _obsBuildEntriesList(session) {
    const wrap = document.createElement('div');
    const entries = session.entries || [];

    if (!entries.length) {
        const empty = document.createElement('div');
        empty.className = 'observation-log-empty';
        empty.textContent = i18n.t('observation_log.no_targets');
        wrap.appendChild(empty);
        return wrap;
    }

    const nights = _obsSortedNights(session);
    if (nights.length <= 1) {
        entries.forEach(entry => wrap.appendChild(_obsBuildEntryRow(session, entry)));
        return wrap;
    }

    const entriesByNight = new Map(nights.map(night => [night.id, []]));
    const unassigned = [];
    entries.forEach(entry => {
        const bucket = entriesByNight.get(entry.night_id);
        if (bucket) bucket.push(entry);
        else unassigned.push(entry);
    });

    nights.forEach(night => {
        const nightEntries = entriesByNight.get(night.id) || [];
        if (!nightEntries.length) return;
        wrap.appendChild(_obsSectionHeader(night.date || ''));
        nightEntries.forEach(entry => wrap.appendChild(_obsBuildEntryRow(session, entry)));
    });

    if (unassigned.length) {
        wrap.appendChild(_obsSectionHeader(i18n.t('observation_log.other_night_group')));
        unassigned.forEach(entry => wrap.appendChild(_obsBuildEntryRow(session, entry)));
    }

    return wrap;
}

/** Resolve an entry's linked Astrodex picture (filename, etc.) via the astrodexData
 * global that loadAstrodex() populates whenever the Astrodex main tab opens - this
 * module never fetches pictures itself. Returns null until that data is loaded, or
 * when the entry has no attached photo. */
function _obsResolveEntryPicture(entry) {
    if (!entry?.astrodex_item_id || !entry?.astrodex_picture_id) return null;
    if (typeof astrodexData === 'undefined' || !Array.isArray(astrodexData.items)) return null;
    const item = astrodexData.items.find(candidate => candidate.id === entry.astrodex_item_id);
    if (!item || !Array.isArray(item.pictures)) return null;
    const picture = item.pictures.find(candidate => candidate.id === entry.astrodex_picture_id);
    return picture ? { item, picture } : null;
}

/** All of a session's attached photos, flattened for showPictureSlideshowFromPictures(). */
function _obsCollectSessionPictures(session) {
    const pictures = [];
    (session.entries || []).forEach(entry => {
        const resolved = _obsResolveEntryPicture(entry);
        if (resolved) pictures.push({ ...resolved.picture, item_name: entry.name || resolved.item.name });
    });
    return pictures;
}

function _obsBuildEntryRow(session, entry) {
    const row = document.createElement('div');
    row.className = 'observation-log-entry-row p-2 mb-2';

    const header = document.createElement('div');
    header.className = 'd-flex flex-wrap justify-content-between align-items-center gap-2';

    const identityGroup = document.createElement('div');
    identityGroup.className = 'd-flex align-items-center gap-2';

    const resolvedPicture = _obsResolveEntryPicture(entry);
    if (resolvedPicture) {
        const thumbButton = document.createElement('button');
        thumbButton.type = 'button';
        thumbButton.className = 'observation-log-entry-thumb btn p-0 border-0';
        thumbButton.title = i18n.t('observation_log.view_photo');
        const thumbImg = document.createElement('img');
        thumbImg.src = `/api/astrodex/images/${resolvedPicture.picture.filename}`;
        thumbImg.alt = entry.name || '';
        thumbImg.loading = 'lazy';
        thumbButton.appendChild(thumbImg);
        thumbButton.addEventListener('click', () => showPictureSlideshow(entry.astrodex_item_id));
        identityGroup.appendChild(thumbButton);
    }

    const identity = document.createElement('div');
    const name = document.createElement('div');
    name.className = 'observation-log-entry-name';
    name.textContent = entry.name || '';
    identity.appendChild(name);

    const subtitleParts = [entry.type, entry.constellation, entry.catalogue].filter(Boolean);
    if (subtitleParts.length) {
        const subtitle = document.createElement('div');
        subtitle.className = 'observation-log-meta';
        subtitle.textContent = subtitleParts.join(' · ');
        identity.appendChild(subtitle);
    }
    identityGroup.appendChild(identity);
    header.appendChild(identityGroup);

    const numbers = document.createElement('div');
    numbers.className = 'd-flex flex-wrap align-items-center gap-2';
    // Always shown (when there's an equipment to show at all), not just for the rare
    // target that used something other than the session's own default - every row
    // states plainly what equipment it was actually captured with.
    const entryCombo = _obsEntryEffectiveCombinationLabel(session, entry);
    if (entryCombo) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-info text-dark';
        DOMUtils.append(badge, DOMUtils.createIcon('bi bi-camera icon-inline'), entryCombo);
        numbers.appendChild(badge);
    }
    if (entry.frame_count) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-secondary';
        badge.textContent = i18n.t('observation_log.frames_badge', { count: entry.frame_count });
        numbers.appendChild(badge);
    }
    const integration = _obsFormatIntegration(entry.integration_minutes);
    if (integration) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-secondary';
        badge.textContent = i18n.t('observation_log.integration_badge', { value: integration });
        numbers.appendChild(badge);
    }
    // Only from an imported plan target - a frozen snapshot of what was scheduled, so it
    // can be compared against what was actually logged above.
    const planned = _obsFormatIntegration(entry.planned_minutes);
    if (planned) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-light text-dark border';
        badge.textContent = i18n.t('observation_log.planned_badge', { value: planned });
        numbers.appendChild(badge);
    }
    if (entry.rating != null) numbers.appendChild(_obsBuildStarRatingDisplay(entry.rating));
    header.appendChild(numbers);

    row.appendChild(header);

    if (entry.notes) {
        const notes = document.createElement('div');
        notes.className = 'observation-log-meta mt-1';
        notes.textContent = entry.notes;
        row.appendChild(notes);
    }

    row.appendChild(_obsBuildEntryActions(session, entry));
    return row;
}

/** The altitude-time chart is only meaningful while its entry's own night is ongoing:
 * the cached alttime file backing it gets recalculated for "tonight" on every
 * SkyTonight run, so it no longer reflects the observation once that night's window
 * closes. */
function _obsIsWithinObservationWindow(night) {
    if (!night?.start_time || !night?.end_time) return false;
    const start = new Date(night.start_time);
    const end = new Date(night.end_time);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return false;
    const now = new Date();
    return now >= start && now <= end;
}

function _obsBuildEntryActions(session, entry) {
    const actions = document.createElement('div');
    actions.className = 'd-flex flex-wrap align-items-center gap-2 mt-2';

    // Astrodex status is shown, never clicked into existence: the item link appears on
    // its own as soon as a frame count is logged (see the backend's auto-link).
    if (entry.astrodex_item_id) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-success';
        DOMUtils.append(
            badge,
            DOMUtils.createIcon('bi bi-check-circle icon-inline'),
            entry.astrodex_picture_id
                ? i18n.t('observation_log.in_astrodex_with_photo')
                : i18n.t('observation_log.in_astrodex')
        );
        actions.appendChild(badge);
    }

    const entryNight = (session.nights || []).find(night => night.id === entry.night_id);
    if (entry.alttime_file && typeof showAlttimePopup === 'function' && _obsIsWithinObservationWindow(entryNight)) {
        const chartButton = document.createElement('button');
        chartButton.type = 'button';
        chartButton.className = 'btn btn-info btn-sm';
        DOMUtils.append(
            chartButton,
            DOMUtils.createIcon('bi bi-graph-up-arrow icon-inline'),
            i18n.t('observation_log.view_altitude_chart')
        );
        chartButton.addEventListener('click', () => {
            const title = `${entry.name || ''} - ${i18n.t('skytonight.altitude_time_title')}`;
            showAlttimePopup(title, entry.alttime_file, session.location_id);
        });
        actions.appendChild(chartButton);
    }

    if (!observationLogData.canEdit) return actions;

    const editButton = document.createElement('button');
    editButton.type = 'button';
    editButton.className = 'btn btn-primary btn-sm';
    DOMUtils.append(editButton, DOMUtils.createIcon('bi bi-pencil icon-inline'), i18n.t('observation_log.edit_target'));
    editButton.addEventListener('click', () => showObservationEntryForm(session.id, entry));
    actions.appendChild(editButton);

    const attachButton = document.createElement('button');
    attachButton.type = 'button';
    attachButton.className = 'btn btn-outline-primary btn-sm';
    DOMUtils.append(
        attachButton,
        DOMUtils.createIcon('bi bi-image icon-inline'),
        i18n.t('observation_log.attach_picture')
    );
    attachButton.addEventListener('click', () => showObservationAttachPictureModal(session.id, entry.id));
    actions.appendChild(attachButton);

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'btn btn-danger btn-sm';
    DOMUtils.append(deleteButton, DOMUtils.createIcon('bi bi-trash icon-inline'), i18n.t('observation_log.delete_target'));
    deleteButton.addEventListener('click', () => deleteObservationEntry(session.id, entry.id));
    actions.appendChild(deleteButton);

    return actions;
}

// ============================================
// Location picker (3-state preset / custom / none + minimap)
// ============================================

/** Location <select> + free-text fallback + minimap, mirroring astrodex.js's picture
 * location picker. `session` omitted -> new-session defaults (active location). */
function _obsBuildLocationFields(session) {
    const fragment = document.createDocumentFragment();

    const hasPreset = !!session?.location_id;
    const hasCustom = !!session && !hasPreset && !!session.location_name;
    const selected = session === null || session === undefined
        ? (observationLogActiveLocationId || '')
        : (hasPreset ? session.location_id : (hasCustom ? _OBS_CUSTOM_LOCATION_VALUE : ''));

    const options = [{ value: '', label: i18n.t('observation_log.no_location') }];
    observationLogLocations.forEach(loc => options.push({ value: loc.id, label: loc.name || '?' }));
    options.push({ value: _OBS_CUSTOM_LOCATION_VALUE, label: i18n.t('observation_log.other_location') });

    const select = _obsSelect('observation-session-location', options, selected);
    select.addEventListener('change', () => {
        _obsToggleCustomLocationFields();
        _obsPrefillSqmFromPreset();
        _obsUpdateLocationMap();
    });
    fragment.appendChild(_obsField('col-md-6', i18n.t('observation_log.location'), select, select.id));

    const nameInput = _obsInput('observation-session-location-name', 'text', hasCustom ? session.location_name : '', {
        placeholder: i18n.t('observation_log.custom_location_placeholder'),
    });
    nameInput.addEventListener('input', _obsOnCoordinatesChanged);
    const nameBlock = _obsField('col-md-6', i18n.t('observation_log.custom_location_name'), nameInput, nameInput.id);
    nameBlock.id = 'observation-session-location-name-block';

    const latInput = _obsInput(
        'observation-session-location-lat',
        'number',
        hasCustom && session.location_latitude != null ? session.location_latitude : '',
        { step: 'any', min: '-90', max: '90', placeholder: '48.85' }
    );
    latInput.addEventListener('input', _obsOnCoordinatesChanged);
    const latBlock = _obsField('col-md-3', i18n.t('observation_log.custom_location_lat'), latInput, latInput.id);
    latBlock.id = 'observation-session-location-lat-block';

    const lngInput = _obsInput(
        'observation-session-location-lng',
        'number',
        hasCustom && session.location_longitude != null ? session.location_longitude : '',
        { step: 'any', min: '-180', max: '180', placeholder: '2.35' }
    );
    lngInput.addEventListener('input', _obsOnCoordinatesChanged);
    const lngBlock = _obsField('col-md-3', i18n.t('observation_log.custom_location_lng'), lngInput, lngInput.id);
    lngBlock.id = 'observation-session-location-lng-block';

    [nameBlock, latBlock, lngBlock].forEach(block => {
        if (!hasCustom) block.style.display = 'none';
        fragment.appendChild(block);
    });

    const mapBlock = document.createElement('div');
    mapBlock.className = 'col-12';
    mapBlock.id = 'observation-session-location-map-block';
    mapBlock.style.display = 'none';
    const mapDiv = document.createElement('div');
    mapDiv.className = 'rounded observation-log-location-map';
    mapDiv.id = 'observation-session-location-map';
    mapBlock.appendChild(mapDiv);
    fragment.appendChild(mapBlock);

    return fragment;
}

function _obsToggleCustomLocationFields() {
    const isOther = document.getElementById('observation-session-location')?.value === _OBS_CUSTOM_LOCATION_VALUE;
    ['name', 'lat', 'lng'].forEach(part => {
        const block = document.getElementById(`observation-session-location-${part}-block`);
        if (block) block.style.display = isOther ? '' : 'none';
    });
}

function _obsOnCoordinatesChanged() {
    clearTimeout(_observationCoordinatesDebounce);
    _observationCoordinatesDebounce = setTimeout(() => _obsUpdateLocationMap(), 400);
}

function _obsEffectiveCoordinates() {
    const value = document.getElementById('observation-session-location')?.value || '';
    if (!value) return null;
    if (value === _OBS_CUSTOM_LOCATION_VALUE) {
        const lat = parseFloat(document.getElementById('observation-session-location-lat')?.value);
        const lng = parseFloat(document.getElementById('observation-session-location-lng')?.value);
        return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null;
    }
    const preset = observationLogLocations.find(loc => loc.id === value);
    const lat = Number(preset?.latitude);
    const lng = Number(preset?.longitude);
    return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null;
}

/** Only one session modal is ever open at a time, so a single shared map instance
 * (torn down and rebuilt on change) is simpler than updating one in place. */
async function _obsUpdateLocationMap() {
    const block = document.getElementById('observation-session-location-map-block');
    const container = document.getElementById('observation-session-location-map');
    if (!block || !container) return;

    const coords = _obsEffectiveCoordinates();
    if (!coords) {
        block.style.display = 'none';
        _obsDestroyLocationMap();
        return;
    }

    block.style.display = '';
    if (typeof _ensureLocationsLeafletLoaded === 'function') {
        try {
            await _ensureLocationsLeafletLoaded();
        } catch (error) {
            console.warn('Leaflet failed to load; session location map unavailable', error);
            block.style.display = 'none';
            return;
        }
    }
    if (!document.body.contains(container)) return; // modal closed while Leaflet was loading
    if (typeof L === 'undefined') return;

    _obsDestroyLocationMap();
    _observationLocationMap = L.map(container, { scrollWheelZoom: false, zoomControl: false })
        .setView([coords.lat, coords.lng], 9);
    addLeafletBasemap(_observationLocationMap, 'light', { maxZoom: 18 });
    L.marker([coords.lat, coords.lng]).addTo(_observationLocationMap);
}

function _obsDestroyLocationMap() {
    if (!_observationLocationMap) return;
    try {
        _observationLocationMap.remove();
    } catch (error) {
        console.debug('Session location map already removed', error);
    }
    _observationLocationMap = null;
}

function _obsCollectLocationFields() {
    const value = document.getElementById('observation-session-location')?.value || '';
    if (value === _OBS_CUSTOM_LOCATION_VALUE) {
        return {
            location_id: null,
            location_name: document.getElementById('observation-session-location-name')?.value.trim() || '',
            location_latitude: _obsNumberOrNull('observation-session-location-lat'),
            location_longitude: _obsNumberOrNull('observation-session-location-lng'),
        };
    }
    return { location_id: value || null, location_name: null };
}

/** Pre-fill SQM from the newly selected preset's own configured value, but never
 * overwrite a number the user already typed - measured SQM varies night to night. */
function _obsPrefillSqmFromPreset() {
    const sqmInput = document.getElementById('observation-session-sqm');
    if (!sqmInput || sqmInput.value.trim() !== '') return;
    const presetId = document.getElementById('observation-session-location')?.value;
    const preset = observationLogLocations.find(loc => loc.id === presetId);
    if (preset?.sqm != null) sqmInput.value = String(preset.sqm);
}

/** Seeing/transparency prefill from the live 7Timer forecast - only meaningful when a
 * night is being logged for today, since forecasts don't cover past dates. Shared by
 * the session-creation form (which seeds night 0) and the add/edit-night form -
 * different field ids, same rule. */
async function _obsPrefillSkyConditionsIfToday(dateInputId, seeingSelectId, transparencySelectId) {
    const dateInput = document.getElementById(dateInputId);
    if (!dateInput || dateInput.value !== _obsTodayIso()) return;

    const seeingSelect = document.getElementById(seeingSelectId);
    const transparencySelect = document.getElementById(transparencySelectId);
    if (!seeingSelect || !transparencySelect) return;
    if (seeingSelect.value !== '' && transparencySelect.value !== '') return;

    try {
        const forecast = await fetchJSON('/api/seeing-forecast');
        if (seeingSelect.value === '' && forecast?.now != null) {
            seeingSelect.value = String(forecast.now);
        }
        const currentSlot = (forecast?.forecast || [])[0];
        if (transparencySelect.value === '' && currentSlot?.transparency != null) {
            transparencySelect.value = String(currentSlot.transparency);
        }
    } catch (error) {
        console.debug('Seeing forecast unavailable for prefill', error);
    }
}

// ============================================
// Session create/edit modal
// ============================================

/** Equipment <select> option list: "No equipment" plus every enabled combination -
 * force-including forceIncludeId even if disabled, so a session/entry already tagged
 * with a since-disabled combination doesn't silently lose its selected option. Shared
 * by the session form and the entry form: an entry's Equipment select pre-selects the
 * real, concrete combination (its own override, or else the session's own) rather than
 * offering a separate "same as session" pseudo-choice alongside the real one - one
 * fewer way to express the same thing. */
function _obsBuildCombinationOptionsList(forceIncludeId) {
    const options = [{ value: _OBS_NO_COMBINATION_VALUE, label: i18n.t('observation_log.no_equipment') }];
    observationLogCombinations
        .filter(combo => !combo.is_disabled || combo.id === forceIncludeId)
        .forEach(combo => {
            const label = combo.owner_username
                ? `${combo.name} ${i18n.t('equipment.shared_fov_suffix', { username: combo.owner_username })}`
                : combo.name;
            options.push({ value: combo.id, label });
        });
    return options;
}

function _obsBuildCombinationOptions(session) {
    return _obsBuildCombinationOptionsList(session?.combination_id || null);
}

/** Creating a session also seeds its first night, so the *create* form keeps asking
 * for date/start/end/sqm/seeing/transparency (mirrors the old single-night form
 * exactly). *Editing* an existing session only touches trip-level fields - location,
 * equipment, notes; a night's own conditions are edited through
 * showObservationNightForm() instead, from the detail view's Nights section. */
function showObservationSessionForm(session) {

    const form = document.createElement('form');
    form.className = 'form row g-3';
    form.id = 'observation-session-form';

    if (!session) {
        form.appendChild(_obsSectionHeader(i18n.t('observation_log.section_when_where')));

        const dateInput = _obsInput('observation-session-date', 'date', _obsTodayIso(), { required: 'required' });
        dateInput.addEventListener('change', () => _obsPrefillSkyConditionsIfToday(
            'observation-session-date', 'observation-session-seeing', 'observation-session-transparency'
        ));
        form.appendChild(_obsField('col-md-4', `${i18n.t('observation_log.date')} *`, dateInput, dateInput.id));

        const startInput = _obsInput('observation-session-start', 'datetime-local', '');
        form.appendChild(_obsField('col-md-4', i18n.t('observation_log.start_time'), startInput, startInput.id));

        const endInput = _obsInput('observation-session-end', 'datetime-local', '');
        form.appendChild(_obsField('col-md-4', i18n.t('observation_log.end_time'), endInput, endInput.id));
    }

    form.appendChild(_obsBuildLocationFields(session));

    form.appendChild(_obsSectionHeader(i18n.t('observation_log.section_equipment')));
    const comboSelect = _obsSelect(
        'observation-session-combination',
        _obsBuildCombinationOptions(session),
        session?.combination_id || ''
    );
    form.appendChild(_obsField('col-md-6', i18n.t('observation_log.default_equipment'), comboSelect, comboSelect.id));

    if (!session) {
        form.appendChild(_obsSectionHeader(i18n.t('observation_log.section_sky')));
        const sqmInput = _obsInput('observation-session-sqm', 'number', '', {
            step: '0.01', min: '0', max: '30', placeholder: '21.2',
        });
        form.appendChild(_obsField('col-md-4', i18n.t('observation_log.sqm'), sqmInput, sqmInput.id));

        const seeingOptions = [{ value: '', label: i18n.t('observation_log.not_recorded') }];
        _OBS_SKY_SCALE.forEach(value => seeingOptions.push({
            value: String(value),
            label: i18n.t('observation_log.seeing_value', { value }),
        }));
        const seeingSelect = _obsSelect('observation-session-seeing', seeingOptions, '');
        form.appendChild(_obsField('col-md-4', i18n.t('observation_log.seeing'), seeingSelect, seeingSelect.id));

        const transparencyOptions = [{ value: '', label: i18n.t('observation_log.not_recorded') }];
        _OBS_SKY_SCALE.forEach(value => transparencyOptions.push({
            value: String(value),
            label: i18n.t('observation_log.transparency_value', { value }),
        }));
        const transparencySelect = _obsSelect('observation-session-transparency', transparencyOptions, '');
        form.appendChild(_obsField('col-md-4', i18n.t('observation_log.transparency'), transparencySelect, transparencySelect.id));
    }

    const notes = document.createElement('textarea');
    notes.className = 'form-control';
    notes.id = 'observation-session-notes';
    notes.rows = 3;
    notes.value = session?.notes || '';
    form.appendChild(_obsField('col-12', i18n.t('observation_log.notes'), notes, notes.id));

    const actions = document.createElement('div');
    actions.className = 'col-12 text-end';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    submit.textContent = session ? i18n.t('observation_log.save_session') : i18n.t('observation_log.create_session');
    actions.appendChild(submit);
    form.appendChild(actions);

    createModal(
        session ? i18n.t('observation_log.edit_session') : i18n.t('observation_log.new_session'),
        form,
        'lg'
    );

    openModal('#modal_lg_close', {
        backdrop: 'static',
        // Leaflet must measure a fully laid-out, visible container - initializing
        // while the modal is still mid fade-in gives it the wrong size and only the
        // top-left tile renders.
        onShown: () => _obsUpdateLocationMap(),
        onHidden: () => _obsDestroyLocationMap(),
    });

    if (!session) {
        _obsPrefillSqmFromPreset();
        _obsPrefillSkyConditionsIfToday(
            'observation-session-date', 'observation-session-seeing', 'observation-session-transparency'
        );
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await saveObservationSession(session?.id || null, submit);
    });
}

/** ISO timestamp -> the value format a datetime-local input expects (and back via _obsFromLocalInput). */
function _obsToLocalInput(isoValue) {
    if (!isoValue) return '';
    const parsed = new Date(isoValue);
    if (Number.isNaN(parsed.getTime())) return '';
    const pad = (value) => String(value).padStart(2, '0');
    return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`
        + `T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function _obsFromLocalInput(elementId) {
    const raw = document.getElementById(elementId)?.value;
    if (!raw) return null;
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

async function saveObservationSession(sessionId, submitButton) {
    // Editing an existing session only ever touches trip-level fields (the date/
    // start/end/sqm/seeing/transparency inputs don't exist in that form at all - see
    // showObservationSessionForm()); creating one also seeds the first night.
    const payload = {
        combination_id: document.getElementById('observation-session-combination')?.value || null,
        notes: document.getElementById('observation-session-notes')?.value || '',
        ..._obsCollectLocationFields(),
    };

    if (!sessionId) {
        payload.date = document.getElementById('observation-session-date')?.value || '';
        payload.start_time = _obsFromLocalInput('observation-session-start');
        payload.end_time = _obsFromLocalInput('observation-session-end');
        payload.sqm = _obsNumberOrNull('observation-session-sqm');
        payload.seeing = _obsNumberOrNull('observation-session-seeing');
        payload.transparency = _obsNumberOrNull('observation-session-transparency');

        if (!payload.date) {
            showMessage('error', i18n.t('observation_log.date_required'));
            return;
        }
    }

    const originalLabel = submitButton?.textContent;
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = i18n.t('common.loading');
    }

    try {
        const response = await fetchJSON(
            sessionId ? `${OBSERVATION_LOG_API}/${sessionId}` : OBSERVATION_LOG_API,
            {
                method: sessionId ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        observationLogOpenSessionId = sessionId || response?.data?.id || null;
        closeModal();
        await loadObservationSessions();
    } catch (error) {
        console.error('Error saving observation session:', error);
        showMessage('error', i18n.t('observation_log.failed_to_save_session'));
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = originalLabel;
        }
    }
}

async function deleteObservationSession(sessionId) {
    if (!confirm(i18n.t('observation_log.confirm_delete_session'))) return;
    try {
        await fetchJSON(`${OBSERVATION_LOG_API}/${sessionId}`, { method: 'DELETE' });
        observationLogOpenSessionId = null;
        await loadObservationSessions();
    } catch (error) {
        console.error('Error deleting observation session:', error);
        showMessage('error', i18n.t('observation_log.failed_to_delete_session'));
    }
}

// ============================================
// Night add/edit modal
// ============================================

/** night omitted -> add a new night to sessionId; night passed -> edit it in place. */
function showObservationNightForm(sessionId, night) {

    const form = document.createElement('form');
    form.className = 'form row g-3';
    form.id = 'observation-night-form';

    const dateInput = _obsInput('observation-night-date', 'date', night?.date || _obsTodayIso(), { required: 'required' });
    dateInput.addEventListener('change', () => _obsPrefillSkyConditionsIfToday(
        'observation-night-date', 'observation-night-seeing', 'observation-night-transparency'
    ));
    form.appendChild(_obsField('col-md-4', `${i18n.t('observation_log.date')} *`, dateInput, dateInput.id));

    const startInput = _obsInput('observation-night-start', 'datetime-local', _obsToLocalInput(night?.start_time));
    form.appendChild(_obsField('col-md-4', i18n.t('observation_log.start_time'), startInput, startInput.id));

    const endInput = _obsInput('observation-night-end', 'datetime-local', _obsToLocalInput(night?.end_time));
    form.appendChild(_obsField('col-md-4', i18n.t('observation_log.end_time'), endInput, endInput.id));

    form.appendChild(_obsSectionHeader(i18n.t('observation_log.section_sky')));
    const sqmInput = _obsInput('observation-night-sqm', 'number', night?.sqm ?? '', {
        step: '0.01', min: '0', max: '30', placeholder: '21.2',
    });
    form.appendChild(_obsField('col-md-4', i18n.t('observation_log.sqm'), sqmInput, sqmInput.id));

    const seeingOptions = [{ value: '', label: i18n.t('observation_log.not_recorded') }];
    _OBS_SKY_SCALE.forEach(value => seeingOptions.push({
        value: String(value),
        label: i18n.t('observation_log.seeing_value', { value }),
    }));
    const seeingSelect = _obsSelect('observation-night-seeing', seeingOptions, night?.seeing ?? '');
    form.appendChild(_obsField('col-md-4', i18n.t('observation_log.seeing'), seeingSelect, seeingSelect.id));

    const transparencyOptions = [{ value: '', label: i18n.t('observation_log.not_recorded') }];
    _OBS_SKY_SCALE.forEach(value => transparencyOptions.push({
        value: String(value),
        label: i18n.t('observation_log.transparency_value', { value }),
    }));
    const transparencySelect = _obsSelect('observation-night-transparency', transparencyOptions, night?.transparency ?? '');
    form.appendChild(_obsField('col-md-4', i18n.t('observation_log.transparency'), transparencySelect, transparencySelect.id));

    const notes = document.createElement('textarea');
    notes.className = 'form-control';
    notes.id = 'observation-night-notes';
    notes.rows = 2;
    notes.value = night?.notes || '';
    form.appendChild(_obsField('col-12', i18n.t('observation_log.night_notes'), notes, notes.id));

    const actions = document.createElement('div');
    actions.className = 'col-12 text-end';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    submit.textContent = night ? i18n.t('observation_log.save_night') : i18n.t('observation_log.add_night');
    actions.appendChild(submit);
    form.appendChild(actions);

    createModal(night ? i18n.t('observation_log.edit_night') : i18n.t('observation_log.add_night'), form, 'lg');
    openModal('#modal_lg_close', { backdrop: 'static' });

    if (!night) {
        _obsPrefillSkyConditionsIfToday(
            'observation-night-date', 'observation-night-seeing', 'observation-night-transparency'
        );
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await saveObservationNight(sessionId, night?.id || null, submit);
    });
}

async function saveObservationNight(sessionId, nightId, submitButton) {
    const payload = {
        date: document.getElementById('observation-night-date')?.value || '',
        start_time: _obsFromLocalInput('observation-night-start'),
        end_time: _obsFromLocalInput('observation-night-end'),
        sqm: _obsNumberOrNull('observation-night-sqm'),
        seeing: _obsNumberOrNull('observation-night-seeing'),
        transparency: _obsNumberOrNull('observation-night-transparency'),
        notes: document.getElementById('observation-night-notes')?.value || '',
    };

    if (!payload.date) {
        showMessage('error', i18n.t('observation_log.night_date_required'));
        return;
    }

    const originalLabel = submitButton?.textContent;
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = i18n.t('common.loading');
    }

    try {
        await fetchJSON(
            nightId
                ? `${OBSERVATION_LOG_API}/${sessionId}/nights/${nightId}`
                : `${OBSERVATION_LOG_API}/${sessionId}/nights`,
            {
                method: nightId ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        observationLogOpenSessionId = sessionId;
        closeModal();
        await loadObservationSessions();
    } catch (error) {
        console.error('Error saving night:', error);
        showMessage('error', i18n.t('observation_log.failed_to_save_night'));
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = originalLabel;
        }
    }
}

async function deleteObservationNight(sessionId, nightId) {
    if (!confirm(i18n.t('observation_log.confirm_delete_night'))) return;
    try {
        await fetchJSON(`${OBSERVATION_LOG_API}/${sessionId}/nights/${nightId}`, { method: 'DELETE' });
        observationLogOpenSessionId = sessionId;
        await loadObservationSessions();
    } catch (error) {
        console.error('Error deleting night:', error);
        showMessage('error', i18n.t('observation_log.failed_to_delete_night'));
    }
}

// ============================================
// Entry create/edit modal
// ============================================

async function showObservationEntryForm(sessionId, entry) {

    const form = document.createElement('form');
    form.className = 'form row g-3';
    form.id = 'observation-entry-form';

    form.appendChild(_obsSectionHeader(i18n.t('observation_log.section_target')));

    // Only shown for a multi-night session - for the overwhelmingly common single-night
    // case this would be a one-option dropdown adding nothing but clutter.
    const parentSession = observationLogData.sessions.find(item => item.id === sessionId);
    const nightsSorted = parentSession ? _obsSortedNights(parentSession) : [];
    if (nightsSorted.length > 1) {
        const rawNights = parentSession?.nights || [];
        const defaultNightId = entry?.night_id || (rawNights.length ? rawNights[rawNights.length - 1].id : '');
        const nightOptions = nightsSorted.map(night => ({ value: night.id, label: night.date || '' }));
        const nightSelect = _obsSelect('observation-entry-night', nightOptions, defaultNightId);
        form.appendChild(_obsField('col-md-6', i18n.t('observation_log.target_night'), nightSelect, nightSelect.id));
    }

    if (!entry) {
        // Same dedicated catalogue-search pattern as Astrodex's add-item modal: a
        // search box separate from the Name field pre-fills name/type/constellation.
        const searchCol = document.createElement('div');
        searchCol.className = 'col-12';
        const inputGroup = document.createElement('div');
        inputGroup.className = 'input-group';
        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.id = 'observation-entry-search-input';
        searchInput.className = 'form-control';
        searchInput.autocomplete = 'off';
        searchInput.placeholder = i18n.t('astrodex.search_catalogue_placeholder');
        const searchBtn = document.createElement('button');
        searchBtn.type = 'button';
        searchBtn.id = 'observation-entry-search-btn';
        searchBtn.className = 'btn btn-secondary';
        searchBtn.title = i18n.t('astrodex.search_catalogue_btn');
        searchBtn.appendChild(DOMUtils.createIcon('bi bi-search'));
        inputGroup.appendChild(searchInput);
        inputGroup.appendChild(searchBtn);
        searchCol.appendChild(inputGroup);
        const feedback = document.createElement('div');
        feedback.id = 'observation-entry-search-feedback';
        feedback.className = 'mt-1 small d-none';
        searchCol.appendChild(feedback);
        form.appendChild(searchCol);

        const divider = document.createElement('div');
        divider.className = 'col-12';
        const hr = document.createElement('hr');
        hr.className = 'my-1 opacity-25';
        divider.appendChild(hr);
        form.appendChild(divider);
    }

    const nameInput = _obsInput('observation-entry-name', 'text', entry?.name || '', {
        required: 'required',
        placeholder: i18n.t('observation_log.target_name_placeholder'),
        autocomplete: 'off',
    });
    // A frozen snapshot: identity fields are captured once, never re-resolved afterwards.
    if (entry) nameInput.readOnly = true;
    form.appendChild(_obsField('col-12', `${i18n.t('observation_log.target_name')} *`, nameInput, nameInput.id));

    // Internal bookkeeping only (matched against the catalogue on search) - not shown
    // to the user, same as Astrodex's hidden item-catalogue field.
    const catalogueInput = document.createElement('input');
    catalogueInput.type = 'hidden';
    catalogueInput.id = 'observation-entry-catalogue';
    catalogueInput.value = entry?.catalogue || '';
    form.appendChild(catalogueInput);

    const typeSelect = document.createElement('select');
    typeSelect.className = 'form-select';
    typeSelect.id = 'observation-entry-type';
    populateObjectTypeSelect(typeSelect, entry?.type || '');
    if (entry) typeSelect.disabled = true;
    form.appendChild(_obsField('col-md-6', i18n.t('observation_log.object_type'), typeSelect, typeSelect.id));

    const constellations = await getConstellationsList();
    const constellationSelect = document.createElement('select');
    constellationSelect.className = 'form-select';
    constellationSelect.id = 'observation-entry-constellation';
    const noneOption = document.createElement('option');
    noneOption.value = '';
    constellationSelect.appendChild(noneOption);
    const currentConstellation = (entry?.constellation || '').toLowerCase();
    constellations.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name.toLowerCase();
        opt.textContent = getConstellationDisplayName(name);
        if (currentConstellation === name.toLowerCase()) opt.selected = true;
        constellationSelect.appendChild(opt);
    });
    if (entry) constellationSelect.disabled = true;
    form.appendChild(_obsField('col-md-6', i18n.t('observation_log.constellation'), constellationSelect, constellationSelect.id));

    form.appendChild(_obsSectionHeader(i18n.t('observation_log.section_equipment')));
    // Pre-select the *effective* combination - this entry's own override if it has one,
    // else the session's own default - as a real, concrete choice rather than a
    // separate "same as session" pseudo-option: what's shown here is exactly what this
    // target will be recorded with unless changed.
    const effectiveComboId = entry?.combination_id || parentSession?.combination_id || '';
    const comboSelect = _obsSelect(
        'observation-entry-combination',
        _obsBuildCombinationOptionsList(effectiveComboId || null),
        effectiveComboId
    );
    form.appendChild(_obsField('col-md-6', i18n.t('observation_log.equipment'), comboSelect, comboSelect.id));

    const comboChecklistWrap = document.createElement('div');
    comboChecklistWrap.className = 'col-md-6';
    comboChecklistWrap.id = 'observation-entry-combo-checklist-wrap';
    comboChecklistWrap.style.display = 'none';
    const comboChecklistLabel = document.createElement('label');
    comboChecklistLabel.className = 'form-label d-block';
    comboChecklistLabel.textContent = i18n.t('observation_log.combination_used_components_label');
    comboChecklistWrap.appendChild(comboChecklistLabel);
    const comboChecklistContainer = document.createElement('div');
    comboChecklistContainer.id = 'observation-entry-combo-checklist';
    comboChecklistWrap.appendChild(comboChecklistContainer);
    form.appendChild(comboChecklistWrap);

    form.appendChild(_obsSectionHeader(i18n.t('observation_log.section_capture')));

    const framesInput = _obsInput('observation-entry-frames', 'number', entry?.frame_count ?? '', { min: '0', step: '1' });
    // Once typed by hand, the auto-computation stops overwriting it - lets either
    // frames or integration be the value the user actually knows.
    framesInput.addEventListener('input', () => { framesInput.dataset.userEdited = 'true'; _obsRecomputeCapture(); });
    form.appendChild(_obsField('col-md-4', i18n.t('observation_log.frame_count'), framesInput, framesInput.id));

    const subExposureInput = _obsInput('observation-entry-sub-exposure', 'number', entry?.sub_exposure_seconds ?? '', {
        min: '0', step: 'any',
    });
    subExposureInput.addEventListener('input', _obsRecomputeCapture);
    form.appendChild(_obsField('col-md-4', i18n.t('observation_log.sub_exposure'), subExposureInput, subExposureInput.id));

    const integrationInput = _obsInput('observation-entry-integration', 'number', entry?.integration_minutes ?? '', {
        min: '0', step: 'any',
    });
    integrationInput.addEventListener('input', () => { integrationInput.dataset.userEdited = 'true'; _obsRecomputeCapture(); });
    form.appendChild(_obsField('col-md-4', i18n.t('observation_log.integration_minutes'), integrationInput, integrationInput.id));

    const captureHint = document.createElement('div');
    captureHint.className = 'col-12 form-text';
    captureHint.textContent = i18n.t('observation_log.capture_hint');
    form.appendChild(captureHint);

    const ratingCol = document.createElement('div');
    ratingCol.className = 'col-12';
    const ratingLabel = document.createElement('label');
    ratingLabel.className = 'form-label d-block';
    ratingLabel.textContent = i18n.t('observation_log.rating');
    ratingCol.appendChild(ratingLabel);
    ratingCol.appendChild(_obsBuildRatingWidget('observation-entry', entry?.rating ?? null));
    form.appendChild(ratingCol);

    const notes = document.createElement('textarea');
    notes.className = 'form-control';
    notes.id = 'observation-entry-notes';
    notes.rows = 3;
    notes.value = entry?.notes || '';
    form.appendChild(_obsField('col-12', i18n.t('observation_log.notes'), notes, notes.id));

    const actions = document.createElement('div');
    actions.className = 'col-12 text-end';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    submit.textContent = entry ? i18n.t('observation_log.save_target') : i18n.t('observation_log.add_target');
    actions.appendChild(submit);
    form.appendChild(actions);

    createModal(
        entry ? i18n.t('observation_log.edit_target') : i18n.t('observation_log.add_target'),
        form,
        'lg'
    );
    openModal('#modal_lg_close', { backdrop: 'static' });

    _obsWireEntryEquipmentSection(entry);

    if (!entry) {
        const searchBtn = document.getElementById('observation-entry-search-btn');
        const searchInput = document.getElementById('observation-entry-search-input');
        if (searchBtn) searchBtn.addEventListener('click', _obsTriggerEntryCatalogueSearch);
        if (searchInput) {
            searchInput.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') { event.preventDefault(); _obsTriggerEntryCatalogueSearch(); }
            });
        }
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await saveObservationEntry(sessionId, entry?.id || null, submit);
    });
}

/** Wire the entry Equipment section's combination select: (re)builds the per-component
 * checklist against whatever combination is currently selected - it starts out
 * pre-selected to this entry's effective equipment (see showObservationEntryForm), so
 * there's no separate "same as session" fallback to resolve here, just the select's own
 * value - reusing the generic checklist helpers astrodex.js already exposes globally
 * (_buildCombinationComponentsChecklist / _collectCombinationUsedComponents), the same
 * way this file already reuses that file's getConstellationsList(). Call once after the
 * modal is mounted; `entry` (when editing) seeds the initial checklist state from its
 * saved combination_used_components. */
function _obsWireEntryEquipmentSection(entry) {
    const select = document.getElementById('observation-entry-combination');
    const checklistWrap = document.getElementById('observation-entry-combo-checklist-wrap');
    const checklistContainer = document.getElementById('observation-entry-combo-checklist');
    if (!select || !checklistWrap || !checklistContainer) return;

    const applySelection = (usedComponents) => {
        DOMUtils.clear(checklistContainer);
        const combo = observationLogCombinations.find(candidate => candidate.id === select.value);
        if (combo) {
            checklistContainer.appendChild(_buildCombinationComponentsChecklist('observation-entry', combo, usedComponents));
            checklistWrap.style.display = '';
        } else {
            checklistWrap.style.display = 'none';
        }
    };

    select.addEventListener('change', () => applySelection(null));
    applySelection(select.value === (entry?.combination_id || '') ? entry?.combination_used_components : null);
}

/** Convenience only: frames x sub-exposure -> integration minutes. The server never
 * recomputes this, so an explicitly typed integration value is left alone. */
/** Works either direction: some people count frames and want the total integration,
 * others know the total integration time (e.g. off a capture app's summary) and want
 * the frame count. Whichever of the two hasn't been typed by hand gets derived from
 * the other two - sub-exposure is always the pivot, since it's rarely unknown. */
function _obsRecomputeCapture() {
    recomputeCaptureTriad('observation-entry-frames', 'observation-entry-sub-exposure', 'observation-entry-integration');
}

/** Same catalogue-search behaviour as Astrodex's add-item modal: fills name, hidden
 * catalogue, object type and constellation from GET /api/astrodex/catalogue-lookup. */
async function _obsTriggerEntryCatalogueSearch() {
    const searchInput = document.getElementById('observation-entry-search-input');
    const searchBtn = document.getElementById('observation-entry-search-btn');
    const feedbackEl = document.getElementById('observation-entry-search-feedback');
    const query = (searchInput?.value || '').trim();
    if (!query) return;

    if (searchBtn) {
        searchBtn.disabled = true;
        DOMUtils.clear(searchBtn);
        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm';
        spinner.setAttribute('role', 'status');
        spinner.setAttribute('aria-hidden', 'true');
        searchBtn.appendChild(spinner);
    }
    if (feedbackEl) feedbackEl.classList.add('d-none');

    try {
        const result = await fetchJSON(`/api/astrodex/catalogue-lookup?name=${encodeURIComponent(query)}`);

        if (!result?.found) {
            if (feedbackEl) {
                DOMUtils.clear(feedbackEl);
                const badge = document.createElement('span');
                badge.className = 'badge bg-warning text-dark';
                DOMUtils.append(badge, DOMUtils.createIcon('bi bi-exclamation-circle me-1'), i18n.t('astrodex.catalogue_not_found'));
                feedbackEl.appendChild(badge);
                feedbackEl.classList.remove('d-none');
            }
            return;
        }

        const nameInput = document.getElementById('observation-entry-name');
        const typeSelect = document.getElementById('observation-entry-type');
        const constellationSelect = document.getElementById('observation-entry-constellation');
        const catalogueInput = document.getElementById('observation-entry-catalogue');

        if (nameInput) nameInput.value = result.preferred_name || query;

        let matchedCatalogue = '';
        for (const [cat, catName] of Object.entries(result.catalogue_names || {})) {
            if (catName === result.preferred_name) { matchedCatalogue = cat; break; }
        }
        if (catalogueInput) catalogueInput.value = matchedCatalogue;

        if (typeSelect) {
            const mappedType = mapCatalogueObjectType(result.object_type);
            if (mappedType) {
                for (const opt of typeSelect.options) {
                    if (opt.value === mappedType) { typeSelect.value = mappedType; break; }
                }
            }
        }
        if (constellationSelect && result.constellation) {
            const constLower = result.constellation.toLowerCase();
            for (const opt of constellationSelect.options) {
                if (opt.value === constLower) { constellationSelect.value = constLower; break; }
            }
        }

        if (feedbackEl) {
            DOMUtils.clear(feedbackEl);
            const badge = document.createElement('span');
            badge.className = 'badge bg-success';
            DOMUtils.append(badge, DOMUtils.createIcon('bi bi-check-circle me-1'), i18n.t('astrodex.catalogue_found'));
            feedbackEl.appendChild(badge);
            feedbackEl.classList.remove('d-none');
        }
    } catch (error) {
        console.debug('Catalogue lookup failed', error);
    } finally {
        if (searchBtn) {
            searchBtn.disabled = false;
            DOMUtils.clear(searchBtn);
            searchBtn.appendChild(DOMUtils.createIcon('bi bi-search'));
        }
    }
}

async function saveObservationEntry(sessionId, entryId, submitButton) {
    const comboChecklistWrap = document.getElementById('observation-entry-combo-checklist-wrap');
    const payload = {
        frame_count: _obsNumberOrNull('observation-entry-frames'),
        sub_exposure_seconds: _obsNumberOrNull('observation-entry-sub-exposure'),
        integration_minutes: _obsNumberOrNull('observation-entry-integration'),
        rating: _obsGetRatingWidgetValue('observation-entry'),
        notes: document.getElementById('observation-entry-notes')?.value || '',
        combination_id: document.getElementById('observation-entry-combination')?.value || null,
        combination_used_components: comboChecklistWrap && comboChecklistWrap.style.display !== 'none'
            ? _collectCombinationUsedComponents('observation-entry')
            : null,
    };

    // The night selector only renders for a multi-night session (see
    // showObservationEntryForm) - for the common single-night case, the backend
    // defaults night_id to the session's only night on its own.
    const nightSelect = document.getElementById('observation-entry-night');
    if (nightSelect) payload.night_id = nightSelect.value;

    if (!entryId) {
        payload.name = document.getElementById('observation-entry-name')?.value.trim() || '';
        payload.catalogue = document.getElementById('observation-entry-catalogue')?.value.trim() || '';
        payload.type = document.getElementById('observation-entry-type')?.value.trim() || '';
        payload.constellation = document.getElementById('observation-entry-constellation')?.value.trim() || '';
        if (!payload.name) {
            showMessage('error', i18n.t('observation_log.target_name_required'));
            return;
        }
    }

    const originalLabel = submitButton?.textContent;
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = i18n.t('common.loading');
    }

    try {
        const url = entryId
            ? `${OBSERVATION_LOG_API}/${sessionId}/entries/${entryId}`
            : `${OBSERVATION_LOG_API}/${sessionId}/entries`;
        await fetchJSON(url, {
            method: entryId ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        observationLogOpenSessionId = sessionId;
        closeModal();
        await loadObservationSessions();
    } catch (error) {
        console.error('Error saving observation entry:', error);
        showMessage('error', i18n.t('observation_log.failed_to_save_target'));
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = originalLabel;
        }
    }
}

async function deleteObservationEntry(sessionId, entryId) {
    if (!confirm(i18n.t('observation_log.confirm_delete_target'))) return;
    try {
        await fetchJSON(`${OBSERVATION_LOG_API}/${sessionId}/entries/${entryId}`, { method: 'DELETE' });
        observationLogOpenSessionId = sessionId;
        await loadObservationSessions();
    } catch (error) {
        console.error('Error deleting observation entry:', error);
        showMessage('error', i18n.t('observation_log.failed_to_delete_target'));
    }
}

// ============================================
// Attach picture (manual half of the Astrodex linkage)
// ============================================

function showObservationAttachPictureModal(sessionId, entryId) {

    const form = document.createElement('form');
    form.className = 'form row g-3';
    form.id = 'observation-attach-picture-form';

    const hint = document.createElement('div');
    hint.className = 'col-12 form-text';
    hint.textContent = i18n.t('observation_log.attach_picture_hint');
    form.appendChild(hint);

    const fileInput = _obsInput('observation-picture-file', 'file', '', { accept: 'image/*', required: 'required' });
    form.appendChild(_obsField('col-12', `${i18n.t('observation_log.image_file')} *`, fileInput, fileInput.id));

    const notes = document.createElement('textarea');
    notes.className = 'form-control';
    notes.id = 'observation-picture-notes';
    notes.rows = 2;
    form.appendChild(_obsField('col-12', i18n.t('observation_log.picture_notes'), notes, notes.id));

    const actions = document.createElement('div');
    actions.className = 'col-12 text-end';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    submit.textContent = i18n.t('observation_log.attach_picture');
    actions.appendChild(submit);
    form.appendChild(actions);

    createModal(i18n.t('observation_log.attach_picture'), form, 'lg');
    openModal('#modal_lg_close', { backdrop: 'static' });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await attachObservationEntryPicture(sessionId, entryId, submit);
    });
}

async function attachObservationEntryPicture(sessionId, entryId, submitButton) {
    const file = document.getElementById('observation-picture-file')?.files?.[0];
    if (!file) {
        showMessage('error', i18n.t('observation_log.please_select_image'));
        return;
    }

    const originalLabel = submitButton?.textContent;
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = i18n.t('observation_log.uploading');
    }

    try {
        // Step 1: the existing, unchanged Astrodex upload route - no parallel upload
        // endpoint exists, and the file lands straight in Astrodex's own image directory.
        const formData = new FormData();
        formData.append('file', file);
        const uploadResponse = await fetchWithRetry('/api/astrodex/upload', {
            method: 'POST',
            body: formData,
            credentials: 'include',
        }, { maxAttempts: 1, timeoutMs: 30000 });

        if (!uploadResponse.ok) throw new Error('Upload failed');
        const uploadResult = await uploadResponse.json();

        // Step 2: attach it to this entry's Astrodex item (created on the fly if needed).
        const notesValue = document.getElementById('observation-picture-notes')?.value || '';
        const body = { filename: uploadResult.filename };
        if (notesValue.trim()) body.notes = notesValue;

        await fetchJSON(`${OBSERVATION_LOG_API}/${sessionId}/entries/${entryId}/astrodex-picture`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        observationLogOpenSessionId = sessionId;
        closeModal();
        // The attached picture lives in astrodexData (populated by loadAstrodex()),
        // not in observationLogData - refresh it too so the entry row's thumbnail
        // resolves immediately instead of only after the Astrodex tab is reopened.
        if (typeof loadAstrodex === 'function') {
            await loadAstrodex();
        }
        await loadObservationSessions();
    } catch (error) {
        console.error('Error attaching picture to observation entry:', error);
        showMessage('error', i18n.t('observation_log.failed_to_attach_picture'));
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = originalLabel;
        }
    }
}

// ============================================
// Session attachments (v1.3.1) - generic files (guiding graphs, subframe logs,
// planning notes), unrelated to the entry -> Astrodex picture link above: no picture
// ever lives here, and no attachment ever lives in Astrodex.
// ============================================

function _obsAttachmentIsImage(attachment) {
    const contentType = attachment.content_type || '';
    if (contentType.startsWith('image/')) return true;
    return /\.(jpe?g|png|webp)$/i.test(attachment.filename || '');
}

function _obsAttachmentIconClass(attachment) {
    if (_obsAttachmentIsImage(attachment)) return 'bi bi-file-earmark-image';
    if ((attachment.content_type || '') === 'application/pdf' || /\.pdf$/i.test(attachment.filename || '')) {
        return 'bi bi-file-earmark-pdf';
    }
    if (/\.docx?$/i.test(attachment.filename || '')) return 'bi bi-file-earmark-word';
    return 'bi bi-file-earmark-text';
}

/** Small list on the session detail view: an icon (or thumbnail for images), the
 * original filename as a link that opens the file, and a delete button. */
function _obsBuildAttachmentsSection(session) {
    const wrap = document.createElement('div');
    wrap.className = 'mb-3';

    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-center mb-2';
    const title = document.createElement('h6');
    title.className = 'text-muted mb-0';
    title.textContent = i18n.t('observation_log.attachments_section');
    header.appendChild(title);

    if (observationLogData.canEdit) {
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.id = 'observation-log-add-attachment';
        addButton.className = 'btn btn-outline-secondary btn-sm';
        DOMUtils.append(
            addButton,
            DOMUtils.createIcon('bi bi-paperclip icon-inline'),
            i18n.t('observation_log.add_attachment')
        );
        addButton.addEventListener('click', () => showObservationAttachmentUploadModal(session.id));
        header.appendChild(addButton);
    }
    wrap.appendChild(header);

    const attachments = session.attachments || [];
    if (!attachments.length) {
        const empty = document.createElement('div');
        empty.className = 'observation-log-meta small';
        empty.textContent = i18n.t('observation_log.no_attachments');
        wrap.appendChild(empty);
        return wrap;
    }

    const list = document.createElement('div');
    list.className = 'list-group observation-log-attachments-list';
    attachments.forEach(attachment => list.appendChild(_obsBuildAttachmentRow(session, attachment)));
    wrap.appendChild(list);

    return wrap;
}

function _obsBuildAttachmentRow(session, attachment) {
    const row = document.createElement('div');
    row.className = 'list-group-item d-flex align-items-center justify-content-between gap-2';

    const link = document.createElement('a');
    link.href = `/api/observation-sessions/attachments/${encodeURIComponent(attachment.filename)}`;
    link.target = '_blank';
    link.rel = 'noopener';
    link.className = 'observation-log-attachment-link d-flex align-items-center gap-2 text-truncate';

    if (_obsAttachmentIsImage(attachment)) {
        const thumb = document.createElement('img');
        thumb.src = link.href;
        thumb.alt = attachment.original_name || '';
        thumb.loading = 'lazy';
        thumb.className = 'observation-log-attachment-thumb';
        link.appendChild(thumb);
    } else {
        const iconBox = document.createElement('span');
        iconBox.className = 'observation-log-attachment-thumb observation-log-attachment-icon';
        iconBox.appendChild(DOMUtils.createIcon(_obsAttachmentIconClass(attachment)));
        link.appendChild(iconBox);
    }
    const name = document.createElement('span');
    name.className = 'text-truncate';
    name.textContent = attachment.display_name || attachment.original_name || attachment.filename;
    link.appendChild(name);
    row.appendChild(link);

    if (observationLogData.canEdit) {
        const actions = document.createElement('div');
        actions.className = 'd-flex gap-2 flex-shrink-0';

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'btn btn-outline-primary btn-sm';
        editButton.title = i18n.t('observation_log.rename_attachment');
        editButton.appendChild(DOMUtils.createIcon('bi bi-pencil'));
        editButton.addEventListener('click', () => showObservationAttachmentRenameModal(session.id, attachment));
        actions.appendChild(editButton);

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'btn btn-outline-danger btn-sm';
        deleteButton.title = i18n.t('observation_log.delete_attachment');
        deleteButton.appendChild(DOMUtils.createIcon('bi bi-trash'));
        deleteButton.addEventListener('click', () => deleteObservationSessionAttachment(session.id, attachment.id));
        actions.appendChild(deleteButton);

        row.appendChild(actions);
    }

    return row;
}

function showObservationAttachmentUploadModal(sessionId) {

    const form = document.createElement('form');
    form.className = 'form row g-3';
    form.id = 'observation-attachment-form';

    const fileInput = _obsInput('observation-attachment-file', 'file', '', {
        accept: '.jpg,.jpeg,.png,.webp,.pdf,.txt,.doc,.docx',
        required: 'required',
    });
    form.appendChild(_obsField('col-12', `${i18n.t('observation_log.attachment_file')} *`, fileInput, fileInput.id));

    const hint = document.createElement('div');
    hint.className = 'col-12 form-text';
    hint.textContent = i18n.t('observation_log.attachment_hint');
    form.appendChild(hint);

    const actions = document.createElement('div');
    actions.className = 'col-12 text-end';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    submit.textContent = i18n.t('observation_log.add_attachment');
    actions.appendChild(submit);
    form.appendChild(actions);

    createModal(i18n.t('observation_log.add_attachment'), form, 'lg');
    openModal('#modal_lg_close', { backdrop: 'static' });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await uploadObservationSessionAttachment(sessionId, submit);
    });
}

async function uploadObservationSessionAttachment(sessionId, submitButton) {
    const file = document.getElementById('observation-attachment-file')?.files?.[0];
    if (!file) {
        showMessage('error', i18n.t('observation_log.please_select_file'));
        return;
    }

    const originalLabel = submitButton?.textContent;
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = i18n.t('observation_log.uploading');
    }

    try {
        const formData = new FormData();
        formData.append('file', file);
        await fetchJSON(`${OBSERVATION_LOG_API}/${sessionId}/attachments`, {
            method: 'POST',
            body: formData,
        });
        observationLogOpenSessionId = sessionId;
        closeModal();
        await loadObservationSessions();
    } catch (error) {
        console.error('Error uploading attachment:', error);
        showMessage('error', i18n.t('observation_log.failed_to_upload_attachment'));
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = originalLabel;
        }
    }
}

async function deleteObservationSessionAttachment(sessionId, attachmentId) {
    if (!confirm(i18n.t('observation_log.confirm_delete_attachment'))) return;
    try {
        await fetchJSON(`${OBSERVATION_LOG_API}/${sessionId}/attachments/${attachmentId}`, { method: 'DELETE' });
        observationLogOpenSessionId = sessionId;
        await loadObservationSessions();
    } catch (error) {
        console.error('Error deleting attachment:', error);
        showMessage('error', i18n.t('observation_log.failed_to_delete_attachment'));
    }
}

/** Rename modal: prefilled with whatever is currently shown (custom name if set, else
 * the original filename) so editing starts from what the user sees, not a blank field.
 * Saving a blank name clears the custom name and falls back to the original filename. */
function showObservationAttachmentRenameModal(sessionId, attachment) {

    const form = document.createElement('form');
    form.className = 'form row g-3';
    form.id = 'observation-attachment-rename-form';

    const currentName = attachment.display_name || attachment.original_name || attachment.filename;
    const nameInput = _obsInput('observation-attachment-name', 'text', currentName, { maxlength: 200 });
    form.appendChild(_obsField('col-12', i18n.t('observation_log.attachment_name'), nameInput, nameInput.id));

    const actions = document.createElement('div');
    actions.className = 'col-12 text-end';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    submit.textContent = i18n.t('common.save');
    actions.appendChild(submit);
    form.appendChild(actions);

    createModal(i18n.t('observation_log.rename_attachment'), form, 'lg');
    openModal('#modal_lg_close', { backdrop: 'static' });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await renameObservationSessionAttachment(sessionId, attachment.id, nameInput.value, submit);
    });
}

async function renameObservationSessionAttachment(sessionId, attachmentId, name, submitButton) {
    if (submitButton) submitButton.disabled = true;
    try {
        await fetchJSON(`${OBSERVATION_LOG_API}/${sessionId}/attachments/${attachmentId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        observationLogOpenSessionId = sessionId;
        closeModal();
        await loadObservationSessions();
    } catch (error) {
        console.error('Error renaming attachment:', error);
        showMessage('error', i18n.t('observation_log.failed_to_rename_attachment'));
        if (submitButton) submitButton.disabled = false;
    }
}

// ============================================
// PDF export (per-session button + global range/order modal)
// ============================================

/** Fetch a PDF as a blob and save it, rather than a plain navigation - the export routes
 * are behind @login_required and a bare `<a href>` would hit them without the session
 * cookie's usual credentialed-fetch handling in some browsers. Locally duplicated from
 * plan_my_night.js's own `_triggerDownload` closure rather than shared, matching this
 * codebase's general preference for independently-deployable feature files. */
async function _obsTriggerPdfDownload(url) {
    try {
        const response = await fetch(url, { credentials: 'same-origin' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob = await response.blob();
        const blobUrl = URL.createObjectURL(blob);
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename[^;=\n]*=(['"]?)([^'";\n]+)\1/);
        const anchor = document.createElement('a');
        anchor.href = blobUrl;
        anchor.download = match ? match[2].trim() : 'observation-log.pdf';
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(blobUrl);
    } catch (error) {
        console.error('Observation Log PDF export failed:', error);
        showMessage('error', i18n.t('observation_log.failed_to_export_pdf'));
    }
}

/** Earliest/latest observation date across all of the user's sessions - the modal's
 * date-range prefill, so "everything" is the default and narrowing is opt-in. */
function _obsSessionDateBounds() {
    const dates = observationLogData.sessions
        .flatMap(session => (session.nights || []).map(night => night.date))
        .filter(Boolean)
        .sort();
    return { min: dates[0] || '', max: dates[dates.length - 1] || '' };
}

function showObservationExportRangeModal() {

    const bounds = _obsSessionDateBounds();

    const form = document.createElement('form');
    form.className = 'form row g-3';
    form.id = 'observation-export-pdf-form';

    const hint = document.createElement('div');
    hint.className = 'col-12 form-text';
    hint.textContent = i18n.t('observation_log.export_pdf_range_hint');
    form.appendChild(hint);

    const fromInput = _obsInput('observation-export-pdf-from', 'date', bounds.min);
    form.appendChild(_obsField('col-md-6', i18n.t('observation_log.export_pdf_from'), fromInput, fromInput.id));

    const toInput = _obsInput('observation-export-pdf-to', 'date', bounds.max);
    form.appendChild(_obsField('col-md-6', i18n.t('observation_log.export_pdf_to'), toInput, toInput.id));

    const orderSelect = _obsSelect('observation-export-pdf-order', [
        { value: 'asc', label: i18n.t('observation_log.export_pdf_order_asc') },
        { value: 'desc', label: i18n.t('observation_log.export_pdf_order_desc') },
    ], 'asc');
    form.appendChild(_obsField('col-md-6', i18n.t('observation_log.export_pdf_order'), orderSelect, orderSelect.id));

    const actions = document.createElement('div');
    actions.className = 'col-12 text-end';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    DOMUtils.append(submit, DOMUtils.createIcon('bi bi-filetype-pdf icon-inline'), i18n.t('observation_log.export_pdf_generate'));
    actions.appendChild(submit);
    form.appendChild(actions);

    createModal(i18n.t('observation_log.export_pdf_modal_title'), form, 'lg');
    openModal('#modal_lg_close', { backdrop: 'static' });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const lang = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : 'en';
        const params = new URLSearchParams({ lang, order: orderSelect.value || 'asc' });
        if (fromInput.value) params.set('from_date', fromInput.value);
        if (toInput.value) params.set('to_date', toInput.value);

        closeModal();
        await _obsTriggerPdfDownload(`${OBSERVATION_LOG_API}/export.pdf?${params.toString()}`);
    });
}

// ============================================
// Import from Plan
// ============================================

/** Plan "combination scope" ids and a session's imported_from marker both use 'default'
 * for the no-equipment plan, so normalize before comparing. */
function _obsNormalizePlanScope(value) {
    return value || 'default';
}

function showObservationImportFromPlanModal() {

    const form = document.createElement('form');
    form.className = 'form row g-3';
    form.id = 'observation-import-plan-form';

    const hint = document.createElement('div');
    hint.className = 'col-12 form-text';
    hint.textContent = i18n.t('observation_log.import_from_plan_hint');
    form.appendChild(hint);

    const options = observationLogPlans.map(plan => ({
        value: _obsNormalizePlanScope(plan.combination_id),
        label: i18n.t('observation_log.import_plan_option', {
            name: plan.combination_name || i18n.t('observation_log.no_equipment'),
            date: String(plan.night_start || '').slice(0, 10),
            start: formatTimeOnly(plan.night_start),
            end: formatTimeOnly(plan.night_end),
            count: plan.entries_count || 0,
        }),
    }));
    const planSelect = _obsSelect('observation-import-plan', options, options[0]?.value);
    form.appendChild(_obsField('col-12', i18n.t('observation_log.plan_to_import'), planSelect, planSelect.id));

    const actions = document.createElement('div');
    actions.className = 'col-12 text-end';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    submit.textContent = i18n.t('observation_log.import_from_plan');
    actions.appendChild(submit);
    form.appendChild(actions);

    createModal(i18n.t('observation_log.import_from_plan'), form, 'lg');
    openModal('#modal_lg_close', { backdrop: 'static' });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        closeModal();
        await importObservationSessionFromPlan(planSelect.value);
    });
}

/**
 * Import a Plan My Night plan into the Observation Log.
 *
 * Also called from plan_my_night.js's "Log this session" button. When exactly one
 * session created today already came from the same plan, offer to merge the new targets
 * into it instead of starting a second session for the same night.
 *
 * @param {string} planCombinationId - 'default' or an equipment combination id
 * @param {boolean} switchToTab - move to the Observation Log sub-tab afterwards
 */
async function importObservationSessionFromPlan(planCombinationId, switchToTab = false) {
    const scope = _obsNormalizePlanScope(planCombinationId);

    try {
        if (!observationLogData.sessions.length) {
            const payload = await fetchJSON(OBSERVATION_LOG_API);
            observationLogData.sessions = payload.sessions || [];
        }

        const today = _obsTodayIso();
        const candidates = observationLogData.sessions.filter(session =>
            _obsNormalizePlanScope(session.imported_from_plan_combination_id) === scope
            && String(session.created_at || '').slice(0, 10) === today
        );

        let sessionId = null;
        if (candidates.length === 1 && confirm(i18n.t('observation_log.confirm_merge_into_session', {
            date: _obsFormatSessionDateLabel(candidates[0]),
        }))) {
            sessionId = candidates[0].id;
        }

        const body = { combination_id: scope === 'default' ? null : scope };
        if (sessionId) body.session_id = sessionId;

        const response = await fetchJSON(`${OBSERVATION_LOG_API}/from-plan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        observationLogOpenSessionId = response?.data?.id || sessionId;

        if (switchToTab && typeof switchSubTab === 'function') {
            switchSubTab('astrodex', 'observation-log');
        } else {
            await loadObservationSessions();
        }
    } catch (error) {
        console.error('Error importing plan into an observation session:', error);
        showMessage('error', i18n.t('observation_log.failed_to_import_plan'));
    }
}

/**
 * Jump straight to one session's detail view from outside this file - the Astrodex
 * item/picture backlink uses this to open "which session logged this" in one click.
 */
function openObservationSessionFromAstrodex(sessionId) {
    if (!sessionId) return;
    if (typeof closeModal === 'function') closeModal();
    observationLogOpenSessionId = sessionId;
    if (typeof switchSubTab === 'function') {
        switchSubTab('astrodex', 'observation-log');
    }
}

// Re-render dynamic labels when the language changes (static data-i18n nodes are
// handled globally by i18n.js).
window.addEventListener('i18nLanguageChanged', () => {
    if (!document.getElementById('observation-log-subtab')?.classList.contains('active')) return;
    renderObservationLogStats();
    if (observationLogOpenSessionId) {
        renderObservationSessionDetail(observationLogOpenSessionId);
    } else {
        renderObservationSessionsList();
    }
});
