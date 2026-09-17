/**
 * Session Analytics (v1.5) - the Analytics sub-tab of the Astrodex main tab.
 *
 * Renders four read-only sections from /api/session-analytics/*: headline totals, the
 * "where your time goes" breakdowns, the sky coverage map and the conditions/results
 * comparison. Everything here is derived from the Observation Log (plus Astrodex for the
 * gallery half of the coverage map) - this module never writes.
 *
 * DOM is built with explicit element APIs and textContent only; charts follow the
 * project's graphing standard (card wrapper, canvas in the body, legend badges in the
 * footer) and are destroyed before being re-created.
 */

/** Categorical palette, readable against both the light and the dark theme. */
const SESSION_ANALYTICS_COLORS = [
    '#4e9af1',
    '#f59e0b',
    '#10b981',
    '#a78bfa',
    '#ef4444',
    '#06b6d4',
    '#f472b6',
    '#84cc16',
    '#fb923c',
    '#64748b',
];

/** Quality bands of a condition bucket, best to worst. */
const SESSION_ANALYTICS_QUALITY_COLORS = {
    best: '#10b981',
    mid: '#f59e0b',
    worst: '#ef4444',
};

/** Live Chart.js instances, keyed by canvas id, so every one can be destroyed. */
const sessionAnalyticsCharts = {};

/** Last payloads, kept so a re-colour or a toggle does not refetch. */
const sessionAnalyticsData = {
    summary: null,
    coverage: null,
    conditions: null,
    bestMonths: null,
    coverageColorBy: 'type',
};

/** Destroy every live chart. Called on sub-tab switch by app.js cleanupTransientCharts(). */
function destroySessionAnalyticsCharts() {
    Object.keys(sessionAnalyticsCharts).forEach(key => {
        try {
            sessionAnalyticsCharts[key]?.destroy();
        } catch (error) {
            console.warn('Could not destroy analytics chart', key, error);
        }
        delete sessionAnalyticsCharts[key];
    });
}

/**
 * Translate, falling back to the supplied English text when the key is missing.
 * @param {string} key
 * @param {string} fallback
 * @param {Object} [params]
 * @returns {string}
 */
function _saT(key, fallback, params) {
    if (typeof i18n === 'undefined' || typeof i18n.t !== 'function') return fallback;
    const translated = i18n.t(key, params);
    return translated && translated !== key ? translated : fallback;
}

/**
 * Format a minute count as the "12h30" / "45 min" shorthand used across the app.
 * @param {number} minutes
 * @returns {string}
 */
function _saHours(minutes) {
    const value = Number(minutes);
    if (!Number.isFinite(value) || value <= 0) return '0';
    const hours = Math.floor(value / 60);
    const rest = Math.round(value % 60);
    if (hours <= 0) return _saT('session_analytics.minutes_short', `${rest} min`, { minutes: rest });
    return `${hours}h${String(rest).padStart(2, '0')}`;
}

/** Minutes to a plain decimal hour count, for chart values. */
function _saHourValue(minutes) {
    const value = Number(minutes);
    return Number.isFinite(value) && value > 0 ? Math.round((value / 60) * 100) / 100 : 0;
}

/** Localized month label for a "YYYY-MM" key. */
function _saMonthLabel(monthKey) {
    const parts = String(monthKey || '').split('-');
    if (parts.length < 2) return String(monthKey || '');
    const date = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, 1));
    if (Number.isNaN(date.getTime())) return String(monthKey || '');
    const locale = (typeof i18n !== 'undefined' && i18n.currentLanguage) || 'en';
    return new Intl.DateTimeFormat(locale, { month: 'short', year: '2-digit', timeZone: 'UTC' }).format(date);
}

/** Localized month name for a 1-12 number. */
function _saMonthName(month) {
    const date = new Date(Date.UTC(2000, Number(month) - 1, 1));
    if (Number.isNaN(date.getTime())) return String(month);
    const locale = (typeof i18n !== 'undefined' && i18n.currentLanguage) || 'en';
    return new Intl.DateTimeFormat(locale, { month: 'short', timeZone: 'UTC' }).format(date);
}

/** Translate an object type through the SkyTonight type keys, else show it as stored. */
function _saTypeLabel(type) {
    const raw = String(type || '').trim();
    if (!raw) return _saT('session_analytics.type_unknown', 'Unknown');
    if (raw === 'Unknown') return _saT('session_analytics.type_unknown', 'Unknown');
    if (typeof strToTranslateKey === 'function') {
        return _saT(`skytonight.type_${strToTranslateKey(raw)}`, raw);
    }
    return raw;
}

