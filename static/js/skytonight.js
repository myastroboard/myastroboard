// SkyTonight Results Display and Management

let catalogueResults = {};
let currentCatalogueTab = 'SkyTonight'; // Always 'SkyTonight' in the new single-section layout
let skytonightDisplayAstrodexCache = null;
let skytonightDisplayAstrodexPromise = null;
let _skytCurrentSection = 'plot'; // Active section: 'plot' | 'report' | 'bodies' | 'comets' | 'log'
let _skytSectionCache = {};       // Cached response per section key
const SKYT_PAGE_SIZE = 100;       // Rows rendered per page in the DSO/bodies/comets tables
let _skytCurrentPages = {};       // sectionKey -> current page number
let _skytMoreRowData = {};        // moreKey -> { type, moreFields, row } for lazy popup
let _skytFilteredData = {};       // sectionKey -> filtered row array (null = no active filter)
let _skytFilterState = {};        // sectionKey -> saved filter values for cross-page persistence
let _skytHasCombinationsCache = null;
let _skytHasCombinationsPromise = null;
const _skytListenerTimers = {};  // catalogue+type -> pending setTimeout id (cancelled on re-render)

const _plotlyLoadState = { promise: null };

/** Lazily load the Plotly library (only needed for the SkyTonight sky map) so it isn't fetched on every page load. */
function _ensurePlotlyLoaded() {
    return ensureVendorScriptLoaded(
        () => typeof Plotly !== 'undefined',
        '/static/vendor/plotly/plotly-3.5.1.min.js?v=3.5.1',
        null,
        _plotlyLoadState,
        'Plotly'
    );
}

/**
 * Show a modal to pick a telescope for "Add to Plan My Night".
 * Returns a Promise that resolves with {telescope_id, telescope_name} or null if cancelled.
 */
async function showPlanTelescopePickerModal(telescopeItems, row, activeLocationId) {
    const existingModal = document.getElementById('plan-telescope-picker-modal');
    if (existingModal) existingModal.remove();

    // Fetch ratings for the target row (non-blocking - render immediately, fill in ratings after)
    let ratingsById = {};
    if (row) {
        try {
            // Recommendations are combination-based; several combinations can share the same
            // telescope, so this picker (still telescope-keyed until it becomes a combination
            // picker) shows the best rating among combinations using that telescope.
            const recoResp = await _skytFetchCombinationRecommendations(row);
            if (recoResp && Array.isArray(recoResp.recommendations)) {
                recoResp.recommendations.forEach(item => {
                    if (!item.telescope_id) return;
                    const rating = parseInt(item.rating_1_to_5, 10) || 1;
                    ratingsById[item.telescope_id] = Math.max(ratingsById[item.telescope_id] || 0, rating);
                });
            }
        } catch (_) { /* ratings optional */ }
    }

    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.id = 'plan-telescope-picker-modal';
        overlay.className = 'modal fade show d-block';
        overlay.setAttribute('tabindex', '-1');
        overlay.style.backgroundColor = 'rgba(0,0,0,0.5)';

        const dialog = document.createElement('div');
        dialog.className = 'modal-dialog modal-dialog-centered';

        const content = document.createElement('div');
        content.className = 'modal-content';

        const header = document.createElement('div');
        header.className = 'modal-header';
        const headerTitle = document.createElement('h5');
        headerTitle.className = 'modal-title';
        headerTitle.textContent = i18n.t('plan_my_night.select_telescope_for_plan');
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'btn-close';
        closeBtn.setAttribute('aria-label', i18n.t('common.close') || 'Close');
        closeBtn.addEventListener('click', () => { overlay.remove(); resolve(null); });
        header.appendChild(headerTitle);
        header.appendChild(closeBtn);

        const body = document.createElement('div');
        body.className = 'modal-body';

        // Solid background wrapper (fixes gradient-on-text readability), same treatment as the setup wizard
        const bodyContent = document.createElement('div');
        bodyContent.className = 'bg-sub-container rounded p-3';
        body.appendChild(bodyContent);

        const hasRatings = Object.keys(ratingsById).length > 0;

        // Exclude orphaned plans from the picker (telescope no longer accessible)
        const ownItems = telescopeItems.filter(t => t.is_own !== false && !t.is_orphaned);
        const sharedItems = telescopeItems.filter(t => t.is_own === false && !t.is_orphaned);

        const appendTelescopeBtn = (t) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-telescope-pick w-100 mb-2 text-start d-flex align-items-center gap-2';

            const stateBadgeEl = document.createElement('span');
            stateBadgeEl.className = t.state !== 'none'
                ? `badge bg-${t.state === 'current' ? 'success' : 'warning'}`
                : 'badge bg-secondary';
            stateBadgeEl.textContent = t.state !== 'none'
                ? i18n.t(`plan_my_night.plan_status_${t.state}`, { defaultValue: t.state })
                : i18n.t('plan_my_night.plan_status_none', { defaultValue: 'no plan' });

            const nameSpan = document.createElement('span');
            nameSpan.className = 'flex-grow-1';
            nameSpan.appendChild(document.createTextNode(t.telescope_name || t.telescope_id));
            if (t.owner_username) {
                const _sharedEl = document.createElement('span');
                _sharedEl.className = 'badge bg-info text-dark';
                _sharedEl.style.fontSize = '0.75em';
                _sharedEl.textContent = i18n.t('equipment.shared_fov_suffix', { username: t.owner_username });
                nameSpan.append(' ');
                nameSpan.appendChild(_sharedEl);
            }
            nameSpan.append(' ');
            nameSpan.appendChild(stateBadgeEl);

            // A plan pins its location at creation (v1.2) - adding a target from a different
            // active location onto an already-current plan would silently mix locations on the
            // same telescope's plan, so that combination is disabled here rather than allowed.
            const hasLocationConflict = t.state === 'current' && t.location_id
                && activeLocationId && t.location_id !== activeLocationId;
            if (hasLocationConflict) {
                const conflictEl = document.createElement('div');
                conflictEl.className = 'small text-muted w-100 mt-1';
                DOMUtils.append(
                    conflictEl,
                    DOMUtils.createIcon('bi bi-geo-alt icon-inline'),
                    ` ${i18n.t('plan_my_night.telescope_location_in_use', { location: t.location_name || '?' })}`
                );
                nameSpan.appendChild(conflictEl);
            }

            const rating = ratingsById[t.telescope_id];
            DOMUtils.append(btn, DOMUtils.createIcon('bi bi-telescope icon-inline flex-shrink-0'), nameSpan);
            if (rating) {
                const ratingEl = document.createElement('span');
                ratingEl.className = 'ms-auto text-warning text-nowrap';
                ratingEl.title = `${String(rating)}/5`;
                ratingEl.setAttribute('aria-label', `${String(rating)} stars`);
                ratingEl.textContent = _skytStarsFromRating(rating);
                btn.appendChild(ratingEl);
            } else if (hasRatings) {
                const ratingEl = document.createElement('span');
                ratingEl.className = 'ms-auto text-muted text-nowrap';
                ratingEl.setAttribute('aria-hidden', 'true');
                ratingEl.textContent = '—';
                btn.appendChild(ratingEl);
            }
            if (hasLocationConflict) {
                btn.disabled = true;
                btn.classList.add('disabled');
                btn.title = i18n.t('plan_my_night.telescope_location_in_use', { location: t.location_name || '?' });
            } else {
                btn.addEventListener('click', () => {
                    overlay.remove();
                    resolve({ telescope_id: t.telescope_id, telescope_name: t.telescope_name });
                });
            }
            bodyContent.appendChild(btn);
        };

        ownItems.forEach(appendTelescopeBtn);

        if (sharedItems.length > 0) {
            const sep = document.createElement('hr');
            sep.className = 'my-2';
            bodyContent.appendChild(sep);
            const sepLabel = document.createElement('div');
            sepLabel.className = 'text-muted small px-1 mb-1';
            sepLabel.textContent = i18n.t('equipment.shared_by_others_section');
            bodyContent.appendChild(sepLabel);
            sharedItems.forEach(appendTelescopeBtn);
        }

        const footer = document.createElement('div');
        footer.className = 'modal-footer';
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn btn-secondary btn-sm';
        cancelBtn.textContent = i18n.t('common.cancel') || 'Cancel';
        cancelBtn.addEventListener('click', () => { overlay.remove(); resolve(null); });
        footer.appendChild(cancelBtn);

        content.appendChild(header);
        content.appendChild(body);
        content.appendChild(footer);
        dialog.appendChild(content);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Close on backdrop click
        overlay.addEventListener('click', (ev) => {
            if (ev.target === overlay) { overlay.remove(); resolve(null); }
        });
    });
}

/**
 * Resolve which telescope's plan an "Add to Plan My Night" action should target:
 * shows a picker when the user owns/shares multiple telescopes, auto-picks the
 * only one when there's exactly one, or leaves it unset (default/no-telescope
 * plan) when there are none. Returns null if the user cancelled the picker.
 */
async function _resolvePlanTelescopeSelection(itemForRatings) {
    let telescopeId = null;
    let telescopeName = null;
    try {
        const listPayload = await fetchJSON('/api/plan-my-night/list');
        const telescopeItems = (listPayload?.plans || []).filter(p => p.telescope_id !== null);

        let activeLocationId = null;
        if (typeof fetchMyLocations === 'function') {
            try {
                const myLocations = await fetchMyLocations();
                activeLocationId = myLocations?.active_location_id || null;
            } catch (_) { /* location check optional - picker just won't grey anything out */ }
        }

        // A single telescope normally auto-picks silently, but if its plan is already
        // pinned to a different location than the one active now, show the picker instead
        // so the (disabled, labelled) conflict is visible rather than silently mixing
        // locations on that telescope's plan - see showPlanTelescopePickerModal.
        const soleConflicts = telescopeItems.length === 1
            && telescopeItems[0].state === 'current'
            && telescopeItems[0].location_id
            && activeLocationId
            && telescopeItems[0].location_id !== activeLocationId;

        if (telescopeItems.length >= 2 || soleConflicts) {
            const picked = await showPlanTelescopePickerModal(telescopeItems, itemForRatings, activeLocationId);
            if (!picked) return null; // user cancelled
            telescopeId = picked.telescope_id;
            telescopeName = picked.telescope_name;
        } else if (telescopeItems.length === 1) {
            telescopeId = telescopeItems[0].telescope_id;
            telescopeName = telescopeItems[0].telescope_name;
        }
    } catch (_) {
        // If list fetch fails, proceed without telescope
    }
    return { telescope_id: telescopeId, telescope_name: telescopeName };
}

function _translatedConstellation(value) {
    if (!value) return value;
    const key = 'constellations.' + strToTranslateKey(value);
    return i18n.has(key) ? i18n.t(key) : value;
}

async function _skytUserHasCombinations() {
    if (_skytHasCombinationsCache !== null) {
        return _skytHasCombinationsCache;
    }
    if (_skytHasCombinationsPromise) {
        return _skytHasCombinationsPromise;
    }

    _skytHasCombinationsPromise = (async () => {
        try {
            const payload = await fetchJSON('/api/equipment/combinations');
            const hasCombinations = (Array.isArray(payload?.data) && payload.data.length > 0) ||
                (Array.isArray(payload?.shared_from_others) && payload.shared_from_others.length > 0);
            _skytHasCombinationsCache = hasCombinations;
            return hasCombinations;
        } catch (_err) {
            _skytHasCombinationsCache = false;
            return false;
        } finally {
            _skytHasCombinationsPromise = null;
        }
    })();

    return _skytHasCombinationsPromise;
}

function _skytTargetPayloadFromRow(row) {
    return {
        id: row['id'] || '',
        target_name: row['target name'] || '',
        type: row['type'] || '',
        size: row['size'] !== undefined ? row['size'] : null,
        mag: row['mag'] !== undefined ? row['mag'] : (row['visual magnitude'] !== undefined ? row['visual magnitude'] : null)
    };
}

function _skytStarsFromRating(ratingValue) {
    const safeRating = Math.min(5, Math.max(1, parseInt(ratingValue, 10) || 1));
    return `${'★'.repeat(safeRating)}${'☆'.repeat(5 - safeRating)}`;
}

function _skytBuildCombinationRecommendationNote(item) {
    const parts = [];

    parts.push(i18n.t('skytonight.combination_reco_note_focal', {
        focal: item.effective_focal_length,
        ideal_min: item.ideal_focal_min,
        ideal_max: item.ideal_focal_max,
    }));

    parts.push(i18n.t('skytonight.combination_reco_note_aperture', {
        aperture: item.aperture_mm,
        f_ratio: item.effective_focal_ratio,
    }));

    if (item.image_scale_arcsec_per_px !== null && item.image_scale_arcsec_per_px !== undefined) {
        parts.push(i18n.t('skytonight.combination_reco_note_sampling', {
            scale: item.image_scale_arcsec_per_px,
            unit: i18n.t('units.arcsec_per_pixel'),
            classification: item.sampling_classification,
        }));
    }

    if (item.target_magnitude !== null && item.target_magnitude !== undefined) {
        parts.push(i18n.t('skytonight.combination_reco_note_target_mag', {
            mag: item.target_magnitude,
        }));
    }

    if (item.target_size_arcmin !== null && item.target_size_arcmin !== undefined) {
        parts.push(i18n.t('skytonight.combination_reco_note_target_size', {
            size: item.target_size_arcmin,
        }));
    }

    return parts.join(' ');
}

