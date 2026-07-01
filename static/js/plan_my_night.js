// Plan My Night frontend module

const _planN2Notified = new Set(); // entry IDs already notified for N2 (in-memory, resets on page reload)

let planMyNightPollTimer = null;
let planMyNightStructureSnapshot = null;
let currentPlanTelescopeId = null;   // null = no/default telescope
let planTelescopeList = [];          // array from /api/plan-my-night/list

// Plan Summary Graph
let planSummaryChartInstance = null;
let planSummaryTargetBands   = [];
let planSummaryGraphGen      = 0;

function isPlanEditRole(role) {
    return role === 'admin' || role === 'user';
}

function clearPlanPollTimer() {
    if (planMyNightPollTimer) {
        clearTimeout(planMyNightPollTimer);
        planMyNightPollTimer = null;
    }
}

async function refreshAstrodexAfterPlanAction() {
    if (typeof loadAstrodex === 'function') {
        try {
            await loadAstrodex();
        } catch (error) {
            console.error('Error refreshing astrodex after Plan My Night action:', error);
        }
    }
}

function getPlanMyNightStructureSnapshot(payload) {
    const plan = payload?.plan;
    const entries = Array.isArray(plan?.entries) ? plan.entries : [];

    return JSON.stringify({
        role: payload?.role ?? null,
        state: payload?.state ?? 'none',
        nightStart: plan?.night_start ?? null,
        nightEnd: plan?.night_end ?? null,
        entries: entries.map(entry => ({
            id: entry?.id ?? null,
            name: entry?.name ?? null,
            targetName: entry?.target_name ?? null,
            catalogue: entry?.catalogue ?? null,
            type: entry?.type ?? null,
            constellation: entry?.constellation ?? null,
            timelineStart: entry?.timeline_start ?? null,
            timelineEnd: entry?.timeline_end ?? null,
            plannedDuration: entry?.planned_duration ?? null,
            plannedMinutes: entry?.planned_minutes ?? null,
            done: Boolean(entry?.done),
            inAstrodex: Boolean(entry?.in_astrodex),
            ra: entry?.ra ?? null,
            dec: entry?.dec ?? null,
            mag: entry?.mag ?? null,
            size: entry?.size ?? null,
            foto: entry?.foto ?? null,
            alttimeFile: entry?.alttime_file ?? null,
        })),
    });
}

function updatePlanCurrentBanner(container, payload, summaryElement) {
    const timeline = payload?.timeline || {};
    const bannerText = timeline.is_inside_night && payload?.current_banner
        ? i18n.t('plan_my_night.current_target_banner', {
            target: payload.current_banner.name || payload.current_banner.target_name || 'N/A'
        })
        : null;

    const existingBanner = document.getElementById('plan-my-night-current-banner');
    if (!bannerText) {
        existingBanner?.remove();
        return true;
    }

    if (existingBanner) {
        existingBanner.textContent = bannerText;
        return true;
    }

    if (!summaryElement) {
        return false;
    }

    const banner = document.createElement('div');
    banner.id = 'plan-my-night-current-banner';
    banner.className = 'alert alert-success plan-current-banner';
    banner.textContent = bannerText;
    container.insertBefore(banner, summaryElement);
    return true;
}

function patchPlanMyNightView(payload) {
    const container = document.getElementById('plan-my-night-display');
    if (!container || !isPlanEditRole(payload?.role)) {
        return false;
    }

    const state = payload?.state || 'none';
    const plan = payload?.plan;
    const timeline = payload?.timeline || {};
    if (state === 'none' || !plan) {
        return false;
    }

    const summaryElement = document.getElementById('plan-my-night-summary');
    const timelineList = document.getElementById('plan-my-night-timeline-list');
    if (!summaryElement || !timelineList) {
        return false;
    }

    if (!updatePlanCurrentBanner(container, payload, summaryElement)) {
        return false;
    }

    updatePlanSummaryChart(timeline);

    const currentTargetId = timeline.current_target_id ? String(timeline.current_target_id) : null;
    timelineList.querySelectorAll('.plan-target-item').forEach(item => {
        const entryId = item.getAttribute('data-plan-entry-id');
        const isCurrent = Boolean(currentTargetId) && entryId === currentTargetId;
        item.classList.toggle('plan-target-current', isCurrent);

        const badge = item.querySelector('.plan-time-badge');
        if (badge) {
            badge.classList.toggle('plan-time-badge-current', isCurrent);
        }
    });

    return true;
}

async function loadMoonCalendar() {
    const container = document.getElementById('plan-moon-calendar');
    if (!container) return;

    let data;
    try {
        data = await fetchJSON('/api/moon/month-calendar');
    } catch (_) {
        return;
    }
    if (!data || !data.nights || data.nights.length === 0) return;

    // Re-render each time (preference may have changed); clear previous render
    DOMUtils.clear(container);

    const startOnMonday = (currentUserPreferences?.first_day_of_week || 'monday') === 'monday';
    const locale = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : navigator.language;

    const section = document.createElement('div');
    section.className = 'plan-moon-calendar-section';

    // ── Header ──────────────────────────────────────────────────────────────
    const header = document.createElement('div');
    header.className = 'plan-moon-calendar-header';
    const title = document.createElement('span');
    title.className = 'fw-semibold small';
    DOMUtils.append(title, DOMUtils.createIcon('bi bi-moon-stars-fill text-info icon-inline'), ` ${i18n.t('plan_my_night.moon_calendar_title')}`);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'btn btn-link btn-sm p-0 ms-2 text-muted plan-moon-calendar-toggle';
    toggle.setAttribute('aria-expanded', 'true');
    toggle.appendChild(DOMUtils.createIcon('bi bi-chevron-up'));
    header.appendChild(title);
    header.appendChild(toggle);
    section.appendChild(header);

    const calBody = document.createElement('div');
    calBody.className = 'plan-moon-calendar-body';

    // ── Grid ─────────────────────────────────────────────────────────────────
    const grid = document.createElement('div');
    grid.className = 'plan-moon-calendar-grid';

    // Weekday header row
    // Jan 5 2025 = Sunday (getDay()=0), Jan 6 = Monday (getDay()=1) ... Jan 11 = Saturday (getDay()=6)
    // Column order: if startOnMonday → Mon(1) Tue(2) Wed(3) Thu(4) Fri(5) Sat(6) Sun(0)
    //               if startOnSunday → Sun(0) Mon(1) Tue(2) Wed(3) Thu(4) Fri(5) Sat(6)
    for (let col = 0; col < 7; col++) {
        const dowIndex = startOnMonday ? (col + 1) % 7 : col; // 0=Sun,1=Mon..6=Sat
        const refDate = new Date(2025, 0, 5 + dowIndex); // Jan 5 2025 = Sunday
        const hdr = document.createElement('div');
        hdr.className = 'plan-moon-cal-weekday-header';
        hdr.textContent = refDate.toLocaleDateString(locale, { weekday: 'short' });
        grid.appendChild(hdr);
    }

    // Blank cells before first night
    const firstDate = new Date(data.nights[0].date + 'T12:00:00');
    const firstDow = firstDate.getDay(); // 0=Sun..6=Sat
    const offset = startOnMonday ? (firstDow + 6) % 7 : firstDow;
    for (let b = 0; b < offset; b++) {
        const blank = document.createElement('div');
        blank.className = 'plan-moon-cal-cell plan-moon-cal-blank';
        grid.appendChild(blank);
    }

    // Night cells
    data.nights.forEach((night, idx) => {
        const d = new Date(night.date + 'T12:00:00');
        const dayNum = d.getDate();
        const isToday = idx === 0;
        const isFirstOfMonth = dayNum === 1;

        const cell = document.createElement('div');
        cell.className = 'plan-moon-cal-cell';
        if (isToday) cell.classList.add('plan-moon-cal-today');
        if (night.astrophoto_score >= 80) cell.classList.add('plan-moon-cal-good');
        else if (night.astrophoto_score >= 50) cell.classList.add('plan-moon-cal-ok');
        else cell.classList.add('plan-moon-cal-bright');

        // Day number - prefix month abbreviation when it's the 1st
        const dayEl = document.createElement('div');
        dayEl.className = 'plan-moon-cal-day';
        if (isFirstOfMonth) {
            const monthAbbr = d.toLocaleDateString(locale, { month: 'short' });
            const mo = document.createElement('span');
            mo.className = 'plan-moon-cal-month-abbr';
            mo.textContent = monthAbbr;
            dayEl.appendChild(mo);
        }
        dayEl.appendChild(document.createTextNode(dayNum));

        // Dark hours (strict)
        const darkEl = document.createElement('div');
        darkEl.className = 'plan-moon-cal-dark';
        darkEl.textContent = `${night.strict_hours.toFixed(1)}h`;

        // Moon illumination
        const illumEl = document.createElement('div');
        illumEl.className = 'plan-moon-cal-illum';
        illumEl.textContent = `${Math.round(night.illumination_percent)}%`;

        cell.title = `${night.date} - ${i18n.t('moon.illumination')}${Math.round(night.illumination_percent)}% - ${i18n.t('best_window.strict')}: ${night.strict_hours.toFixed(1)}h`;
        cell.appendChild(dayEl);
        cell.appendChild(darkEl);
        cell.appendChild(illumEl);
        grid.appendChild(cell);
    });

    calBody.appendChild(grid);

    // ── Legend ────────────────────────────────────────────────────────────────
    const legend = document.createElement('div');
    legend.className = 'plan-moon-cal-legend';
    [
        ['plan-moon-cal-good',   i18n.t('plan_my_night.moon_calendar_legend_good')],
        ['plan-moon-cal-ok',     i18n.t('plan_my_night.moon_calendar_legend_ok')],
        ['plan-moon-cal-bright', i18n.t('plan_my_night.moon_calendar_legend_bright')],
    ].forEach(([cls, label]) => {
        const dot = document.createElement('span');
        dot.className = `plan-moon-cal-legend-dot ${cls}`;
        const txt = document.createElement('span');
        txt.className = 'plan-moon-cal-legend-label';
        txt.textContent = label;
        legend.appendChild(dot);
        legend.appendChild(txt);
    });
    calBody.appendChild(legend);

    section.appendChild(calBody);
    container.appendChild(section);

    toggle.addEventListener('click', () => {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        DOMUtils.clear(toggle);
        toggle.appendChild(DOMUtils.createIcon(expanded ? 'bi bi-chevron-down' : 'bi bi-chevron-up'));
        calBody.style.display = expanded ? 'none' : '';
    });
}