/** Translate a constellation name through the shared constellations namespace. */
function _saConstellationLabel(name) {
    if (typeof getConstellationDisplayName === 'function') return getConstellationDisplayName(name);
    return String(name || '');
}

/**
 * Build the standard chart card (header title, canvas body, legend footer).
 * @param {string} canvasId
 * @param {string} title
 * @param {Array<{label: string, color: string}>} legend
 * @param {Object} [options]
 * @param {string} [options.columnClass]
 * @param {boolean} [options.tall]
 * @param {string} [options.note]
 * @returns {{column: HTMLElement, canvas: HTMLCanvasElement}}
 */
function _saChartCard(canvasId, title, legend = [], options = {}) {
    const column = document.createElement('div');
    column.className = options.columnClass || 'col';

    const card = document.createElement('div');
    card.className = 'card h-100';

    const header = document.createElement('div');
    header.className = 'card-header';
    const heading = document.createElement('h5');
    heading.className = 'mb-0';
    heading.textContent = title;
    header.appendChild(heading);

    const body = document.createElement('div');
    body.className = 'card-body';
    // Chart.js sizes a responsive canvas to its parent, so it gets a dedicated
    // fixed-height container: sizing it against .card-body would feed back through the
    // resize observer as soon as the card has any other child.
    const canvasWrap = document.createElement('div');
    canvasWrap.className = options.tall ? 'session-analytics-chart-wrap-tall' : 'session-analytics-chart-wrap';
    const canvas = document.createElement('canvas');
    canvas.id = canvasId;
    canvasWrap.appendChild(canvas);
    body.appendChild(canvasWrap);

    card.appendChild(header);
    card.appendChild(body);

    if (legend.length || options.note) {
        const footer = document.createElement('div');
        footer.className = 'card-footer text-muted small';
        const row = document.createElement('div');
        row.className = 'row g-2';
        legend.forEach(item => {
            const col = document.createElement('div');
            col.className = 'col-auto';
            const badge = document.createElement('span');
            badge.className = 'session-analytics-legend-badge';
            const swatch = document.createElement('span');
            swatch.className = 'session-analytics-legend-swatch';
            // Per-series colour: a genuinely per-instance computed value, not static styling.
            swatch.style.backgroundColor = item.color;
            const label = document.createElement('span');
            label.textContent = item.label;
            badge.appendChild(swatch);
            badge.appendChild(label);
            col.appendChild(badge);
            row.appendChild(col);
        });
        if (options.note) {
            const noteCol = document.createElement('div');
            noteCol.className = 'col-12';
            noteCol.textContent = options.note;
            row.appendChild(noteCol);
        }
        footer.appendChild(row);
        card.appendChild(footer);
    }

    column.appendChild(card);
    return { column, canvas };
}

/**
 * Create a chart, replacing any previous instance on the same canvas id.
 * @param {HTMLCanvasElement} canvas
 * @param {Object} config
 */
function _saCreateChart(canvas, config) {
    if (typeof Chart === 'undefined' || !canvas) return;
    if (sessionAnalyticsCharts[canvas.id]) {
        sessionAnalyticsCharts[canvas.id].destroy();
        delete sessionAnalyticsCharts[canvas.id];
    }
    sessionAnalyticsCharts[canvas.id] = new Chart(canvas, config);
}

/**
 * Render an empty-state block into a container.
 * @param {HTMLElement} container
 * @param {string} message
 * @param {string} [iconClass]
 */
function _saEmptyState(container, message, iconClass = 'bi bi-journal-x') {
    const wrapper = document.createElement('div');
    wrapper.className = 'session-analytics-empty';
    const icon = document.createElement('i');
    icon.className = `${iconClass} session-analytics-empty-icon`;
    icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('div');
    text.textContent = message;
    wrapper.appendChild(icon);
    wrapper.appendChild(text);
    container.appendChild(wrapper);
}

// ============================================
// Section 1 - headline totals
// ============================================