async function _skytFetchCombinationRecommendations(row) {
    const payload = _skytTargetPayloadFromRow(row);
    try {
        return await fetchJSON('/api/skytonight/combination-recommendations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    } catch (error) {
        console.error('Error loading combination recommendations:', error);
        return null;
    }
}

function _skytBuildCombinationRecommendationsHtml(response, row) {
    if (!response || !response.has_combinations) {
        return null;
    }

    const targetTitle = response.target?.target_name || row['target name'] || row['id'] || '';
    const recommendations = Array.isArray(response.recommendations) ? response.recommendations : [];

    const wrapper = document.createElement('div');
    wrapper.className = 'mt-3 pt-3 border-top';

    const h6 = document.createElement('h6');
    h6.className = 'mb-2';
    h6.textContent = tSkyTonightCompat('combination_reco_title');
    wrapper.appendChild(h6);

    const titleDiv = document.createElement('div');
    titleDiv.className = 'small text-muted mb-2';
    titleDiv.textContent = targetTitle;
    wrapper.appendChild(titleDiv);

    if (recommendations.length === 0) {
        const p = document.createElement('p');
        p.className = 'text-muted mb-0';
        p.textContent = tSkyTonightCompat('combination_reco_no_result');
        wrapper.appendChild(p);
        return wrapper;
    }

    const tableResponsive = document.createElement('div');
    tableResponsive.className = 'table-responsive';
    const table = document.createElement('table');
    table.className = 'table table-striped table-sm align-middle mb-0';
    const thead = document.createElement('thead');
    const trh = document.createElement('tr');
    [
        { text: tSkyTonightCompat('combination_reco_table_combination'), cls: '' },
        { text: tSkyTonightCompat('combination_reco_table_rating'), cls: 'text-center' },
        { text: tSkyTonightCompat('combination_reco_table_note'), cls: '' }
    ].forEach(({ text, cls }) => {
        const th = document.createElement('th');
        if (cls) th.className = cls;
        th.textContent = text;
        trh.appendChild(th);
    });
    thead.appendChild(trh);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    const sorted = [...recommendations].sort((a, b) => {
        const aOwned = !a.owner_username ? 0 : 1;
        const bOwned = !b.owner_username ? 0 : 1;
        if (aOwned !== bOwned) return aOwned - bOwned;
        return (b.rating_1_to_5 || 0) - (a.rating_1_to_5 || 0);
    });

    sorted.forEach((item) => {
        const rating = parseInt(item.rating_1_to_5, 10) || 1;
        const noteText = _skytBuildCombinationRecommendationNote(item);
        const tr = document.createElement('tr');

        const tdName = document.createElement('td');
        const nameLine = document.createElement('div');
        nameLine.textContent = item.combination_name || '';
        tdName.appendChild(nameLine);

        const compositionParts = [];
        if (item.telescope_name) compositionParts.push(item.telescope_name);
        if (item.camera_name) {
            compositionParts.push(
                item.is_camera_only
                    ? `${item.camera_name} ${tSkyTonightCompat('combination_reco_lens_suffix')}`
                    : item.camera_name
            );
        }
        if (compositionParts.length > 0) {
            const compLine = document.createElement('div');
            compLine.className = 'small text-muted';
            compLine.textContent = compositionParts.join(' + ');
            tdName.appendChild(compLine);
        }
        if (item.owner_username) {
            const _sb = document.createElement('span');
            _sb.className = 'badge bg-info text-dark';
            _sb.style.fontSize = '0.7em';
            _sb.textContent = tSkyTonightCompat('combination_reco_shared_by').replace('{username}', item.owner_username);
            tdName.append(' ');
            tdName.appendChild(_sb);
        }

        const tdRating = document.createElement('td');
        tdRating.className = 'text-center';
        tdRating.title = `${String(rating)}/5`;
        tdRating.textContent = _skytStarsFromRating(rating);

        const tdNote = document.createElement('td');
        tdNote.textContent = noteText;

        tr.appendChild(tdName);
        tr.appendChild(tdRating);
        tr.appendChild(tdNote);
        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    tableResponsive.appendChild(table);
    wrapper.appendChild(tableResponsive);
    return wrapper;
}

// ── AstroScore visual helpers ─────────────────────────────────────────────────

function _astroScoreBadgeClass(score) {
    if (score >= 0.85) return 'astroscore-badge astroscore-badge-exceptional';
    if (score >= 0.65) return 'astroscore-badge astroscore-badge-good';
    if (score >= 0.45) return 'astroscore-badge astroscore-badge-average';
    return 'astroscore-badge astroscore-badge-poor';
}

function _astroScoreTierKey(score) {
    if (score >= 0.85) return 'astroscore_exceptional';
    if (score >= 0.65) return 'astroscore_good';
    if (score >= 0.45) return 'astroscore_average';
    return 'astroscore_poor';
}

/** Returns an HTML string: a coloured Bootstrap badge showing the score as %. */
function _astroScoreBadgeHtml(score) {
    if (score === null || score === undefined || score === '') return '-';
    const num = parseFloat(score);
    if (isNaN(num)) return escapeHtml(String(score));
    const pct = Math.round(num * 100);
    const cls = _astroScoreBadgeClass(num);
    const tier = tSkyTonightCompat(_astroScoreTierKey(num));
    return `<span class="badge ${cls}" title="${escapeHtml(tier)}">${pct}%</span>`;
}

// ── Difficulty visual helpers (Feature 2) ──────────────────────────────────

function _difficultyBadgeClass(difficulty) {
    if (difficulty === 'beginner') return 'bg-success';
    if (difficulty === 'advanced') return 'bg-danger';
    return 'bg-warning text-dark';
}

/** Returns an HTML string badge, for use in the legacy template-string DSO table renderer. */
function _difficultyBadgeHtml(difficulty) {
    if (!difficulty) return '-';
    const cls = _difficultyBadgeClass(difficulty);
    const label = escapeHtml(i18n.t(`difficulty.${difficulty}`));
    return `<span class="badge ${cls}">${label}</span>`;
}

/**
 * Returns a DOM node badge, for use in DOMUtils/createElement-based contexts
 * (recommendations panel, astrodex.js, plan_my_night.js). Exposed on window
 * so those other modules can call it without a module import system.
 */
function createDifficultyBadgeNode(difficulty) {
    const badge = document.createElement('span');
    if (!difficulty) {
        badge.className = 'badge bg-secondary';
        badge.textContent = '-';
        return badge;
    }
    badge.className = `badge ${_difficultyBadgeClass(difficulty)}`;
    badge.textContent = i18n.t(`difficulty.${difficulty}`);
    return badge;
}
window.createDifficultyBadgeNode = createDifficultyBadgeNode;

/**
 * Returns the "Captured" (in Astrodex) badge node shared by the beginner-catalog
 * and recommendation cards.
 */
function _buildCapturedBadge() {
    const capturedBadge = document.createElement('span');
    capturedBadge.className = 'badge bg-success';
    DOMUtils.append(capturedBadge, DOMUtils.createIcon('bi bi-check-circle-fill'), ` ${i18n.t('beginner_catalog.captured')}`);
    return capturedBadge;
}

/**
 * Populate a card thumbnail <img>: use a server-provided thumbnail_url directly
 * if present, otherwise fall back to resolving it client-side via fetchObjectInfo
 * (used when the caller has no known coordinates to build a thumbnail URL from).
 */
function _loadCardThumbnail(imgEl, thumbnailUrl, identifier) {
    if (thumbnailUrl) {
        imgEl.src = thumbnailUrl;
        imgEl.style.display = '';
        return;
    }
    if (identifier && typeof fetchObjectInfo === 'function') {
        fetchObjectInfo(identifier).then((data) => {
            if (data?.image?.url) {
                imgEl.src = data.image.url;
                imgEl.style.display = '';
            }
        });
    }
}

/**
 * Returns a colour-coded badge for solar elongation (angular distance from the Sun).
 * Reuses the same quality CSS classes as the AstroScore badge for consistency.
 *   ≥ 90° → exceptional (green)  - opposition / quadrature zone
 *   45-89° → good (blue)         - well separated from the Sun
 *   20-44° → average (amber)     - twilight-affected, challenging
 *   < 20°  → poor (red)          - solar glare zone, effectively unobservable
 */
function _elongationBadgeHtml(deg) {
    if (deg === null || deg === undefined || deg === '') return '-';
    const num = parseFloat(deg);
    if (isNaN(num)) return '-';
    let cls;
    if (num >= 90) cls = 'astroscore-badge astroscore-badge-exceptional';
    else if (num >= 45) cls = 'astroscore-badge astroscore-badge-good';
    else if (num >= 20) cls = 'astroscore-badge astroscore-badge-average';
    else cls = 'astroscore-badge astroscore-badge-poor';
    return `<span class="badge ${cls}">${num.toFixed(1)}°</span>`;
}

/** Returns an HTML string: a compact legend row for all 4 AstroScore tiers. */
function _astroScoreLegendHtml() {
    const tiers = [
        { key: 'astroscore_exceptional', cls: 'astroscore-badge astroscore-badge-exceptional', range: '≥ 85%' },
        { key: 'astroscore_good', cls: 'astroscore-badge astroscore-badge-good', range: '65-84%' },
        { key: 'astroscore_average', cls: 'astroscore-badge astroscore-badge-average', range: '45-64%' },
        { key: 'astroscore_poor', cls: 'astroscore-badge astroscore-badge-poor', range: '< 45%' },
    ];
    let html = `<div class="d-flex flex-wrap gap-2 mb-2 align-items-center small mt-3">`;
    html += `<span class="text-muted fw-semibold">${escapeHtml(tSkyTonightCompat('astroscore_legend_title'))}:</span>`;
    tiers.forEach(({ key, cls, range }) => {
        const label = tSkyTonightCompat(key);
        html += `<span class="badge ${cls}">${escapeHtml(range)} - ${escapeHtml(label)}</span>`;
    });
    html += `</div>`;
    return html;
}

async function getSkyTonightDisplayAstrodex() {
    if (skytonightDisplayAstrodexCache !== null) {
        return skytonightDisplayAstrodexCache;
    }

    if (skytonightDisplayAstrodexPromise) {
        return skytonightDisplayAstrodexPromise;
    }

    skytonightDisplayAstrodexPromise = (async () => {
        const roleUser = await getUserRole();
        const canDisplay = roleUser === 'user' || roleUser === 'admin';
        skytonightDisplayAstrodexCache = canDisplay;
        skytonightDisplayAstrodexPromise = null;
        return canDisplay;
    })();

    return skytonightDisplayAstrodexPromise;
}

// ======================
// Interactive Sky Map (Plotly scatterpolar)
// ======================

/**
 * Render an interactive polar sky-dome chart into `container`.
 *
 * Coordinate mapping:
 *   r     = 90 - altitude  →  centre = zenith (alt 90°), edge = horizon (alt 0°)
 *   theta = azimuth (CW from N)  →  N at top, E at right, matching compass convention
 *
 * All targets (DSOs, bodies, comets) are plotted at their peak-altitude position
 * for tonight, sized by AstroScore and coloured by object type.
 */
async function _renderSkyMap(reports, container) {
    // NOTE: do NOT clear 'container' here - the caller already inserted a loading indicator.
    // We clear it only once we have data (or an error) to show.

    try {
        await _ensurePlotlyLoaded();
    } catch (_) {
        DOMUtils.clear(container);
        const w = document.createElement('div');
        w.className = 'alert alert-warning mt-3';
        w.textContent = tSkyTonightCompat('no_data_available');
        container.appendChild(w);
        return;
    }

    // ── fetch trajectory data from backend ───────────────────────────────────
    let skymap;
    try {
        skymap = await fetchJSON('/api/skytonight/skymap');
    } catch (_) {
        DOMUtils.clear(container);
        const err = document.createElement('div');
        err.className = 'alert alert-danger mt-3';
        err.textContent = tSkyTonightCompat('no_data_available');
        container.appendChild(err);
        return;
    }

    DOMUtils.clear(container); // loading indicator has served its purpose

    const targets = (skymap && skymap.targets) || [];
    const mapConstraints = (skymap && skymap.constraints) || {};
    if (targets.length === 0) {
        const info = document.createElement('div');
        info.className = 'alert alert-info mt-3';
        info.textContent = tSkyTonightCompat('no_data_available');
        container.appendChild(info);
        return;
    }

    // ── colour palette (cycling) ────────────────────────────────────────────
    const PALETTE = [
        '#4dabf7', '#ffd43b', '#51cf66', '#ff8c00', '#f783ac',
        '#a9e34b', '#74c0fc', '#ff6b6b', '#cc5de8', '#20c997',
        '#fd7e14', '#748ffc', '#e599f7', '#94d82d', '#63e6be',
        '#ff922b', '#339af0', '#f06595', '#a9e34b', '#845ef7',
    ];

    // ── category → marker symbol for the numbered start dot ─────────────────
    const CAT_SYMBOL = {
        'Galaxy': 'circle',
        'Nebula': 'diamond',
        'Planetary Nebula': 'diamond',
        'Star Cluster': 'square',
        'Open Cluster': 'square',
        'Globular Cluster': 'circle',
    };

    // ── theme ────────────────────────────────────────────────────────────────
    const isDark = document.documentElement.getAttribute('data-bs-theme') !== 'light';
    const skyBg = isDark ? '#07101f' : '#d9eaf7';
    const gridClr = isDark ? 'rgba(180,210,255,0.12)' : 'rgba(40,60,120,0.15)';
    const tickClr = isDark ? '#9ab0cc' : '#334466';

    // ── build traces, keeping an index map per target ────────────────────────
    const traces = [];
    const traceMap = []; // [{arcIdx, dotIdx, target}] in same order as targets[]

    targets.forEach((tgt, i) => {
        const color = PALETTE[i % PALETTE.length];
        const alt = tgt.alt;
        const az = tgt.az;
        const label = String(tgt.n);
        const scoreStr = tgt.score != null ? (tgt.score * 100).toFixed(0) + '%' : '-';
        const constLabel = tgt.constellation ? _translatedConstellation(tgt.constellation) : '';
        const tooltip = `<b>${label}: ${escapeHtml(tgt.name)}</b><br>` +
            `${escapeHtml(tSkyTonightType(tgt.type || tgt.category))}<br>` +
            `AstroScore: ${scoreStr}<br>` +
            (constLabel ? `${escapeHtml(constLabel)}<br>` : '');

        const r = alt.map(a => Math.max(0, 90 - a));
        const theta = az;

        const arcIdx = traces.length;
        traces.push({
            type: 'scatterpolar', mode: 'lines',
            name: `${label}: ${tgt.name}`,
            r, theta,
            line: { color, width: 1.8 },
            hoverinfo: 'skip',
            showlegend: false,
        });

        const dotSymbol = CAT_SYMBOL[tgt.type] || (tgt.category === 'bodies' ? 'star' : 'x');
        const dotIdx = traces.length;
        traces.push({
            type: 'scatterpolar', mode: 'markers+text',
            name: `${label}: ${tgt.name}`,
            r: [r[0]], theta: [theta[0]],
            text: [label],
            textposition: 'top center',
            textfont: { color, size: 9 },
            hovertext: [tooltip],
            hoverinfo: 'text',
            marker: {
                symbol: dotSymbol, color, size: 8, opacity: 0.95,
                line: { color: isDark ? '#111' : '#fff', width: 1 },
            },
            showlegend: false,
        });

        traceMap.push({ arcIdx, dotIdx, target: tgt });
    });

    // ── Plotly layout ─────────────────────────────────────────────────────────
    const plotLayout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        autosize: true,
        polar: {
            bgcolor: skyBg,
            radialaxis: {
                range: [0, 90],
                tickvals: [0, 30, 60, 90],
                ticktext: ['90°', '60°', '30°', '0°'],
                tickfont: { size: 9, color: tickClr },
                gridcolor: gridClr, linecolor: gridClr, showline: true,
            },
            angularaxis: {
                direction: 'clockwise', rotation: 90,
                tickvals: [0, 45, 90, 135, 180, 225, 270, 315],
                ticktext: ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'],
                tickfont: { size: 11, color: tickClr },
                gridcolor: gridClr,
            },
        },
        showlegend: false,
        margin: { t: 10, r: 10, b: 10, l: 10 },
        font: { color: tickClr },
    };

    const plotConfig = {
        responsive: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['toImage'],
    };

    // ── DOM: outer row ────────────────────────────────────────────────────────
    const row = document.createElement('div');
    row.className = 'row g-3 mt-1';
    container.appendChild(row);

    // ── Left column: chart card ───────────────────────────────────────────────
    const colChart = document.createElement('div');
    colChart.className = 'col-12 col-xl-8';
    row.appendChild(colChart);

    const chartCard = document.createElement('div');
    chartCard.className = 'card h-100';
    colChart.appendChild(chartCard);

    const chartHeader = document.createElement('div');
    chartHeader.className = 'card-header d-flex justify-content-between align-items-center';

    const chartTitle = document.createElement('span');
    chartTitle.className = 'fw-semibold';
    DOMUtils.append(chartTitle, DOMUtils.createIcon('bi bi-globe2 icon-inline'), tSkyTonightCompat('sky_map_title'));

    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'btn btn-sm btn-outline-secondary';
    DOMUtils.append(resetBtn, DOMUtils.createIcon('bi bi-arrows-fullscreen icon-inline'), tSkyTonightCompat('sky_map_reset_view'));

    chartHeader.appendChild(chartTitle);
    chartHeader.appendChild(resetBtn);
    chartCard.appendChild(chartHeader);

    const chartBody = document.createElement('div');
    chartBody.className = 'card-body p-2';
    chartCard.appendChild(chartBody);

    const hint = document.createElement('div');
    hint.className = 'text-muted small mb-2';
    DOMUtils.append(hint, DOMUtils.createIcon('bi bi-info-circle icon-inline'), tSkyTonightCompat('sky_map_hint'));
    chartBody.appendChild(hint);

    const mapDiv = document.createElement('div');
    mapDiv.className = 'sky-map-plotly';
    chartBody.appendChild(mapDiv);

    // ── Horizon boundary lines (dashed) on sky map ───────────────────────────
    const altMin = mapConstraints.altitude_constraint_min ?? 30;
    const horizonProfile = mapConstraints.horizon_profile || [];
    const horizonGridClr = isDark ? 'rgba(20, 140, 50, 0.55)' : 'rgba(10, 110, 30, 0.65)';

    // Flat alt_min circle: r = 90 - alt_min at every azimuth
    const circleTheta = Array.from({ length: 361 }, (_, i) => i);
    const circleR = circleTheta.map(() => 90 - altMin);
    traces.push({
        type: 'scatterpolar', mode: 'lines',
        name: `${altMin}° min`,
        r: circleR, theta: circleTheta,
        line: { color: horizonGridClr, width: 1.5, dash: 'dash' },
        hoverinfo: 'skip', showlegend: false,
    });

    // Custom horizon profile polygon: r = 90 - horizon_alt_at(az)
    if (horizonProfile.length > 0) {
        // Densify the profile to a point per degree for a smooth polygon
        const customTheta = Array.from({ length: 361 }, (_, i) => i);
        const customR = customTheta.map(az => {
            const alt = _horizonAltAtAz(az, horizonProfile);
            return alt !== null ? 90 - alt : 90 - altMin;
        });
        traces.push({
            type: 'scatterpolar', mode: 'lines',
            name: tSkyTonightCompat('horizon_custom_line') || 'Custom Horizon',
            r: customR, theta: customTheta,
            line: { color: 'rgba(200, 80, 0, 0.70)', width: 1.5, dash: 'dot' },
            hoverinfo: 'skip', showlegend: false,
        });
    }

    Plotly.newPlot(mapDiv, traces, plotLayout, plotConfig);

    resetBtn.addEventListener('click', () => {
        Plotly.relayout(mapDiv, {
            'polar.radialaxis.range': [0, 90],
            'polar.radialaxis.autorange': false,
        });
    });

    const ro = new ResizeObserver(() => Plotly.Plots.resize(mapDiv));
    ro.observe(mapDiv);

    // ── Sky map card footer: horizon line legend ──────────────────────────────
    const skyMapFooter = document.createElement('div');
    skyMapFooter.className = 'card-footer text-muted small';
    const skyMapFooterRow = document.createElement('div');
    skyMapFooterRow.className = 'd-flex flex-wrap gap-2 align-items-center';

    const skyMapLegendItems = [
        {
            color: isDark ? 'rgba(20, 140, 50, 0.75)' : 'rgba(10, 110, 30, 0.85)',
            dash: '6px 4px',
            label: `${tSkyTonightCompat('sky_map_horizon_min') || 'Min altitude'} (${altMin}°)`,
        },
        ...(horizonProfile.length > 0 ? [{
            color: 'rgba(200, 80, 0, 0.85)',
            dash: '2px 3px',
            label: tSkyTonightCompat('horizon_custom_line') || 'Custom Horizon',
        }] : []),
    ];

    skyMapLegendItems.forEach(item => {
        const col = document.createElement('div');
        col.className = 'col-auto d-flex align-items-center gap-1';

        // Dashed line swatch using a short SVG
        const swatch = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        swatch.setAttribute('width', '28');
        swatch.setAttribute('height', '10');
        swatch.setAttribute('aria-hidden', 'true');
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', '0');
        line.setAttribute('y1', '5');
        line.setAttribute('x2', '28');
        line.setAttribute('y2', '5');
        line.setAttribute('stroke', item.color);
        line.setAttribute('stroke-width', '2');
        line.setAttribute('stroke-dasharray', item.dash);
        swatch.appendChild(line);

        const lbl = document.createElement('span');
        lbl.textContent = item.label;

        col.appendChild(swatch);
        col.appendChild(lbl);
        skyMapFooterRow.appendChild(col);
    });

    skyMapFooter.appendChild(skyMapFooterRow);
    chartCard.appendChild(skyMapFooter);

    // ── Right column: filters + legend card ──────────────────────────────────
    const colLegend = document.createElement('div');
    colLegend.className = 'col-12 col-xl-4';
    row.appendChild(colLegend);

    const legendCard = document.createElement('div');
    legendCard.className = 'card h-100';
    colLegend.appendChild(legendCard);

    const legendHeader = document.createElement('div');
    legendHeader.className = 'card-header fw-semibold';
    DOMUtils.append(legendHeader, DOMUtils.createIcon('bi bi-funnel icon-inline'), tSkyTonightCompat('sky_map_legend_title'));
    legendCard.appendChild(legendHeader);

    const legendBody = document.createElement('div');
    legendBody.className = 'card-body p-2';
    legendCard.appendChild(legendBody);

    // ── Filter state ──────────────────────────────────────────────────────────
    const activeCategories = new Set(['deep_sky', 'bodies', 'comets']);
    let minScore = 0.65;
    let messierOnly = false;
    const allConstellations = [...new Set(
        targets.map(t => t.constellation).filter(c => c && c.trim())
    )].sort();
    const activeConstellations = new Set(allConstellations);

    // ── Group toggle buttons ──────────────────────────────────────────────────
    const groupDefs = [
        { cat: 'deep_sky', key: 'sky_map_filter_dso' },
        { cat: 'bodies', key: 'sky_map_filter_bodies' },
        { cat: 'comets', key: 'sky_map_filter_comets' },
    ];

    // Only show group buttons for categories that actually have targets
    const presentCats = new Set(targets.map(t => t.category));
    const visibleGroups = groupDefs.filter(g => presentCats.has(g.cat));

    if (visibleGroups.length > 1) {
        const groupRow = document.createElement('div');
        groupRow.className = 'd-flex gap-2 flex-wrap mb-2';
        legendBody.appendChild(groupRow);

        visibleGroups.forEach(({ cat, key }) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm btn-primary sky-map-filter-btn';
            btn.dataset.cat = cat;
            btn.textContent = tSkyTonightCompat(key);
            btn.addEventListener('click', () => {
                if (activeCategories.has(cat)) {
                    activeCategories.delete(cat);
                    btn.classList.replace('btn-primary', 'btn-outline-secondary');
                } else {
                    activeCategories.add(cat);
                    btn.classList.replace('btn-outline-secondary', 'btn-primary');
                }
                applyFilters();
            });
            groupRow.appendChild(btn);
        });
    }

    // ── Messier-only toggle (only shown when deep_sky targets are present) ────
    const hasMessier = targets.some(t => t.category === 'deep_sky' && t.messier);
    if (hasMessier) {
        const messierRow = document.createElement('div');
        messierRow.className = 'd-flex gap-2 flex-wrap mb-2';
        legendBody.appendChild(messierRow);

        const messierBtn = document.createElement('button');
        messierBtn.type = 'button';
        messierBtn.className = 'btn btn-sm btn-outline-secondary sky-map-filter-btn';
        DOMUtils.append(messierBtn, DOMUtils.createIcon('bi bi-star icon-inline'), 'Messier');
        messierBtn.title = tSkyTonightCompat('sky_map_filter_dso') + ' - Messier only';
        messierBtn.addEventListener('click', () => {
            messierOnly = !messierOnly;
            if (messierOnly) {
                messierBtn.classList.replace('btn-outline-secondary', 'btn-warning');
            } else {
                messierBtn.classList.replace('btn-warning', 'btn-outline-secondary');
            }
            applyFilters();
        });
        messierRow.appendChild(messierBtn);
    }

    // ── AstroScore slider ─────────────────────────────────────────────────────
    const sliderWrap = document.createElement('div');
    sliderWrap.className = 'mb-3';
    legendBody.appendChild(sliderWrap);

    const sliderLabel = document.createElement('label');
    sliderLabel.className = 'form-label small text-muted mb-1';
    const sliderLabelText = document.createTextNode(
        `${tSkyTonightCompat('sky_map_min_score')}: `
    );
    const sliderValueSpan = document.createElement('span');
    sliderValueSpan.className = 'fw-semibold';
    sliderValueSpan.textContent = '0%';
    sliderLabel.appendChild(sliderLabelText);
    sliderLabel.appendChild(sliderValueSpan);
    sliderWrap.appendChild(sliderLabel);

    const slider = document.createElement('input');
    slider.type = 'range';
    slider.className = 'form-range';
    slider.min = '0';
    slider.max = '100';
    slider.step = '5';
    slider.value = '65';
    sliderValueSpan.textContent = '65%';
    slider.addEventListener('input', () => {
        minScore = parseInt(slider.value, 10) / 100;
        sliderValueSpan.textContent = `${slider.value}%`;
        applyFilters();
    });
    sliderWrap.appendChild(slider);

    // ── AstroScore tier legend ────────────────────────────────────────────────
    const scoreLegendWrap = document.createElement('div');
    scoreLegendWrap.className = 'mb-3';
    const scoreLegendFrag = document.createRange().createContextualFragment(_astroScoreLegendHtml());
    scoreLegendWrap.appendChild(scoreLegendFrag);
    legendBody.appendChild(scoreLegendWrap);

    // ── Constellation filter ───────────────────────────────────────────────────
    const constBtnMap = {};
    if (allConstellations.length > 1) {
        const constSection = document.createElement('div');
        constSection.className = 'mb-2';
        legendBody.appendChild(constSection);

        const constLabelRow = document.createElement('div');
        constLabelRow.className = 'd-flex align-items-center justify-content-between mb-1';
        constSection.appendChild(constLabelRow);

        const constLabel = document.createElement('span');
        constLabel.className = 'form-label small text-muted mb-0';
        constLabel.textContent = tSkyTonightCompat('sky_map_filter_constellation');
        constLabelRow.appendChild(constLabel);

        const resetConstBtn = document.createElement('button');
        resetConstBtn.type = 'button';
        resetConstBtn.className = 'btn btn-sm btn-link p-0 text-muted';
        resetConstBtn.title = 'Show all constellations';
        resetConstBtn.appendChild(DOMUtils.createIcon('bi bi-arrow-counterclockwise'));
        constLabelRow.appendChild(resetConstBtn);

        const constBtnWrap = document.createElement('div');
        constBtnWrap.className = 'sky-map-constellation-filter d-flex flex-wrap gap-1';
        constSection.appendChild(constBtnWrap);

        allConstellations.forEach(name => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'btn btn-sm btn-primary sky-map-filter-btn';
            b.textContent = _translatedConstellation(name);
            b.dataset.constellation = name;
            b.addEventListener('click', () => {
                if (activeConstellations.has(name)) {
                    activeConstellations.delete(name);
                    b.classList.replace('btn-primary', 'btn-outline-secondary');
                } else {
                    activeConstellations.add(name);
                    b.classList.replace('btn-outline-secondary', 'btn-primary');
                }
                applyFilters();
            });
            constBtnWrap.appendChild(b);
            constBtnMap[name] = b;
        });

        resetConstBtn.addEventListener('click', () => {
            allConstellations.forEach(name => {
                activeConstellations.add(name);
                constBtnMap[name].classList.replace('btn-outline-secondary', 'btn-primary');
            });
            applyFilters();
        });
    }

    // ── Legend table ──────────────────────────────────────────────────────────
    const statsLine = document.createElement('div');
    statsLine.className = 'text-muted small text-end mb-1';
    statsLine.textContent = tSkyTonightCompat('sky_map_count', { count: targets.length });
    legendBody.appendChild(statsLine);

    const tblWrap = document.createElement('div');
    tblWrap.className = 'sky-map-legend-wrap';
    legendBody.appendChild(tblWrap);

    const tbl = document.createElement('table');
    tbl.className = 'table table-sm table-hover table-borderless sky-map-legend mb-0';
    tblWrap.appendChild(tbl);

    const thead = tbl.createTHead();
    const hr = thead.insertRow();
    [
        tSkyTonightCompat('sky_map_col_rank'),
        tSkyTonightCompat('sky_map_col_name'),
        tSkyTonightCompat('sky_map_col_type'),
        tSkyTonightCompat('sky_map_col_score'),
        tSkyTonightCompat('sky_map_col_constellation'),
    ].forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        th.scope = 'col';
        hr.appendChild(th);
    });

    const tbody = tbl.createTBody();
    const legendRows = [];

    targets.forEach((tgt, i) => {
        const color = PALETTE[i % PALETTE.length];
        const tableRow = tbody.insertRow();
        tableRow.dataset.cat = tgt.category;
        tableRow.dataset.score = tgt.score != null ? tgt.score : '0';

        [
            { text: tgt.n, colored: true },
            { text: tgt.name, colored: false },
            { text: tSkyTonightType(tgt.type || tgt.category), colored: false },
            { score: tgt.score },
            { text: tgt.constellation ? _translatedConstellation(tgt.constellation) : '-', colored: false },
        ].forEach(cell => {
            const td = tableRow.insertCell();
            if (cell.score !== undefined) {
                if (cell.score != null) {
                    const badge = document.createElement('span');
                    badge.className = `badge ${_astroScoreBadgeClass(cell.score)}`;
                    badge.textContent = Math.round(cell.score * 100) + '%';
                    badge.title = tSkyTonightCompat(_astroScoreTierKey(cell.score));
                    td.appendChild(badge);
                } else {
                    td.textContent = '-';
                }
            } else {
                td.textContent = cell.text;
                if (cell.colored) {
                    td.style.color = color;
                    td.style.fontWeight = 'bold';
                }
            }
        });

        legendRows.push(tableRow);
    });

    // ── Filter logic ──────────────────────────────────────────────────────────
    function applyFilters() {
        const visArr = new Array(traces.length).fill(true);
        traceMap.forEach(({ arcIdx, dotIdx, target }) => {
            const show = activeCategories.has(target.category) &&
                (target.score == null || target.score >= minScore) &&
                (!messierOnly || (target.category === 'deep_sky' && target.messier)) &&
                (allConstellations.length === 0 || !target.constellation || activeConstellations.has(target.constellation));
            visArr[arcIdx] = show;
            visArr[dotIdx] = show;
        });
        Plotly.restyle(mapDiv, { visible: visArr });

        let visible = 0;
        legendRows.forEach((tableRow, i) => {
            const tgt = targets[i];
            const show = activeCategories.has(tgt.category) &&
                (tgt.score == null || tgt.score >= minScore) &&
                (!messierOnly || (tgt.category === 'deep_sky' && tgt.messier)) &&
                (allConstellations.length === 0 || !tgt.constellation || activeConstellations.has(tgt.constellation));
            tableRow.style.display = show ? '' : 'none';
            if (show) visible++;
        });
        statsLine.textContent = tSkyTonightCompat('sky_map_count', { count: visible });
    }

    // Apply initial filter (default slider is 65 %)
    applyFilters();
}


// ======================
// Catalogue Management
// ======================

async function loadCatalogues() {
    try {
        const catalogues = await fetchJSON('/api/catalogues');

        const container = document.getElementById('catalogues-list');
        if (!container) return; // Element doesn't exist on this page view

        DOMUtils.clear(container);

        // Ensure Messier is checked by default if no catalogues selected
        const selectedCatalogues = currentConfig.selected_catalogues || ['Messier'];

        catalogues.forEach(catalogue => {
            const checkboxElt = document.createElement('div');
            checkboxElt.className = 'form-check form-switch bg-checkbox';

            const input = document.createElement('input');
            input.className = 'form-check-input';
            input.type = 'checkbox';
            input.value = catalogue;
            input.id = `catalogue-${catalogue}`;
            input.toggleAttribute('checked', selectedCatalogues.includes(catalogue));
            input.setAttribute('switch', '');

            const label = document.createElement('label');
            label.className = 'form-check-label';
            label.setAttribute('for', `catalogue-${catalogue}`);
            label.textContent = catalogue;

            checkboxElt.appendChild(input);
            checkboxElt.appendChild(label);
            container.appendChild(checkboxElt);
        });

    } catch (error) {
        console.error('Error loading catalogues:', error);
    }
}