// ── Seeing strip ──────────────────────────────────────────────────────────────

function _seeingLocalDateKey(utcDate, tz) {
    return utcDate.toLocaleDateString('en-CA', { timeZone: tz }); // 'YYYY-MM-DD'
}

function _aggregateSeeingByDate(forecast, tz) {
    // Groups all forecast points by local calendar date, keeps best (lowest) seeing per day.
    // No nighttime filtering: 7Timer ASTRO seeing represents the atmospheric column quality
    // for the whole day. Simpler and avoids timezone edge-cases with hour boundaries.
    const map = new Map();
    for (const point of (forecast || [])) {
        const key = _seeingLocalDateKey(new Date(point.time), tz);
        const current = map.get(key);
        if (current === undefined || point.seeing < current) {
            map.set(key, point.seeing);
        }
    }
    return map;
}

async function loadSeeingWeek() {
    const container = document.getElementById('plan-seeing-week');
    if (!container) return;

    DOMUtils.clear(container);

    let data;
    try {
        data = await fetchJSON('/api/seeing-forecast');
    } catch (_) {
        return;
    }

    const seeingData = data?.seeing_forecast;
    const forecast = seeingData?.forecast;
    const tz = seeingData?.location?.timezone || 'UTC';
    if (!forecast || forecast.length === 0) return;

    const dateMap = _aggregateSeeingByDate(forecast, tz);
    const locale = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : navigator.language;

    // Collect only the dates that have data, up to 7 days starting from today.
    const todayStr = new Date().toLocaleDateString('en-CA', { timeZone: tz });
    const [ty, tm, td] = todayStr.split('-').map(Number);
    const nights = [];
    for (let i = 0; i < 7; i++) {
        const utc = new Date(Date.UTC(ty, tm - 1, td + i));
        const key = _seeingLocalDateKey(utc, tz);
        if (dateMap.has(key)) nights.push({ key, utc });
    }

    // No data at all → skip rendering entirely
    if (nights.length === 0) return;

    const section = document.createElement('div');
    section.className = 'plan-moon-calendar-section';

    // Header
    const header = document.createElement('div');
    header.className = 'plan-moon-calendar-header';
    const title = document.createElement('span');
    title.className = 'fw-semibold small';
    DOMUtils.append(title, DOMUtils.createIcon('bi bi-eye text-info icon-inline'), ` ${i18n.t('plan_my_night.seeing_week_title')}`);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'btn btn-link btn-sm p-0 ms-2 text-muted plan-moon-calendar-toggle';
    toggle.setAttribute('aria-expanded', 'true');
    toggle.appendChild(DOMUtils.createIcon('bi bi-chevron-up'));
    header.appendChild(title);
    header.appendChild(toggle);
    section.appendChild(header);

    const calBody = document.createElement('div');
    calBody.className = 'plan-moon-calendar-body';

    const grid = document.createElement('div');
    grid.className = 'plan-seeing-week-grid';
    // Adapt column count to however many nights have data (not always 7)
    grid.style.gridTemplateColumns = `repeat(${nights.length}, 1fr)`;

    nights.forEach(({ key, utc }, idx) => {
        const isToday = idx === 0;
        const bestSeeing = dateMap.get(key);

        const cell = document.createElement('div');
        cell.className = 'plan-seeing-week-cell';
        if (isToday) cell.classList.add('plan-moon-cal-today');
        if (bestSeeing <= 2) cell.classList.add('plan-moon-cal-good');
        else if (bestSeeing <= 3) cell.classList.add('plan-moon-cal-ok');
        else cell.classList.add('plan-moon-cal-bright');

        // Weekday abbreviation
        const dowEl = document.createElement('div');
        dowEl.className = 'plan-seeing-week-dow';
        dowEl.textContent = utc.toLocaleDateString(locale, { timeZone: tz, weekday: 'short' });

        // Day number (+ month abbr on 1st)
        const dayNum = parseInt(key.split('-')[2]);
        const dayEl = document.createElement('div');
        dayEl.className = 'plan-moon-cal-day';
        if (dayNum === 1) {
            const mo = document.createElement('span');
            mo.className = 'plan-moon-cal-month-abbr';
            mo.textContent = utc.toLocaleDateString(locale, { timeZone: tz, month: 'short' });
            dayEl.appendChild(mo);
        }
        dayEl.appendChild(document.createTextNode(dayNum));

        // Score (coloured)
        const scoreEl = document.createElement('div');
        scoreEl.className = `plan-seeing-week-score ${getSeeingBadgeClass(bestSeeing)}`;
        scoreEl.textContent = bestSeeing;

        // Quality label
        const qualEl = document.createElement('div');
        qualEl.className = 'plan-seeing-week-quality';
        qualEl.textContent = getLocalizedSeeingQuality(bestSeeing, '');

        cell.title = `${key} - ${i18n.t('seeing_forecast.current_seeing')}: ${bestSeeing}/8 - ${getLocalizedSeeingQuality(bestSeeing, '')}`;
        cell.appendChild(dowEl);
        cell.appendChild(dayEl);
        cell.appendChild(scoreEl);
        cell.appendChild(qualEl);
        grid.appendChild(cell);
    });

    calBody.appendChild(grid);
    section.appendChild(calBody);
    container.appendChild(section);

    toggle.addEventListener('click', () => {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        DOMUtils.clear(toggle);
        toggle.appendChild(DOMUtils.createIcon(expanded ? 'bi bi-chevron-down' : 'bi bi-chevron-up'));
        calBody.style.display = expanded ? 'none' : '';
    });
}

// ─────────────────────────────────────────────────────────────────────────────

async function loadPlanMyNight(options = {}) {
    const {
        silent = false,
        restoreFocus = null,
        preserveViewport = false,
        preferPatchOnly = false,
    } = options;
    clearPlanPollTimer();

    const container = document.getElementById('plan-my-night-display');
    if (!container) return;

    const viewportState = preserveViewport
        ? {
            scrollX: window.scrollX,
            scrollY: window.scrollY,
            minHeight: container.offsetHeight,
        }
        : null;

    if (viewportState && viewportState.minHeight > 0) {
        container.style.minHeight = `${viewportState.minHeight}px`;
    }

    if (!silent) {
        DOMUtils.clear(container);

        const loading = document.createElement('div');
        loading.className = 'alert alert-info';
        loading.textContent = i18n.t('common.loading');
        container.appendChild(loading);
    }

    try {
        const telescopeListPayload = await fetchJSON('/api/plan-my-night/list');
        planTelescopeList = telescopeListPayload?.plans || [];
        const telescopeItems = (telescopeListPayload?.telescope_count) || 0;

        // Auto-select the first telescope (by display sort order) if none selected yet
        if (currentPlanTelescopeId === null && telescopeItems > 0) {
            const sorted = planTelescopeList
                .filter(p => p.telescope_id !== null)
                .sort((a, b) => {
                    const groupA = a.state === 'current' ? 0 : (a.is_own !== false ? 1 : 2);
                    const groupB = b.state === 'current' ? 0 : (b.is_own !== false ? 1 : 2);
                    if (groupA !== groupB) return groupA - groupB;
                    return (a.telescope_name || '').localeCompare(b.telescope_name || '');
                });
            if (sorted.length > 0) currentPlanTelescopeId = sorted[0].telescope_id;
        }

        const telescopeIdParam = currentPlanTelescopeId
            ? `?telescope_id=${encodeURIComponent(currentPlanTelescopeId)}`
            : '';
        const payload = await fetchJSON(`/api/plan-my-night${telescopeIdParam}`);
        const nextStructureSnapshot = getPlanMyNightStructureSnapshot(payload);
        const canPatchInPlace = silent && planMyNightStructureSnapshot === nextStructureSnapshot;
        const patchedInPlace = patchPlanMyNightView(payload);
        const shouldUsePatchOnly = silent && preferPatchOnly && patchedInPlace;

        if (!(canPatchInPlace && patchedInPlace) && !shouldUsePatchOnly) {
            renderPlanMyNight(payload);
        } else if (shouldUsePatchOnly && !canPatchInPlace) {
            // Structure changed (e.g. reorder shifted timeline_start/end) but DOM was patched
            // in place - rebuild only the summary graph with the updated entry order/times.
            const graphContainer = document.getElementById('plan-summary-graph-container');
            if (graphContainer) {
                buildPlanSummaryGraph(graphContainer, payload?.plan?.entries || [], payload?.plan, payload?.timeline || {})
                    .catch(err => console.error('Plan summary graph error:', err));
            }
        }

        restorePlanMyNightViewport(viewportState, container);
        restorePlanMyNightFocus(restoreFocus);

        planMyNightStructureSnapshot = nextStructureSnapshot;

        // Keep timeline/current target fresh while tab remains visible.
        // Use a shorter interval during the night so the graph cursor stays accurate.
        const pollIntervalMs = payload?.timeline?.is_inside_night ? 30000 : 60000;
        planMyNightPollTimer = setTimeout(() => {
            const tab = document.getElementById('plan-my-night-subtab');
            if (tab && tab.classList.contains('active') && !document.hidden) {
                loadPlanMyNight({ silent: true });
            }
        }, pollIntervalMs);
    } catch (error) {
        restorePlanMyNightViewport(viewportState, container);

        if (silent) {
            console.warn('Silent Plan My Night refresh failed:', error);
            planMyNightPollTimer = setTimeout(() => {
                const tab = document.getElementById('plan-my-night-subtab');
                if (tab && tab.classList.contains('active')) {
                    loadPlanMyNight({ silent: true });
                }
            }, 60000);
            return;
        }

        planMyNightStructureSnapshot = null;
        DOMUtils.clear(container);
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger';
        alert.textContent = i18n.t('plan_my_night.failed_to_load');
        container.appendChild(alert);
    }
}