function _saRenderStats(summary) {
    const container = document.getElementById('session-analytics-stats');
    if (!container) return;
    DOMUtils.clear(container);

    const totals = (summary && summary.totals) || {};
    const tiles = [
        {
            value: _saHours(totals.integration_minutes_lifetime),
            label: _saT('session_analytics.stat_integration_lifetime', 'Total integration'),
            hint: _saT('session_analytics.stat_integration_hint', 'Everything you have logged'),
        },
        {
            value: _saHours(totals.integration_minutes_year),
            label: _saT('session_analytics.stat_integration_year', 'This year'),
            hint: String(summary?.year ?? ''),
        },
        {
            value: _saHours(totals.integration_minutes_month),
            label: _saT('session_analytics.stat_integration_month', 'This month'),
            hint: '',
        },
        {
            value: String(totals.objects_captured ?? 0),
            label: _saT('session_analytics.stat_objects', 'Objects captured'),
            hint: _saT('session_analytics.stat_objects_hint', 'Distinct objects, from your log'),
        },
        {
            value: String(totals.sessions ?? 0),
            label: _saT('session_analytics.stat_sessions', 'Sessions'),
            hint: _saT('session_analytics.stat_nights_hint', '{count} nights', { count: totals.nights ?? 0 }),
        },
        {
            value: String(totals.constellations ?? 0),
            label: _saT('session_analytics.stat_constellations', 'Constellations'),
            hint: '',
        },
        {
            value: totals.average_rating != null ? String(totals.average_rating) : '-',
            label: _saT('session_analytics.stat_rating', 'Average rating'),
            hint: _saT('session_analytics.stat_rating_hint', '{count} rated targets', {
                count: totals.rated_entries ?? 0,
            }),
        },
        {
            value: String(totals.astrodex_items ?? 0),
            label: _saT('session_analytics.stat_astrodex', 'In your Astrodex'),
            hint: _saT('session_analytics.stat_astrodex_hint', 'Gallery, counted separately'),
        },
    ];

    tiles.forEach(tile => {
        const col = document.createElement('div');
        col.className = 'col';
        const card = document.createElement('div');
        card.className = 'card h-100 text-center';
        const body = document.createElement('div');
        body.className = 'card-body';

        const value = document.createElement('span');
        value.className = 'session-analytics-stat-value';
        value.textContent = tile.value;
        const label = document.createElement('span');
        label.className = 'session-analytics-stat-label';
        label.textContent = tile.label;
        body.appendChild(value);
        body.appendChild(label);

        if (tile.hint) {
            const hint = document.createElement('span');
            hint.className = 'session-analytics-stat-hint';
            hint.textContent = tile.hint;
            body.appendChild(hint);
        }

        card.appendChild(body);
        col.appendChild(card);
        container.appendChild(col);
    });
}

// ============================================
// Section 2 - breakdowns
// ============================================

function _saRenderBreakdowns(summary) {
    const container = document.getElementById('session-analytics-charts');
    if (!container) return;
    DOMUtils.clear(container);

    const monthly = Array.isArray(summary?.monthly) ? summary.monthly : [];
    if (!monthly.length && !(summary?.object_types || []).length) {
        _saEmptyState(
            container,
            _saT('session_analytics.empty_log', 'Nothing logged yet. Record a session in the Observation Log and your stats will appear here.')
        );
        return;
    }

    _saRenderMonthlyChart(container, monthly);
    _saRenderTypesChart(container, summary?.object_types || []);
    _saRenderConstellationsChart(container, summary?.constellations || [], summary?.constellations_total || 0);
    _saRenderEquipmentChart(container, summary?.equipment || []);
}

function _saRenderMonthlyChart(container, monthly) {
    if (!monthly.length) return;
    const seriesLabel = _saT('session_analytics.chart_integration_series', 'Integration hours');
    const { column, canvas } = _saChartCard(
        'sessionAnalyticsMonthlyChart',
        _saT('session_analytics.chart_integration_title', 'Integration over time'),
        [{ label: seriesLabel, color: SESSION_ANALYTICS_COLORS[0] }],
        { columnClass: 'col-12' }
    );
    container.appendChild(column);

    _saCreateChart(canvas, {
        type: 'bar',
        data: {
            labels: monthly.map(row => _saMonthLabel(row.month)),
            datasets: [
                {
                    label: seriesLabel,
                    data: monthly.map(row => _saHourValue(row.integration_minutes)),
                    backgroundColor: SESSION_ANALYTICS_COLORS[0],
                    borderRadius: 3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        afterLabel: context => {
                            const row = monthly[context.dataIndex] || {};
                            return _saT('session_analytics.chart_integration_tooltip', '{nights} nights, {entries} targets', {
                                nights: row.nights ?? 0,
                                entries: row.entries ?? 0,
                            });
                        },
                    },
                },
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: _saT('session_analytics.axis_hours', 'Hours') },
                },
            },
        },
    });
}