// ======================
// SkyTonight Section UI  (5 direct section buttons replacing the old subtab)
// ======================

/**
 * Main entry point - called when the SkyTonight tab is activated,
 * after a calculation finishes, or after plan changes that need badge refresh.
 * Builds/refreshes the 5 section buttons and ensures content wrappers exist.
 */
async function loadSkyTonightResultsTabs() {
    // Invalidate section caches so fresh data is fetched on next view
    _skytSectionCache = {};
    currentCatalogueTab = 'SkyTonight';

    _buildSkyTonightSectionButtons();
    // Show + load the current (or default) section
    activateSubTab('skytonight', `skytonight-${_skytCurrentSection}`);
    await _showSkyTonightSectionData(_skytCurrentSection);
}

/**
 * Build the 5 section navigation buttons in #skytonight-subtabs and ensure
 * the corresponding sub-tab-content divs exist in #skytonight-tab.
 * Follows the same pattern as other tabs (sub-tab-btn / sub-tab-content).
 */
function _buildSkyTonightSectionButtons() {
    const navContainer = document.getElementById('skytonight-subtabs');
    if (!navContainer) return;
    DOMUtils.clear(navContainer);

    const skytonightTab = document.getElementById('skytonight-tab');

    const sections = [
        { key: 'plot', icon: 'bi-bar-chart-line text-success', labelKey: 'plot' },
        { key: 'report', icon: 'bi-galaxy', labelKey: 'deep_sky_objects' },
        { key: 'beginner', icon: 'bi-book text-primary', labelKey: 'beginner_catalog_tab_label' },
        { key: 'bodies', icon: 'bi-globe2 text-warning', labelKey: 'bodies' },
        { key: 'comets', icon: 'bi-comet text-warning', labelKey: 'comets' },
        { key: 'log', icon: 'bi-journal-text text-danger', labelKey: 'logs' },
        { key: 'debug', icon: 'bi-question-circle text-info', labelKey: 'target_debug' },
    ].filter(sec => sec.key !== 'beginner' || currentUserPreferences?.beginner_catalog_enabled !== false);

    // If the currently-active section was just hidden (preference toggled off), fall back to 'report'.
    if (_skytCurrentSection === 'beginner' && !sections.some(sec => sec.key === 'beginner')) {
        _skytCurrentSection = 'report';
    }

    sections.forEach(sec => {
        const subtabName = `skytonight-${sec.key}`;

        // ── Nav button ──────────────────────────────────────────────────────
        const li = document.createElement('li');
        li.className = 'nav-item';
        const a = document.createElement('a');
        a.className = `nav-link sub-tab-btn${sec.key === _skytCurrentSection ? ' active' : ''}`;
        a.href = `#skytonight/${subtabName}`;
        a.setAttribute('data-subtab', subtabName);
        const _navSpan = document.createElement('span');
        _navSpan.textContent = tSkyTonightCompat(sec.labelKey);
        DOMUtils.append(a, DOMUtils.createIcon(`bi ${sec.icon} icon-inline`), ' ', _navSpan);
        li.appendChild(a);
        navContainer.appendChild(li);

        // ── Content wrapper (created once, reused on re-renders) ────────────
        if (!document.getElementById(`${subtabName}-subtab`)) {
            const contentDiv = document.createElement('div');
            contentDiv.id = `${subtabName}-subtab`;
            contentDiv.className = 'sub-tab-content';

            const wrapper = document.createElement('div');
            wrapper.className = 'shadow p-2 mb-3 rounded bg-sub-container';

            const h2 = document.createElement('h2');
            const _h2Span = document.createElement('span');
            _h2Span.textContent = tSkyTonightCompat(sec.labelKey);
            DOMUtils.append(h2, DOMUtils.createIcon(`bi ${sec.icon} icon-inline`), ' ', _h2Span);
            wrapper.appendChild(h2);

            const dataDiv = document.createElement('div');
            dataDiv.id = `skytonight-${sec.key}-data`;
            wrapper.appendChild(dataDiv);

            contentDiv.appendChild(wrapper);
            skytonightTab.appendChild(contentDiv);
        }
    });
}

/**
 * Called by app.js switchSubTab when a skytonight-* subtab is activated.
 * Loads data into the already-visible sub-tab-content div.
 *
 * @param {string} sectionKey  'plot' | 'report' | 'bodies' | 'comets' | 'log' | 'debug'
 */
async function _showSkyTonightSectionData(sectionKey) {
    _skytCurrentSection = sectionKey;

    const dataDiv = document.getElementById(`skytonight-${sectionKey}-data`);
    if (!dataDiv) return;

    if (sectionKey === 'plot') {
        if (_skytSectionCache['plot']) return;  // prevent concurrent renders
        _skytSectionCache['plot'] = true;
        DOMUtils.clear(dataDiv);
        const plotLoading = document.createElement('div');
        plotLoading.className = 'alert alert-info';
        plotLoading.textContent = i18n.t('common.loading');
        dataDiv.appendChild(plotLoading);
        try {
            await _renderSkyMap(null, dataDiv);
        } catch (e) {
            delete _skytSectionCache['plot'];   // allow retry on error
            throw e;
        }
        return;
    }

    if (sectionKey === 'log') {
        await _showSkyTonightLogSection(dataDiv);
        return;
    }

    if (sectionKey === 'debug') {
        _renderSkytDebugSection(dataDiv);
        return;
    }

    if (sectionKey === 'beginner') {
        await _showBeginnerCatalogSection(dataDiv);
        return;
    }

    await _showSkyTonightDataSection(sectionKey, dataDiv);
}

async function _showSkyTonightLogSection(container) {
    DOMUtils.clear(container);
    const loading = document.createElement('div');
    loading.className = 'alert alert-info';
    loading.textContent = tSkyTonightCompat('loading_log_content');
    container.appendChild(loading);

    const logContent = await loadSkytonightLog();
    DOMUtils.clear(container);

    if (typeof logContent !== 'string') {
        const err = document.createElement('div');
        err.className = 'alert alert-danger';
        err.textContent = tSkyTonightCompat('failed_to_load_log_content');
        container.appendChild(err);
        return;
    }

    const lines = logContent.trim().split('\n').filter(l => l.trim()).reverse();
    if (lines.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'alert alert-info';
        empty.textContent = tSkyTonightCompat('no_data_available');
        container.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    lines.forEach(line => {
        let entry;
        try { entry = JSON.parse(line); } catch {
            const pre = document.createElement('pre');
            pre.className = 'small text-muted my-1';
            pre.textContent = line;
            frag.appendChild(pre);
            return;
        }

        const { timestamp, status, payload } = entry;
        const isError = status && status.includes('error');

        const card = document.createElement('div');
        card.className = `card mb-2 border-${isError ? 'danger' : 'success'}`;

        // Header
        const header = document.createElement('div');
        header.className = 'card-header d-flex align-items-center gap-2 py-1';

        const badge = document.createElement('span');
        badge.className = `badge bg-${isError ? 'danger' : 'success'}`;
        badge.textContent = status || '?';
        header.appendChild(badge);

        const tsEl = document.createElement('small');
        tsEl.className = 'text-muted ms-auto';
        if (timestamp) {
            try { tsEl.textContent = new Date(timestamp).toLocaleString(); }
            catch { tsEl.textContent = timestamp; }
        }
        header.appendChild(tsEl);
        card.appendChild(header);

        // Body - key/value rows from payload
        if (payload && typeof payload === 'object') {
            const body = document.createElement('div');
            body.className = 'card-body py-2 px-3 small';

            Object.entries(payload).forEach(([key, value]) => {
                const row = document.createElement('div');
                row.className = 'd-flex gap-2 align-items-baseline border-bottom py-1';

                const keyEl = document.createElement('span');
                keyEl.className = 'fw-semibold text-nowrap';
                keyEl.style.minWidth = '10rem';
                keyEl.textContent = key.replace(/_/g, ' ');

                const valEl = document.createElement('span');
                valEl.className = 'text-break';
                if (typeof value === 'object' && value !== null) {
                    valEl.textContent = JSON.stringify(value);
                } else if (typeof value === 'boolean') {
                    valEl.appendChild(DOMUtils.createIcon(value ? 'bi bi-check-circle-fill text-success' : 'bi bi-x-circle-fill text-danger'));
                } else {
                    valEl.textContent = String(value ?? '\u2014');
                }

                row.appendChild(keyEl);
                row.appendChild(valEl);
                body.appendChild(row);
            });

            card.appendChild(body);
        }

        frag.appendChild(card);
    });
    container.appendChild(frag);
}

// ---------------------------------------------------------------------------
// Debug section - "DSO not found?"
// ---------------------------------------------------------------------------

/** Chart instance used by the debug altitude-time chart; cleaned up on re-search or tab switch. */
let _debugAlttimeChart = null;

function destroyDebugAlttimeChart() {
    if (_debugAlttimeChart) {
        _debugAlttimeChart.destroy();
        _debugAlttimeChart = null;
    }
}

/**
 * Render the static shell of the debug section (search form + empty results area).
 * Called once when the user first visits the 'debug' sub-tab.
 */
function _renderSkytDebugSection(container) {
    if (container.dataset.debugReady === '1') return;
    container.dataset.debugReady = '1';

    DOMUtils.clear(container);

    // Intro text
    const intro = document.createElement('p');
    intro.className = 'text-muted mb-3';
    intro.textContent = tSkyTonightCompat('target_debug_intro');
    container.appendChild(intro);

    // Search form
    const formRow = document.createElement('div');
    formRow.className = 'row g-2 mb-4 align-items-end';

    const inputCol = document.createElement('div');
    inputCol.className = 'col-12 col-sm-8 col-md-6';
    const input = document.createElement('input');
    input.type = 'text';
    input.id = 'skyt-debug-search-input';
    input.className = 'form-control';
    input.placeholder = tSkyTonightCompat('target_debug_search_placeholder');
    inputCol.appendChild(input);

    const btnCol = document.createElement('div');
    btnCol.className = 'col-auto';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-primary';
    btn.id = 'skyt-debug-search-btn';
    const btnIcon = document.createElement('i');
    btnIcon.className = 'bi bi-search me-1';
    btnIcon.setAttribute('aria-hidden', 'true');
    btn.appendChild(btnIcon);
    btn.appendChild(document.createTextNode(tSkyTonightCompat('target_debug_search_btn')));
    btnCol.appendChild(btn);

    formRow.appendChild(inputCol);
    formRow.appendChild(btnCol);
    container.appendChild(formRow);

    // Results container
    const results = document.createElement('div');
    results.id = 'skyt-debug-results';
    container.appendChild(results);

    // Wire up search
    const doSearch = () => {
        const name = input.value.trim();
        if (name) _searchTargetDebug(results, name);
    };
    btn.addEventListener('click', doSearch);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });
}

/**
 * Call the /api/skytonight/target-debug endpoint and render the result.
 */
async function _searchTargetDebug(resultsContainer, name) {
    // Destroy previous chart before clearing DOM
    if (_debugAlttimeChart) {
        _debugAlttimeChart.destroy();
        _debugAlttimeChart = null;
    }
    DOMUtils.clear(resultsContainer);

    const spinner = document.createElement('div');
    spinner.className = 'text-muted';
    const spinnerIcon = document.createElement('i');
    spinnerIcon.className = 'bi bi-hourglass-split me-1';
    spinnerIcon.setAttribute('aria-hidden', 'true');
    spinner.appendChild(spinnerIcon);
    spinner.appendChild(document.createTextNode(i18n.t('common.loading')));
    resultsContainer.appendChild(spinner);

    let data;
    try {
        data = await fetchJSON(`${API_BASE}/api/skytonight/target-debug?name=${encodeURIComponent(name)}`);
    } catch (err) {
        DOMUtils.clear(resultsContainer);
        const errDiv = document.createElement('div');
        errDiv.className = 'alert alert-danger';
        errDiv.textContent = i18n.t('common.error');
        resultsContainer.appendChild(errDiv);
        return;
    }

    DOMUtils.clear(resultsContainer);

    // Not found in catalogue
    if (!data || !data.found) {
        const notFound = document.createElement('div');
        notFound.className = 'alert alert-warning';
        const icon = document.createElement('i');
        icon.className = 'bi bi-search me-2';
        icon.setAttribute('aria-hidden', 'true');
        notFound.appendChild(icon);
        notFound.appendChild(document.createTextNode(tSkyTonightCompat('target_debug_not_found')));
        resultsContainer.appendChild(notFound);
        return;
    }

    // Overall status banner
    _renderDebugStatusBanner(resultsContainer, data);

    // Two-column layout for cards on wider screens
    const row = document.createElement('div');
    row.className = 'row g-3 mt-0';

    const leftCol = document.createElement('div');
    leftCol.className = 'col-12 col-lg-5';

    const rightCol = document.createElement('div');
    rightCol.className = 'col-12 col-lg-7';

    // Object info card (left)
    _renderDebugObjectCard(leftCol, data.target);

    // Night window card (left, below object)
    if (data.night_window) {
        const tz = (data.alttime && data.alttime.timezone) || 'UTC';
        _renderDebugNightCard(leftCol, data.night_window, data.moon, tz);
    }

    // Constraints table (right)
    if (data.checks && data.checks.length > 0) {
        _renderDebugChecksCard(rightCol, data.checks, data.constraints);
    }

    row.appendChild(leftCol);
    row.appendChild(rightCol);
    resultsContainer.appendChild(row);

    // Altitude-time chart (full width below)
    if (data.alttime && data.alttime.times_utc && data.alttime.times_utc.length > 0) {
        const chartRow = document.createElement('div');
        chartRow.className = 'row g-3 mt-0';
        const chartCol = document.createElement('div');
        chartCol.className = 'col-12';
        _renderDebugAltimeChart(chartCol, data.alttime, data.target);
        chartRow.appendChild(chartCol);
        resultsContainer.appendChild(chartRow);
    }
}

function _renderDebugStatusBanner(container, data) {
    const banner = document.createElement('div');
    const overall = data.overall;

    if (overall === 'visible') {
        banner.className = 'alert alert-success d-flex align-items-center gap-2 mb-3';
        const icon = document.createElement('i');
        icon.className = 'bi bi-check-circle-fill flex-shrink-0';
        icon.setAttribute('aria-hidden', 'true');
        const txt = document.createElement('span');
        txt.textContent = tSkyTonightCompat('target_debug_visible');
        banner.appendChild(icon);
        banner.appendChild(txt);
    } else if (overall === 'no_night') {
        banner.className = 'alert alert-warning d-flex align-items-center gap-2 mb-3';
        const icon = document.createElement('i');
        icon.className = 'bi bi-moon-stars flex-shrink-0';
        icon.setAttribute('aria-hidden', 'true');
        const txt = document.createElement('span');
        txt.textContent = tSkyTonightCompat('target_debug_no_night');
        banner.appendChild(icon);
        banner.appendChild(txt);
    } else if (overall === 'no_coordinates') {
        banner.className = 'alert alert-secondary d-flex align-items-center gap-2 mb-3';
        const icon = document.createElement('i');
        icon.className = 'bi bi-crosshair flex-shrink-0';
        icon.setAttribute('aria-hidden', 'true');
        const txt = document.createElement('span');
        txt.textContent = tSkyTonightCompat('target_debug_no_coordinates');
        banner.appendChild(icon);
        banner.appendChild(txt);
    } else {
        banner.className = 'alert alert-danger d-flex align-items-center gap-2 mb-3';
        const icon = document.createElement('i');
        icon.className = 'bi bi-funnel-fill flex-shrink-0';
        icon.setAttribute('aria-hidden', 'true');
        const txt = document.createElement('span');
        txt.textContent = tSkyTonightCompat('target_debug_filtered');
        banner.appendChild(icon);
        banner.appendChild(txt);
    }
    container.appendChild(banner);
}

function _renderDebugObjectCard(container, target) {
    const card = document.createElement('div');
    card.className = 'card mb-3';

    const header = document.createElement('div');
    header.className = 'card-header';
    const title = document.createElement('h6');
    title.className = 'mb-0';
    const hIcon = document.createElement('i');
    hIcon.className = 'bi bi-stars me-1';
    hIcon.setAttribute('aria-hidden', 'true');
    title.appendChild(hIcon);
    title.appendChild(document.createTextNode(tSkyTonightCompat('target_debug_object_card_title')));
    header.appendChild(title);

    const body = document.createElement('div');
    body.className = 'card-body py-2';

    const rows = [
        [tSkyTonightCompat('table_name'), target.preferred_name],
        [tSkyTonightCompat('table_type'), target.object_type],
        [tSkyTonightCompat('table_constellation') || 'Constellation', target.constellation],
        [tSkyTonightCompat('table_mag'), target.magnitude != null ? target.magnitude : '-'],
        [tSkyTonightCompat('table_size'), target.size_arcmin != null ? `${target.size_arcmin} arcmin` : '-'],
    ];

    if (target.catalogue_names && Object.keys(target.catalogue_names).length > 0) {
        const names = Object.entries(target.catalogue_names).map(([k, v]) => `${k}: ${v}`).join(' · ');
        rows.push([tSkyTonightCompat('catalogue_names'), names]);
    }

    const dl = document.createElement('dl');
    dl.className = 'row mb-0 small';
    rows.forEach(([label, value]) => {
        const dt = document.createElement('dt');
        dt.className = 'col-5 text-muted fw-normal';
        dt.textContent = label;
        const dd = document.createElement('dd');
        dd.className = 'col-7 mb-1';
        dd.textContent = value ?? '-';
        dl.appendChild(dt);
        dl.appendChild(dd);
    });
    body.appendChild(dl);

    card.appendChild(header);
    card.appendChild(body);
    container.appendChild(card);
}

function _renderDebugNightCard(container, nightWindow, moon, tz) {
    const card = document.createElement('div');
    card.className = 'card mb-3';

    const header = document.createElement('div');
    header.className = 'card-header';
    const title = document.createElement('h6');
    title.className = 'mb-0';
    const hIcon = document.createElement('i');
    hIcon.className = 'bi bi-moon me-1';
    hIcon.setAttribute('aria-hidden', 'true');
    title.appendChild(hIcon);
    title.appendChild(document.createTextNode(tSkyTonightCompat('target_debug_night_card_title')));
    header.appendChild(title);

    const body = document.createElement('div');
    body.className = 'card-body py-2';

    const tzFmt = new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', timeZone: tz || 'UTC', hour12: false });
    const fmtIso = (iso) => {
        try { return tzFmt.format(new Date(iso)); } catch { return iso || '-'; }
    };

    const rows = [];
    if (nightWindow.available) {
        rows.push([tSkyTonightCompat('altitude_time_night_window'), `${fmtIso(nightWindow.night_start)} – ${fmtIso(nightWindow.night_end)}`]);
        rows.push([tSkyTonightCompat('target_debug_night_hours'), nightWindow.night_hours != null ? `${nightWindow.night_hours.toFixed(1)} h` : '-']);
    }
    if (moon) {
        rows.push([tSkyTonightCompat('target_debug_moon_phase'), `${moon.phase_pct}%`]);
    }

    const dl = document.createElement('dl');
    dl.className = 'row mb-0 small';
    rows.forEach(([label, value]) => {
        const dt = document.createElement('dt');
        dt.className = 'col-6 text-muted fw-normal';
        dt.textContent = label;
        const dd = document.createElement('dd');
        dd.className = 'col-6 mb-1';
        dd.textContent = value ?? '-';
        dl.appendChild(dt);
        dl.appendChild(dd);
    });
    body.appendChild(dl);

    card.appendChild(header);
    card.appendChild(body);
    container.appendChild(card);
}

function _renderDebugChecksCard(container, checks, constraints) {
    const card = document.createElement('div');
    card.className = 'card mb-3';

    const header = document.createElement('div');
    header.className = 'card-header';
    const title = document.createElement('h6');
    title.className = 'mb-0';
    const hIcon = document.createElement('i');
    hIcon.className = 'bi bi-funnel me-1';
    hIcon.setAttribute('aria-hidden', 'true');
    title.appendChild(hIcon);
    title.appendChild(document.createTextNode(tSkyTonightCompat('target_debug_constraints_title')));
    header.appendChild(title);

    const body = document.createElement('div');
    body.className = 'card-body py-0';

    const table = document.createElement('table');
    table.className = 'table table-sm table-borderless mb-0 small align-middle';

    const tbody = document.createElement('tbody');

    const checkLabelKeys = {
        'size_min': 'target_debug_check_size_min',
        'size_max': 'target_debug_check_size_max',
        'moon_separation': 'target_debug_check_moon_separation',
        'max_altitude': 'target_debug_check_max_altitude',
        'observable_fraction': 'target_debug_check_observable_fraction',
    };

    const horizonActive = constraints && constraints.horizon_active;
    const checkSettingKeys = {
        'size_min': ['settings.size_min'],
        'size_max': ['settings.size_max'],
        'moon_separation': ['settings.moon_sep'],
        'max_altitude': ['settings.altitude_min'],
        'observable_fraction': horizonActive
            ? ['settings.time_threshold', 'settings.horizon_profile']
            : ['settings.time_threshold'],
    };

    checks.forEach(check => {
        if (check.name === 'night_window' || check.name === 'coordinates' || check.name === 'altaz_computation') return;

        const isNa = check.note && !check.passed && check.note.includes('filter skipped');
        const tr = document.createElement('tr');

        // Status badge
        const tdStatus = document.createElement('td');
        tdStatus.style.width = '70px';
        const badge = document.createElement('span');
        if (isNa) {
            badge.className = 'badge bg-secondary';
            badge.textContent = tSkyTonightCompat('target_debug_check_na');
        } else if (check.passed) {
            badge.className = 'badge bg-success';
            badge.textContent = tSkyTonightCompat('target_debug_check_pass');
        } else {
            badge.className = 'badge bg-danger';
            badge.textContent = tSkyTonightCompat('target_debug_check_fail');
        }
        tdStatus.appendChild(badge);

        // Constraint name
        const tdName = document.createElement('td');
        const labelKey = checkLabelKeys[check.name] || check.name;
        tdName.textContent = tSkyTonightCompat(labelKey) || labelKey;

        // Value vs threshold
        const tdValue = document.createElement('td');
        tdValue.className = 'text-end text-muted';

        if (check.name === 'observable_fraction') {
            const obsH = check.observable_hours != null ? check.observable_hours.toFixed(1) : '?';
            const frac = check.value != null ? (check.value * 100).toFixed(1) : '?';
            const fracThresh = check.threshold != null ? (check.threshold * 100).toFixed(0) : '?';
            const minHSuffix = check.min_observable_hours != null
                ? ` or ${check.min_observable_hours.toFixed(1)}h`
                : '';
            tdValue.textContent = `${frac}% (${obsH}h) - min ${fracThresh}%${minHSuffix}`;
        } else if (check.name === 'moon_separation') {
            const val = check.value != null ? `${check.value}°` : '?';
            const thr = check.threshold != null ? `${check.threshold}°` : '?';
            const moonPct = check.moon_phase_pct != null ? ` (moon ${check.moon_phase_pct}%)` : '';
            tdValue.textContent = `${val} - min ${thr}${moonPct}`;
        } else {
            const val = check.value != null ? `${check.value}${check.unit || ''}` : (check.note || '-');
            const thr = check.threshold != null ? ` - min ${check.threshold}${check.unit || ''}` : '';
            tdValue.textContent = `${val}${thr}`;
        }

        tr.appendChild(tdStatus);
        tr.appendChild(tdName);
        tr.appendChild(tdValue);
        tbody.appendChild(tr);

        if (!check.passed && !isNa && checkSettingKeys[check.name]) {
            const hintTr = document.createElement('tr');
            const hintTd = document.createElement('td');
            hintTd.setAttribute('colspan', '3');
            hintTd.className = 'pt-0 pb-2';
            const small = document.createElement('small');
            small.className = 'text-muted fst-italic';
            const icon = document.createElement('i');
            icon.className = 'bi bi-gear me-1';
            icon.setAttribute('aria-hidden', 'true');
            const settingLabels = checkSettingKeys[check.name].map(k =>
                (i18n.t(k) || k).replace(/[:\s]+$/, '').trim()
            ).join(', ');
            small.appendChild(icon);
            small.appendChild(document.createTextNode(
                `${tSkyTonightCompat('target_debug_adjust_hint') || 'Adjust:'} ${settingLabels}`
            ));
            hintTd.appendChild(small);
            hintTr.appendChild(hintTd);
            tbody.appendChild(hintTr);
        }
    });

    table.appendChild(tbody);
    body.appendChild(table);
    card.appendChild(header);
    card.appendChild(body);
    container.appendChild(card);
}

