// Plan My Night frontend module

let planMyNightPollTimer = null;
let planMyNightStructureSnapshot = null;
let currentPlanTelescopeId = null;   // null = no/default telescope
let planTelescopeList = [];          // array from /api/plan-my-night/list

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
    const progressLabel = document.getElementById('plan-my-night-progress-label');
    const progressBar = document.getElementById('plan-my-night-progress-bar');
    const timelineList = document.getElementById('plan-my-night-timeline-list');
    if (!summaryElement || !progressLabel || !progressBar || !timelineList) {
        return false;
    }

    if (!updatePlanCurrentBanner(container, payload, summaryElement)) {
        return false;
    }

    progressLabel.textContent = i18n.t('plan_my_night.timeline_progress', {
        progress: (timeline.progress_percent || 0).toFixed(1)
    });
    progressBar.style.width = `${Math.max(0, Math.min(100, timeline.progress_percent || 0))}%`;
    progressBar.setAttribute('aria-valuenow', String(Math.round(timeline.progress_percent || 0)));

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

        // Auto-select the first telescope if none selected yet and there are telescopes
        if (currentPlanTelescopeId === null && telescopeItems > 0) {
            const firstTelescope = planTelescopeList.find(p => p.telescope_id !== null);
            if (firstTelescope) {
                currentPlanTelescopeId = firstTelescope.telescope_id;
            }
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
        }

        restorePlanMyNightViewport(viewportState, container);
        restorePlanMyNightFocus(restoreFocus);

        planMyNightStructureSnapshot = nextStructureSnapshot;

        // Keep timeline/current target fresh while tab remains visible.
        planMyNightPollTimer = setTimeout(() => {
            const tab = document.getElementById('plan-my-night-subtab');
            if (tab && tab.classList.contains('active') && !document.hidden) {
                loadPlanMyNight({ silent: true });
            }
        }, 60000);
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
    // Icon if pdf or csv to add with text
    let ico = '';
    if (labelKey === 'plan_my_night.export_pdf') {
        ico = '<i class="bi bi-filetype-pdf"></i> ';
    } else if (labelKey === 'plan_my_night.export_csv') {
        ico = '<i class="bi bi-filetype-csv"></i> ';
    } else if (labelKey === 'plan_my_night.clear_this_plan' || labelKey === 'plan_my_night.clear_plan' || labelKey === 'plan_my_night.clear_all_plans') {
        ico = '<i class="bi bi-trash"></i> ';
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.innerHTML = ico + i18n.t(labelKey);
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

    // Subtract start delay — the usable observing window is shorter
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

function getPlanCoverageSegmentColor(index) {
    const palette = [
        'bg-primary',
        'bg-info',
        'bg-success',
        'bg-warning',
        'bg-danger',
        'bg-secondary',
    ];
    return palette[index % palette.length];
}

function buildPlanCoverageSegments(entries, nightMinutes) {
    const safeNightMinutes = Math.max(0, Number(nightMinutes) || 0);
    const sourceEntries = Array.isArray(entries) ? entries : [];

    if (!sourceEntries.length || safeNightMinutes <= 0) {
        return [];
    }

    let consumedMinutes = 0;
    const segments = [];

    sourceEntries.forEach((entry, index) => {
        const entryMinutes = Math.max(0, getPlanEntryMinutes(entry));
        if (entryMinutes <= 0) {
            return;
        }

        const remainingNightMinutes = Math.max(0, safeNightMinutes - consumedMinutes);
        if (remainingNightMinutes <= 0) {
            return;
        }

        const visibleMinutes = Math.min(entryMinutes, remainingNightMinutes);
        const widthPercent = (visibleMinutes / safeNightMinutes) * 100;
        if (widthPercent <= 0) {
            return;
        }

        consumedMinutes += visibleMinutes;

        segments.push({
            widthPercent,
            targetNumber: index + 1,
            label: entry?.name || entry?.target_name || `Target ${index + 1}`,
            minutes: entryMinutes,
            colorClass: getPlanCoverageSegmentColor(index),
        });
    });

    return segments;
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

function renderPlanMyNight(payload) {
    const container = document.getElementById('plan-my-night-display');
    if (!container) return;

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

    // Telescope selector (shown when 2+ telescopes exist)
    const telescopeItems = planTelescopeList.filter(p => p.telescope_id !== null);
    if (telescopeItems.length >= 2) {
        const selectorWrap = document.createElement('div');
        selectorWrap.className = 'd-flex align-items-center gap-2 me-2';

        const selectorLabel = document.createElement('label');
        selectorLabel.className = 'form-label mb-0 small fw-semibold';
        selectorLabel.textContent = i18n.t('plan_my_night.telescope_label');
        selectorLabel.setAttribute('for', 'plan-telescope-selector');

        const selector = document.createElement('select');
        selector.id = 'plan-telescope-selector';
        selector.className = 'form-select form-select-sm';
        selector.style.maxWidth = '220px';

        telescopeItems.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.telescope_id;
            opt.textContent = t.telescope_name || t.telescope_id;
            const stateLabel = t.state !== 'none'
                ? ` (${i18n.t(`plan_my_night.plan_status_${t.state}`, {defaultValue: t.state})})`
                : ` (${i18n.t('plan_my_night.plan_status_none', {defaultValue: 'no plan'})})`;
            opt.textContent += stateLabel;
            if (t.telescope_id === currentPlanTelescopeId) {
                opt.selected = true;
            }
            selector.appendChild(opt);
        });

        selector.addEventListener('change', async () => {
            currentPlanTelescopeId = selector.value || null;
            planMyNightStructureSnapshot = null;
            await loadPlanMyNight();
        });

        selectorWrap.appendChild(selectorLabel);
        selectorWrap.appendChild(selector);
        toolbar.appendChild(selectorWrap);
    } else if (telescopeItems.length === 1) {
        // Show telescope name as plain text
        const telescopeName = document.createElement('span');
        telescopeName.className = 'badge bg-secondary me-2';
        telescopeName.innerHTML = `<i class="bi bi-telescope icon-inline" aria-hidden="true"></i> ${telescopeItems[0].telescope_name || i18n.t('plan_my_night.no_telescope_created')}`;
        toolbar.appendChild(telescopeName);
    } else {
        // No telescopes created
        const noTelescope = document.createElement('span');
        noTelescope.className = 'text-muted small me-2';
        noTelescope.textContent = i18n.t('plan_my_night.no_telescope_created');
        toolbar.appendChild(noTelescope);
    }

    if (state !== 'none' && plan) {
        if (state === 'current') {
            const exportCsvBtn = makePlanActionButton('plan_my_night.export_csv', 'btn btn-primary btn-sm', async () => {
                const lang = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : 'en';
                const tidParam = currentPlanTelescopeId ? `&telescope_id=${encodeURIComponent(currentPlanTelescopeId)}` : '';
                window.location.href = `/api/plan-my-night/export.csv?lang=${encodeURIComponent(lang)}${tidParam}`;
            });
            const exportPdfBtn = makePlanActionButton('plan_my_night.export_pdf', 'btn btn-success btn-sm', async () => {
                const lang = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : 'en';
                const tidParam = currentPlanTelescopeId ? `&telescope_id=${encodeURIComponent(currentPlanTelescopeId)}` : '';
                window.location.href = `/api/plan-my-night/export.pdf?lang=${encodeURIComponent(lang)}${tidParam}`;
            });
            toolbar.appendChild(exportPdfBtn);
            toolbar.appendChild(exportCsvBtn);
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
        toolbar.appendChild(clearButton);

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
            toolbar.appendChild(clearAllButton);
        }
    }

    if (toolbar.children.length > 0) {
        container.appendChild(toolbar);
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
        const telescopeBadge = document.createElement('span');
        telescopeBadge.className = 'badge bg-secondary ms-2 small';
        telescopeBadge.innerHTML = `<i class="bi bi-telescope icon-inline" aria-hidden="true"></i> ${selectedTelescope.telescope_name}`;
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
    coverageHeader.className = 'd-flex align-items-center justify-content-between gap-2 mb-1 flex-wrap';

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

    const coverageProgress = document.createElement('div');
    coverageProgress.className = 'progress-stacked plan-coverage-progress';

    const coverageSegments = buildPlanCoverageSegments(entries, coverage.nightMinutes);
    if (coverageSegments.length) {
        coverageSegments.forEach(segment => {
            const segmentWrap = document.createElement('div');
            segmentWrap.className = 'progress';
            segmentWrap.style.width = `${segment.widthPercent.toFixed(2)}%`;

            const segmentBar = document.createElement('div');
            segmentBar.className = `progress-bar ${segment.colorClass}`;
            segmentBar.setAttribute('role', 'progressbar');
            segmentBar.setAttribute('aria-valuemin', '0');
            segmentBar.setAttribute('aria-valuemax', '100');
            segmentBar.setAttribute('aria-valuenow', String(Math.round(segment.widthPercent)));
            segmentBar.setAttribute('aria-label', `${segment.label} (${formatMinutesAsHourMinute(segment.minutes)})`);
            segmentBar.title = `${segment.label} (${formatMinutesAsHourMinute(segment.minutes)})`;
            segmentBar.textContent = String(segment.targetNumber);

            segmentWrap.appendChild(segmentBar);
            coverageProgress.appendChild(segmentWrap);
        });
    } else {
        const coverageProgressBar = document.createElement('div');
        coverageProgressBar.className = `progress-bar ${coverage.fillPercent > 100 ? 'bg-danger' : 'bg-success'}`;
        coverageProgressBar.style.width = `${Math.max(0, Math.min(100, coverage.fillPercent))}%`;
        coverageProgressBar.setAttribute('role', 'progressbar');
        coverageProgressBar.setAttribute('aria-valuemin', '0');
        coverageProgressBar.setAttribute('aria-valuemax', '100');
        coverageProgressBar.setAttribute('aria-valuenow', String(Math.round(Math.min(100, coverage.fillPercent))));
        coverageProgress.appendChild(coverageProgressBar);
    }

    coverageWrap.appendChild(coverageHeader);
    coverageWrap.appendChild(coverageProgress);
    summaryBody.appendChild(coverageWrap);

    if (coverage.overflowMinutes > 0) {
        const overflowAlert = document.createElement('div');
        overflowAlert.className = 'alert alert-warning mt-2 mb-0 py-2';
        overflowAlert.textContent = i18n.t('plan_my_night.overflow_warning', {
            overflow: formatMinutesAsHourMinute(coverage.overflowMinutes)
        });
        summaryBody.appendChild(overflowAlert);
    }

    const timelineWrap = document.createElement('div');
    timelineWrap.className = 'mt-3';

    const progressLabel = document.createElement('div');
    progressLabel.id = 'plan-my-night-progress-label';
    progressLabel.className = 'small text-muted mb-1';
    progressLabel.textContent = i18n.t('plan_my_night.timeline_progress', {
        progress: (timeline.progress_percent || 0).toFixed(1)
    });

    const progress = document.createElement('div');
    progress.className = 'progress';
    const progressBar = document.createElement('div');
    progressBar.id = 'plan-my-night-progress-bar';
    progressBar.className = 'progress-bar bg-info';
    progressBar.style.width = `${Math.max(0, Math.min(100, timeline.progress_percent || 0))}%`;
    progressBar.setAttribute('role', 'progressbar');
    progressBar.setAttribute('aria-valuemin', '0');
    progressBar.setAttribute('aria-valuemax', '100');
    progressBar.setAttribute('aria-valuenow', String(Math.round(timeline.progress_percent || 0)));
    progress.appendChild(progressBar);

    timelineWrap.appendChild(progressLabel);
    timelineWrap.appendChild(progress);

    summaryBody.appendChild(timelineWrap);
    summary.appendChild(summaryBody);
    container.appendChild(summary);

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
        head.appendChild(meta);
        head.appendChild(timeRange);

        const controls = document.createElement('div');
        controls.className = 'd-flex gap-1 flex-wrap';

        if (entry.in_astrodex) {
            const capturedBadge = document.createElement('span');
            capturedBadge.className = 'in-astrodex-badge';
            capturedBadge.innerHTML = `<i class="bi bi-check-circle-fill icon-inline" aria-hidden="true"></i>${tSkyTonightCompat('captured')}`;
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
        if (hasAlttime && typeof showAlttimePopup === 'function') {
            const alttimeButton = document.createElement('button');
            alttimeButton.type = 'button';
            alttimeButton.className = 'btn btn-info btn-sm mt-1';
            alttimeButton.innerHTML = `<i class="bi bi-graph-up-arrow icon-inline" aria-hidden="true"></i>${i18n.t('settings.feature_alttime')}`;
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
});