function escapePlanSelectorValue(value) {
    if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
        return CSS.escape(String(value));
    }
    // Fallback: escape backslashes first, then double-quotes, for use inside a
    // double-quoted attribute selector value (e.g. [attr="<value>"]).
    return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

function restorePlanMyNightFocus(target) {
    if (!target?.entryId || !target?.action) {
        return;
    }

    const entrySelectorValue = escapePlanSelectorValue(target.entryId);
    const actionSelectorValue = escapePlanSelectorValue(target.action);

    requestAnimationFrame(() => {
        const element = document.querySelector(
            `.plan-target-item[data-plan-entry-id="${entrySelectorValue}"] [data-plan-action="${actionSelectorValue}"]`
        );
        if (element instanceof HTMLElement) {
            element.focus({ preventScroll: true });
        }
    });
}

function restorePlanMyNightViewport(viewportState, container) {
    if (!viewportState) {
        return;
    }

    requestAnimationFrame(() => {
        window.scrollTo({ top: viewportState.scrollY, left: viewportState.scrollX, behavior: 'auto' });

        requestAnimationFrame(() => {
            window.scrollTo({ top: viewportState.scrollY, left: viewportState.scrollX, behavior: 'auto' });
            if (container) {
                container.style.minHeight = '';
            }
        });
    });
}

function updatePlanTargetOrderLabels() {
    const items = Array.from(document.querySelectorAll('#plan-my-night-timeline-list .plan-target-item'));
    items.forEach((item, index) => {
        const title = item.querySelector('h5');
        const targetName = item.getAttribute('data-plan-target-name') || 'N/A';
        if (title) {
            title.textContent = `${index + 1}. ${targetName}`;
        }
    });
}

function updatePlanMoveButtonsState() {
    const items = Array.from(document.querySelectorAll('#plan-my-night-timeline-list .plan-target-item'));
    items.forEach((item, index) => {
        const moveUpBtn = item.querySelector('[data-plan-action="move-up"]');
        const moveDownBtn = item.querySelector('[data-plan-action="move-down"]');
        if (moveUpBtn instanceof HTMLButtonElement) {
            moveUpBtn.disabled = index === 0;
        }
        if (moveDownBtn instanceof HTMLButtonElement) {
            moveDownBtn.disabled = index === items.length - 1;
        }
    });
}

function movePlanTargetItemInDom(entryId, direction) {
    const timelineList = document.getElementById('plan-my-night-timeline-list');
    if (!timelineList || !entryId || !Number.isInteger(direction) || direction === 0) {
        return false;
    }

    const selectorValue = escapePlanSelectorValue(entryId);
    const item = timelineList.querySelector(`.plan-target-item[data-plan-entry-id="${selectorValue}"]`);
    if (!(item instanceof HTMLElement)) {
        return false;
    }

    const items = Array.from(timelineList.querySelectorAll('.plan-target-item'));
    const currentIndex = items.indexOf(item);
    if (currentIndex < 0) {
        return false;
    }

    const newIndex = currentIndex + direction;
    if (newIndex < 0 || newIndex >= items.length) {
        return false;
    }

    const sibling = items[newIndex];
    if (!sibling) {
        return false;
    }

    if (direction < 0) {
        timelineList.insertBefore(item, sibling);
    } else {
        timelineList.insertBefore(sibling, item);
    }

    updatePlanTargetOrderLabels();
    updatePlanMoveButtonsState();
    return true;
}

function makePlanActionButton(labelKey, className, onClick) {
    let iconClass = null;
    if (labelKey === 'plan_my_night.export_pdf') {
        iconClass = 'bi bi-filetype-pdf';
    } else if (labelKey === 'plan_my_night.export_csv') {
        iconClass = 'bi bi-filetype-csv';
    } else if (labelKey === 'plan_my_night.clear_this_plan' || labelKey === 'plan_my_night.clear_plan' || labelKey === 'plan_my_night.clear_all_plans') {
        iconClass = 'bi bi-trash';
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    if (iconClass) {
        DOMUtils.append(button, DOMUtils.createIcon(iconClass), ` ${i18n.t(labelKey)}`);
    } else {
        button.textContent = i18n.t(labelKey);
    }
    button.addEventListener('click', onClick);
    return button;
}

function makePlanIconActionButton(labelKey, className, iconClass, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `${className} btn-icon-square`;
    button.title = i18n.t(labelKey);
    button.setAttribute('aria-label', i18n.t(labelKey));

    const icon = document.createElement('i');
    icon.className = `${iconClass} icon-inline`;
    icon.setAttribute('aria-hidden', 'true');
    button.appendChild(icon);

    button.addEventListener('click', onClick);
    return button;
}

function getPlanTargetTypeDisplayName(value) {
    return tSkyTonightType(value);
}

function getPlanConstellationDisplayName(value) {
    const normalizedValue = (value || '').toString().trim();
    if (!normalizedValue) {
        return '-';
    }

    const translationKey = 'constellations.' + strToTranslateKey(normalizedValue);
    if (i18n.has(translationKey)) {
        return i18n.t(translationKey);
    }

    return capitalizeWords(normalizedValue);
}

function formatPlanNumericValue(value, decimals = 2) {
    if (value === null || value === undefined || value === '') {
        return null;
    }

    const parsed = Number.parseFloat(String(value));
    if (!Number.isFinite(parsed)) {
        return String(value);
    }

    return parsed.toFixed(decimals);
}

function parsePlanDurationToMinutes(value) {
    const text = String(value || '').trim();
    if (!text) {
        return 0;
    }

    const parts = text.split(':');
    if (parts.length !== 2) {
        return 0;
    }

    const hours = Number.parseInt(parts[0], 10);
    const minutes = Number.parseInt(parts[1], 10);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours < 0 || minutes < 0 || minutes > 59) {
        return 0;
    }

    return (hours * 60) + minutes;
}

function normalizePlanDurationHHMM(value) {
    const text = String(value || '').trim();
    if (!text) {
        return null;
    }

    const parts = text.split(':');
    if (parts.length !== 2) {
        return null;
    }

    const hours = Number.parseInt(parts[0], 10);
    const minutes = Number.parseInt(parts[1], 10);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours < 0 || hours > 23 || minutes < 0 || minutes > 59) {
        return null;
    }

    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

function formatMinutesAsHourMinute(minutes) {
    const safeMinutes = Math.max(0, Math.round(Number(minutes) || 0));
    const hours = Math.floor(safeMinutes / 60);
    const remainingMinutes = safeMinutes % 60;
    return `${hours}h${String(remainingMinutes).padStart(2, '0')}`;
}

function computePlannedCoverage(entries, plan) {
    const nightStart = plan && plan.night_start ? new Date(plan.night_start) : null;
    const nightEnd = plan && plan.night_end ? new Date(plan.night_end) : null;

    let nightMinutes = 0;
    if (nightStart instanceof Date && !Number.isNaN(nightStart.getTime()) &&
        nightEnd instanceof Date && !Number.isNaN(nightEnd.getTime()) &&
        nightEnd > nightStart) {
        nightMinutes = Math.round((nightEnd.getTime() - nightStart.getTime()) / 60000);
    }

    // Subtract start delay - the usable observing window is shorter
    const startDelayMinutes = Math.max(0, parseInt(plan && plan.start_delay_minutes) || 0);
    nightMinutes = Math.max(0, nightMinutes - startDelayMinutes);

    let plannedMinutes = 0;
    (entries || []).forEach(entry => {
        const explicitMinutes = Number.parseInt(String(entry.planned_minutes ?? ''), 10);
        if (Number.isFinite(explicitMinutes) && explicitMinutes >= 0) {
            plannedMinutes += explicitMinutes;
            return;
        }
        plannedMinutes += parsePlanDurationToMinutes(entry.planned_duration);
    });

    const fillPercentRaw = nightMinutes > 0 ? (plannedMinutes / nightMinutes) * 100 : 0;
    const fillPercent = Math.max(0, fillPercentRaw);
    const overflowMinutes = Math.max(0, plannedMinutes - nightMinutes);

    return {
        nightMinutes,
        plannedMinutes,
        fillPercent,
        overflowMinutes,
    };
}