function _renderDebugAltimeChart(container, alttimeData, target) {
    const card = document.createElement('div');
    card.className = 'card mb-3';

    const cardHeader = document.createElement('div');
    cardHeader.className = 'card-header';
    const cardTitle = document.createElement('h6');
    cardTitle.className = 'mb-0';
    const hIcon = document.createElement('i');
    hIcon.className = 'bi bi-graph-up-arrow me-1 text-primary';
    hIcon.setAttribute('aria-hidden', 'true');
    cardTitle.appendChild(hIcon);
    const titleText = target && target.preferred_name
        ? `${tSkyTonightCompat('target_debug_altitude_chart_title')} - ${target.preferred_name}`
        : tSkyTonightCompat('target_debug_altitude_chart_title');
    cardTitle.appendChild(document.createTextNode(titleText));
    cardHeader.appendChild(cardTitle);

    const cardBody = document.createElement('div');
    cardBody.className = 'card-body';
    const canvas = document.createElement('canvas');
    canvas.id = 'skyt-debug-alttime-canvas';
    canvas.style.width = '100%';
    canvas.style.height = '280px';
    cardBody.appendChild(canvas);

    // Footer with legend
    const cardFooter = document.createElement('div');
    cardFooter.className = 'card-footer text-muted small';
    const footerRow = document.createElement('div');
    footerRow.className = 'row align-items-center';

    const rootStyle = getComputedStyle(document.documentElement);
    const theme = (document.documentElement.getAttribute('data-theme') || '').toLowerCase();
    const bsTheme = (document.documentElement.getAttribute('data-bs-theme') || '').toLowerCase();
    const isDark = theme === 'dark' || theme === 'red' || bsTheme === 'dark';
    const primaryRgb = rootStyle.getPropertyValue('--bs-primary-rgb').trim() || '13, 110, 253';
    const altColor = `rgba(${primaryRgb}, 0.92)`;
    const zoneColor = 'rgba(20, 110, 40, 0.8)';

    [{ color: altColor, label: tSkyTonightCompat('altitude_time_altitude_label') || 'Altitude (°)' },
    { color: zoneColor, label: tSkyTonightCompat('altitude_time_observable_zone') }].forEach(item => {
        const col = document.createElement('div');
        col.className = 'col-auto';
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.backgroundColor = item.color;
        badge.textContent = item.label;
        col.appendChild(badge);
        footerRow.appendChild(col);
    });

    // Night window text on right
    if (alttimeData.night_start && alttimeData.night_end) {
        const obsTz = alttimeData.timezone || 'UTC';
        const tzFmt = new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', timeZone: obsTz, hour12: false });
        const nightStartFmt = tzFmt.format(new Date(alttimeData.night_start));
        const nightEndFmt = tzFmt.format(new Date(alttimeData.night_end));
        const col = document.createElement('div');
        col.className = 'col-auto ms-auto text-end';
        const span = document.createElement('span');
        span.textContent = `${tSkyTonightCompat('altitude_time_night_window')}: ${nightStartFmt} – ${nightEndFmt}`;
        col.appendChild(span);
        footerRow.appendChild(col);
    }
    cardFooter.appendChild(footerRow);

    card.appendChild(cardHeader);
    card.appendChild(cardBody);
    card.appendChild(cardFooter);
    container.appendChild(card);

    // Build chart data
    const obsTz = alttimeData.timezone || 'UTC';
    const tzFmt2 = new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', timeZone: obsTz, hour12: false });
    const labels = (alttimeData.times_utc || []).map(t => tzFmt2.format(new Date(t + 'Z')));
    const altitudes = alttimeData.altitudes || [];
    const altMin = alttimeData.altitude_constraint_min ?? 30;
    const altMax = alttimeData.altitude_constraint_max ?? 80;
    const yMax = altMax >= 85 ? altMax + 5 : 90;

    const textColor = rootStyle.getPropertyValue('--text-color').trim() || '#1f2937';
    const mutedColor = rootStyle.getPropertyValue('--text-grey').trim() || '#4b4b4b';
    const gridColor = isDark ? 'rgba(255,255,255,0.16)' : 'rgba(15,23,42,0.12)';

    const observableBgPlugin = {
        id: 'debug_alttime_bg',
        beforeDatasetsDraw(chart) {
            const { ctx, chartArea, scales } = chart;
            if (!chartArea) return;
            const yScale = scales.y;
            const { left, right, top, bottom } = chartArea;
            const yMinPx = Math.min(bottom, Math.max(top, yScale.getPixelForValue(altMin)));
            const yMaxPx = Math.min(bottom, Math.max(top, yScale.getPixelForValue(altMax)));
            ctx.save();
            ctx.fillStyle = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.07)';
            if (yMaxPx > top) ctx.fillRect(left, top, right - left, yMaxPx - top);
            if (yMinPx < bottom) ctx.fillRect(left, yMinPx, right - left, bottom - yMinPx);
            ctx.restore();
        },
    };

    if (_debugAlttimeChart) { _debugAlttimeChart.destroy(); _debugAlttimeChart = null; }

    _debugAlttimeChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: tSkyTonightCompat('altitude_time_altitude_label') || 'Altitude (°)',
                    data: altitudes,
                    borderColor: altColor,
                    backgroundColor: `rgba(${primaryRgb}, 0.15)`,
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: tSkyTonightCompat('altitude_time_observable_zone'),
                    data: altitudes.map(() => altMax),
                    borderColor: zoneColor,
                    borderWidth: 1.5,
                    borderDash: [4, 4],
                    pointRadius: 0,
                    fill: false,
                },
                {
                    label: '_floor',
                    data: altitudes.map(() => altMin),
                    borderColor: zoneColor,
                    borderWidth: 1.5,
                    borderDash: [4, 4],
                    pointRadius: 0,
                    fill: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => ctx.dataset.label && ctx.dataset.label !== '_floor'
                            ? `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}°`
                            : null,
                    },
                    filter: (item) => item.dataset.label !== '_floor',
                },
            },
            scales: {
                x: {
                    ticks: { maxTicksLimit: 12, color: mutedColor },
                    grid: { color: gridColor },
                    title: { display: true, text: tSkyTonightCompat('altitude_time_x_axis') || 'Time', color: textColor },
                },
                y: {
                    min: 0,
                    max: yMax,
                    ticks: { stepSize: 15, color: mutedColor },
                    grid: { color: gridColor },
                    title: { display: true, text: tSkyTonightCompat('altitude_time_y_axis') || 'Altitude (°)', color: textColor },
                },
            },
        },
        plugins: [observableBgPlugin],
    });
}

// ======================
// "Tonight for you" recommendations panel (Feature 2)
// ======================

/**
 * Render the difficulty-aware "Tonight for you" recommendations panel into
 * `container`. Used both at the top of the SkyTonight DSO sub-tab and inline
 * in the Guided Setup Wizard's "Tonight" step.
 */
async function renderSkyTonightRecommendationsPanel(container, options = {}) {
    const { limit = 10 } = options;
    if (!container) return;
    DOMUtils.clear(container);

    if (currentUserPreferences?.recommendations_enabled === false) return;

    const card = document.createElement('div');
    card.className = 'card mb-3';

    const header = document.createElement('div');
    header.className = 'card-header';
    const title = document.createElement('h5');
    title.className = 'mb-0';
    DOMUtils.append(title, DOMUtils.createIcon('bi bi-stars text-warning icon-inline'), ' ', i18n.t('recommender.title'));
    header.appendChild(title);
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'card-body';
    body.appendChild(DOMUtils.createSpinnerWrapper(i18n.t('common.loading')));
    card.appendChild(body);
    container.appendChild(card);

    try {
        const lang = i18n.getCurrentLanguage();
        const data = await fetchJSON(`/api/skytonight/recommendations?limit=${limit}&lang=${encodeURIComponent(lang)}`);
        DOMUtils.clear(body);

        const subtitle = document.createElement('p');
        subtitle.className = 'text-muted small mb-3';
        subtitle.textContent = i18n.t('recommender.subtitle');
        body.appendChild(subtitle);

        const targets = data.targets || [];
        if (targets.length === 0) {
            // Nothing to recommend yet (e.g. SkyTonight hasn't calculated tonight's results) -
            // hide the whole panel rather than showing an empty-state card.
            DOMUtils.clear(container);
            return;
        }

        const strip = document.createElement('div');
        strip.className = 'd-flex flex-nowrap gap-2 pb-2';
        strip.style.overflowX = 'auto';
        targets.forEach((target) => strip.appendChild(_buildRecommendationCard(target)));
        body.appendChild(strip);
    } catch (err) {
        console.error('Error loading SkyTonight recommendations:', err);
        DOMUtils.clear(body);
        const errAlert = document.createElement('div');
        errAlert.className = 'alert alert-danger mb-0';
        errAlert.textContent = i18n.t('recommender.empty');
        body.appendChild(errAlert);
    }
}
window.renderSkyTonightRecommendationsPanel = renderSkyTonightRecommendationsPanel;

function _buildRecommendationCard(target) {
    const identifier = target.id || target.messier || target.preferred_name;

    const card = document.createElement('div');
    card.className = 'card';
    // Grow to fill the strip on wide screens (no leftover blank space); never
    // shrink below 160px so small/mobile screens keep the horizontal scroll.
    card.style.flex = '1 0 160px';
    card.style.maxWidth = '220px';

    // ── Thumbnail (clickable -> Object Information modal) ──────────────────
    const thumbBtn = document.createElement('button');
    thumbBtn.type = 'button';
    thumbBtn.className = 'btn p-0 border-0 bg-transparent w-100';
    thumbBtn.disabled = !identifier;
    const img = document.createElement('img');
    img.className = 'card-img-top';
    img.style.height = '90px';
    img.style.objectFit = 'cover';
    img.loading = 'lazy';
    img.alt = target.preferred_name || '';
    img.style.display = 'none';
    thumbBtn.appendChild(img);
    _loadCardThumbnail(img, target.thumbnail_url, identifier);
    if (identifier) {
        thumbBtn.addEventListener('click', () => {
            if (typeof showObjectInfoModal === 'function') showObjectInfoModal(identifier);
        });
    }
    card.appendChild(thumbBtn);

    const body = document.createElement('div');
    body.className = 'card-body p-2 d-flex flex-column';

    // ── Name + Messier label ────────────────────────────────────────────────
    const nameRow = document.createElement('div');
    nameRow.className = 'd-flex align-items-center flex-wrap gap-1 mb-1';
    const nameLink = document.createElement('a');
    nameLink.href = '#';
    nameLink.className = 'fw-semibold small link-underline link-underline-opacity-0 text-truncate';
    nameLink.style.maxWidth = '100%';
    nameLink.title = target.preferred_name || '';
    nameLink.textContent = target.preferred_name || '';
    if (identifier) {
        nameLink.addEventListener('click', (e) => {
            e.preventDefault();
            if (typeof showObjectInfoModal === 'function') showObjectInfoModal(identifier);
        });
    }
    nameRow.appendChild(nameLink);
    if (target.messier) {
        const messierBadge = document.createElement('span');
        messierBadge.className = 'messier-badge';
        messierBadge.title = target.messier;
        messierBadge.textContent = target.messier;
        nameRow.appendChild(messierBadge);
    }
    body.appendChild(nameRow);

    // ── Badges ───────────────────────────────────────────────────────────────
    const badgeRow = document.createElement('div');
    badgeRow.className = 'd-flex flex-wrap gap-1 mb-1';
    badgeRow.style.minWidth = '0';
    const typeBadge = document.createElement('span');
    typeBadge.className = 'badge bg-secondary text-truncate d-inline-block';
    typeBadge.style.maxWidth = '100%';
    typeBadge.style.minWidth = '0';
    typeBadge.style.verticalAlign = 'bottom';
    const typeTranslationKey = `skytonight.type_${strToTranslateKey(target.object_type || '')}`;
    const typeLabel = i18n.has(typeTranslationKey) ? i18n.t(typeTranslationKey) : (target.object_type || '-');
    typeBadge.title = typeLabel;
    typeBadge.textContent = typeLabel;
    badgeRow.appendChild(typeBadge);
    badgeRow.appendChild(createDifficultyBadgeNode(target.difficulty));
    if (target.in_astrodex) badgeRow.appendChild(_buildCapturedBadge());
    body.appendChild(badgeRow);

    // ── Integration estimate ────────────────────────────────────────────────
    const integration = document.createElement('div');
    integration.className = 'text-muted small mb-2';
    integration.style.cursor = 'help';
    const hoursLabel = target.estimated_integration_hours_is_estimate
        ? `~${target.estimated_integration_hours}h`
        : `${target.estimated_integration_hours}h`;
    integration.title = target.estimated_integration_hours_is_estimate
        ? i18n.t('recommender.integration_estimated_tooltip')
        : i18n.t('recommender.integration_catalog_tooltip');
    DOMUtils.append(integration, DOMUtils.createIcon('bi bi-clock-history icon-inline'), ` ${hoursLabel}`);
    body.appendChild(integration);

    // ── Add to Plan ──────────────────────────────────────────────────────────
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-sm btn-outline-primary w-100 mt-auto';
    if (target.in_plan) {
        addBtn.textContent = i18n.t('recommender.add_to_plan_done');
        addBtn.disabled = true;
    } else {
        addBtn.textContent = i18n.t('recommender.add_to_plan');
        addBtn.addEventListener('click', async () => {
            addBtn.disabled = true;
            try {
                const telescopeSelection = await _resolvePlanTelescopeSelection(target);
                if (!telescopeSelection) { addBtn.disabled = false; return; } // user cancelled the telescope picker
                await fetchJSON('/api/plan-my-night/targets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        item: {
                            name: target.preferred_name,
                            catalogue: target.catalogue,
                            type: target.object_type,
                            constellation: target.constellation,
                            ra: target.coordinates?.ra_hours,
                            dec: target.coordinates?.dec_degrees,
                            mag: target.magnitude,
                            size: target.size_arcmin,
                            difficulty: target.difficulty,
                            alttime_file: target.target_id,
                            source_type: 'recommendation',
                        },
                        catalogue: target.catalogue,
                        telescope_id: telescopeSelection.telescope_id,
                        telescope_name: telescopeSelection.telescope_name,
                    }),
                });
                addBtn.textContent = i18n.t('recommender.add_to_plan_done');
                showMessage('success', i18n.t('plan_my_night.target_added'));
                updateCataloguePlanMyNightBadge(target.preferred_name, true);
                updateCataloguePlanMyNightData(target.preferred_name, true);
            } catch (err) {
                console.error('Error adding recommendation to plan:', err);
                addBtn.disabled = false;
                showMessage('error', i18n.t('plan_my_night.failed_to_add_target'));
            }
        });
    }
    body.appendChild(addBtn);

    card.appendChild(body);
    return card;
}

// ======================
// Beginner Catalog sub-tab (Feature 3)
// ======================

const _beginnerCatalogState = {
    objects: [],
    visibleOnly: true,
    difficultyFilter: '',
    typeFilter: '',
};

async function _showBeginnerCatalogSection(container) {
    DOMUtils.clear(container);
    container.appendChild(DOMUtils.createSpinnerWrapper(i18n.t('common.loading')));

    try {
        const lang = i18n.getCurrentLanguage();
        const visibleOnlyParam = _beginnerCatalogState.visibleOnly ? 'true' : 'false';
        const data = await fetchJSON(`/api/beginner-catalog?lang=${encodeURIComponent(lang)}&visible_only=${visibleOnlyParam}`);
        _beginnerCatalogState.objects = data.objects || [];
        _renderBeginnerCatalogUI(container);
    } catch (err) {
        console.error('Error loading beginner catalog:', err);
        DOMUtils.clear(container);
        const errAlert = document.createElement('div');
        errAlert.className = 'alert alert-danger';
        errAlert.textContent = i18n.t('common.error');
        container.appendChild(errAlert);
    }
}

function _renderBeginnerCatalogUI(container) {
    DOMUtils.clear(container);

    const header = document.createElement('div');
    header.className = 'mb-3';
    const title = document.createElement('h5');
    title.textContent = i18n.t('beginner_catalog.title');
    const subtitle = document.createElement('p');
    subtitle.className = 'text-muted small mb-0';
    subtitle.textContent = i18n.t('beginner_catalog.subtitle');
    header.appendChild(title);
    header.appendChild(subtitle);
    container.appendChild(header);

    const filterRow = document.createElement('div');
    filterRow.className = 'row g-2 align-items-center mb-3';

    const visibleCol = document.createElement('div');
    visibleCol.className = 'col-auto';
    const visibleCheckWrap = document.createElement('div');
    visibleCheckWrap.className = 'form-check form-switch';
    const visibleCheck = document.createElement('input');
    visibleCheck.className = 'form-check-input';
    visibleCheck.type = 'checkbox';
    visibleCheck.id = 'beginner-catalog-visible-toggle';
    visibleCheck.checked = _beginnerCatalogState.visibleOnly;
    const visibleLabel = document.createElement('label');
    visibleLabel.className = 'form-check-label';
    visibleLabel.htmlFor = 'beginner-catalog-visible-toggle';
    visibleLabel.textContent = i18n.t('beginner_catalog.filter_visible');
    visibleCheckWrap.appendChild(visibleCheck);
    visibleCheckWrap.appendChild(visibleLabel);
    visibleCol.appendChild(visibleCheckWrap);
    filterRow.appendChild(visibleCol);

    const difficultyCol = document.createElement('div');
    difficultyCol.className = 'col-auto';
    const difficultySelect = document.createElement('select');
    difficultySelect.className = 'form-select form-select-sm';
    difficultySelect.id = 'beginner-catalog-difficulty-filter';
    const diffNoneOpt = document.createElement('option');
    diffNoneOpt.value = '';
    diffNoneOpt.textContent = i18n.t('beginner_catalog.filter_difficulty');
    difficultySelect.appendChild(diffNoneOpt);
    // Only offer difficulties up to the user's own experience level (a beginner-level user has no
    // reason to filter a beginner catalog down to "advanced"), and only ones actually present in
    // the fetched objects - otherwise a level-appropriate option could still yield an empty grid.
    const _DIFFICULTY_ORDER = ['beginner', 'intermediate', 'advanced'];
    const userLevel = currentUserPreferences?.experience_level;
    const maxLevelIndex = _DIFFICULTY_ORDER.includes(userLevel) ? _DIFFICULTY_ORDER.indexOf(userLevel) : _DIFFICULTY_ORDER.length - 1;
    const presentDifficulties = new Set(_beginnerCatalogState.objects.map((o) => o.difficulty).filter(Boolean));
    const allowedDifficulties = _DIFFICULTY_ORDER.slice(0, maxLevelIndex + 1).filter((d) => presentDifficulties.has(d));
    allowedDifficulties.forEach((d) => {
        const opt = document.createElement('option');
        opt.value = d;
        opt.textContent = i18n.t(`difficulty.${d}`);
        difficultySelect.appendChild(opt);
    });
    if (!allowedDifficulties.includes(_beginnerCatalogState.difficultyFilter)) {
        _beginnerCatalogState.difficultyFilter = '';
    }
    difficultySelect.value = _beginnerCatalogState.difficultyFilter;
    difficultyCol.appendChild(difficultySelect);
    filterRow.appendChild(difficultyCol);

    const typeCol = document.createElement('div');
    typeCol.className = 'col-auto';
    const typeSelect = document.createElement('select');
    typeSelect.className = 'form-select form-select-sm';
    typeSelect.id = 'beginner-catalog-type-filter';
    const typeNoneOpt = document.createElement('option');
    typeNoneOpt.value = '';
    typeNoneOpt.textContent = i18n.t('beginner_catalog.filter_type');
    typeSelect.appendChild(typeNoneOpt);
    const distinctTypes = [...new Set(_beginnerCatalogState.objects.map((o) => o.object_type).filter(Boolean))].sort();
    distinctTypes.forEach((t) => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        typeSelect.appendChild(opt);
    });
    typeSelect.value = _beginnerCatalogState.typeFilter;
    typeCol.appendChild(typeSelect);
    filterRow.appendChild(typeCol);

    container.appendChild(filterRow);

    const gridContainer = document.createElement('div');
    gridContainer.id = 'beginner-catalog-grid';
    gridContainer.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-4 g-3';
    container.appendChild(gridContainer);

    _renderBeginnerCatalogGrid(gridContainer);

    visibleCheck.addEventListener('change', () => {
        _beginnerCatalogState.visibleOnly = visibleCheck.checked;
        _showBeginnerCatalogSection(container);
    });
    difficultySelect.addEventListener('change', () => {
        _beginnerCatalogState.difficultyFilter = difficultySelect.value;
        _renderBeginnerCatalogGrid(gridContainer);
    });
    typeSelect.addEventListener('change', () => {
        _beginnerCatalogState.typeFilter = typeSelect.value;
        _renderBeginnerCatalogGrid(gridContainer);
    });
}

function _renderBeginnerCatalogGrid(gridContainer) {
    DOMUtils.clear(gridContainer);
    let objects = _beginnerCatalogState.objects;
    if (_beginnerCatalogState.difficultyFilter) {
        objects = objects.filter((o) => o.difficulty === _beginnerCatalogState.difficultyFilter);
    }
    if (_beginnerCatalogState.typeFilter) {
        objects = objects.filter((o) => o.object_type === _beginnerCatalogState.typeFilter);
    }

    if (objects.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'col-12';
        const alert = document.createElement('div');
        alert.className = 'alert alert-info';
        alert.textContent = i18n.t('beginner_catalog.empty_tonight');
        empty.appendChild(alert);
        gridContainer.appendChild(empty);
        return;
    }

    objects.forEach((obj) => gridContainer.appendChild(_buildBeginnerCatalogCard(obj)));
}