function _saRenderTypesChart(container, types) {
    if (!types.length) return;
    const rows = types.slice(0, SESSION_ANALYTICS_COLORS.length);
    const colors = rows.map((_row, index) => SESSION_ANALYTICS_COLORS[index % SESSION_ANALYTICS_COLORS.length]);
    const { column, canvas } = _saChartCard(
        'sessionAnalyticsTypesChart',
        _saT('session_analytics.chart_types_title', 'Object types'),
        [],
        { columnClass: 'col-12 col-xl-6', note: _saT('session_analytics.chart_types_note', 'Share of your logged integration time.') }
    );
    container.appendChild(column);

    _saCreateChart(canvas, {
        type: 'doughnut',
        data: {
            labels: rows.map(row => _saTypeLabel(row.type)),
            datasets: [{ data: rows.map(row => _saHourValue(row.integration_minutes)), backgroundColor: colors }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' },
                tooltip: {
                    callbacks: {
                        label: context => {
                            const row = rows[context.dataIndex] || {};
                            return `${_saTypeLabel(row.type)}: ${_saHours(row.integration_minutes)} (${row.entries ?? 0})`;
                        },
                    },
                },
            },
        },
    });
}

function _saRenderConstellationsChart(container, constellations, total) {
    if (!constellations.length) return;
    const seriesLabel = _saT('session_analytics.chart_integration_series', 'Integration hours');
    const note = total > constellations.length
        ? _saT('session_analytics.chart_top_note', 'Top {shown} of {total}.', { shown: constellations.length, total })
        : '';
    const { column, canvas } = _saChartCard(
        'sessionAnalyticsConstellationsChart',
        _saT('session_analytics.chart_constellations_title', 'Constellation spread'),
        [{ label: seriesLabel, color: SESSION_ANALYTICS_COLORS[2] }],
        { columnClass: 'col-12 col-xl-6', note }
    );
    container.appendChild(column);

    _saCreateChart(canvas, {
        type: 'bar',
        data: {
            labels: constellations.map(row => _saConstellationLabel(row.constellation)),
            datasets: [
                {
                    label: seriesLabel,
                    data: constellations.map(row => _saHourValue(row.integration_minutes)),
                    backgroundColor: SESSION_ANALYTICS_COLORS[2],
                    borderRadius: 3,
                },
            ],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { beginAtZero: true, title: { display: true, text: _saT('session_analytics.axis_hours', 'Hours') } } },
        },
    });
}

function _saRenderEquipmentChart(container, equipment) {
    if (!equipment.length) return;
    const seriesLabel = _saT('session_analytics.chart_integration_series', 'Integration hours');
    const { column, canvas } = _saChartCard(
        'sessionAnalyticsEquipmentChart',
        _saT('session_analytics.chart_equipment_title', 'Equipment usage'),
        [{ label: seriesLabel, color: SESSION_ANALYTICS_COLORS[3] }],
        {
            columnClass: 'col-12',
            note: _saT('session_analytics.chart_equipment_note', 'Hours are attributed to the equipment recorded on each target.'),
        }
    );
    container.appendChild(column);

    const labels = equipment.map(row =>
        row.combination_name || _saT('session_analytics.no_equipment', 'No equipment recorded')
    );

    _saCreateChart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: seriesLabel,
                    data: equipment.map(row => _saHourValue(row.integration_minutes)),
                    backgroundColor: SESSION_ANALYTICS_COLORS[3],
                    borderRadius: 3,
                },
            ],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        afterLabel: context => {
                            const row = equipment[context.dataIndex] || {};
                            return _saT('session_analytics.chart_equipment_tooltip', '{sessions} sessions, {entries} targets', {
                                sessions: row.sessions ?? 0,
                                entries: row.entries ?? 0,
                            });
                        },
                    },
                },
            },
            scales: { x: { beginAtZero: true, title: { display: true, text: _saT('session_analytics.axis_hours', 'Hours') } } },
        },
    });
}

// ============================================
// Section 3 - sky coverage
// ============================================