function getPlanEntryMinutes(entry) {
    const explicitMinutes = Number.parseInt(String(entry?.planned_minutes ?? ''), 10);
    if (Number.isFinite(explicitMinutes) && explicitMinutes >= 0) {
        return explicitMinutes;
    }
    return parsePlanDurationToMinutes(entry?.planned_duration);
}



function getCoverageStatus(fillPercent) {
    const safePercent = Number(fillPercent) || 0;
    if (safePercent > 100) {
        return { key: 'overloaded', className: 'text-bg-danger' };
    }
    if (safePercent >= 80) {
        return { key: 'optimal', className: 'text-bg-success' };
    }
    return { key: 'underplanned', className: 'text-bg-warning' };
}

// ── Plan Summary Altitude Graph ─────────────────────────────────────────────

function destroyPlanSummaryChart() {
    if (planSummaryChartInstance) {
        planSummaryChartInstance.destroy();
        planSummaryChartInstance = null;
    }
    planSummaryTargetBands = [];
    planSummaryGraphGen++;
}

/**
 * Clip alttime arrays to a time window, interpolating boundary points.
 * Returns [{x: ms, y: altitude, az: azimuth|null}, ...]
 */
function _planClipAlttime(timesUtc, altitudes, azimuths, windowStartIso, windowEndIso) {
    const wsMs = new Date(windowStartIso).getTime();
    const weMs = new Date(windowEndIso).getTime();
    if (wsMs >= weMs || !timesUtc || !timesUtc.length) return [];

    // times_utc values have no 'Z' suffix (bare ISO strings) - force UTC parsing,
    // matching the same pattern used in skytonight.js: new Date(t + 'Z')
    const pts = timesUtc.map((t, i) => ({
        x:  new Date(t + 'Z').getTime(),
        y:  altitudes[i],
        az: azimuths ? (azimuths[i] ?? null) : null,
    }));

    function lerpPt(a, b, x) {
        const t = (x - a.x) / (b.x - a.x);
        return { x, y: a.y + t * (b.y - a.y), az: (a.az !== null && b.az !== null) ? a.az + t * (b.az - a.az) : null };
    }

    const out = [];
    for (let i = 0; i < pts.length; i++) {
        const p    = pts[i];
        const prev = pts[i - 1];
        const next = pts[i + 1];
        if (prev && prev.x < wsMs && p.x > wsMs)  out.push(lerpPt(prev, p, wsMs));
        if (p.x >= wsMs && p.x <= weMs)             out.push({ x: p.x, y: p.y, az: p.az });
        if (p.x <= weMs && next && next.x > weMs)   out.push(lerpPt(p, next, weMs));
    }
    return out;
}

/**
 * Linearly interpolate custom horizon altitude at a given azimuth.
 * Matches _horizonAltAtAz in skytonight.js.
 */
function _planHorizonAltAtAz(az, profile) {
    if (!profile || !profile.length) return null;
    const sorted = [...profile].sort((a, b) => a.az - b.az);
    const azNorm = ((az % 360) + 360) % 360;
    const idx = sorted.findIndex(p => p.az > azNorm);
    if (idx === -1) {
        const p0 = sorted[sorted.length - 1];
        const p1 = { az: sorted[0].az + 360, alt: sorted[0].alt };
        const t  = (azNorm - p0.az) / (p1.az - p0.az);
        return p0.alt + t * (p1.alt - p0.alt);
    }
    if (idx === 0) {
        const p0 = { az: sorted[sorted.length - 1].az - 360, alt: sorted[sorted.length - 1].alt };
        const t  = (azNorm - p0.az) / (sorted[0].az - p0.az);
        return p0.alt + t * (sorted[0].alt - p0.alt);
    }
    const p0 = sorted[idx - 1];
    const p1 = sorted[idx];
    const t  = (azNorm - p0.az) / (p1.az - p0.az);
    return p0.alt + t * (p1.alt - p0.alt);
}

function _planBandStatus(entryId, endMs, currentTargetId) {
    if (currentTargetId && String(entryId) === String(currentTargetId)) return 'current';
    if (endMs < Date.now()) return 'done';
    return 'future';
}

function _planBandColors(status) {
    if (status === 'current') return { border: '#198754', bg: 'rgba(25,135,84,0.18)' };
    if (status === 'done')    return { border: '#fd7e14', bg: 'rgba(253,126,20,0.12)' };
    return                           { border: '#6c757d', bg: 'rgba(108,117,125,0.09)' };
}