function _buildBeginnerCatalogCard(obj) {
    const col = document.createElement('div');
    col.className = 'col';

    const card = document.createElement('div');
    card.className = 'card h-100';
    if (obj.in_astrodex) card.classList.add('border-success');

    const img = document.createElement('img');
    img.className = 'card-img-top';
    img.style.maxHeight = '140px';
    img.style.objectFit = 'cover';
    img.loading = 'lazy';
    img.alt = obj.preferred_name || '';
    img.style.display = 'none';
    card.appendChild(img);
    _loadCardThumbnail(img, obj.thumbnail_url, obj.catalogue_id || obj.preferred_name);

    const body = document.createElement('div');
    body.className = 'card-body';

    const name = document.createElement('h6');
    name.className = 'card-title mb-1';
    name.textContent = obj.preferred_name || '';
    body.appendChild(name);

    const badgeRow = document.createElement('div');
    badgeRow.className = 'd-flex flex-wrap gap-1 mb-2';
    const typeBadge = document.createElement('span');
    typeBadge.className = 'badge bg-secondary';
    const typeTranslationKey = `skytonight.type_${strToTranslateKey(obj.object_type || '')}`;
    typeBadge.textContent = i18n.has(typeTranslationKey) ? i18n.t(typeTranslationKey) : (obj.object_type || '-');
    badgeRow.appendChild(typeBadge);
    badgeRow.appendChild(createDifficultyBadgeNode(obj.difficulty));
    if (obj.constellation) {
        const constBadge = document.createElement('span');
        constBadge.className = 'badge bg-light text-dark border';
        constBadge.textContent = typeof getConstellationDisplayName === 'function'
            ? getConstellationDisplayName(obj.constellation)
            : obj.constellation;
        badgeRow.appendChild(constBadge);
    }
    if (obj.in_astrodex) badgeRow.appendChild(_buildCapturedBadge());
    body.appendChild(badgeRow);

    const visibility = document.createElement('div');
    visibility.className = `small mb-2 ${obj.visible_tonight ? 'text-success' : 'text-muted'}`;
    visibility.textContent = obj.visible_tonight
        ? i18n.t('beginner_catalog.visible_tonight')
        : i18n.t('beginner_catalog.not_visible');
    body.appendChild(visibility);

    if (obj.why_beginner) {
        const whyLabel = document.createElement('div');
        whyLabel.className = 'fw-semibold small mt-2';
        whyLabel.textContent = i18n.t('beginner_catalog.why_beginner_label');
        const why = document.createElement('p');
        why.className = 'small mb-2';
        why.textContent = obj.why_beginner;
        body.appendChild(whyLabel);
        body.appendChild(why);
    }

    if (obj.suggested_framing) {
        const framingLabel = document.createElement('div');
        framingLabel.className = 'fw-semibold small';
        framingLabel.textContent = i18n.t('beginner_catalog.suggested_framing_label');
        const framing = document.createElement('p');
        framing.className = 'small mb-2';
        framing.textContent = obj.suggested_framing;
        body.appendChild(framingLabel);
        body.appendChild(framing);
    }

    const integration = document.createElement('div');
    integration.className = 'text-muted small mb-3';
    integration.textContent = `${i18n.t('beginner_catalog.integration_time')}: ${obj.typical_integration_hours}h`;
    body.appendChild(integration);

    const ctaRow = document.createElement('div');
    ctaRow.className = 'd-flex gap-2';

    const captureBtn = document.createElement('button');
    captureBtn.type = 'button';
    captureBtn.className = 'btn btn-sm btn-outline-success flex-fill';
    if (obj.in_astrodex) {
        captureBtn.textContent = i18n.t('beginner_catalog.captured');
        captureBtn.disabled = true;
    } else {
        captureBtn.textContent = i18n.t('beginner_catalog.mark_captured');
        captureBtn.addEventListener('click', () => _beginnerCatalogAddToAstrodex(obj, captureBtn));
    }
    ctaRow.appendChild(captureBtn);

    const planBtn = document.createElement('button');
    planBtn.type = 'button';
    planBtn.className = 'btn btn-sm btn-outline-primary flex-fill';
    if (obj.in_plan) {
        planBtn.textContent = i18n.t('beginner_catalog.in_plan');
        planBtn.disabled = true;
    } else {
        planBtn.textContent = i18n.t('beginner_catalog.plan_it');
        planBtn.addEventListener('click', () => _beginnerCatalogAddToPlan(obj, planBtn));
    }
    ctaRow.appendChild(planBtn);

    body.appendChild(ctaRow);
    card.appendChild(body);
    col.appendChild(card);
    return col;
}

async function _beginnerCatalogAddToAstrodex(obj, buttonEl) {
    buttonEl.disabled = true;
    try {
        const response = await fetchJSON('/api/astrodex/items', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: obj.preferred_name,
                catalogue: obj.catalogue_id,
                type: obj.object_type,
                constellation: (obj.constellation || '').toLowerCase(),
            }),
        });
        if (response && response.status === 'success') {
            obj.in_astrodex = true;
            buttonEl.textContent = i18n.t('beginner_catalog.captured');
        }
    } catch (err) {
        console.error('Error adding beginner catalog item to Astrodex:', err);
        buttonEl.disabled = false;
        showMessage('error', tSkyTonightCompat('failed_to_add_astrodex'));
    }
}

async function _beginnerCatalogAddToPlan(obj, buttonEl) {
    buttonEl.disabled = true;
    try {
        const telescopeSelection = await _resolvePlanTelescopeSelection(obj);
        if (!telescopeSelection) { buttonEl.disabled = false; return; } // user cancelled the telescope picker
        const response = await fetchJSON('/api/plan-my-night/targets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                item: {
                    name: obj.preferred_name,
                    catalogue: obj.catalogue_id,
                    type: obj.object_type,
                    constellation: (obj.constellation || '').toLowerCase(),
                    ra: obj.ra_hours,
                    dec: obj.dec_degrees,
                    difficulty: obj.difficulty,
                    alttime_file: obj.alttime_file || '',
                },
                catalogue: obj.catalogue_id,
                telescope_id: telescopeSelection.telescope_id,
                telescope_name: telescopeSelection.telescope_name,
            }),
        });
        if (response && response.status === 'success') {
            obj.in_plan = true;
            buttonEl.textContent = i18n.t('beginner_catalog.in_plan');
            showMessage('success', i18n.t('plan_my_night.target_added'));
            updateCataloguePlanMyNightBadge(obj.preferred_name, true);
            updateCataloguePlanMyNightData(obj.preferred_name, true);
        }
    } catch (err) {
        console.error('Error adding beginner catalog item to Plan My Night:', err);
        buttonEl.disabled = false;
        showMessage('error', i18n.t('plan_my_night.failed_to_add_target'));
    }
}

async function _showSkyTonightDataSection(sectionKey, container) {
    const displayAstrodex = await getSkyTonightDisplayAstrodex();

    DOMUtils.clear(container);
    // Show loading indicator
    const loading = document.createElement('div');
    loading.className = 'alert alert-info';
    loading.textContent = i18n.t('common.loading');
    container.appendChild(loading);

    try {
        let data;
        if (_skytSectionCache[sectionKey]) {
            data = _skytSectionCache[sectionKey];
        } else {
            const endpoint = {
                report: '/api/skytonight/data/dso',
                bodies: '/api/skytonight/data/bodies',
                comets: '/api/skytonight/data/comets',
            }[sectionKey];
            data = await fetchJSON(endpoint);
            if (data.error) throw new Error(data.error);
            _skytSectionCache[sectionKey] = data;
            _skytCurrentPages[sectionKey] = 0; // reset to first page when loading fresh data
            _skytFilteredData[sectionKey] = null; // clear any previous filter
            delete _skytFilterState[sectionKey];  // clear saved filter state

            // Keep window.catalogueReports in sync for badge update functions
            window.catalogueReports = window.catalogueReports || {};
            window.catalogueReportSources = window.catalogueReportSources || {};
            if (!window.catalogueReports['SkyTonight']) {
                window.catalogueReports['SkyTonight'] = { report: [], bodies: [], comets: [] };
            }
            if (sectionKey === 'report') window.catalogueReports['SkyTonight'].report = data.report || [];
            if (sectionKey === 'bodies') window.catalogueReports['SkyTonight'].bodies = data.bodies || [];
            if (sectionKey === 'comets') window.catalogueReports['SkyTonight'].comets = data.comets || [];
            window.catalogueReportSources['SkyTonight'] = 'skytonight';
        }

        DOMUtils.clear(container);

        // "Tonight for you" recommendations panel, injected above the filters/table on the DSO tab only.
        if (sectionKey === 'report') {
            const recoContainer = document.createElement('div');
            recoContainer.id = 'skytonight-recommendations-panel';
            container.appendChild(recoContainer);
            renderSkyTonightRecommendationsPanel(recoContainer);
        }

        // Banner when a calculation is still running
        if (data.in_progress) {
            const banner = document.createElement('div');
            banner.className = 'alert alert-warning d-flex align-items-center gap-2 mb-2';
            const _spinner0 = document.createElement('span');
            _spinner0.className = 'spinner-border spinner-border-sm';
            _spinner0.setAttribute('role', 'status');
            _spinner0.setAttribute('aria-hidden', 'true');
            banner.appendChild(_spinner0);
            banner.appendChild(document.createTextNode(tSkyTonightCompat('calculation_in_progress')));
            container.appendChild(banner);
        }

        const dataKey = { report: 'report', bodies: 'bodies', comets: 'comets' }[sectionKey];
        const tableData = data[dataKey];

        if (!tableData || tableData.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'alert alert-info mt-3';
            const noNightFound = data.night_metadata && data.night_metadata.night_found === false;
            empty.textContent = noNightFound
                ? tSkyTonightCompat('no_nautical_night')
                : data.available
                    ? tSkyTonightCompat('no_target_in_report')
                    : tSkyTonightCompat('no_data_available');
            container.appendChild(empty);
            appendDataSourceFooter(container, {
                text: tSkyTonightCompat('footer_source')
            });
            return;
        }

        // Solar elongation info box - only on the Bodies sub-tab
        if (sectionKey === 'bodies') {
            const infoBox = document.createElement('div');
            infoBox.className = 'alert alert-info d-flex flex-column gap-2 mb-3';

            const infoRow = document.createElement('div');
            infoRow.className = 'd-flex align-items-start gap-2';
            const infoIcon = document.createElement('i');
            infoIcon.className = 'bi bi-info-circle-fill flex-shrink-0 mt-1';
            infoIcon.setAttribute('aria-hidden', 'true');
            const infoText = document.createElement('span');
            infoText.textContent = tSkyTonightCompat('bodies_elongation_info');
            infoRow.appendChild(infoIcon);
            infoRow.appendChild(infoText);

            const scaleRow = document.createElement('div');
            scaleRow.className = 'd-flex flex-wrap gap-2';
            const scale = [
                { cls: 'astroscore-badge astroscore-badge-exceptional', key: 'bodies_elongation_scale_excellent' },
                { cls: 'astroscore-badge astroscore-badge-good', key: 'bodies_elongation_scale_good' },
                { cls: 'astroscore-badge astroscore-badge-average', key: 'bodies_elongation_scale_average' },
                { cls: 'astroscore-badge astroscore-badge-poor', key: 'bodies_elongation_scale_poor' },
            ];
            scale.forEach(({ cls, key }) => {
                const badge = document.createElement('span');
                badge.className = `badge ${cls}`;
                badge.textContent = tSkyTonightCompat(key);
                scaleRow.appendChild(badge);
            });

            infoBox.appendChild(infoRow);
            infoBox.appendChild(scaleRow);
            container.appendChild(infoBox);
        }

        const tableType = sectionKey === 'report' ? 'report' : sectionKey;
        const currentPage = _skytCurrentPages[sectionKey] || 0;
        const tableHtml = generateReportTable(tableData, 'SkyTonight', tableType, displayAstrodex, currentPage);
        const fragment = document.createRange().createContextualFragment(tableHtml);
        container.appendChild(fragment);
        appendDataSourceFooter(container, {
            text: tSkyTonightCompat('footer_source')
        });

    } catch (err) {
        console.error('Error loading SkyTonight section:', sectionKey, err);
        DOMUtils.clear(container);
        const errAlert = document.createElement('div');
        errAlert.className = 'alert alert-danger mt-3';
        errAlert.textContent = tSkyTonightCompat('failed_to_load_catalogue_results');
        container.appendChild(errAlert);
    }
}

// ======================
// Report Table Generation
// ======================

/**
 * Build Bootstrap 5.3 pagination bar for a table section.
 * Renders a footer row: item count on the left, icon-based page buttons on the right.
 */
function _buildPaginationHtml(catalogue, type, page, totalPages, totalItems) {
    const startItem = page * SKYT_PAGE_SIZE + 1;
    const endItem = Math.min((page + 1) * SKYT_PAGE_SIZE, totalItems);
    const atFirst = page === 0;
    const atLast = page >= totalPages - 1;
    const esc = escapeHtml;

    const btn = (iconClass, targetPage, disabled, ariaLabel) =>
        `<li class="page-item${disabled ? ' disabled' : ''}">` +
        `<a class="page-link skyt-page-btn" href="#" aria-label="${esc(ariaLabel)}" ` +
        `data-catalogue="${esc(catalogue)}" data-type="${esc(type)}" data-page="${targetPage}">` +
        `<i class="bi ${esc(iconClass)}" aria-hidden="true"></i>` +
        `</a></li>`;

    // Numbered page buttons: show up to 5 pages centred around the current page
    const WIN = 2;
    const rangeStart = Math.max(0, Math.min(page - WIN, totalPages - 2 * WIN - 1));
    const rangeEnd = Math.min(totalPages - 1, rangeStart + 2 * WIN);
    let pageButtons = '';
    for (let p = rangeStart; p <= rangeEnd; p++) {
        pageButtons +=
            `<li class="page-item${p === page ? ' active' : ''}">` +
            `<a class="page-link skyt-page-btn" href="#" ` +
            `data-catalogue="${esc(catalogue)}" data-type="${esc(type)}" data-page="${p}">${p + 1}</a></li>`;
    }

    const countLabel =
        `<span class="skyt-pagination-count text-muted small">` +
        `${startItem}\u2013${endItem} <span class="opacity-50">/</span> ${totalItems}</span>`;

    return (
        `<div class="skyt-pagination-bar d-flex flex-wrap justify-content-between align-items-center gap-2 mt-2 pt-2 border-top">` +
        countLabel +
        `<nav aria-label="${esc(tSkyTonightCompat('table_pagination') || 'Pagination')}">` +
        `<ul class="pagination pagination-sm mb-0 gap-1">` +
        btn('bi-chevron-double-left', 0, atFirst, 'First') +
        btn('bi-chevron-left', page - 1, atFirst, 'Previous') +
        pageButtons +
        btn('bi-chevron-right', page + 1, atLast, 'Next') +
        btn('bi-chevron-double-right', totalPages - 1, atLast, 'Last') +
        `</ul></nav>` +
        `</div>`
    );
}

/**
 * Lazily build and show the "More" popup from pre-stored row data
 * (replaces the old pre-generated hidden-div approach).
 */