function _saCoveragePointColor(point, colorBy, typeIndex) {
    if (colorBy === 'date') {
        const year = Number(String(point.last_date || '').slice(0, 4));
        if (!Number.isFinite(year) || year <= 0) return SESSION_ANALYTICS_COLORS[9];
        return SESSION_ANALYTICS_COLORS[year % SESSION_ANALYTICS_COLORS.length];
    }
    const index = typeIndex.get(point.type || 'Unknown') ?? 0;
    return SESSION_ANALYTICS_COLORS[index % SESSION_ANALYTICS_COLORS.length];
}

function _saRenderCoverage(coverage) {
    const container = document.getElementById('session-analytics-coverage');
    if (!container) return;
    DOMUtils.clear(container);

    const points = Array.isArray(coverage?.points) ? coverage.points : [];
    if (!points.length) {
        _saEmptyState(
            container,
            _saT('session_analytics.empty_coverage', 'No captured object could be placed on the sky yet.'),
            'bi bi-compass'
        );
        return;
    }

    const colorBy = sessionAnalyticsData.coverageColorBy;
    const types = [...new Set(points.map(point => point.type || 'Unknown'))];
    const typeIndex = new Map(types.map((type, index) => [type, index]));

    const toolbar = document.createElement('div');
    toolbar.className = 'session-analytics-coverage-toolbar';
    const toolbarLabel = document.createElement('span');
    toolbarLabel.className = 'small text-muted';
    toolbarLabel.textContent = _saT('session_analytics.coverage_color_by', 'Colour by');
    toolbar.appendChild(toolbarLabel);

    const select = document.createElement('select');
    select.className = 'form-select form-select-sm w-auto';
    select.id = 'session-analytics-coverage-color';
    [
        { value: 'type', label: _saT('session_analytics.coverage_color_type', 'Object type') },
        { value: 'date', label: _saT('session_analytics.coverage_color_date', 'Capture year') },
    ].forEach(option => {
        const element = document.createElement('option');
        element.value = option.value;
        element.textContent = option.label;
        if (option.value === colorBy) element.selected = true;
        select.appendChild(element);
    });
    select.addEventListener('change', () => {
        sessionAnalyticsData.coverageColorBy = select.value;
        _saRenderCoverage(sessionAnalyticsData.coverage);
    });
    toolbar.appendChild(select);

    const summaryLine = document.createElement('span');
    summaryLine.className = 'session-analytics-unplaced';
    const unplaced = Number(coverage?.unplaced_count || 0);
    summaryLine.textContent = unplaced > 0
        ? _saT('session_analytics.coverage_summary_with_unplaced', '{placed} objects placed, {unplaced} could not be placed.', {
            placed: points.length,
            unplaced,
        })
        : _saT('session_analytics.coverage_summary', '{placed} objects placed.', { placed: points.length });
    toolbar.appendChild(summaryLine);
    container.appendChild(toolbar);

    const legend = colorBy === 'type'
        ? types.slice(0, SESSION_ANALYTICS_COLORS.length).map((type, index) => ({
            label: _saTypeLabel(type),
            color: SESSION_ANALYTICS_COLORS[index % SESSION_ANALYTICS_COLORS.length],
        }))
        : [];

    const neverVisible = coverage?.never_visible_dec_below;
    const note = Number.isFinite(Number(neverVisible))
        ? _saT('session_analytics.coverage_never_visible', 'The shaded band never rises at your location ({name}).', {
            name: coverage?.location_name || '',
        })
        : '';

    const { column, canvas } = _saChartCard(
        'sessionAnalyticsCoverageChart',
        _saT('session_analytics.chart_coverage_title', 'Where you have been'),
        legend,
        { columnClass: 'col-12', tall: true, note }
    );
    const row = document.createElement('div');
    row.className = 'row';
    row.appendChild(column);
    container.appendChild(row);

    const datasets = [
        {
            label: _saT('session_analytics.chart_coverage_series', 'Captured objects'),
            data: points.map(point => ({ x: point.ra_hours, y: point.dec_deg, point })),
            pointBackgroundColor: points.map(point => _saCoveragePointColor(point, colorBy, typeIndex)),
            pointBorderColor: points.map(point => _saCoveragePointColor(point, colorBy, typeIndex)),
            pointRadius: 5,
            pointHoverRadius: 7,
        },
    ];

    if (Number.isFinite(Number(neverVisible))) {
        const bound = Number(neverVisible);
        const isSouthernBound = bound > 0;
        datasets.push({
            label: _saT('session_analytics.coverage_never_visible_series', 'Never rises here'),
            type: 'line',
            data: [
                { x: 0, y: bound },
                { x: 24, y: bound },
            ],
            borderColor: 'rgba(148, 163, 184, 0.7)',
            borderDash: [6, 4],
            borderWidth: 1,
            pointRadius: 0,
            fill: isSouthernBound ? 'end' : 'start',
            backgroundColor: 'rgba(148, 163, 184, 0.15)',
        });
    }

    _saCreateChart(canvas, {
        type: 'scatter',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: context => {
                            const point = context.raw?.point;
                            if (!point) return '';
                            const parts = [point.name];
                            if (point.integration_minutes > 0) parts.push(_saHours(point.integration_minutes));
                            if (point.last_date) parts.push(point.last_date);
                            return parts.join(' - ');
                        },
                    },
                },
            },
            scales: {
                x: {
                    // RA increases to the left, as on every sky chart.
                    reverse: true,
                    min: 0,
                    max: 24,
                    ticks: { stepSize: 2, callback: value => `${value}h` },
                    title: { display: true, text: _saT('session_analytics.axis_ra', 'Right ascension') },
                },
                y: {
                    min: -90,
                    max: 90,
                    ticks: { stepSize: 30, callback: value => `${value}°` },
                    title: { display: true, text: _saT('session_analytics.axis_dec', 'Declination') },
                },
            },
        },
    });

    if (unplaced > 0 && Array.isArray(coverage?.unplaced_names) && coverage.unplaced_names.length) {
        const unplacedLine = document.createElement('div');
        unplacedLine.className = 'session-analytics-unplaced mt-2';
        unplacedLine.textContent = `${_saT('session_analytics.coverage_unplaced_list', 'Not placed:')} ${coverage.unplaced_names.join(', ')}`;
        container.appendChild(unplacedLine);
    }
}