async function buildPlanSummaryGraph(container, entries, plan, timeline) {
    destroyPlanSummaryChart();
    const myGen = planSummaryGraphGen;

    const nightStartMs = plan.night_start ? new Date(plan.night_start).getTime() : null;
    const nightEndMs   = plan.night_end   ? new Date(plan.night_end).getTime()   : null;
    if (!nightStartMs || !nightEndMs || !entries.length) return;

    // Loading state
    DOMUtils.clear(container);
    const loadingEl = document.createElement('div');
    loadingEl.className = 'text-center text-muted small py-3';
    loadingEl.textContent = i18n.t('common.loading');
    container.appendChild(loadingEl);

    // Fetch alttime for all entries concurrently
    const entriesWithAlt = entries.filter(e => e.alttime_file);
    const settled = await Promise.allSettled(
        entriesWithAlt.map(e =>
            fetchJSON(`/api/skytonight/alttime/${encodeURIComponent(e.alttime_file)}`)
        )
    );

    if (myGen !== planSummaryGraphGen) return; // stale - a new render started

    const alttimeMap = {};
    entriesWithAlt.forEach((e, i) => {
        const r = settled[i];
        if (r.status === 'fulfilled' && r.value && !r.value.error) {
            alttimeMap[e.id] = r.value;
        }
    });

    DOMUtils.clear(container);

    // Settings from first available alttime response
    const firstAlt  = Object.values(alttimeMap)[0];
    const altMin    = firstAlt?.altitude_constraint_min ?? 30;
    const altMax    = firstAlt?.altitude_constraint_max ?? 80;
    const horizProf = firstAlt?.horizon_profile ?? null;
    const timezone  = firstAlt?.timezone ?? null;
    const yMax      = altMax >= 85 ? altMax + 5 : altMax + 10;

    // Resolve theme-aware chart colors - same CSS variables as skytonight.js
    const rootStyle      = getComputedStyle(document.documentElement);
    const bsTheme        = (document.documentElement.getAttribute('data-bs-theme') || '').toLowerCase();
    const theme          = (document.documentElement.getAttribute('data-theme') || '').toLowerCase();
    const isDark         = theme === 'dark' || theme === 'red' || bsTheme === 'dark';
    const cssVar         = (name, fb) => { const v = rootStyle.getPropertyValue(name); return v ? v.trim() : fb; };
    const primaryRgb     = cssVar('--bs-primary-rgb', '13, 110, 253');
    const gridColor      = isDark ? 'rgba(255,255,255,0.16)' : 'rgba(15,23,42,0.12)';
    const altLineColor   = `rgba(${primaryRgb}, 0.92)`;
    const constColor     = 'rgba(20,110,40,0.8)';
    const horizLineColor = 'rgba(200,80,0,0.75)';

    const tzFmt = timezone
        ? new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', timeZone: timezone, hour12: false })
        : null;

    function fmtXTick(ms) {
        if (tzFmt) return tzFmt.format(new Date(ms));
        const d = new Date(ms);
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    const currentTargetId = timeline?.current_target_id;
    const datasets = [];
    const bands    = [];

    entries.forEach((entry, index) => {
        const startMs  = entry.timeline_start ? new Date(entry.timeline_start).getTime() : null;
        const rawEndMs = entry.timeline_end   ? new Date(entry.timeline_end).getTime()   : null;
        const endMs    = rawEndMs ? Math.min(rawEndMs, nightEndMs) : null;

        if (!startMs || !endMs || startMs >= nightEndMs || endMs <= startMs) return;

        const status    = _planBandStatus(entry.id, endMs, currentTargetId);
        const colors    = _planBandColors(status);
        const entryName = entry.name || entry.target_name || `Target ${index + 1}`;

        bands.push({
            startMs,
            endMs,
            num:         index + 1,
            name:        entryName,
            entryId:     entry.id,
            status,
            borderColor: colors.border,
            bgColor:     colors.bg,
        });

        const atd = alttimeMap[entry.id];
        if (!atd?.times_utc) return;

        const clippedEndMs  = Math.min(rawEndMs, nightEndMs);
        const clippedEndIso = new Date(clippedEndMs).toISOString();
        const clipped = _planClipAlttime(atd.times_utc, atd.altitudes, atd.azimuths, entry.timeline_start, clippedEndIso);
        if (!clipped.length) return;

        // Altitude curve - consistent primary color for all targets
        datasets.push({
            label:            entryName,
            data:             clipped.map(p => ({ x: p.x, y: p.y })),
            parsing:          false,
            borderColor:      altLineColor,
            backgroundColor:  'transparent',
            fill:             false,
            tension:          0.3,
            borderWidth:      2,
            pointRadius:      0,
            pointHoverRadius: 3,
            order:            2,
            _entryId:         entry.id,
        });

        // Custom horizon curve per target (azimuth-mapped)
        if (horizProf && clipped.some(p => p.az !== null)) {
            const horizPts = clipped
                .map(p => ({ x: p.x, y: p.az !== null ? _planHorizonAltAtAz(p.az, horizProf) : null }))
                .filter(p => p.y !== null);
            if (horizPts.length) {
                datasets.push({
                    label:           '',
                    data:            horizPts,
                    parsing:         false,
                    borderColor:     horizLineColor,
                    backgroundColor: 'transparent',
                    fill:            false,
                    tension:         0.3,
                    borderWidth:     1,
                    borderDash:      [3, 3],
                    pointRadius:     0,
                    order:           3,
                    _isHorizon:      true,
                });
            }
        }
    });

    // Observable zone lines spanning the full night (matching skytonight.js style)
    datasets.push({
        label:           `${altMin}°`,
        data:            [{ x: nightStartMs, y: altMin }, { x: nightEndMs, y: altMin }],
        parsing:         false,
        borderColor:     constColor,
        backgroundColor: 'transparent',
        fill:            false,
        borderWidth:     1,
        borderDash:      [5, 4],
        pointRadius:     0,
        tension:         0,
        order:           4,
        _isConstraint:   true,
    });
    datasets.push({
        label:           `${altMax}°`,
        data:            [{ x: nightStartMs, y: altMax }, { x: nightEndMs, y: altMax }],
        parsing:         false,
        borderColor:     constColor,
        backgroundColor: 'transparent',
        fill:            false,
        borderWidth:     1,
        borderDash:      [5, 4],
        pointRadius:     0,
        tension:         0,
        order:           4,
        _isConstraint:   true,
    });

    // Current time vertical line
    const nowMs = Date.now();
    datasets.push({
        label:           '',
        data:            [{ x: nowMs, y: 0 }, { x: nowMs, y: yMax }],
        parsing:         false,
        borderColor:     '#ef4444',
        backgroundColor: 'transparent',
        fill:            false,
        borderWidth:     1.5,
        borderDash:      [4, 4],
        pointRadius:     0,
        tension:         0,
        order:           1,
        _isCurrentTime:  true,
    });

    planSummaryTargetBands = bands;

    // Plugin: colored band rectangles with number + name label
    const planTargetBandsPlugin = {
        id: 'planTargetBands',
        beforeDatasetsDraw(chart) {
            const { ctx, chartArea, scales } = chart;
            if (!chartArea) return;
            const xScale = scales.x;
            const { top, bottom } = chartArea;
            ctx.save();
            ctx.textBaseline = 'middle';
            ctx.save();
            ctx.rect(chartArea.left, top, chartArea.right - chartArea.left, bottom - top);
            ctx.clip();
            const bandRadius  = 5;
            const labelFont   = 'bold 12px sans-serif';
            const labelPadX   = 7;
            const labelPadY   = 4;
            const labelRadius = 3;
            ctx.font = labelFont;
            for (const band of planSummaryTargetBands) {
                const x1 = Math.max(chartArea.left,  xScale.getPixelForValue(band.startMs));
                const x2 = Math.min(chartArea.right, xScale.getPixelForValue(band.endMs));
                if (x2 <= x1) continue;
                // Border - rounded rect, no horizontal inset so adjacent bands share the edge pixel
                ctx.strokeStyle = band.borderColor;
                ctx.lineWidth   = 1.5;
                ctx.setLineDash([]);
                ctx.beginPath();
                ctx.roundRect(x1, top + 1, x2 - x1, bottom - top - 2, bandRadius);
                ctx.stroke();
                // Label: "N. Name" with pill background, truncated to fit band width
                const full       = `${band.num}. ${band.name}`;
                const bandW      = x2 - x1;
                const maxTextW   = bandW - labelPadX * 2 - 8;
                if (maxTextW > 12) {
                    let label = full;
                    while (ctx.measureText(label).width > maxTextW && label.length > `${band.num}.`.length) {
                        label = label.slice(0, -1);
                    }
                    if (label !== full) label += '…';
                    const textW  = ctx.measureText(label).width;
                    const pillW  = textW + labelPadX * 2;
                    const pillH  = 12 + labelPadY * 2;
                    const pillX  = x1 + 6;
                    const pillY  = top + 7;
                    ctx.fillStyle = band.borderColor;
                    ctx.beginPath();
                    ctx.roundRect(pillX, pillY, pillW, pillH, labelRadius);
                    ctx.fill();
                    ctx.fillStyle = '#ffffff';
                    ctx.fillText(label, pillX + labelPadX, pillY + pillH / 2);
                }
            }
            ctx.restore(); // pop clip
            ctx.restore(); // pop font/textBaseline
        },
    };

    // ── DOM structure (canvas wrapper with fixed height + legend footer) ──
    // The canvas must be the only child of its wrapper so Chart.js responsive
    // mode reads a stable fixed height and does not enter an infinite growth loop.

    const canvasWrap = document.createElement('div');
    canvasWrap.className = 'plan-summary-graph-canvas-wrap';
    const canvas = document.createElement('canvas');
    canvasWrap.appendChild(canvas);
    container.appendChild(canvasWrap);

    // Legend footer row (matching card-footer badge style from horizon-graph.js)
    const footerRow = document.createElement('div');
    footerRow.className = 'row align-items-center mt-2';

    const mkBadge = (color, text, dashed) => {
        const col   = document.createElement('div');
        col.className = 'col-auto';
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.backgroundColor = color;
        if (dashed) badge.style.outline = `2px dashed ${color}`;
        badge.textContent = text;
        col.appendChild(badge);
        return col;
    };

    footerRow.appendChild(mkBadge(altLineColor,   i18n.t('skytonight.altitude_time_altitude_label') || 'Altitude'));
    footerRow.appendChild(mkBadge(constColor,      i18n.t('skytonight.altitude_time_observable_zone') || 'Observable zone'));
    if (horizProf) {
        footerRow.appendChild(mkBadge(horizLineColor, i18n.t('skytonight.horizon_custom_line') || 'Custom horizon'));
    }
    footerRow.appendChild(mkBadge('#198754', i18n.t('plan_my_night.plan_status_current') || 'Active'));
    footerRow.appendChild(mkBadge('#fd7e14', i18n.t('plan_my_night.plan_status_previous') || 'Expired'));
    footerRow.appendChild(mkBadge('#6c757d', i18n.t('skytonight.planned') || 'Planned'));
    footerRow.appendChild(mkBadge('#ef4444', i18n.t('astro_weather.now_badge') || 'Now', true));

    container.appendChild(footerRow);

    // Custom interaction mode: nearest altitude-only point (excludes horizon, constraint, now-line)
    if (!Chart.Interaction.modes.planAltNearest) {
        Chart.Interaction.modes.planAltNearest = function(chart, e, options, useFinalPosition) {
            return Chart.Interaction.modes.nearest(chart, e, options, useFinalPosition)
                .filter(i => {
                    const ds = chart.data.datasets[i.datasetIndex];
                    return !ds._isHorizon && !ds._isConstraint && !ds._isCurrentTime;
                });
        };
    }

    planSummaryChartInstance = new Chart(canvas.getContext('2d'), {
        type:    'line',
        plugins: [planTargetBandsPlugin],
        data:    { datasets },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            animation:           false,
            interaction:         { mode: 'planAltNearest', intersect: false, axis: 'x' },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title(items) {
                            if (!items.length) return '';
                            const x = items[0].parsed?.x ?? items[0].raw?.x;
                            return fmtXTick(x);
                        },
                        label(ctx) {
                            const y = +(ctx.parsed?.y ?? ctx.raw?.y);
                            if (isNaN(y)) return null;
                            return `${ctx.dataset.label}  ${y.toFixed(1)}°`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    type:  'linear',
                    min:   nightStartMs,
                    max:   nightEndMs,
                    ticks: { maxTicksLimit: 8, callback: v => fmtXTick(v) },
                    grid:  { color: gridColor },
                },
                y: {
                    type:  'linear',
                    min:   0,
                    max:   yMax,
                    ticks: { maxTicksLimit: 5, callback: v => `${v}°` },
                    grid:  { color: gridColor },
                    title: { display: true, text: i18n.t('units.degrees') || '°', font: { size: 10 } },
                },
            },
        },
    });
}

function updatePlanSummaryChart(timeline) {
    if (!planSummaryChartInstance) return;

    const currentTargetId = timeline?.current_target_id;
    const nowMs           = Date.now();

    // Update current time line position
    const nowDs = planSummaryChartInstance.data.datasets.find(d => d._isCurrentTime);
    if (nowDs) {
        nowDs.data[0].x = nowMs;
        nowDs.data[1].x = nowMs;
    }

    // Update band border/bg colors based on current status
    // (altitude curve colors remain constant - only the band boxes change)
    for (const band of planSummaryTargetBands) {
        const status = _planBandStatus(band.entryId, band.endMs, currentTargetId);
        if (status !== band.status) {
            const colors     = _planBandColors(status);
            band.status      = status;
            band.borderColor = colors.border;
            band.bgColor     = colors.bg;
        }
    }

    planSummaryChartInstance.update('none');
}

// ────────────────────────────────────────────────────────────────────────────