async function showMorePopupFromRowData(moreData) {
    const { type, moreFields, row } = moreData;

    const titleEl = document.getElementById('modal_lg_close_title');
    if (titleEl) titleEl.textContent = tSkyTonightCompat('more_info');

    const contentEl = document.getElementById('modal_lg_close_body');
    if (!contentEl) return;
    DOMUtils.clear(contentEl);

    const tableDiv = document.createElement('div');
    tableDiv.className = 'table-responsive';
    const table = document.createElement('table');
    table.className = 'table table-striped';
    const tbody = document.createElement('tbody');

    moreFields.forEach(field => {
        let value = row[field];

        // Special handling: catalogue_names dict → one row per entry
        if (field === 'catalogue_names') {
            if (value && typeof value === 'object') {
                const entries = Object.entries(value);
                if (entries.length > 0) {
                    const headerTr = document.createElement('tr');
                    const headerTd = document.createElement('td');
                    headerTd.colSpan = 2;
                    headerTd.className = 'more-section-header fw-semibold text-muted small pt-2';
                    headerTd.textContent = tSkyTonightCompat('catalogue_names');
                    headerTr.appendChild(headerTd);
                    tbody.appendChild(headerTr);
                    entries.forEach(([catName, catValue]) => {
                        if (catValue) {
                            const tr = document.createElement('tr');
                            const td1 = document.createElement('td');
                            td1.className = 'more-label';
                            const translatedCatName = (catName === 'CommonName' && i18n.has('astrodex.catalogue_label_commonname'))
                                ? i18n.t('astrodex.catalogue_label_commonname')
                                : catName;
                            td1.textContent = translatedCatName;
                            const td2 = document.createElement('td');
                            td2.className = 'more-value';
                            td2.textContent = String(catValue);
                            tr.appendChild(td1);
                            tr.appendChild(td2);
                            tbody.appendChild(tr);
                        }
                    });
                }
            }
            return;
        }

        let label = field.charAt(0).toUpperCase() + field.slice(1);
        const labelKey = 'skytonight.' + strToTranslateKey(label);
        if (i18n.has(labelKey)) {
            label = i18n.t(labelKey);
        } else {
            console.warn(`Missing translation for: ${labelKey}`);
        }

        const hasValue = value !== null && value !== undefined && value !== '';
        let displayValue = hasValue ? String(value) : '-';

        // Comet-specific field formatting
        if (type === 'comets') {
            if (field === 'absolute magnitude' && hasValue && !isNaN(value)) {
                displayValue = parseFloat(value).toFixed(2);
            } else if (field === 'distance sun au') {
                label = tSkyTonightCompat('distance_sun');
                if (hasValue && !isNaN(value)) displayValue = parseFloat(value).toFixed(2) + ' au';
            } else if (field === 'distance earth au') {
                if (hasValue && !isNaN(value)) displayValue = parseFloat(value).toFixed(2) + ' au';
            }
        }

        const tr = document.createElement('tr');
        const td1 = document.createElement('td');
        td1.className = 'more-label';
        td1.textContent = label;
        const td2 = document.createElement('td');
        td2.className = 'more-value';
        td2.textContent = displayValue;
        tr.appendChild(td1);
        tr.appendChild(td2);
        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    tableDiv.appendChild(table);
    contentEl.appendChild(tableDiv);

    const _modalEl1 = document.getElementById('modal_lg_close');
    let bs_modal = bootstrap.Modal.getInstance(_modalEl1);
    if (!bs_modal) {
        bs_modal = new bootstrap.Modal(_modalEl1, { backdrop: true, focus: true, keyboard: true });
    }
    bs_modal.show();

    const hasCombinations = await _skytUserHasCombinations();
    if (!hasCombinations) {
        return;
    }

    const recoContainer = document.createElement('div');
    recoContainer.className = 'mt-3 pt-3 border-top';
    const _loadDiv = document.createElement('div');
    _loadDiv.className = 'text-muted small';
    _loadDiv.textContent = tSkyTonightCompat('loading_report_content');
    recoContainer.appendChild(_loadDiv);
    contentEl.appendChild(recoContainer);

    const response = await _skytFetchCombinationRecommendations(row);
    if (!response) {
        DOMUtils.clear(recoContainer);
        const _errDiv = document.createElement('div');
        _errDiv.className = 'text-danger small';
        _errDiv.textContent = tSkyTonightCompat('combination_reco_load_error');
        recoContainer.appendChild(_errDiv);
        return;
    }

    const _recoEl = _skytBuildCombinationRecommendationsHtml(response, row);
    if (_recoEl) {
        recoContainer.replaceWith(_recoEl);
    } else {
        recoContainer.remove();
    }
}

/**
 * Apply filters to the full cached dataset for a SkyTonight section, then re-render.
 * Falls back to the standard DOM row-hide filterTable() for non-paginated sections.
 */
function _skytApplyFilter(catalogue, type) {
    if (catalogue !== 'SkyTonight' || !_skytSectionCache[type]) {
        filterTable(catalogue, type);
        return;
    }

    const filterInput = document.getElementById(`filter-${catalogue}-${type}`);
    const fotoCheckbox = document.getElementById(`foto-filter-${catalogue}-${type}`);
    const fotoValueInput = document.getElementById(`foto-value-${catalogue}-${type}`);
    const constellationSelect = document.getElementById(`constellation-filter-${catalogue}-${type}`);
    const typeSelect = document.getElementById(`type-filter-${catalogue}-${type}`);
    const catalogueSelect = document.getElementById(`catalogue-filter-${catalogue}-${type}`);
    const difficultySelect = document.getElementById(`difficulty-filter-${catalogue}-${type}`);

    const filterRaw = filterInput ? filterInput.value : '';
    const filterText = filterRaw.trim().toLowerCase();
    const fotoEnabled = fotoCheckbox ? fotoCheckbox.checked : false;
    const fotoThreshold = fotoValueInput ? parseFloat(sanitizeFotoFilterValue(fotoValueInput.value)) / 100 : 0.8;
    const constellation = constellationSelect ? constellationSelect.value : '';
    const typeVal = typeSelect ? typeSelect.value : '';
    const catalogueVal = catalogueSelect ? catalogueSelect.value : '';
    const difficultyVal = difficultySelect ? difficultySelect.value : '';

    // Persist state so it survives pagination re-renders.
    // filterRaw preserves the original un-trimmed value so it can be restored
    // exactly as typed if the user revisits the section.
    _skytFilterState[type] = { filterText, filterRaw, fotoEnabled, fotoThreshold, constellation, typeVal, catalogueVal, difficultyVal };

    const hasFilter = filterText || fotoEnabled || constellation || typeVal || catalogueVal || difficultyVal;
    const fullData = _skytSectionCache[type][type];
    if (!Array.isArray(fullData)) return;

    if (!hasFilter) {
        _skytFilteredData[type] = null;
        _skytCurrentPages[type] = 0;
        _reRenderTablePage(type, 0);
        return;
    }

    _skytFilteredData[type] = fullData.filter(row => {
        if (filterText) {
            let haystack = Object.entries(row)
                .filter(([k]) => k !== 'catalogue_names')
                .map(([, v]) => (v !== null && v !== undefined ? String(v) : ''))
                .join(' ')
                .toLowerCase();
            const catNames = row.catalogue_names;
            if (catNames && typeof catNames === 'object') {
                haystack += ' ' + Object.values(catNames).filter(Boolean).join(' ').toLowerCase();
            }
            if (!haystack.includes(filterText)) return false;
        }
        if (fotoEnabled) {
            const fotoVal = parseFloat(row['foto'] ?? row['fraction of time observable'] ?? 0);
            if (isNaN(fotoVal) || fotoVal < fotoThreshold) return false;
        }
        if (constellation && (row.constellation || '') !== constellation) return false;
        if (typeVal && (row.type || '') !== typeVal) return false;
        if (catalogueVal && !(row.catalogue_names && row.catalogue_names[catalogueVal])) return false;
        if (difficultyVal && (row.difficulty || '') !== difficultyVal) return false;
        return true;
    });

    _skytCurrentPages[type] = 0;
    _reRenderTablePage(type, 0);
}

/**
 * Re-render a tabular section at the given page number.
 * Used by pagination buttons after the initial render.
 */
async function _reRenderTablePage(sectionKey, page) {
    const dataDiv = document.getElementById(`skytonight-${sectionKey}-data`);
    if (!dataDiv) return;

    const cachedData = _skytSectionCache[sectionKey];
    if (!cachedData) return;

    const displayAstrodex = await getSkyTonightDisplayAstrodex();
    // Use filtered data if a filter is active, otherwise the full cached array
    const isFiltered = _skytFilteredData[sectionKey] !== null && _skytFilteredData[sectionKey] !== undefined;
    const tableData = isFiltered ? _skytFilteredData[sectionKey] : cachedData[sectionKey];

    // Target only the table sub-div so the filter controls in skyt-ctrl-… are
    // never cleared - the filter input keeps its DOM node, its value, and focus
    // across every filter/pagination re-render.
    const tableType = sectionKey === 'report' ? 'report' : sectionKey;
    const tblDiv = document.getElementById(`skyt-tbl-SkyTonight-${tableType}`);
    const targetDiv = tblDiv || dataDiv;
    DOMUtils.clear(targetDiv);

    // Empty result from an active filter - show a message instead of leaving the old table
    if (!Array.isArray(tableData) || tableData.length === 0) {
        const msg = document.createElement('div');
        msg.className = 'alert alert-info mt-3';
        msg.textContent = isFiltered
            ? tSkyTonightCompat('no_target_in_report')
            : tSkyTonightCompat('no_data_available');
        targetDiv.appendChild(msg);
        return;
    }

    if (cachedData.in_progress) {
        const banner = document.createElement('div');
        banner.className = 'alert alert-warning d-flex align-items-center gap-2 mb-2';
        const _spinner1 = document.createElement('span');
        _spinner1.className = 'spinner-border spinner-border-sm';
        _spinner1.setAttribute('role', 'status');
        _spinner1.setAttribute('aria-hidden', 'true');
        banner.appendChild(_spinner1);
        banner.appendChild(document.createTextNode(tSkyTonightCompat('calculation_in_progress')));
        targetDiv.appendChild(banner);
    }

    const fragment = document.createRange().createContextualFragment(
        generateReportTable(tableData, 'SkyTonight', tableType, displayAstrodex, page, true)
    );
    targetDiv.appendChild(fragment);
    dataDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function generateReportTable(report, catalogue, type, displayAstrodex = true, page = 0, isRerender = false) {
    if (!report || report.length === 0) return `<p>${tSkyTonightCompat('no_target_in_report')}</p>`;

    // Define column order and configuration for Report type
    const reportColumns = [
        { key: 'id', label: tSkyTonightCompat('table_id'), align: 'left' },
        { key: 'target name', label: tSkyTonightCompat('table_name'), align: 'left' },
        { key: 'size', label: tSkyTonightCompat('table_size'), align: 'center', unit: "'" },
        { key: 'foto', label: tSkyTonightCompat('table_foto'), align: 'center' },
        { key: 'mag', label: tSkyTonightCompat('table_mag'), align: 'center' },
        { key: 'constellation', label: tSkyTonightCompat('table_constellation'), align: 'center' },
        { key: 'type', label: tSkyTonightCompat('table_type'), align: 'center' },
        { key: 'difficulty', label: tSkyTonightCompat('table_difficulty'), align: 'center' },
        { key: 'altitude', label: tSkyTonightCompat('table_altitude'), align: 'center', unit: '°', decimals: 2 },
        { key: 'azimuth', label: tSkyTonightCompat('table_azimuth'), align: 'center', unit: '°', decimals: 2 },
        ...(displayAstrodex ? [{ key: 'astrodex', label: tSkyTonightCompat('table_astrodex'), align: 'center' }] : []),
        ...(displayAstrodex ? [{ key: 'plan_my_night', label: tSkyTonightCompat('table_plan_my_night'), align: 'center' }] : []),
        { key: 'more', label: tSkyTonightCompat('table_more'), align: 'center' }
    ];

    // Define column order and configuration for Bodies type
    const bodiesColumns = [
        { key: 'target name', label: tSkyTonightCompat('table_name'), align: 'left' },
        { key: 'altitude', label: tSkyTonightCompat('table_altitude'), align: 'center', unit: '°', decimals: 2 },
        { key: 'azimuth', label: tSkyTonightCompat('table_azimuth'), align: 'center', unit: '°', decimals: 2 },
        { key: 'solar elongation', label: tSkyTonightCompat('table_solar_elongation'), align: 'center' },
        { key: 'max altitude time', label: tSkyTonightCompat('table_max_altitude_time'), align: 'center' },
        { key: 'visual magnitude', label: tSkyTonightCompat('table_visual_magnitude'), align: 'center', decimals: 2 },
        { key: 'foto', label: tSkyTonightCompat('table_foto'), align: 'center' },
        { key: 'type', label: tSkyTonightCompat('table_type'), align: 'center' },
        ...(displayAstrodex ? [{ key: 'astrodex', label: tSkyTonightCompat('table_astrodex'), align: 'center' }] : []),
        ...(displayAstrodex ? [{ key: 'plan_my_night', label: tSkyTonightCompat('table_plan_my_night'), align: 'center' }] : []),
        { key: 'more', label: tSkyTonightCompat('table_more'), align: 'center' }
    ];

    // Define column order and configuration for Comets type
    const cometsColumns = [
        { key: 'target name', label: tSkyTonightCompat('table_name'), align: 'left' },
        { key: 'foto', label: tSkyTonightCompat('table_foto'), align: 'center' },
        { key: 'altitude', label: tSkyTonightCompat('table_altitude'), align: 'center', unit: '°', decimals: 2 },
        { key: 'azimuth', label: tSkyTonightCompat('table_azimuth'), align: 'center', unit: '°', decimals: 2 },
        { key: 'visual magnitude', label: tSkyTonightCompat('table_visual_magnitude'), align: 'center', decimals: 2 },
        { key: 'distance earth au', label: tSkyTonightCompat('table_distance_earth'), align: 'center', unit: ' au', decimals: 2 },
        ...(displayAstrodex ? [{ key: 'astrodex', label: tSkyTonightCompat('table_astrodex'), align: 'center' }] : []),
        ...(displayAstrodex ? [{ key: 'plan_my_night', label: tSkyTonightCompat('table_plan_my_night'), align: 'center' }] : []),
        { key: 'more', label: tSkyTonightCompat('table_more'), align: 'center' }
    ];

    // Fields to show in "More" popup
    let moreFields = ['catalogue_names', 'meridian transit', 'antimeridian transit', 'right ascension', 'declination', 'hmsdms'];

    // Select columns based on type
    let columns;
    if (type === 'report') {
        columns = reportColumns;
    } else if (type === 'bodies') {
        columns = bodiesColumns;
    } else if (type === 'comets') {
        columns = cometsColumns;
        // Comets have different fields in More popup
        moreFields = ['absolute magnitude', 'distance sun au', 'rise time', 'set time', 'hmsdms'];
    } else {
        // For other types, use all keys
        columns = Object.keys(report[0]).map(key => ({
            key: key,
            label: key.charAt(0).toUpperCase() + key.slice(1),
            align: 'left'
        }));
    }

    // Pagination: compute the row slice for the current page
    const _totalItems = report.length;
    const _totalPages = Math.ceil(_totalItems / SKYT_PAGE_SIZE);
    const _startIdx = page * SKYT_PAGE_SIZE;
    const _pageRows = report.slice(_startIdx, Math.min(_startIdx + SKYT_PAGE_SIZE, _totalItems));

    // Extract unique values for constellation and type filters (from the FULL dataset for complete filter lists).
    // Sort by translated label so the dropdown order is alphabetical in the active locale.
    const constellations = [...new Set(report.map(r => r.constellation).filter(c => c))]
        .sort((a, b) => _translatedConstellation(a).localeCompare(_translatedConstellation(b)));
    const types = [...new Set(report.map(r => r.type).filter(t => t))]
        .sort((a, b) => tSkyTonightType(a).localeCompare(tSkyTonightType(b)));

    const eCat = escapeHtml(catalogue);
    const eType = escapeHtml(type);

    // Filter controls are rendered ONCE inside their own container (skyt-ctrl-…).
    // On re-renders only the table rows change; the filter input element is never
    // destroyed so focus and the virtual keyboard are naturally preserved while typing.
    let html = '';
    if (!isRerender) {
        html += `<div id="skyt-ctrl-${eCat}-${eType}">`;
        html += `
        <div class="row row-cols-lg-auto g-3 align-items-center mt-3">
            <div class="col-12">
                <label for="filter-${eCat}-${eType}" class="visually-hidden">${tSkyTonightCompat('search')}</label>
                <input type="text" id="filter-${eCat}-${eType}" placeholder="${tSkyTonightCompat('search_placeholder')}" class="filter-input form-control">
            </div>`;

        // Show foto filter for all table types (report, bodies, comets)
        {
            html += `
            <div class="col-12">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="foto-filter-${eCat}-${eType}">
                    <label class="form-check-label" for="inlineFormCheck"> ${tSkyTonightCompat('search_foto')} </label>
                </div>
            </div>`;

            html += `
            <div class="col-12">
                <label for="foto-value-${eCat}-${eType}" class="visually-hidden">${tSkyTonightCompat('search_foto_score')}</label>
                <input type="number" id="foto-value-${eCat}-${eType}" step="5" min="0" max="100" inputmode="numeric" class="shared-foto-value form-control">
            </div>`;
        }

        // Add constellation filter if constellation field exists
        if (constellations.length > 0) {
            html += `
            <div class="col-12">
                <label class="visually-hidden" for="constellation-filter-${eCat}-${eType}">${tSkyTonightCompat('search_constellations')}</label>
                <select class="form-select filter-select" id="constellation-filter-${eCat}-${eType}">
                    <option value="">${tSkyTonightCompat('search_all_constellations')}</option>`;
            constellations.forEach(c => {
                let label_c = c;
                let translationKey = 'constellations.' + strToTranslateKey(label_c);
                if (i18n.has(translationKey)) {
                    label_c = i18n.t(translationKey);
                } else {
                    console.warn(`Translation key not found: ${translationKey}`);
                }
                html += `<option value="${escapeHtml(c)}">${escapeHtml(label_c)}</option>`;
            });
            html += `</select>
            </div>`;
        }

        // Add type filter if type field exists
        if (types.length > 0) {
            html += `
            <div class="col-12">
                <label class="visually-hidden" for="type-filter-${eCat}-${eType}">${tSkyTonightCompat('search_types')}</label>
                <select id="type-filter-${eCat}-${eType}" class="form-select filter-select">
                    <option value="">${tSkyTonightCompat('search_all_types')}</option>`;
            types.forEach(t => {
                let label_t = t;
                label_t = tSkyTonightType(label_t);
                html += `<option value="${escapeHtml(t)}">${escapeHtml(label_t)}</option>`;
            });
            html += `</select>
            </div>`;
        }

        // Add catalogue filter for curated sub-lists present in this report
        const _catFilterOptions = [
            { key: 'AbellClusters', label: 'Abell Clusters' },
            { key: 'AbellPNe', label: 'Abell PNe' },
            { key: 'Arp', label: 'Arp' },
            { key: 'Barnard', label: 'Barnard' },
            { key: 'Caldwell', label: 'Caldwell' },
            { key: 'GaryImm', label: 'GaryImm' },
            { key: 'Herschel400', label: 'Herschel 400' },
            { key: 'OpenIC', label: 'IC' },
            { key: 'LBN', label: 'LBN' },
            { key: 'Messier', label: 'Messier' },
            { key: 'OpenNGC', label: 'NGC' },
            { key: 'Pensack500', label: 'Pensack 500' },
            { key: 'Sharpless', label: 'Sharpless' },
            { key: 'vdB', label: 'vdB' },
        ];
        const _availableCatFilters = _catFilterOptions.filter(opt =>
            report.some(r => r.catalogue_names && r.catalogue_names[opt.key])
        );
        if (_availableCatFilters.length > 0) {
            html += `
            <div class="col-12">
                <label class="visually-hidden" for="catalogue-filter-${eCat}-${eType}">${tSkyTonightCompat('search_catalogue')}</label>
                <select id="catalogue-filter-${eCat}-${eType}" class="form-select filter-select">
                    <option value="">${tSkyTonightCompat('search_all_catalogues')}</option>`;
            _availableCatFilters.forEach(opt => {
                html += `<option value="${escapeHtml(opt.key)}">${escapeHtml(opt.label)}</option>`;
            });
            html += `</select>
            </div>`;
        }

        // Difficulty filter - DSO report table only (difficulty is not computed for bodies/comets).
        if (type === 'report') {
            html += `
            <div class="col-12">
                <label class="visually-hidden" for="difficulty-filter-${eCat}-${eType}">${tSkyTonightCompat('search_difficulty')}</label>
                <select id="difficulty-filter-${eCat}-${eType}" class="form-select filter-select">
                    <option value="">${tSkyTonightCompat('search_difficulty')}</option>
                    <option value="beginner">${i18n.t('difficulty.beginner')}</option>
                    <option value="intermediate">${i18n.t('difficulty.intermediate')}</option>
                    <option value="advanced">${i18n.t('difficulty.advanced')}</option>
                </select>
            </div>`;
        }

        html += `
        </div>`; // closes filter row div
        html += `</div>`; // closes skyt-ctrl div
    }

    // Table content container - replaced on every filter/pagination change.
    if (!isRerender) html += `<div id="skyt-tbl-${eCat}-${eType}">`;
    html += _astroScoreLegendHtml();

    html += `
        <div class="table-responsive mt-3">
            <table class="table table-striped table-hover table-sm" id="table-${eCat}-${eType}">
                <thead>
                    <tr>
    `;

    // Generate table headers
    columns.forEach(col => {
        if (col.key === 'more' || col.key === 'astrodex') {
            html += `<th style="text-align: ${col.align}">${col.label}</th>`;
        } else {
            html += `<th class="sortable" data-column="${escapeHtml(col.key)}" onclick="sortTable('${escapeHtml(catalogue)}', '${escapeHtml(col.key)}', '${escapeHtml(type)}')" style="text-align: ${col.align}">${escapeHtml(col.label)} <span class="sort-indicator"></span></th>`;
        }
    });

    html += `</tr></thead><tbody class="table-group-divider">`;

    // Generate table rows (current page slice only)
    _pageRows.forEach((row, _pageIdx) => {
        const idx = _startIdx + _pageIdx; // absolute row index across all pages
        const fotoValue = row['foto'] || row['fraction of time observable'] || 0;
        const _catKeys = row.catalogue_names ? Object.keys(row.catalogue_names).join(',') : '';
        html += `<tr data-foto="${escapeHtml(String(fotoValue))}" data-constellation="${escapeHtml(row.constellation || '')}" data-type="${escapeHtml(row.type || '')}" data-catalogues="${escapeHtml(_catKeys)}">`;

        columns.forEach(col => {
            if (col.key === 'more') {
                // Lazy more popup: store row data by key, referenced via data attribute
                const moreKey = `${catalogue}-${type}-${idx}`;
                _skytMoreRowData[moreKey] = { type, moreFields, row };
                html += `<td style="text-align: ${col.align}"><a href="#" class="skyt-more-link link-underline link-underline-opacity-0" data-more-key="${escapeHtml(moreKey)}"><i class="bi bi-clipboard-data icon-inline" aria-hidden="true"></i>${tSkyTonightCompat('table_more')}</a></td>`;
            } else if (col.key === 'astrodex') {
                // Generate Astrodex action button
                const itemName = row['id'] || row['target name'];
                const isInAstrodex = row['in_astrodex'] || false;
                const itemData = {
                    id: row['id'],
                    'target name': row['target name'],
                    name: itemName,
                    type: row['type'] || row['targettype'],
                    source_type: type,
                    catalogue: catalogue,
                    ra: row['ra'] || row['right ascension'],
                    dec: row['dec'] || row['declination'],
                    constellation: (row['constellation'] || row['const'] || '').toLowerCase(),
                    mag: row['mag'] || row['visual magnitude'],
                    size: row['size']
                };
                const itemDataJson = escapeHtml(JSON.stringify(itemData));

                if (displayAstrodex) {
                    if (isInAstrodex) {
                        html += `<td style="text-align: ${col.align}" data-item="${itemDataJson}"><button type="button" class="in-astrodex-badge astrodex-captured-btn" data-item="${itemDataJson}" title="${tSkyTonightCompat('captured')}"><i class="bi bi-check-circle-fill icon-inline" aria-hidden="true"></i>${tSkyTonightCompat('captured')}</button></td>`;
                    } else if (itemName) {
                        html += `<td style="text-align: ${col.align}" data-item="${itemDataJson}"><button class="btn btn-sm btn-outline-primary astrodex-add-btn" data-item="${itemDataJson}"><i class="bi bi-plus-circle icon-inline" aria-hidden="true"></i>${tSkyTonightCompat('add')}</button></td>`;
                    } else {
                        html += `<td style="text-align: ${col.align}">-</td>`;
                    }
                }
            } else if (col.key === 'plan_my_night') {
                const itemName = row['id'] || row['target name'];
                const isInPlanMyNight = row['in_plan_my_night'] || false;
                const planState = row['plan_state'] || 'none';
                const itemData = {
                    id: row['id'],
                    'target name': row['target name'],
                    name: itemName,
                    type: row['type'] || row['targettype'],
                    source_type: type,
                    catalogue: catalogue,
                    ra: row['ra'] || row['right ascension'],
                    dec: row['dec'] || row['declination'],
                    constellation: (row['constellation'] || row['const'] || '').toLowerCase(),
                    mag: row['mag'] || row['visual magnitude'],
                    size: row['size'],
                    foto: row['foto'] || row['fraction of time observable'],
                    difficulty: row['difficulty'] || '',
                    alttime_file: row['alttime_file'] || '',
                    catalogue_group_id: row['catalogue_group_id'] || '',
                    catalogue_aliases: row['catalogue_aliases'] || {}
                };
                const itemDataJson = escapeHtml(JSON.stringify(itemData));

                if (displayAstrodex) {
                    if (isInPlanMyNight) {
                        html += `<td style="text-align: ${col.align}" data-item="${itemDataJson}"><span class="in-astrodex-badge in-plan-my-night-badge"><i class="bi bi-check-circle-fill icon-inline" aria-hidden="true"></i>${tSkyTonightCompat('planned')}</span></td>`;
                    } else if (planState === 'previous') {
                        html += `<td style="text-align: ${col.align}" data-item="${itemDataJson}"><button class="btn btn-sm btn-outline-secondary" disabled title="${tSkyTonightCompat('plan_clear_required')}">${tSkyTonightCompat('add')}</button></td>`;
                    } else if (itemName) {
                        html += `<td style="text-align: ${col.align}" data-item="${itemDataJson}"><button class="btn btn-sm btn-outline-info plan-my-night-add-btn" data-item="${itemDataJson}" data-catalogue="${escapeHtml(catalogue)}"><i class="bi bi-moon-stars-fill icon-inline" aria-hidden="true"></i>${tSkyTonightCompat('add')}</button></td>`;
                    } else {
                        html += `<td style="text-align: ${col.align}">-</td>`;
                    }
                }
            } else if (col.key === 'foto') {
                const fotoNum = (row[col.key] !== null && row[col.key] !== undefined)
                    ? parseFloat(row[col.key]) : NaN;
                const sortVal = isNaN(fotoNum) ? -1 : Math.round(fotoNum * 100);
                html += `<td style="text-align: ${col.align}" data-sort-value="${sortVal}">${isNaN(fotoNum) ? '\u2014' : _astroScoreBadgeHtml(fotoNum)}</td>`;
            } else if (col.key === 'difficulty') {
                const difficultyVal = row[col.key] || '';
                html += `<td style="text-align: ${col.align}" data-sort-value="${escapeHtml(difficultyVal)}">${_difficultyBadgeHtml(difficultyVal)}</td>`;
            } else if (col.key === 'solar elongation') {
                const elongVal = (row[col.key] !== null && row[col.key] !== undefined)
                    ? parseFloat(row[col.key]) : NaN;
                const elongSort = isNaN(elongVal) ? -1 : Math.round(elongVal * 10);
                html += `<td style="text-align: ${col.align}" data-sort-value="${elongSort}">${isNaN(elongVal) ? '\u2014' : _elongationBadgeHtml(elongVal)}</td>`;
            } else {
                let value = row[col.key];

                // Format values
                if (col.key === 'target name' && value) {
                    value = String(value).replace(/\s*\([^)]*\)/g, '');
                } else if (col.key === 'mag' && !isNaN(value) && value !== null) {
                    value = parseFloat(value).toFixed(2);
                } else if (col.key === 'visual magnitude' && !isNaN(value) && value !== null) {
                    value = parseFloat(value).toFixed(2);
                } else if (col.decimals && !isNaN(value) && value !== null) {
                    // Apply decimal rounding for fields with decimals config
                    value = parseFloat(value).toFixed(col.decimals);
                } else if (col.key === 'type' && value) { // Type field - try to translate the value
                    value = tSkyTonightType(value);
                } else if (col.key === 'constellation' && value) { // Constellation field - try to translate the value
                    let translationKey = 'constellations.' + strToTranslateKey(value);
                    if (i18n.has(translationKey)) {
                        value = i18n.t(translationKey);
                    }
                }

                // Add unit if specified
                let displayValue = value !== null && value !== undefined && value !== '' ? escapeHtml(String(value)) : '';
                if (col.unit && displayValue) {
                    displayValue += col.unit;
                }

                // Make ID or Target name clickable
                if ((col.key === 'id' || col.key === 'target name')) {
                    // Messier badge: shown in the target name cell when the object is in the Messier catalogue
                    const messierNum = (col.key === 'target name')
                        ? (row['catalogue_names'] && row['catalogue_names']['Messier'] ? row['catalogue_names']['Messier'] : null)
                        : null;
                    const messierBadge = messierNum
                        ? `<span class="messier-badge" title="${escapeHtml(messierNum)}">${escapeHtml(messierNum)}</span>`
                        : '';
                    // For DSO (report): ID cell opens object-info modal; target name cell opens alttime
                    if (col.key === 'id' && type === 'report') {
                        const infoId = (row['id'] || row['target name'] || '').trim();
                        if (infoId) {
                            html += `<td style="text-align: ${col.align}">${messierBadge}<a href="#" class="link-underline link-underline-opacity-0 skyt-info-link" data-identifier="${escapeHtml(infoId)}">${displayValue}</a></td>`;
                        } else {
                            html += `<td style="text-align: ${col.align}">${messierBadge}${displayValue}</td>`;
                        }
                    } else if (row['alttime_file'] != '') {
                        const alttimeSource = row['id'] || row['target name'];
                        html += `
                        <td style="text-align: ${col.align}" class="alttime-check" data-alttime-id="${escapeHtml(row['alttime_file'])}" data-title="${escapeHtml(alttimeSource)} - ${escapeHtml(tSkyTonightCompat('altitude_time_title'))}">
                            ${messierBadge}<a href="#" class="link-underline link-underline-opacity-0 alttime-popup-link">${displayValue}</a>
                        </td>`;
                    } else {
                        html += `<td style="text-align: ${col.align}">${messierBadge}${displayValue}</td>`;
                    }
                } else {
                    html += `<td style="text-align: ${col.align}">${displayValue}</td>`;
                }
            }
        });

        html += `</tr>`;
    });

    html += `</tbody></table>`;

    // Pagination bar (only when the dataset spans more than one page)
    if (_totalPages > 1) {
        html += _buildPaginationHtml(catalogue, type, page, _totalPages, _totalItems);
    }

    html += `</div>`; // closes table-responsive
    if (!isRerender) html += `</div>`; // closes skyt-tbl div

    // Add event listeners for filtering
    // Cancel any previous pending timer for this table key to avoid duplicate listeners
    // when rapid re-renders (pagination, filter) fire before the previous timer expires.
    const _timerKey = `${catalogue}-${type}`;
    clearTimeout(_skytListenerTimers[_timerKey]);
    _skytListenerTimers[_timerKey] = setTimeout(() => {
        const filterInput = document.getElementById(`filter-${catalogue}-${type}`);
        const fotoCheckbox = document.getElementById(`foto-filter-${catalogue}-${type}`);
        const fotoValueInput = document.getElementById(`foto-value-${catalogue}-${type}`);
        const constellationSelect = document.getElementById(`constellation-filter-${catalogue}-${type}`);
        const typeSelect = document.getElementById(`type-filter-${catalogue}-${type}`);

        // Filter controls live in skyt-ctrl-… which is never cleared on re-render.
        // Only set up listeners and restore values on the initial render.
        if (!isRerender) {
            // Load saved filter values from localStorage
            if (fotoCheckbox) {
                const savedCheckboxState = localStorage.getItem('fotoFilterEnabled');
                if (savedCheckboxState === 'true') {
                    fotoCheckbox.checked = true;
                }
            }
            if (fotoValueInput) {
                fotoValueInput.value = sanitizeFotoFilterValue(localStorage.getItem('fotoFilterValue'));
            }

            // Restore any persisted filter state (from a previous section visit)
            const _savedFilter = _skytFilterState[type];
            if (_savedFilter && catalogue === 'SkyTonight') {
                if (filterInput) filterInput.value = (_savedFilter.filterRaw !== undefined) ? _savedFilter.filterRaw : _savedFilter.filterText;
                if (fotoCheckbox) fotoCheckbox.checked = _savedFilter.fotoEnabled;
                if (fotoValueInput) fotoValueInput.value = String(Math.round(_savedFilter.fotoThreshold * 100));
                if (constellationSelect) constellationSelect.value = _savedFilter.constellation;
                if (typeSelect) typeSelect.value = _savedFilter.typeVal;
                const _catSel = document.getElementById(`catalogue-filter-${catalogue}-${type}`);
                if (_catSel && _savedFilter.catalogueVal) _catSel.value = _savedFilter.catalogueVal;
                const _diffSel = document.getElementById(`difficulty-filter-${catalogue}-${type}`);
                if (_diffSel && _savedFilter.difficultyVal) _diffSel.value = _savedFilter.difficultyVal;
            }
        }

        // Attach filter/select listeners whenever the element is new (not yet marked).
        // Using a per-element flag prevents duplicate listeners when the same DOM node
        // (in skyt-ctrl-* which is never cleared on re-render) passes through this timer
        // more than once. On full re-renders (initial or section revisit) elements are new
        // and will always receive a listener.
        if (filterInput && !filterInput._skytListened) {
            filterInput._skytListened = true;
            filterInput.addEventListener('input', () => _skytApplyFilter(catalogue, type));
        }
        if (fotoCheckbox && !fotoCheckbox._skytListened) {
            fotoCheckbox._skytListened = true;
            fotoCheckbox.addEventListener('change', () => {
                localStorage.setItem('fotoFilterEnabled', fotoCheckbox.checked);
                syncFotoCheckboxes(fotoCheckbox.checked);
                _skytApplyFilter(catalogue, type);
            });
        }
        if (fotoValueInput && !fotoValueInput._skytListened) {
            fotoValueInput._skytListened = true;
            fotoValueInput.addEventListener('input', () => {
                const normalizedFotoValue = sanitizeFotoFilterValue(fotoValueInput.value);
                fotoValueInput.value = normalizedFotoValue;
                localStorage.setItem('fotoFilterValue', normalizedFotoValue);
                syncFotoValues(normalizedFotoValue);
                _skytApplyFilter(catalogue, type);
            });
        }
        if (constellationSelect && !constellationSelect._skytListened) {
            constellationSelect._skytListened = true;
            constellationSelect.addEventListener('change', () => _skytApplyFilter(catalogue, type));
        }
        if (typeSelect && !typeSelect._skytListened) {
            typeSelect._skytListened = true;
            typeSelect.addEventListener('change', () => _skytApplyFilter(catalogue, type));
        }
        const _catSelEl = document.getElementById(`catalogue-filter-${catalogue}-${type}`);
        if (_catSelEl && !_catSelEl._skytListened) {
            _catSelEl._skytListened = true;
            _catSelEl.addEventListener('change', () => _skytApplyFilter(catalogue, type));
        }
        const _diffSelEl = document.getElementById(`difficulty-filter-${catalogue}-${type}`);
        if (_diffSelEl && !_diffSelEl._skytListened) {
            _diffSelEl._skytListened = true;
            _diffSelEl.addEventListener('change', () => _skytApplyFilter(catalogue, type));
        }

        // Add event listeners for Astrodex "Add" buttons
        const addButtons = document.querySelectorAll('.astrodex-add-btn');
        addButtons.forEach(button => {
            button.addEventListener('click', function (e) {
                e.preventDefault();
                try {
                    const itemDataJson = this.getAttribute('data-item');
                    const itemData = JSON.parse(itemDataJson);

                    // Validate the parsed object structure
                    if (!itemData || typeof itemData !== 'object') {
                        throw new Error('Invalid item data');
                    }

                    // Ensure required fields exist
                    if (!itemData.name) {
                        throw new Error('Item name is required');
                    }

                    addFromCatalogue(itemData);
                } catch (error) {
                    console.error('Error adding to astrodex:', error);
                    showMessage('error', tSkyTonightCompat('failed_to_add_astrodex'));
                }
            });
        });

        // Add event listeners for captured Astrodex buttons (open pictures popup)
        const capturedButtons = document.querySelectorAll('.astrodex-captured-btn');
        capturedButtons.forEach(button => {
            button.addEventListener('click', async function (e) {
                e.preventDefault();
                try {
                    const itemDataJson = this.getAttribute('data-item');
                    const itemData = JSON.parse(itemDataJson);
                    await openCapturedAstrodexItem(itemData);
                } catch (error) {
                    console.error('Error opening captured astrodex item:', error);
                }
            });
        });

        // Add event listeners for Plan My Night "Add" buttons
        const addPlanButtons = document.querySelectorAll('.plan-my-night-add-btn');
        addPlanButtons.forEach(button => {
            button.addEventListener('click', async function (e) {
                e.preventDefault();
                try {
                    const itemDataJson = this.getAttribute('data-item');
                    const catalogueName = this.getAttribute('data-catalogue');
                    const itemData = JSON.parse(itemDataJson);

                    if (!itemData || typeof itemData !== 'object' || !itemData.name) {
                        throw new Error('Invalid item data');
                    }

                    const telescopeSelection = await _resolvePlanTelescopeSelection(itemData);
                    if (!telescopeSelection) return; // user cancelled the telescope picker

                    const response = await fetchJSON('/api/plan-my-night/targets', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            item: itemData,
                            catalogue: catalogueName || itemData.catalogue || currentCatalogueTab,
                            telescope_id: telescopeSelection.telescope_id,
                            telescope_name: telescopeSelection.telescope_name,
                        })
                    });

                    if (response && response.status === 'success') {
                        showMessage('success', i18n.t('plan_my_night.target_added'));
                        const referenceItem = response.entry || itemData;
                        updateCataloguePlanMyNightBadge(referenceItem, true);
                        updateCataloguePlanMyNightData(referenceItem, true);

                        const planTab = document.getElementById('plan-my-night-subtab');
                        if (planTab && planTab.classList.contains('active')) {
                            await loadPlanMyNight();
                        }
                    }
                } catch (error) {
                    console.error('Error adding to Plan My Night:', error);
                    if (error.message && error.message.includes('Plan belongs to previous night')) {
                        showMessage('warning', tSkyTonightCompat('plan_clear_required'));
                    } else {
                        showMessage('error', i18n.t('plan_my_night.failed_to_add_target'));
                    }
                }
            });
        });

        // Add event listeners for Alttime popup links (avoid inline onclick quoting issues)
        const alttimeLinks = document.querySelectorAll('.alttime-popup-link');
        alttimeLinks.forEach(link => {
            link.addEventListener('click', function (e) {
                e.preventDefault();
                const parentCell = this.closest('.alttime-check');
                if (!parentCell) {
                    return;
                }
                const title = parentCell.getAttribute('data-title') || 'Target Altitude-Time';
                const targetId = parentCell.getAttribute('data-alttime-id') || '';
                if (!targetId) {
                    return;
                }
                showAlttimePopup(title, targetId);
            });
        });

        // Apply default sorting based on table type
        applyDefaultSort(catalogue, type);

        // Apply filter on initial render only (not on pagination/filter re-renders to avoid loops).
        // Re-renders already display the correct filtered slice; just restore the input values above.
        if (!isRerender && ((fotoCheckbox && fotoCheckbox.checked) || _skytFilterState[type])) {
            _skytApplyFilter(catalogue, type);
        }

        // Lazy "More" popup: delegate via data-more-key attribute
        document.querySelectorAll('.skyt-more-link').forEach(link => {
            link.addEventListener('click', async (e) => {
                e.preventDefault();
                const moreKey = link.getAttribute('data-more-key');
                const moreData = _skytMoreRowData[moreKey];
                if (moreData) await showMorePopupFromRowData(moreData);
            });
        });

        // DSO ID link: open object-info modal
        document.querySelectorAll('.skyt-info-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const identifier = link.getAttribute('data-identifier');
                if (identifier && typeof showObjectInfoModal === 'function') {
                    showObjectInfoModal(identifier);
                }
            });
        });

        // Pagination buttons
        document.querySelectorAll('.skyt-page-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.preventDefault();
                if (btn.closest('.page-item')?.classList.contains('disabled')) return;
                const tp = btn.getAttribute('data-type');
                const newPage = parseInt(btn.getAttribute('data-page'), 10);
                _skytCurrentPages[tp] = newPage;
                await _reRenderTablePage(tp, newPage);
            });
        });
    }, 100);

    return html;
}