// ============================================
// Section 5 - best months
// ============================================

function _saRenderBestMonths(bestMonths) {
    const container = document.getElementById('session-analytics-best-months');
    if (!container) return;
    DOMUtils.clear(container);

    const astronomical = Array.isArray(bestMonths?.astronomical) ? bestMonths.astronomical : [];
    const logged = Array.isArray(bestMonths?.logged) ? bestMonths.logged : [];
    if (!astronomical.length && !logged.some(row => row.integration_hours > 0)) {
        _saEmptyState(
            container,
            _saT('session_analytics.empty_best_months', 'Nothing to compare yet - log a session, or pick a location, and this chart fills in.'),
            'bi bi-calendar3'
        );
        return;
    }

    const darkLabel = _saT('session_analytics.series_dark_hours', 'Dark hours available');
    const moonlessLabel = _saT('session_analytics.series_moonless_hours', 'Moonless dark hours');
    const loggedLabel = _saT('session_analytics.series_logged_hours', 'Hours you logged');

    const legend = [
        { label: darkLabel, color: SESSION_ANALYTICS_COLORS[5] },
        { label: moonlessLabel, color: SESSION_ANALYTICS_COLORS[0] },
        { label: loggedLabel, color: SESSION_ANALYTICS_COLORS[1] },
    ];
    const note = bestMonths?.astronomical_available === false
        ? _saT('session_analytics.best_months_unavailable', 'Only your own logged hours are shown - the sky figures could not be computed for this location.')
        : _saT('session_analytics.best_months_note', 'Availability is computed from the Sun and Moon at {location}; it is not a weather forecast.', {
            location: bestMonths?.location_name || '',
        });

    const { column, canvas } = _saChartCard(
        'sessionAnalyticsBestMonthsChart',
        _saT('session_analytics.chart_best_months_title', 'Available darkness vs. your own nights'),
        legend,
        { columnClass: 'col-12', note }
    );
    const row = document.createElement('div');
    row.className = 'row';
    row.appendChild(column);
    container.appendChild(row);

    const months = Array.from({ length: 12 }, (_value, index) => index + 1);
    const byMonth = new Map(astronomical.map(item => [item.month, item]));
    const loggedByMonth = new Map(logged.map(item => [item.month, item]));

    _saCreateChart(canvas, {
        type: 'bar',
        data: {
            labels: months.map(month => _saMonthName(month)),
            datasets: [
                {
                    label: darkLabel,
                    data: months.map(month => byMonth.get(month)?.dark_hours ?? 0),
                    backgroundColor: SESSION_ANALYTICS_COLORS[5],
                    borderRadius: 3,
                    order: 3,
                    yAxisID: 'y',
                },
                {
                    label: moonlessLabel,
                    data: months.map(month => byMonth.get(month)?.moonless_dark_hours ?? 0),
                    backgroundColor: SESSION_ANALYTICS_COLORS[0],
                    borderRadius: 3,
                    order: 2,
                    yAxisID: 'y',
                },
                {
                    label: loggedLabel,
                    type: 'line',
                    data: months.map(month => loggedByMonth.get(month)?.integration_hours ?? 0),
                    borderColor: SESSION_ANALYTICS_COLORS[1],
                    backgroundColor: SESSION_ANALYTICS_COLORS[1],
                    tension: 0.3,
                    order: 1,
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        afterLabel: context => {
                            if (context.datasetIndex !== 2) return '';
                            const item = loggedByMonth.get(months[context.dataIndex]) || {};
                            return _saT('session_analytics.best_months_tooltip', '{nights} nights logged', {
                                nights: item.nights_logged ?? 0,
                            });
                        },
                    },
                },
            },
            scales: {
                // The bars are a nightly average and the line is a month total, so they
                // cannot share one axis: on a single scale the logged total climbs above
                // the available darkness and reads as an impossibility.
                y: {
                    beginAtZero: true,
                    position: 'left',
                    title: {
                        display: true,
                        text: _saT('session_analytics.axis_hours_per_night', 'Hours per night'),
                    },
                },
                y1: {
                    beginAtZero: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    title: {
                        display: true,
                        text: _saT('session_analytics.axis_hours_logged', 'Hours logged'),
                    },
                },
            },
        },
    });
}