function renderPlanMyNight(payload) {
    const container = document.getElementById('plan-my-night-display');
    if (!container) return;

    destroyPlanSummaryChart();
    DOMUtils.clear(container);

    if (!isPlanEditRole(payload.role)) {
        const alert = document.createElement('div');
        alert.className = 'alert alert-info';
        alert.textContent = i18n.t('plan_my_night.read_only_message');
        container.appendChild(alert);
        return;
    }

    const state = payload.state || 'none';
    const plan = payload.plan;
    const timeline = payload.timeline || {};

    const toolbar = document.createElement('div');
    toolbar.className = 'd-flex gap-2 mb-3 flex-wrap align-items-center';

    // Telescope selector - colored badge buttons (1 telescope: static badge; 2+: clickable)
    const telescopeItems = planTelescopeList.filter(p => p.telescope_id !== null);

    const _stateColor = (s) => s === 'current' ? 'success' : s === 'previous' ? 'warning' : 'secondary';

    const _makeBadgeBtn = (t, clickable) => {
        const color = _stateColor(t.state);
        const isSelected = t.telescope_id === currentPlanTelescopeId;
        const el = document.createElement(clickable ? 'button' : 'span');
        if (clickable) {
            el.type = 'button';
            el.className = `btn btn-sm ${isSelected ? `btn-${color}` : `btn-outline-${color}`} plan-telescope-badge`;
        } else {
            el.className = `badge bg-${color}${color === 'warning' ? ' text-dark' : ''} plan-telescope-badge`;
        }
        DOMUtils.append(el, DOMUtils.createIcon('bi bi-telescope icon-inline'), ` ${t.telescope_name || t.telescope_id}`);
        if (t.is_own === false) {
            const ownerLabel = t.owner_username
                ? i18n.t('equipment.shared_fov_suffix', { username: t.owner_username })
                : '';
            el.title = ownerLabel;
            const shareIcon = DOMUtils.createIcon('bi bi-share-fill plan-telescope-shared-icon');
            shareIcon.setAttribute('aria-label', ownerLabel);
            el.append(' ', shareIcon);
        }
        if (t.is_orphaned) {
            const orphanIcon = DOMUtils.createIcon('bi bi-exclamation-triangle-fill plan-telescope-orphan-icon');
            orphanIcon.setAttribute('aria-label', i18n.t('plan_my_night.orphaned_telescope'));
            el.append(' ', orphanIcon);
        }
        return el;
    };

    if (telescopeItems.length >= 2) {
        // Sort: active first (all), then owned, then shared - alphabetically within each group
        const sorted = [...telescopeItems].sort((a, b) => {
            const groupA = a.state === 'current' ? 0 : (a.is_own !== false ? 1 : 2);
            const groupB = b.state === 'current' ? 0 : (b.is_own !== false ? 1 : 2);
            if (groupA !== groupB) return groupA - groupB;
            return (a.telescope_name || '').localeCompare(b.telescope_name || '');
        });

        const badgeWrap = document.createElement('div');
        badgeWrap.className = 'd-flex flex-wrap gap-2 align-items-center me-2';

        sorted.forEach(t => {
            const btn = _makeBadgeBtn(t, true);
            btn.addEventListener('click', async () => {
                currentPlanTelescopeId = t.telescope_id || null;
                planMyNightStructureSnapshot = null;
                await loadPlanMyNight();
            });
            badgeWrap.appendChild(btn);
        });

        toolbar.appendChild(badgeWrap);
    } else if (telescopeItems.length === 1) {
        toolbar.appendChild(_makeBadgeBtn(telescopeItems[0], false));
    } else {
        const noTelescope = document.createElement('span');
        noTelescope.className = 'text-muted small me-2';
        noTelescope.textContent = i18n.t('plan_my_night.no_telescope_created');
        toolbar.appendChild(noTelescope);
    }

    const actionsRow = document.createElement('div');
    actionsRow.className = 'd-flex gap-2 mb-3 flex-wrap align-items-center';

    if (state !== 'none' && plan) {
        if (state === 'current') {
            const _triggerDownload = async (url) => {
                try {
                    const resp = await fetch(url, { credentials: 'same-origin' });
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                    const blob    = await resp.blob();
                    const blobUrl = URL.createObjectURL(blob);
                    const disposition = resp.headers.get('Content-Disposition') || '';
                    const match    = disposition.match(/filename[^;=\n]*=(['"]?)([^'";\n]+)\1/);
                    const filename = match ? match[2].trim() : '';
                    const a = document.createElement('a');
                    a.href     = blobUrl;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(blobUrl);
                } catch (err) {
                    console.error('Export download failed:', err);
                }
            };
            const exportCsvBtn = makePlanActionButton('plan_my_night.export_csv', 'btn btn-primary btn-sm', async () => {
                const lang = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : 'en';
                const tidParam = currentPlanTelescopeId ? `&telescope_id=${encodeURIComponent(currentPlanTelescopeId)}` : '';
                _triggerDownload(`/api/plan-my-night/export.csv?lang=${encodeURIComponent(lang)}${tidParam}`);
            });
            const exportPdfBtn = makePlanActionButton('plan_my_night.export_pdf', 'btn btn-success btn-sm', async () => {
                const lang = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : 'en';
                const tidParam = currentPlanTelescopeId ? `&telescope_id=${encodeURIComponent(currentPlanTelescopeId)}` : '';
                _triggerDownload(`/api/plan-my-night/export.pdf?lang=${encodeURIComponent(lang)}${tidParam}`);
            });
            actionsRow.appendChild(exportPdfBtn);
            actionsRow.appendChild(exportCsvBtn);
        }

        const clearButton = makePlanActionButton('plan_my_night.clear_this_plan', 'btn btn-danger btn-sm', async () => {
            const confirmClear = window.confirm(i18n.t('plan_my_night.confirm_clear'));
            if (!confirmClear) return;
            const tidParam = currentPlanTelescopeId ? `?telescope_id=${encodeURIComponent(currentPlanTelescopeId)}` : '';
            await fetchJSON(`/api/plan-my-night/clear${tidParam}`, { method: 'DELETE' });
            showMessage('success', i18n.t('plan_my_night.plan_cleared'));
            await loadPlanMyNight();
            await loadSkyTonightResultsTabs();
        });
        actionsRow.appendChild(clearButton);

        // Show "Clear all plans" only when there are 2+ telescopes
        if (planTelescopeList.filter(p => p.telescope_id !== null).length >= 2) {
            const clearAllButton = makePlanActionButton('plan_my_night.clear_all_plans', 'btn btn-outline-danger btn-sm', async () => {
                const confirmClearAll = window.confirm(i18n.t('plan_my_night.confirm_clear_all'));
                if (!confirmClearAll) return;
                await fetchJSON('/api/plan-my-night/clear-all', { method: 'DELETE' });
                currentPlanTelescopeId = null;
                planMyNightStructureSnapshot = null;
                showMessage('success', i18n.t('plan_my_night.all_plans_cleared'));
                await loadPlanMyNight();
                await loadSkyTonightResultsTabs();
            });
            actionsRow.appendChild(clearAllButton);
        }
    }

    if (toolbar.children.length > 0) {
        container.appendChild(toolbar);
    }
    if (actionsRow.children.length > 0) {
        container.appendChild(actionsRow);
    }

    if (state === 'none' || !plan) {
        const info = document.createElement('div');
        info.className = 'alert alert-info';
        info.textContent = i18n.t('plan_my_night.no_plan_message');
        container.appendChild(info);
        return;
    }

    if (state === 'previous') {
        const warning = document.createElement('div');
        warning.className = 'alert alert-warning';
        warning.textContent = i18n.t('plan_my_night.previous_plan_message');
        container.appendChild(warning);
    }

    if (timeline.is_inside_night && payload.current_banner) {
        const banner = document.createElement('div');
        banner.className = 'alert alert-success plan-current-banner';
        banner.textContent = i18n.t('plan_my_night.current_target_banner', {
            target: payload.current_banner.name || payload.current_banner.target_name || 'N/A'
        });
        container.appendChild(banner);
    }

    const summary = document.createElement('div');
    summary.id = 'plan-my-night-summary';
    summary.className = 'card mb-3';
    const summaryBody = document.createElement('div');
    summaryBody.className = 'card-body';

    const title = document.createElement('h5');
    title.className = 'card-title';
    title.textContent = i18n.t('plan_my_night.night_summary');

    // Show telescope name in the summary if one is selected
    const selectedTelescope = planTelescopeList.find(t => t.telescope_id === currentPlanTelescopeId);
    if (selectedTelescope && selectedTelescope.telescope_name) {
        const color = _stateColor(selectedTelescope.state);
        const telescopeBadge = document.createElement('span');
        telescopeBadge.className = `badge bg-${color}${color === 'warning' ? ' text-dark' : ''} ms-2 small`;
        DOMUtils.append(telescopeBadge, DOMUtils.createIcon('bi bi-telescope icon-inline'), ` ${selectedTelescope.telescope_name}`);
        if (selectedTelescope.is_own === false && selectedTelescope.owner_username) {
            telescopeBadge.appendChild(document.createTextNode(` · ${selectedTelescope.owner_username}`));
        }
        title.appendChild(telescopeBadge);
    }

    const nightRange = document.createElement('div');
    nightRange.className = 'text-muted';
    nightRange.textContent = `${formatDateTime(plan.night_start)} -> ${formatDateTime(plan.night_end)}`;

    summaryBody.appendChild(title);
    summaryBody.appendChild(nightRange);

    const entries = Array.isArray(plan.entries) ? plan.entries : [];
    const coverage = computePlannedCoverage(entries, plan);

    const coverageWrap = document.createElement('div');
    coverageWrap.className = 'mt-3';

    const coverageHeader = document.createElement('div');
    coverageHeader.className = 'd-flex align-items-center justify-content-between gap-2 mb-2 flex-wrap';

    const coverageLabel = document.createElement('div');
    coverageLabel.className = 'small text-muted';
    coverageLabel.textContent = i18n.t('plan_my_night.planned_fill_progress', {
        progress: coverage.fillPercent.toFixed(1),
        planned: formatMinutesAsHourMinute(coverage.plannedMinutes),
        total: formatMinutesAsHourMinute(coverage.nightMinutes)
    });

    const coverageStatus = getCoverageStatus(coverage.fillPercent);
    const coverageBadge = document.createElement('span');
    coverageBadge.className = `badge ${coverageStatus.className}`;
    coverageBadge.textContent = i18n.t(`plan_my_night.coverage_status_${coverageStatus.key}`);

    coverageHeader.appendChild(coverageLabel);
    coverageHeader.appendChild(coverageBadge);

    // Graph container - replaces both the stacked coverage bar and the timeline progress bar
    const graphContainer = document.createElement('div');
    graphContainer.id = 'plan-summary-graph-container';
    graphContainer.className = 'plan-summary-graph-wrap';

    coverageWrap.appendChild(coverageHeader);
    coverageWrap.appendChild(graphContainer);
    summaryBody.appendChild(coverageWrap);

    if (coverage.overflowMinutes > 0) {
        const overflowAlert = document.createElement('div');
        overflowAlert.className = 'alert alert-warning mt-2 mb-0 py-2';
        overflowAlert.textContent = i18n.t('plan_my_night.overflow_warning', {
            overflow: formatMinutesAsHourMinute(coverage.overflowMinutes)
        });
        summaryBody.appendChild(overflowAlert);
    }

    summary.appendChild(summaryBody);
    container.appendChild(summary);

    if (state !== 'previous') {
        buildPlanSummaryGraph(graphContainer, entries, plan, timeline)
            .catch(err => console.error('Plan summary graph error:', err));
    }

    if (!entries.length) {
        const empty = document.createElement('div');
        empty.className = 'alert alert-info';
        empty.textContent = i18n.t('plan_my_night.empty_plan_targets');
        container.appendChild(empty);
        return;
    }

    const timelineList = document.createElement('ul');
    timelineList.id = 'plan-my-night-timeline-list';
    timelineList.className = 'timeline-with-icons plan-my-night-timeline';

    const civilStartItem = document.createElement('li');
    civilStartItem.className = 'timeline-item mb-3 rounded p-2 ps-3 plan-boundary-item';
    const civilStartBadge = document.createElement('span');
    civilStartBadge.className = 'timeline-icon plan-time-badge plan-boundary-badge';
    civilStartBadge.textContent = formatTimeOnly(plan.night_start);
    civilStartItem.appendChild(civilStartBadge);
    const civilStartTitle = document.createElement('h5');
    civilStartTitle.className = 'fw-bold mb-1';
    civilStartTitle.textContent = i18n.t('plan_my_night.observing_session_start');
    civilStartItem.appendChild(civilStartTitle);
    const civilStartDescription = document.createElement('p');
    civilStartDescription.className = 'text-muted mb-0';
    civilStartDescription.textContent = formatDateTime(plan.night_start);
    civilStartItem.appendChild(civilStartDescription);
    timelineList.appendChild(civilStartItem);

    // ── Observation start delay input ────────────────────────────────────────
    if (state !== 'previous') {
        const delayItem = document.createElement('li');
        delayItem.className = 'timeline-item mb-3 rounded p-2 ps-3 plan-boundary-item plan-start-delay-item';
        delayItem.id = 'plan-start-delay-item';

        const delayBadge = document.createElement('span');
        delayBadge.className = 'timeline-icon plan-time-badge plan-boundary-badge';
        const startDelayMinutes = parseInt(plan.start_delay_minutes) || 0;
        const delayedStart = plan.night_start
            ? new Date(new Date(plan.night_start).getTime() + startDelayMinutes * 60000)
            : null;
        delayBadge.textContent = delayedStart ? formatTimeOnly(delayedStart.toISOString()) : '--:--';
        delayItem.appendChild(delayBadge);

        const delayRow = document.createElement('div');
        delayRow.className = 'd-flex align-items-center gap-2 flex-wrap';

        const delayLabel = document.createElement('label');
        delayLabel.className = 'form-label mb-0 small text-muted';
        delayLabel.textContent = i18n.t('plan_my_night.start_delay_label');

        const delayInput = document.createElement('input');
        delayInput.type = 'time';
        delayInput.className = 'form-control plan-duration-input';
        delayInput.id = 'plan-start-delay-input';
        delayInput.step = '60';
        delayInput.min = '00:00';
        delayInput.max = '23:59';
        delayInput.inputMode = 'numeric';
        delayInput.pattern = '^([01]\\d|2[0-3]):[0-5]\\d$';
        delayInput.placeholder = '00:00';
        delayInput.value = `${String(Math.floor(startDelayMinutes / 60)).padStart(2, '0')}:${String(startDelayMinutes % 60).padStart(2, '0')}`;

        const delaySaveBtn = makePlanActionButton('plan_my_night.save_duration', 'btn btn-secondary btn-sm', async () => {
            const normalized = normalizePlanDurationHHMM(delayInput.value);
            if (!normalized) { delayInput.reportValidity(); delayInput.focus(); return; }
            const [h, m] = normalized.split(':').map(Number);
            const minutes = h * 60 + m;
            await fetchJSON('/api/plan-my-night', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ start_delay_minutes: minutes, telescope_id: currentPlanTelescopeId })
            });
            await loadPlanMyNight();
        });

        delayRow.appendChild(delayLabel);
        delayRow.appendChild(delayInput);
        delayRow.appendChild(delaySaveBtn);
        delayItem.appendChild(delayRow);
        timelineList.appendChild(delayItem);
    }
    // ────────────────────────────────────────────────────────────────────────

    entries.forEach((entry, index) => {
        const item = document.createElement('li');
        if (entry.id !== undefined && entry.id !== null) {
            item.setAttribute('data-plan-entry-id', String(entry.id));
        }
        item.className = 'timeline-item mb-3 rounded p-2 ps-3 plan-target-item';
        if (entry.id && entry.id === timeline.current_target_id) {
            item.classList.add('plan-target-current');
        }
        if (entry.done) {
            item.classList.add('plan-target-done');
        }

        const startTimeText = entry.timeline_start ? formatTimeOnly(entry.timeline_start) : '--:--';
        const startBadge = document.createElement('span');
        startBadge.className = 'timeline-icon plan-time-badge';
        if (entry.id && entry.id === timeline.current_target_id) {
            startBadge.classList.add('plan-time-badge-current');
        }
        if (entry.done) {
            startBadge.classList.add('plan-time-badge-done');
        }
        startBadge.textContent = startTimeText;
        item.appendChild(startBadge);

        const top = document.createElement('div');
        top.className = 'd-flex justify-content-between align-items-start gap-2 flex-wrap';

        const head = document.createElement('div');
        const name = document.createElement('h5');
        name.className = 'fw-bold mb-1';
        const entryDisplayName = entry.name || entry.target_name || 'N/A';
        item.setAttribute('data-plan-target-name', entryDisplayName);
        name.textContent = `${index + 1}. ${entryDisplayName}`;

        const targetTypeLabel = getPlanTargetTypeDisplayName(entry.type);
        const constellationLabel = getPlanConstellationDisplayName(entry.constellation);
        const meta = document.createElement('p');
        meta.className = 'text-muted mb-1';
        meta.textContent = `${entry.catalogue || '-'} | ${targetTypeLabel} | ${constellationLabel}`;

        const timeRange = document.createElement('p');
        timeRange.className = 'text-muted fw-bold mb-0';
        timeRange.textContent = `${startTimeText} -> ${entry.timeline_end ? formatTimeOnly(entry.timeline_end) : '--:--'}`;

        head.appendChild(name);
        if (entry.difficulty && typeof createDifficultyBadgeNode === 'function') {
            const difficultyWrap = document.createElement('div');
            difficultyWrap.className = 'mb-1';
            difficultyWrap.appendChild(createDifficultyBadgeNode(entry.difficulty));
            head.appendChild(difficultyWrap);
        }
        head.appendChild(meta);
        head.appendChild(timeRange);

        const controls = document.createElement('div');
        controls.className = 'd-flex gap-1 flex-wrap';

        if (entry.in_astrodex) {
            const capturedBadge = document.createElement('span');
            capturedBadge.className = 'in-astrodex-badge';
            DOMUtils.append(capturedBadge, DOMUtils.createIcon('bi bi-check-circle-fill icon-inline'), tSkyTonightCompat('captured'));
            controls.appendChild(capturedBadge);
        } else {
            const addToAstrodexBtn = makePlanActionButton('plan_my_night.add_to_astrodex', 'btn btn-primary btn-sm', async () => {
                const tidParam = currentPlanTelescopeId ? `?telescope_id=${encodeURIComponent(currentPlanTelescopeId)}` : '';
                const response = await fetchJSON(`/api/plan-my-night/targets/${encodeURIComponent(entry.id)}/add-to-astrodex${tidParam}`, { method: 'POST' });
                if (response && response.reason === 'already_in_astrodex') {
                    showMessage('info', i18n.t('plan_my_night.already_in_astrodex'));
                } else {
                    showMessage('success', i18n.t('plan_my_night.added_to_astrodex'));
                }
                await loadPlanMyNight();
                await loadSkyTonightResultsTabs();
                await refreshAstrodexAfterPlanAction();
            });
            controls.appendChild(addToAstrodexBtn);
        }

        if (state !== 'previous') {
            const doneBtn = makePlanActionButton(
                entry.done ? 'plan_my_night.mark_undone' : 'plan_my_night.mark_done',
                entry.done ? 'btn btn-secondary btn-sm' : 'btn btn-success btn-sm',
                async () => {
                    await fetchJSON(`/api/plan-my-night/targets/${encodeURIComponent(entry.id)}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ done: !entry.done, telescope_id: currentPlanTelescopeId })
                    });
                    await loadPlanMyNight();
                }
            );
            controls.appendChild(doneBtn);

            const removeBtn = makePlanActionButton('plan_my_night.remove_target', 'btn btn-danger btn-sm', async () => {
                const tidParam = currentPlanTelescopeId ? `?telescope_id=${encodeURIComponent(currentPlanTelescopeId)}` : '';
                await fetchJSON(`/api/plan-my-night/targets/${encodeURIComponent(entry.id)}${tidParam}`, { method: 'DELETE' });
                await loadPlanMyNight();
                await loadSkyTonightResultsTabs();
            });
            controls.appendChild(removeBtn);
        }

        top.appendChild(head);
        top.appendChild(controls);
        item.appendChild(top);

        const details = document.createElement('div');
        details.className = 'mt-2 d-flex gap-2 align-items-center flex-wrap';

        const durationLabel = document.createElement('label');
        durationLabel.className = 'form-label mb-0 small';
        durationLabel.textContent = i18n.t('plan_my_night.photo_duration');

        const durationInput = document.createElement('input');
        durationInput.type = 'time';
        durationInput.className = 'form-control plan-duration-input';
        durationInput.step = '60';
        durationInput.min = '00:00';
        durationInput.max = '23:59';
        durationInput.inputMode = 'numeric';
        durationInput.pattern = '^([01]\\d|2[0-3]):[0-5]\\d$';
        durationInput.placeholder = 'hh:mm';
        durationInput.required = true;
        durationInput.value = normalizePlanDurationHHMM(entry.planned_duration) || '01:00';
        durationInput.disabled = state === 'previous';

        details.appendChild(durationLabel);
        details.appendChild(durationInput);

        if (state !== 'previous') {
            const durationSaveBtn = makePlanActionButton('plan_my_night.save_duration', 'btn btn-secondary btn-sm', async () => {
                const normalizedDuration = normalizePlanDurationHHMM(durationInput.value);
                if (!normalizedDuration) {
                    durationInput.reportValidity();
                    durationInput.focus();
                    return;
                }

                await fetchJSON(`/api/plan-my-night/targets/${encodeURIComponent(entry.id)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ planned_duration: normalizedDuration, telescope_id: currentPlanTelescopeId })
                });
                await loadPlanMyNight();
            });
            details.appendChild(durationSaveBtn);

            const moveUpBtn = makePlanIconActionButton('plan_my_night.move_up', 'btn btn-secondary btn-sm', 'bi bi-arrow-up', async () => {
                await fetchJSON(`/api/plan-my-night/targets/${encodeURIComponent(entry.id)}/reorder`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ new_index: index - 1, telescope_id: currentPlanTelescopeId })
                });
                movePlanTargetItemInDom(entry.id, -1);
                await loadPlanMyNight({
                    silent: true,
                    preferPatchOnly: true,
                    restoreFocus: { entryId: entry.id, action: 'move-up' }
                });
            });
            moveUpBtn.setAttribute('data-plan-action', 'move-up');
            moveUpBtn.disabled = index === 0;
            details.appendChild(moveUpBtn);

            const moveDownBtn = makePlanIconActionButton('plan_my_night.move_down', 'btn btn-secondary btn-sm', 'bi bi-arrow-down', async () => {
                await fetchJSON(`/api/plan-my-night/targets/${encodeURIComponent(entry.id)}/reorder`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ new_index: index + 1, telescope_id: currentPlanTelescopeId })
                });
                movePlanTargetItemInDom(entry.id, 1);
                await loadPlanMyNight({
                    silent: true,
                    preferPatchOnly: true,
                    restoreFocus: { entryId: entry.id, action: 'move-down' }
                });
            });
            moveDownBtn.setAttribute('data-plan-action', 'move-down');
            moveDownBtn.disabled = index === entries.length - 1;
            details.appendChild(moveDownBtn);
        }

        item.appendChild(details);

        const astroInfoValues = [];
        const rightAscensionLabel = tSkyTonightCompat('right_ascension');
        const declinationLabel = tSkyTonightCompat('declination');
        const magLabel = tSkyTonightCompat('table_mag');
        const sizeLabel = tSkyTonightCompat('table_size');
        const fotoLabel = tSkyTonightCompat('table_foto');

        if (entry.ra) {
            astroInfoValues.push(`${rightAscensionLabel}: ${entry.ra}`);
        }
        if (entry.dec) {
            astroInfoValues.push(`${declinationLabel}: ${entry.dec}`);
        }

        const magnitudeValue = formatPlanNumericValue(entry.mag, 2);
        if (magnitudeValue !== null) {
            astroInfoValues.push(`${magLabel}: ${magnitudeValue}`);
        }

        const sizeValue = formatPlanNumericValue(entry.size, 2);
        if (sizeValue !== null) {
            astroInfoValues.push(`${sizeLabel}: ${sizeValue}'`);
        }

        const fotoValue = formatPlanNumericValue(entry.foto, 2);
        if (fotoValue !== null) {
            astroInfoValues.push(`${fotoLabel}: ${fotoValue}`);
        }

        if (astroInfoValues.length) {
            const astroInfo = document.createElement('p');
            astroInfo.className = 'text-muted mb-1 mt-2';
            astroInfo.textContent = astroInfoValues.join(' | ');
            item.appendChild(astroInfo);
        }

        const hasAlttime = entry.alttime_file;
        if (hasAlttime && state !== 'previous' && typeof showAlttimePopup === 'function') {
            const alttimeButton = document.createElement('button');
            alttimeButton.type = 'button';
            alttimeButton.className = 'btn btn-info btn-sm mt-1';
            DOMUtils.append(alttimeButton, DOMUtils.createIcon('bi bi-graph-up-arrow icon-inline'), i18n.t('settings.feature_alttime'));
            alttimeButton.addEventListener('click', () => {
                const targetTitle = `${entry.name || entry.target_name || 'Target'} - ${i18n.t('skytonight.altitude_time_title') || 'Altitude vs Time'}`;
                showAlttimePopup(targetTitle, entry.alttime_file);
            });
            item.appendChild(alttimeButton);
        }

        timelineList.appendChild(item);
    });

    const civilEndItem = document.createElement('li');
    civilEndItem.className = 'timeline-item mb-0 rounded p-2 ps-3 plan-boundary-item';
    const civilEndBadge = document.createElement('span');
    civilEndBadge.className = 'timeline-icon plan-time-badge plan-boundary-badge';
    civilEndBadge.textContent = formatTimeOnly(plan.night_end);
    civilEndItem.appendChild(civilEndBadge);
    const civilEndTitle = document.createElement('h5');
    civilEndTitle.className = 'fw-bold mb-1';
    civilEndTitle.textContent = i18n.t('plan_my_night.observing_session_end');
    civilEndItem.appendChild(civilEndTitle);
    const civilEndDescription = document.createElement('p');
    civilEndDescription.className = 'text-muted mb-0';
    civilEndDescription.textContent = formatDateTime(plan.night_end);
    civilEndItem.appendChild(civilEndDescription);
    timelineList.appendChild(civilEndItem);

    container.appendChild(timelineList);
}