// ======================
// Table Filtering and Sorting
// ======================

function sanitizeFotoFilterValue(value, fallback = 80) {
    const numericValue = Number.parseFloat(value);
    if (!Number.isFinite(numericValue)) {
        return String(fallback);
    }
    // Migrate legacy 0-1 decimal values to 0-100 percentage
    const pctValue = numericValue <= 1.0 ? numericValue * 100 : numericValue;
    const clampedValue = Math.min(100, Math.max(0, Math.round(pctValue)));
    return String(clampedValue);
}

// Sync foto filter value across all Report and Bodies tables
function syncFotoValues(value) {
    const safeValue = sanitizeFotoFilterValue(value);
    const fotoInputs = document.querySelectorAll('.shared-foto-value');
    fotoInputs.forEach(input => {
        if (input.value !== safeValue) {
            input.value = safeValue;
        }
    });
}

function syncFotoCheckboxes(checked) {
    const fotoCheckboxes = document.querySelectorAll('[id^="foto-filter-"]');
    fotoCheckboxes.forEach(checkbox => {
        if (checkbox.checked !== checked) {
            checkbox.checked = checked;
        }
    });
}

// Apply default sorting to tables
function applyDefaultSort(catalogue, type) {
    let defaultColumn = '';
    let defaultDirection = 'desc';

    if (type === 'report') {
        defaultColumn = 'foto';
        defaultDirection = 'desc';
    } else if (type === 'bodies') {
        defaultColumn = 'foto';
        defaultDirection = 'desc';
    } else if (type === 'comets') {
        defaultColumn = 'foto';
        defaultDirection = 'desc';
    }

    if (defaultColumn) {
        // Trigger the sort
        const table = document.getElementById(`table-${catalogue}-${type}`);
        if (!table) return;

        const thead = table.querySelector('thead');
        const th = thead.querySelector(`th[data-column="${defaultColumn}"]`);

        if (th) {
            // Set the sort state to opposite of desired, since sortTable will toggle
            const oppositeDirection = defaultDirection === 'asc' ? 'desc' : 'asc';
            th.setAttribute('data-sort', oppositeDirection);

            // Call sortTable which will toggle to the desired direction
            sortTable(catalogue, defaultColumn, type);
        }
    }
}

function filterTable(catalogue, type) {
    const filterInput = document.getElementById(`filter-${catalogue}-${type}`);
    const fotoCheckbox = document.getElementById(`foto-filter-${catalogue}-${type}`);
    const fotoValueInput = document.getElementById(`foto-value-${catalogue}-${type}`);
    const constellationSelect = document.getElementById(`constellation-filter-${catalogue}-${type}`);
    const typeSelect = document.getElementById(`type-filter-${catalogue}-${type}`);
    const catalogueSelect = document.getElementById(`catalogue-filter-${catalogue}-${type}`);
    const table = document.getElementById(`table-${catalogue}-${type}`);

    if (!table) return;

    const filterText = filterInput ? filterInput.value.toLowerCase() : '';
    const fotoFilter = fotoCheckbox ? fotoCheckbox.checked : false;
    const fotoThreshold = fotoValueInput ? parseFloat(sanitizeFotoFilterValue(fotoValueInput.value)) / 100 : 0.8;
    const constellationFilter = constellationSelect ? constellationSelect.value : '';
    const typeFilter = typeSelect ? typeSelect.value : '';
    const catalogueFilter = catalogueSelect ? catalogueSelect.value : '';
    const rows = table.querySelectorAll('tbody tr');

    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        const fotoValue = parseFloat(row.getAttribute('data-foto')) || 0;
        const constellation = row.getAttribute('data-constellation') || '';
        const rowType = row.getAttribute('data-type') || '';
        const rowCatalogues = (row.getAttribute('data-catalogues') || '').split(',');

        const matchesFilter = !filterText || text.includes(filterText);
        const matchesFoto = !fotoFilter || fotoValue >= fotoThreshold;
        const matchesConstellation = !constellationFilter || constellation === constellationFilter;
        const matchesType = !typeFilter || rowType === typeFilter;
        const matchesCatalogue = !catalogueFilter || rowCatalogues.includes(catalogueFilter);

        row.style.display = (matchesFilter && matchesFoto && matchesConstellation && matchesType && matchesCatalogue) ? '' : 'none';
    });
}

function sortTable(catalogue, column, type) {
    // Simple client-side sorting implementation with type parameter
    const table = document.getElementById(`table-${catalogue}-${type}`);
    if (!table) return;

    const tbody = table.querySelector('tbody');
    const thead = table.querySelector('thead');
    const rows = Array.from(tbody.querySelectorAll('tr'));

    // Get current sort state for this column
    const th = thead.querySelector(`th[data-column="${column}"]`);
    const currentSort = th.getAttribute('data-sort') || 'none';

    // Clear other columns' sort indicators (but preserve current column state for toggle logic)
    thead.querySelectorAll('th').forEach(header => {
        if (header !== th) {
            header.setAttribute('data-sort', 'none');
            const indicator = header.querySelector('.sort-indicator');
            if (indicator) indicator.classList.remove('bi-caret-up-fill', 'bi-caret-down-fill');
        }
    });

    // Toggle sort direction
    let sortDirection = 'asc';
    if (currentSort === 'asc') {
        sortDirection = 'desc';
    } else if (currentSort === 'desc') {
        sortDirection = 'asc';
    }

    th.setAttribute('data-sort', sortDirection);
    const indicator = th.querySelector('.sort-indicator');
    if (indicator) {
        indicator.classList.remove('bi-caret-up-fill', 'bi-caret-down-fill');

        indicator.classList.add(
            sortDirection === 'asc' ? 'bi-caret-up-fill' : 'bi-caret-down-fill',
            'bi'
        );
    }

    // Sort rows
    rows.sort((a, b) => {
        const aCell = a.querySelector(`td:nth-child(${getColumnIndex(table, column)})`);
        const bCell = b.querySelector(`td:nth-child(${getColumnIndex(table, column)})`);
        const aVal = 'sortValue' in aCell.dataset ? aCell.dataset.sortValue : aCell.textContent;
        const bVal = 'sortValue' in bCell.dataset ? bCell.dataset.sortValue : bCell.textContent;

        let comparison = 0;
        if (!isNaN(aVal) && !isNaN(bVal)) {
            comparison = parseFloat(aVal) - parseFloat(bVal);
        } else {
            comparison = aVal.localeCompare(bVal);
        }

        return sortDirection === 'asc' ? comparison : -comparison;
    });

    DOMUtils.clear(tbody);
    rows.forEach(row => tbody.appendChild(row));
}

function getColumnIndex(table, columnName) {
    const headers = table.querySelectorAll('th');
    for (let i = 0; i < headers.length; i++) {
        // Use data-column attribute for reliable matching
        if (headers[i].getAttribute('data-column') === columnName) {
            return i + 1;
        }
    }
    return 1;
}

function sanitizeImageSource(rawSrc) {
    if (typeof rawSrc !== 'string') {
        return '';
    }

    const src = rawSrc.trim();
    if (!src) {
        return '';
    }

    // Allow only local relative paths and same-origin http(s) URLs.
    // Block javascript:, data:, blob:, and cross-origin URLs.
    try {
        const parsed = new URL(src, window.location.origin);
        if (!['http:', 'https:'].includes(parsed.protocol)) {
            return '';
        }
        if (parsed.origin !== window.location.origin) {
            return '';
        }
        return parsed.toString();
    } catch (error) {
        return '';
    }
}

// ======================
// Modal Popups
// ======================

function showPlotPopup(title, src) {
    const modalElement = document.getElementById('modal_full_close');
    if (!modalElement) {
        console.error('Modal element not found');
        return;
    }

    const modal = new bootstrap.Modal(modalElement);

    // Title
    const titleElement = document.getElementById('modal_full_close_title');
    if (titleElement) {
        titleElement.textContent = title; // safe
    }

    const bodyElement = document.getElementById('modal_full_close_body');
    if (bodyElement) {
        // Clear existing content safely
        DOMUtils.clear(bodyElement);

        const safeSrc = sanitizeImageSource(src);
        if (!safeSrc) {
            console.error('Invalid image source');
            return;
        }

        const img = document.createElement('img');
        img.id = 'image-display';
        img.src = safeSrc;
        img.alt = 'Plot';
        img.title = title;            // safe
        img.className = 'img-fluid rounded';

        bodyElement.appendChild(img);
    }

    modal.show();
}

// Altitude-time Chart.js instance - stored so it can be destroyed when the modal closes.
let _alttimeChartInstance = null;

function _destroyAlttimeChart() {
    if (_alttimeChartInstance) {
        _alttimeChartInstance.destroy();
        _alttimeChartInstance = null;
    }
}

/**
 * Linearly interpolate the custom horizon minimum altitude at a given azimuth.
 * Profile is an array of {az, alt} objects sorted or unsorted.
 * Returns null when the profile is empty.
 */
function _horizonAltAtAz(az, profile) {
    if (!profile || profile.length === 0) return null;
    const sorted = [...profile].sort((a, b) => a.az - b.az);
    const azNorm = ((az % 360) + 360) % 360;
    const idx = sorted.findIndex(p => p.az > azNorm);
    if (idx === -1) {
        // azNorm is beyond all profile points - interpolate between last and first (wrapped)
        const p0 = sorted[sorted.length - 1];
        const p1 = { az: sorted[0].az + 360, alt: sorted[0].alt };
        const t = (azNorm - p0.az) / (p1.az - p0.az);
        return p0.alt + t * (p1.alt - p0.alt);
    }
    if (idx === 0) {
        // azNorm is before all profile points - interpolate between last (wrapped back) and first
        const p0 = { az: sorted[sorted.length - 1].az - 360, alt: sorted[sorted.length - 1].alt };
        const p1 = sorted[0];
        const t = (azNorm - p0.az) / (p1.az - p0.az);
        return p0.alt + t * (p1.alt - p0.alt);
    }
    const p0 = sorted[idx - 1];
    const p1 = sorted[idx];
    const t = (azNorm - p0.az) / (p1.az - p0.az);
    return p0.alt + t * (p1.alt - p0.alt);
}

/**
 * Show altitude vs time chart for a target in a modal popup.
 * Fetches JSON from /api/skytonight/alttime/<targetId>, renders a Chart.js line
 * chart inside a card shell matching the weather-chart style, and destroys the
 * chart instance when the modal is closed.
 *
 * @param {string} title    - Modal title (target name)
 * @param {string} targetId - SkyTonight target_id used to build the API URL
 */