// ============================================
// Section 4 - conditions
// ============================================

const SESSION_ANALYTICS_CONDITION_ORDER = ['seeing', 'transparency', 'sqm', 'moon_illumination_percent'];

function _saConditionTitle(metric) {
    const titles = {
        seeing: _saT('session_analytics.condition_seeing', 'Seeing'),
        transparency: _saT('session_analytics.condition_transparency', 'Transparency'),
        sqm: _saT('session_analytics.condition_sqm', 'Sky brightness (SQM)'),
        moon_illumination_percent: _saT('session_analytics.condition_moon', 'Moon illumination'),
    };
    return titles[metric] || metric;
}

function _saDirectionNote(direction) {
    return direction === 'lower_is_better'
        ? _saT('session_analytics.direction_lower_is_better', 'On this scale, lower is better.')
        : _saT('session_analytics.direction_higher_is_better', 'On this scale, higher is better.');
}

function _saRenderConditions(conditions) {
    const container = document.getElementById('session-analytics-conditions');
    if (!container) return;
    DOMUtils.clear(container);

    const samples = Array.isArray(conditions?.samples) ? conditions.samples : [];
    if (!samples.length) {
        _saEmptyState(
            container,
            _saT('session_analytics.empty_conditions', 'Rate your logged targets and record the night conditions (seeing, transparency, SQM) to see how they line up.'),
            'bi bi-clipboard-data'
        );
        return;
    }

    const row = document.createElement('div');
    row.className = 'row row-cols-1 row-cols-xl-2 g-3';
    container.appendChild(row);

    SESSION_ANALYTICS_CONDITION_ORDER.forEach(metric => {
        const definition = conditions?.metrics?.[metric];
        if (!definition || !definition.measured_samples) return;

        const points = samples
            .filter(sample => sample[metric] != null)
            .map(sample => ({ x: Number(sample[metric]), y: Number(sample.rating), sample }));
        if (!points.length) return;

        const { column, canvas } = _saChartCard(
            `sessionAnalyticsCondition_${metric}`,
            _saConditionTitle(metric),
            (definition.buckets || []).map(bucket => ({
                label: _saBucketRangeLabel(metric, bucket),
                color: SESSION_ANALYTICS_QUALITY_COLORS[bucket.quality] || SESSION_ANALYTICS_COLORS[9],
            })),
            { columnClass: 'col' }
        );

        const cardBody = column.querySelector('.card-body');
        const direction = document.createElement('div');
        direction.className = 'session-analytics-direction-note';
        direction.textContent = _saDirectionNote(definition.direction);
        cardBody.insertBefore(direction, cardBody.firstChild);

        const bucketList = document.createElement('div');
        bucketList.className = 'mt-2';
        (definition.buckets || []).forEach(bucket => {
            bucketList.appendChild(_saBucketRow(metric, bucket, conditions.minimum_samples));
        });
        cardBody.appendChild(bucketList);

        row.appendChild(column);

        _saCreateChart(canvas, {
            type: 'scatter',
            data: {
                datasets: [
                    {
                        label: _saT('session_analytics.chart_conditions_series', 'Your rating'),
                        data: points,
                        pointBackgroundColor: points.map(
                            point => SESSION_ANALYTICS_QUALITY_COLORS[_saQualityFor(definition, point.x)] || SESSION_ANALYTICS_COLORS[0]
                        ),
                        pointRadius: 5,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: context => {
                                const sample = context.raw?.sample || {};
                                return `${sample.name || ''} - ${sample.date || ''}`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        // A "lower is better" scale reads best-first left to right when reversed.
                        reverse: definition.direction === 'lower_is_better',
                        title: { display: true, text: _saConditionTitle(metric) },
                    },
                    y: {
                        min: 0,
                        max: 5,
                        ticks: { stepSize: 1 },
                        title: { display: true, text: _saT('session_analytics.axis_rating', 'Rating') },
                    },
                },
            },
        });
    });
}

/** Which quality band a raw value falls into, using the bounds the API sent. */
function _saQualityFor(definition, value) {
    const bucket = (definition.buckets || []).find(item => value >= item.min && value <= item.max);
    return bucket ? bucket.quality : null;
}

function _saBucketRangeLabel(metric, bucket) {
    if (metric === 'moon_illumination_percent') return `${bucket.min}-${bucket.max}%`;
    return `${bucket.min}-${bucket.max}`;
}

function _saBucketRow(metric, bucket, minimumSamples) {
    const row = document.createElement('div');
    row.className = 'session-analytics-bucket-row';

    const label = document.createElement('span');
    label.textContent = _saBucketRangeLabel(metric, bucket);
    row.appendChild(label);

    const value = document.createElement('span');
    if (bucket.insufficient_data) {
        value.className = 'session-analytics-bucket-thin';
        value.textContent = _saT('session_analytics.bucket_insufficient', 'not enough data yet ({count}/{needed})', {
            count: bucket.samples,
            needed: minimumSamples,
        });
    } else {
        value.textContent = _saT('session_analytics.bucket_average', 'average {rating} over {count} targets', {
            rating: bucket.average_rating,
            count: bucket.samples,
        });
        value.className = 'session-analytics-bucket-samples';
    }
    row.appendChild(value);
    return row;
}

// ============================================
// Entry point
// ============================================

/**
 * Load and render the whole Analytics sub-tab.
 * @returns {Promise<void>}
 */
async function loadSessionAnalytics() {
    destroySessionAnalyticsCharts();

    const statsContainer = document.getElementById('session-analytics-stats');
    if (statsContainer) DOMUtils.setLoading(statsContainer, _saT('common.loading', 'Loading...'));

    const [summary, coverage, conditions, bestMonths] = await Promise.all([
        fetchJSON('/api/session-analytics/summary').catch(error => {
            console.error('Error loading analytics summary:', error);
            return null;
        }),
        fetchJSON('/api/session-analytics/sky-coverage').catch(error => {
            console.error('Error loading analytics sky coverage:', error);
            return null;
        }),
        fetchJSON('/api/session-analytics/conditions').catch(error => {
            console.error('Error loading analytics conditions:', error);
            return null;
        }),
        fetchJSON('/api/session-analytics/best-months').catch(error => {
            console.error('Error loading analytics best months:', error);
            return null;
        }),
    ]);

    sessionAnalyticsData.summary = summary;
    sessionAnalyticsData.coverage = coverage;
    sessionAnalyticsData.conditions = conditions;
    sessionAnalyticsData.bestMonths = bestMonths;

    if (!summary) {
        if (statsContainer) {
            DOMUtils.clear(statsContainer);
            _saEmptyState(
                statsContainer,
                _saT('session_analytics.load_error', 'Could not load your analytics.'),
                'bi bi-exclamation-triangle'
            );
        }
        return;
    }

    _saRenderStats(summary);
    _saRenderBreakdowns(summary);
    _saRenderCoverage(coverage);
    _saRenderBestMonths(bestMonths);
    _saRenderConditions(conditions);
}