window.addEventListener('beforeunload', () => {
    clearPlanPollTimer();
    destroyPlanSummaryChart();
});

function _checkPlanNotifications(payload) {
    if (typeof notificationManager === 'undefined') return;
    const plan     = payload?.plan;
    const timeline = payload?.timeline || {};
    if (!plan) return;

    const now    = Date.now();
    const entries = Array.isArray(plan.entries) ? plan.entries : [];

    // N1 - session starts soon (only before the night begins)
    if (notificationManager.isTriggerEnabled('N1') && !timeline.is_inside_night) {
        const nightStart = plan.night_start ? new Date(plan.night_start).getTime() : null;
        if (nightStart) {
            const msUntil = nightStart - now;
            const leadMs  = notificationManager.getLeadMinutes('N1') * 60 * 1000;
            if (msUntil > 0 && msUntil <= leadMs &&
                !notificationManager.wasRecentlyNotified('N1', 2 * 60 * 60 * 1000)) {
                const minutes = Math.round(msUntil / 60000);
                notificationManager.notify(
                    'N1',
                    i18n.t('notifications.n1_title'),
                    i18n.t('notifications.n1_body', { minutes }),
                    { url: '#astrodex/plan-my-night' }
                );
            }
        }
    }

    // N2 - next target starts soon (only while inside the night)
    if (notificationManager.isTriggerEnabled('N2') && timeline.is_inside_night) {
        const leadMs = notificationManager.getLeadMinutes('N2') * 60 * 1000;
        for (const entry of entries) {
            if (entry.done) continue;
            const start = entry.timeline_start ? new Date(entry.timeline_start).getTime() : null;
            if (!start || start <= now) continue;
            if (start - now > leadMs) break; // entries are chronological, no need to keep looking
            const entryId = entry.id || entry.target_name || entry.name;
            if (_planN2Notified.has(entryId)) break;
            _planN2Notified.add(entryId);
            const minutes = Math.round((start - now) / 60000);
            const name    = entry.name || entry.target_name || '?';
            notificationManager.notify(
                'N2',
                i18n.t('notifications.n2_title'),
                i18n.t('notifications.n2_body', { name, minutes }),
                { url: '#astrodex/plan-my-night' }
            );
            break; // one at a time
        }
    }
}