async function showAlttimePopup(title, targetId, locationId) {
    const modalElement = document.getElementById('modal_xl_close');
    if (!modalElement) {
        console.error('Alttime modal element not found');
        return;
    }

    const titleElement = document.getElementById('modal_xl_close_title');
    const bodyElement = document.getElementById('modal_xl_close_body');
    if (titleElement) titleElement.textContent = title;
    if (bodyElement) {
        DOMUtils.clear(bodyElement);
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'text-center p-3';
        loadingDiv.textContent = i18n.t('common.loading');
        bodyElement.appendChild(loadingDiv);
    }

    const modal = new bootstrap.Modal(modalElement);

    // Destroy chart when modal is fully hidden to free canvas resources
    const onHidden = () => {
        _destroyAlttimeChart();
        modalElement.removeEventListener('hidden.bs.modal', onHidden);
    };
    modalElement.addEventListener('hidden.bs.modal', onHidden);

    modal.show();

    let data;
    try {
        const locationQuery = locationId ? `?location_id=${encodeURIComponent(locationId)}` : '';
        data = await fetchJSON(`${API_BASE}/api/skytonight/alttime/${encodeURIComponent(targetId)}${locationQuery}`);
        if (data && data.error) throw new Error(data.error);
    } catch (err) {
        console.error('Failed to load alttime data:', err);
        if (bodyElement) {
            DOMUtils.clear(bodyElement);
            const errDiv = document.createElement('div');
            errDiv.className = 'alert alert-danger';
            errDiv.textContent = tSkyTonightCompat('altitude_time_load_error');
            bodyElement.appendChild(errDiv);
        }
        return;
    }

    if (!bodyElement) return;
    DOMUtils.clear(bodyElement);

    // Format times in the observatory's configured timezone, not the browser's.
    const obsTz = data.timezone || 'UTC';
    const tzFmt = new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', timeZone: obsTz, hour12: false });

    // Build time labels from UTC ISO strings, displayed in observatory timezone.
    const times = (data.times_utc || []).map(t => tzFmt.format(new Date(t + 'Z')));
    const altitudes = data.altitudes || [];
    const azimuths = data.azimuths || [];
    const altMin = data.altitude_constraint_min ?? 30;
    const altMax = data.altitude_constraint_max ?? 80;
    const horizonProfile = data.horizon_profile || [];
    const hasCustomHorizon = horizonProfile.length > 0 && azimuths.length === altitudes.length;

    const nightStart = data.night_start ? tzFmt.format(new Date(data.night_start)) : '';
    const nightEnd = data.night_end ? tzFmt.format(new Date(data.night_end)) : '';

    const nightAstroStart = data.night_astro_start ? new Date(data.night_astro_start) : null;
    const nightAstroEnd = data.night_astro_end ? new Date(data.night_astro_end) : null;
    const nightAstroStartFmt = nightAstroStart ? tzFmt.format(nightAstroStart) : '';
    const nightAstroEndFmt = nightAstroEnd ? tzFmt.format(nightAstroEnd) : '';
    // UTC millisecond timestamps for each sample - used by the astro-night plugin
    // to find the chart x-index matching the astronomical twilight boundaries.
    const timesUtcMs = (data.times_utc || []).map(t => new Date(t + 'Z').getTime());

    // Resolve chart colors from current theme variables so dark/red modes stay readable.
    const rootStyle = getComputedStyle(document.documentElement);
    const theme = (document.documentElement.getAttribute('data-theme') || '').toLowerCase();
    const bsTheme = (document.documentElement.getAttribute('data-bs-theme') || '').toLowerCase();
    const isDarkLikeTheme = theme === 'dark' || theme === 'red' || bsTheme === 'dark';
    const cssVar = (name, fallback) => {
        const raw = rootStyle.getPropertyValue(name);
        return raw ? raw.trim() : fallback;
    };
    const primaryRgb = cssVar('--bs-primary-rgb', '13, 110, 253');
    const textColor = cssVar('--text-color', '#1f2937');
    const mutedTextColor = cssVar('--text-grey', '#4b4b4b');
    const gridColor = isDarkLikeTheme ? 'rgba(255, 255, 255, 0.16)' : 'rgba(15, 23, 42, 0.12)';
    const constraintLineColor = 'rgba(20, 110, 40, 0.8)';
    const altitudeLineColor = `rgba(${primaryRgb}, 0.92)`;
    const altitudeFillColor = `rgba(${primaryRgb}, 0.2)`;
    const customHorizonLineColor = 'rgba(200, 80, 0, 0.75)';
    const customHorizonFillColor = isDarkLikeTheme ? 'rgba(200, 80, 0, 0.16)' : 'rgba(200, 80, 0, 0.07)';

    // -----------------------------------------------------------------------
    // Build card shell matching the weather-chart style (createChartShell)
    // -----------------------------------------------------------------------
    const card = document.createElement('div');
    card.className = 'card h-100';

    // Card header
    const cardHeader = document.createElement('div');
    cardHeader.className = 'card-header';
    const cardTitle = document.createElement('h5');
    cardTitle.className = 'mb-0';
    DOMUtils.append(cardTitle, DOMUtils.createIcon('bi bi-graph-up-arrow icon-inline text-primary'), title);
    cardHeader.appendChild(cardTitle);

    // Card body - canvas fills the full width, explicit height like weather charts
    const cardBody = document.createElement('div');
    cardBody.className = 'card-body';
    const canvas = document.createElement('canvas');
    canvas.id = 'alttime-chart-canvas';
    canvas.style.width = '100%';
    canvas.style.height = '300px';
    cardBody.appendChild(canvas);

    // Card footer - legend badges + night window info
    const cardFooter = document.createElement('div');
    cardFooter.className = 'card-footer text-muted small';
    const footerRow = document.createElement('div');
    footerRow.className = 'row align-items-center';

    const legendDefs = [
        { color: altitudeLineColor, label: tSkyTonightCompat('altitude_time_altitude_label') || 'Altitude (°)' },
        { color: constraintLineColor, label: tSkyTonightCompat('altitude_time_observable_zone') },
    ];
    if (hasCustomHorizon) {
        legendDefs.push({ color: customHorizonLineColor, label: tSkyTonightCompat('horizon_custom_line') || 'Custom Horizon' });
    }
    legendDefs.forEach(item => {
        const col = document.createElement('div');
        col.className = 'col-auto';
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.backgroundColor = item.color;
        badge.textContent = item.label;
        col.appendChild(badge);
        footerRow.appendChild(col);
    });

    // Night window text (nautical + astronomical stacked on the right)
    if (nightStart && nightEnd) {
        const col = document.createElement('div');
        col.className = 'col-auto ms-auto text-end';
        const span1 = document.createElement('div');
        span1.className = 'text-muted';
        span1.textContent = `${tSkyTonightCompat('altitude_time_night_window')}: ${nightStart} - ${nightEnd}`;
        col.appendChild(span1);
        if (nightAstroStartFmt && nightAstroEndFmt) {
            const span2 = document.createElement('div');
            span2.className = 'text-muted';
            span2.textContent = `${tSkyTonightCompat('altitude_time_astro_night_window')}: ${nightAstroStartFmt} - ${nightAstroEndFmt}`;
            col.appendChild(span2);
        }
        footerRow.appendChild(col);
    }

    cardFooter.appendChild(footerRow);

    // Stale-data notice: profile configured but azimuths not in cached file
    if (horizonProfile.length > 0 && !hasCustomHorizon) {
        const staleRow = document.createElement('div');
        staleRow.className = 'mt-1';
        const staleIcon = document.createElement('i');
        staleIcon.className = 'bi bi-exclamation-triangle-fill text-warning me-1';
        staleIcon.setAttribute('aria-hidden', 'true');
        const staleText = document.createElement('span');
        staleText.className = 'text-warning';
        staleText.textContent = tSkyTonightCompat('altitude_time_horizon_stale');
        staleRow.appendChild(staleIcon);
        staleRow.appendChild(staleText);
        cardFooter.appendChild(staleRow);
    }

    card.appendChild(cardHeader);
    card.appendChild(cardBody);
    card.appendChild(cardFooter);
    bodyElement.appendChild(card);

    // -----------------------------------------------------------------------
    // Render chart
    // -----------------------------------------------------------------------
    _destroyAlttimeChart();

    const constraintBand = altitudes.map(() => altMax);
    const constraintFloor = altitudes.map(() => altMin);

    // Build custom horizon curve: per-step altitude derived from azimuth + profile
    const customHorizonData = hasCustomHorizon
        ? azimuths.map(az => _horizonAltAtAz(az, horizonProfile))
        : null;

    // Add 5° of breathing room when altMax is near or at the top of the chart
    const yMax = altMax >= 85 ? altMax + 5 : 90;

    // Plugin: shade areas outside the observable zone with a darker overlay
    const observableBgPlugin = {
        id: 'alttime_observable_bg',
        beforeDatasetsDraw(chart) {
            const { ctx, chartArea, scales } = chart;
            if (!chartArea) return;
            const yScale = scales.y;
            const { left, right, top, bottom } = chartArea;
            const yMinPx = Math.min(bottom, Math.max(top, yScale.getPixelForValue(altMin)));
            const yMaxPx = Math.min(bottom, Math.max(top, yScale.getPixelForValue(altMax)));
            ctx.save();
            ctx.fillStyle = isDarkLikeTheme ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.07)';
            if (yMaxPx > top) {
                ctx.fillRect(left, top, right - left, yMaxPx - top);
            }
            if (yMinPx < bottom) {
                ctx.fillRect(left, yMinPx, right - left, bottom - yMinPx);
            }
            ctx.restore();
        },
    };

    // Plugin: tint the nautical-but-not-astronomical twilight zones (before astro dusk
    // and after astro dawn) with a warm overlay so the true dark-sky period stands out.
    const astroNightPlugin = {
        id: 'alttime_astro_night',
        beforeDatasetsDraw(chart) {
            if (!nightAstroStart || !nightAstroEnd || timesUtcMs.length === 0) return;
            const { ctx, chartArea, scales } = chart;
            if (!chartArea) return;
            const { left, right, top, bottom } = chartArea;
            const astroStartMs = nightAstroStart.getTime();
            const astroEndMs = nightAstroEnd.getTime();

            // Find the chart x-index closest to astro dusk and astro dawn.
            let xAstroStart = left;
            for (let i = 0; i < timesUtcMs.length; i++) {
                if (timesUtcMs[i] >= astroStartMs) { xAstroStart = scales.x.getPixelForValue(i); break; }
            }
            let xAstroEnd = right;
            for (let i = timesUtcMs.length - 1; i >= 0; i--) {
                if (timesUtcMs[i] <= astroEndMs) { xAstroEnd = scales.x.getPixelForValue(i); break; }
            }

            // Twilight tint color: warm amber works for both light and dark themes.
            const twilightColor = isDarkLikeTheme ? 'rgba(255, 160, 40, 0.12)' : 'rgba(200, 110, 0, 0.10)';
            ctx.save();
            ctx.fillStyle = twilightColor;
            if (xAstroStart > left) ctx.fillRect(left, top, xAstroStart - left, bottom - top);
            if (xAstroEnd < right) ctx.fillRect(xAstroEnd, top, right - xAstroEnd, bottom - top);
            ctx.restore();
        },
    };

    const ctx2d = canvas.getContext('2d');
    _alttimeChartInstance = new Chart(ctx2d, {
        type: 'line',
        plugins: [observableBgPlugin, astroNightPlugin],
        data: {
            labels: times,
            datasets: [
                {
                    // Top bound of observable zone
                    label: tSkyTonightCompat('altitude_time_observable_zone'),
                    data: constraintBand,
                    fill: false,
                    borderColor: constraintLineColor,
                    borderWidth: 2,
                    borderDash: [5, 4],
                    pointRadius: 0,
                    tension: 0,
                    order: 3,
                },
                {
                    // Bottom bound of observable zone
                    label: `${altMin}° (min)`,
                    data: constraintFloor,
                    fill: false,
                    borderColor: constraintLineColor,
                    borderWidth: 2,
                    borderDash: [5, 4],
                    pointRadius: 0,
                    tension: 0,
                    order: 3,
                },
                ...(customHorizonData ? [{
                    label: tSkyTonightCompat('horizon_custom_line') || 'Custom Horizon',
                    data: customHorizonData,
                    fill: 'origin',
                    borderColor: customHorizonLineColor,
                    backgroundColor: customHorizonFillColor,
                    borderWidth: 1.5,
                    borderDash: [4, 3],
                    pointRadius: 0,
                    tension: 0.2,
                    order: 2,
                }] : []),
                {
                    label: tSkyTonightCompat('altitude_time_altitude_label') || 'Altitude (°)',
                    data: altitudes,
                    fill: false,
                    borderColor: altitudeLineColor,
                    backgroundColor: altitudeFillColor,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.4,
                    order: 1,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true,
                    callbacks: {
                        label: ctx => {
                            const label = ctx.dataset.label || '';
                            return `${label}: ${Number(ctx.raw).toFixed(1)}°`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    ticks: { maxTicksLimit: 12, maxRotation: 0, color: mutedTextColor },
                    grid: { color: gridColor },
                    title: {
                        display: true,
                        text: `${tSkyTonightCompat('altitude_time_x_axis')} (${obsTz})`,
                        color: textColor,
                    },
                },
                y: {
                    min: 0,
                    max: yMax,
                    ticks: { stepSize: 15, color: mutedTextColor },
                    grid: { color: gridColor },
                    title: {
                        display: true,
                        text: tSkyTonightCompat('altitude_time_y_axis') || 'Altitude (°)',
                        color: textColor,
                    },
                },
            },
        },
    });
}

function showMorePopup(popupId) {
    const popup = document.getElementById(popupId);

    if (popup) {
        // Use BS modal
        //Prepare modal title
        const titleElement = document.getElementById('modal_lg_close_title');
        titleElement.textContent = tSkyTonightCompat('more_info');

        //Prepare modal content
        const contentElement = document.getElementById('modal_lg_close_body');
        DOMUtils.clear(contentElement);
        Array.from(popup.childNodes).forEach((node) => {
            contentElement.appendChild(node.cloneNode(true));
        });

        const _modalEl2 = document.getElementById('modal_lg_close');
        let bs_modal = bootstrap.Modal.getInstance(_modalEl2);
        if (!bs_modal) {
            bs_modal = new bootstrap.Modal(_modalEl2, { backdrop: true, focus: true, keyboard: true });
        }
        bs_modal.show();

    }
}

// Close popup when clicking outside
window.addEventListener('click', function (event) {
    if (event.target.classList.contains('more-popup')) {
        event.target.style.display = 'none';
    }
});

// ======================
// Astrodex Integration
// ======================

function _normalizeAstrodexLookup(value) {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function _findAstrodexItemFromSkytonightItem(itemData) {
    if (!itemData || !Array.isArray(astrodexData?.items)) {
        return null;
    }

    const namesToMatch = new Set([
        _normalizeAstrodexLookup(itemData.name),
        _normalizeAstrodexLookup(itemData['target name']),
        _normalizeAstrodexLookup(itemData.id)
    ]);

    const aliases = itemData.catalogue_aliases;
    if (aliases && typeof aliases === 'object') {
        Object.values(aliases).forEach(name => namesToMatch.add(_normalizeAstrodexLookup(name)));
    }
    namesToMatch.delete('');
    if (namesToMatch.size === 0) {
        return null;
    }

    return astrodexData.items.find(item => {
        const candidateNames = new Set([
            _normalizeAstrodexLookup(item.name),
            _normalizeAstrodexLookup(item.id)
        ]);

        const itemAliases = item.catalogue_aliases;
        if (itemAliases && typeof itemAliases === 'object') {
            Object.values(itemAliases).forEach(name => candidateNames.add(_normalizeAstrodexLookup(name)));
        }
        candidateNames.delete('');

        for (const name of candidateNames) {
            if (namesToMatch.has(name)) {
                return true;
            }
        }
        return false;
    }) || null;
}

async function openCapturedAstrodexItem(itemData) {
    if (!itemData) {
        return;
    }

    // Keep the user on SkyTonight: refresh Astrodex cache silently only when needed.
    if (typeof astrodexData !== 'undefined') {
        const hasLoadedItems = Array.isArray(astrodexData.items) && astrodexData.items.length > 0;
        if (!hasLoadedItems && typeof fetchJSON === 'function') {
            try {
                const response = await fetchJSON('/api/astrodex');
                astrodexData.items = response.items || [];
                astrodexData.stats = response.stats || {};
                astrodexData.privateMode = response.private_mode !== false;
                astrodexData.currentUserId = response.current_user_id || null;
            } catch (error) {
                console.error('Error loading astrodex cache for SkyTonight popup:', error);
            }
        }
    }

    const matchedItem = _findAstrodexItemFromSkytonightItem(itemData);
    if (!matchedItem && typeof astrodexData !== 'undefined' && typeof fetchJSON === 'function') {
        // Retry once after background refresh in case data changed since last load.
        try {
            const response = await fetchJSON('/api/astrodex');
            astrodexData.items = response.items || [];
            astrodexData.stats = response.stats || {};
            astrodexData.privateMode = response.private_mode !== false;
            astrodexData.currentUserId = response.current_user_id || null;
        } catch (error) {
            console.error('Error refreshing astrodex cache for SkyTonight popup:', error);
        }
    }

    const retryMatchedItem = matchedItem || _findAstrodexItemFromSkytonightItem(itemData);
    if (!retryMatchedItem) {
        return;
    }

    if (typeof showPictureSlideshow === 'function') {
        showPictureSlideshow(retryMatchedItem.id);
    }
}

/**
 * Update the "Captured" badges in catalogue tables after Astrodex changes
 * @param {string} itemName - Name of the item to update
 * @param {boolean} isInAstrodex - Whether the item is now in Astrodex
 */
async function updateCatalogueCapturedBadge(itemDataOrName, isInAstrodex) {
    if (!itemDataOrName) return;

    const normalize = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');

    const targetNames = new Set();
    if (typeof itemDataOrName === 'string') {
        targetNames.add(normalize(itemDataOrName));
    } else {
        targetNames.add(normalize(itemDataOrName.name || itemDataOrName['target name'] || itemDataOrName.id));
        const aliases = itemDataOrName.catalogue_aliases;
        if (aliases && typeof aliases === 'object') {
            Object.values(aliases).forEach(name => targetNames.add(normalize(name)));
        }
    }
    targetNames.delete('');
    if (targetNames.size === 0) return;

    // Find all table rows with matching item name
    const tables = document.querySelectorAll('table[id^="table-"]');

    tables.forEach(table => {
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            // Find the astrodex column cell
            const astrodexCell = Array.from(row.cells).find(cell => {
                const badge = cell.querySelector('.astrodex-captured-btn');
                const button = cell.querySelector('.astrodex-add-btn');
                return badge || button;
            });

            if (!astrodexCell) return;

            const rawItem = astrodexCell.getAttribute('data-item');
            if (!rawItem) return;

            let rowItemData = null;
            try {
                rowItemData = JSON.parse(rawItem.replace(/&quot;/g, '"'));
            } catch (error) {
                return;
            }

            const rowItemName = rowItemData.name || rowItemData['target name'] || rowItemData.id;
            const rowNormalizedName = normalize(rowItemName);
            if (!targetNames.has(rowNormalizedName)) return;

            if (isInAstrodex) {
                DOMUtils.clear(astrodexCell);
                const badge = document.createElement('button');
                badge.type = 'button';
                badge.className = 'in-astrodex-badge astrodex-captured-btn';
                badge.setAttribute('data-item', JSON.stringify(rowItemData));
                badge.setAttribute('title', tSkyTonightCompat('captured'));
                DOMUtils.append(badge, DOMUtils.createIcon('bi bi-check-circle-fill icon-inline'), tSkyTonightCompat('captured'));
                badge.addEventListener('click', async (event) => {
                    event.preventDefault();
                    await openCapturedAstrodexItem(rowItemData);
                });
                astrodexCell.appendChild(badge);
            } else {
                const itemDataJson = JSON.stringify(rowItemData);
                DOMUtils.clear(astrodexCell);
                const addButton = document.createElement('button');
                addButton.className = 'btn btn-sm btn-outline-primary astrodex-add-btn';
                addButton.setAttribute('data-item', itemDataJson);
                DOMUtils.append(addButton, DOMUtils.createIcon('bi bi-plus-circle icon-inline'), tSkyTonightCompat('add'));
                astrodexCell.appendChild(addButton);
            }
        });
    });
}

/**
 * Update the "Planned" badges in catalogue tables after Plan My Night changes
 * @param {object|string} itemDataOrName - Item payload or item name
 * @param {boolean} isPlanned - Whether the item is now in Plan My Night
 */
function updateCataloguePlanMyNightBadge(itemDataOrName, isPlanned) {
    if (!itemDataOrName) return;

    const normalize = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');

    const targetNames = new Set();
    if (typeof itemDataOrName === 'string') {
        targetNames.add(normalize(itemDataOrName));
    } else {
        targetNames.add(normalize(itemDataOrName.name || itemDataOrName['target name'] || itemDataOrName.id));
        const aliases = itemDataOrName.catalogue_aliases;
        if (aliases && typeof aliases === 'object') {
            Object.values(aliases).forEach(name => targetNames.add(normalize(name)));
        }
    }
    targetNames.delete('');
    if (targetNames.size === 0) return;

    const tables = document.querySelectorAll('table[id^="table-"]');

    tables.forEach(table => {
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            const planCell = Array.from(row.cells).find(cell => {
                const badge = cell.querySelector('.in-plan-my-night-badge');
                const button = cell.querySelector('.plan-my-night-add-btn');
                return badge || button;
            });

            if (!planCell) return;

            const rawItem = planCell.getAttribute('data-item');
            if (!rawItem) return;

            let rowItemData = null;
            try {
                rowItemData = JSON.parse(rawItem.replace(/&quot;/g, '"'));
            } catch (error) {
                return;
            }

            const rowItemName = rowItemData.name || rowItemData['target name'] || rowItemData.id;
            const rowNames = new Set([normalize(rowItemName)]);
            const rowAliases = rowItemData.catalogue_aliases;
            if (rowAliases && typeof rowAliases === 'object') {
                Object.values(rowAliases).forEach(name => rowNames.add(normalize(name)));
            }

            const hasMatch = Array.from(rowNames).some(name => name && targetNames.has(name));
            if (!hasMatch) return;

            if (isPlanned) {
                DOMUtils.clear(planCell);
                const badge = document.createElement('span');
                badge.className = 'in-astrodex-badge in-plan-my-night-badge';
                DOMUtils.append(badge, DOMUtils.createIcon('bi bi-check-circle-fill icon-inline'), tSkyTonightCompat('planned'));
                planCell.appendChild(badge);
            } else {
                const itemDataJson = JSON.stringify(rowItemData);
                DOMUtils.clear(planCell);
                const addButton = document.createElement('button');
                addButton.className = 'btn btn-sm btn-outline-info plan-my-night-add-btn';
                addButton.setAttribute('data-item', itemDataJson);
                addButton.setAttribute('data-catalogue', rowItemData.catalogue || currentCatalogueTab || '');
                DOMUtils.append(addButton, DOMUtils.createIcon('bi bi-moon-stars-fill icon-inline'), tSkyTonightCompat('add'));
                planCell.appendChild(addButton);
            }
        });
    });
}

/**
 * Keep cached catalogue reports synchronized after Plan My Night mutations.
 * This avoids stale "Add" buttons when switching catalogue/type tabs.
 */
function updateCataloguePlanMyNightData(itemDataOrName, isPlanned) {
    if (!window.catalogueReports || !itemDataOrName) return;

    const normalize = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');

    const targetNames = new Set();
    if (typeof itemDataOrName === 'string') {
        targetNames.add(normalize(itemDataOrName));
    } else {
        targetNames.add(normalize(itemDataOrName.name || itemDataOrName['target name'] || itemDataOrName.id));
        const aliases = itemDataOrName.catalogue_aliases;
        if (aliases && typeof aliases === 'object') {
            Object.values(aliases).forEach(name => targetNames.add(normalize(name)));
        }
    }
    targetNames.delete('');
    if (targetNames.size === 0) return;

    Object.keys(window.catalogueReports).forEach(catalogue => {
        const reportPayload = window.catalogueReports[catalogue];
        if (!reportPayload || typeof reportPayload !== 'object') return;

        ['report', 'bodies', 'comets'].forEach(key => {
            const rows = reportPayload[key];
            if (!Array.isArray(rows)) return;

            rows.forEach(row => {
                const rowItemName = row.id || row['target name'] || row.name;
                const rowNames = new Set([normalize(rowItemName)]);
                const rowAliases = row.catalogue_aliases;
                if (rowAliases && typeof rowAliases === 'object') {
                    Object.values(rowAliases).forEach(name => rowNames.add(normalize(name)));
                }

                const hasMatch = Array.from(rowNames).some(name => name && targetNames.has(name));
                if (!hasMatch) return;

                row.in_plan_my_night = isPlanned;
                if (isPlanned) {
                    row.plan_state = 'current';
                }
            });
        });
    });
}

// ======================
// Log Management
// ======================

async function loadSkytonightLog() {
    try {
        const result = await fetchJSON('/api/skytonight/log');
        return result.log_content;
    } catch (error) {
        console.error('Error loading SkyTonight log file:', error);
        return null;
    }
}

// ======================
// Report Management
// ======================

