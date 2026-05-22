// ======================
// ISS Passes + Real-time Map
// ======================

// ---- Map module state ----
let _issMap = null;
let _issMarker = null;
let _userLocationMarker = null;
let _issPastLines = [];
let _issFutureLines = [];
let _issMapInterval = null;

/**
 * Split a ground-track point array into segments that don't cross the
 * anti-meridian (|Δlon| > 180°).  Leaflet draws straight lines and would
 * otherwise wrap the wrong way around the globe.
 */
function _splitAtAntimeridian(points) {
    if (!points || !points.length) return [];
    const segments = [];
    let current = [points[0]];
    for (let i = 1; i < points.length; i++) {
        if (Math.abs(points[i][1] - points[i - 1][1]) > 180) {
            segments.push(current);
            current = [points[i]];
        } else {
            current.push(points[i]);
        }
    }
    segments.push(current);
    return segments.filter(s => s.length > 0);
}

/** Remove all existing ground-track polylines from the map. */
function _clearIssTrackLines() {
    _issPastLines.forEach(l => { if (_issMap) _issMap.removeLayer(l); });
    _issFutureLines.forEach(l => { if (_issMap) _issMap.removeLayer(l); });
    _issPastLines = [];
    _issFutureLines = [];
}

/**
 * (Re-)draw ground-track polylines and reposition the ISS marker.
 * Safe to call on every poll cycle.
 */
function _updateIssMapContent(data) {
    if (!_issMap || !_issMarker) return;

    const lat = Number(data.latitude);
    const lon = Number(data.longitude);

    // Update marker position (no setView - avoids the infinite-tiles zoom loop)
    _issMarker.setLatLng([lat, lon]);

    // Build popup content including observer visibility when available
    const obs = data.observer;
    let popupHtml = `<b>ISS</b><br>${i18n.t('iss.map_altitude_label')}: ${data.altitude_km} km`;
    if (obs) {
        const visLabel = obs.is_visible
            ? `<span style="color:#22c55e">&#9679; ${i18n.t('iss.map_visible')}</span>`
            : `<span style="color:#6b7280">&#9675; ${i18n.t('iss.map_not_visible')}</span>`;
        popupHtml += `<br>${visLabel}`;
        if (obs.iss_altitude_deg > 0) {
            popupHtml += `<br>Alt: ${obs.iss_altitude_deg}° Az: ${obs.iss_azimuth_deg}°`;
        }
    }
    _issMarker.getPopup().setContent(popupHtml);

    // Update the visibility ring colour via DOM (avoids full icon redraw)
    const markerEl = _issMarker.getElement();
    if (markerEl) {
        const ring = markerEl.querySelector('.iss-visibility-ring');
        if (ring) {
            ring.className = 'iss-visibility-ring ' + (obs && obs.is_visible ? 'iss-visible' : 'iss-not-visible');
        }
    }

    // Redraw tracks
    _clearIssTrackLines();
    _splitAtAntimeridian(data.past_track || []).forEach(seg => {
        _issPastLines.push(L.polyline(seg, { color: '#f97316', weight: 2, opacity: 0.55, dashArray: '5,6' }).addTo(_issMap));
    });
    _splitAtAntimeridian(data.future_track || []).forEach(seg => {
        _issFutureLines.push(L.polyline(seg, { color: '#6366f1', weight: 2, opacity: 0.85 }).addTo(_issMap));
    });

    // Update meta bar if present
    const metaEl = document.getElementById('iss-map-meta');
    if (metaEl) {
        metaEl.textContent = `${i18n.t('iss.map_altitude_label')}: ${data.altitude_km} km`;
    }
}

/** Poll /api/iss/location and refresh map. */
async function _pollIssLocation() {
    try {
        const resp = await fetch('/api/iss/location', { credentials: 'same-origin', cache: 'no-store' });
        if (!resp.ok) return;
        const data = await resp.json();
        if (data && data.latitude !== undefined) {
            _updateIssMapContent(data);
        }
    } catch (_) { /* silent - map just stays stale */ }
}

/** Stop the auto-refresh interval for the ISS map. */
function _stopIssMapRefresh() {
    if (_issMapInterval !== null) {
        clearInterval(_issMapInterval);
        _issMapInterval = null;
    }
}

/**
 * Create the ISS real-time map card, insert it into `container`, and start
 * a 10-second refresh cycle.
 */
async function _createIssMapCard(container) {
    // Card shell
    const row = document.createElement('div');
    row.className = 'row row-cols-1 mb-3';
    const col = document.createElement('div');
    col.className = 'col';
    const card = document.createElement('div');
    card.className = 'card h-100';

    const cardHeader = document.createElement('div');
    cardHeader.className = 'card-header fw-bold d-flex align-items-center gap-2';
    cardHeader.innerHTML =
        `<i class="bi bi-globe-americas icon-inline" aria-hidden="true"></i>${i18n.t('iss.map_title')}` +
        `<span class="ms-auto iss-map-legend d-flex gap-3">` +
        `<span><span class="iss-legend-dot iss-legend-past"></span>${i18n.t('iss.map_past_track')}</span>` +
        `<span><span class="iss-legend-dot iss-legend-future"></span>${i18n.t('iss.map_future_track')}</span>` +
        `</span>`;

    // Meta bar (altitude etc.)
    const metaBar = document.createElement('div');
    metaBar.id = 'iss-map-meta';
    metaBar.className = 'iss-map-meta text-muted';
    metaBar.textContent = i18n.t('iss.map_loading');

    // Map container
    const mapEl = document.createElement('div');
    mapEl.id = 'iss-map';
    mapEl.className = 'iss-map';

    card.appendChild(cardHeader);
    card.appendChild(metaBar);
    card.appendChild(mapEl);
    col.appendChild(card);
    row.appendChild(col);
    container.appendChild(row);

    // Initialise Leaflet (needs the element to be in the DOM first)
    // A tiny delay ensures the element has been painted and has a size.
    await new Promise(r => setTimeout(r, 50));

    if (typeof L === 'undefined') {
        metaBar.textContent = i18n.t('iss.map_error');
        return;
    }

    _issMap = L.map('iss-map', { zoomControl: true, scrollWheelZoom: true });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 7,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(_issMap);

    // Custom ISS icon with a visibility ring (green = visible, grey = not visible)
    const issIcon = L.divIcon({
        className: '',
        html: '<span class="iss-marker-icon" aria-label="ISS"><span class="iss-visibility-ring iss-not-visible"></span><i class="bi bi-iss" style="font-size:1.6rem;color:#f97316;text-shadow:0 0 4px #000a"></i></span>',
        iconSize: [44, 44],
        iconAnchor: [22, 22],
    });

    _issMarker = L.marker([0, 0], { icon: issIcon })
        .addTo(_issMap)
        .bindPopup('<b>ISS</b>');

    // First fetch
    try {
        const resp = await fetch('/api/iss/location', { credentials: 'same-origin', cache: 'no-store' });
        if (resp.ok) {
            const data = await resp.json();
            if (data && data.latitude !== undefined) {
                _updateIssMapContent(data);
                _issMap.setView([data.latitude, data.longitude], 2);

                // Add user location pin once (from observer data returned by backend)
                if (data.observer && data.observer.latitude !== undefined && !_userLocationMarker) {
                    const userIcon = L.divIcon({
                        className: '',
                        html: `<span class="iss-user-location-pin" title="${i18n.t('iss.map_your_location')}"></span>`,
                        iconSize: [20, 20],
                        iconAnchor: [10, 10],
                    });
                    _userLocationMarker = L.marker([data.observer.latitude, data.observer.longitude], { icon: userIcon, zIndexOffset: 500 })
                        .addTo(_issMap)
                        .bindPopup(`<b>${i18n.t('iss.map_your_location')}</b>`);
                }
            }
        } else {
            metaBar.textContent = i18n.t('iss.map_error');
        }
    } catch (_) {
        metaBar.textContent = i18n.t('iss.map_error');
    }

    // Auto-refresh every 15 s (position is computed locally from TLE - no external API per poll)
    _stopIssMapRefresh();
    _issMapInterval = setInterval(_pollIssLocation, 15000);
}


function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function computeVisibilityScore(pass) {
    const peakAltitudeDeg = Number(pass?.peak_altitude_deg);
    const startMs = Date.parse(pass?.start_time || '');
    const endMs = Date.parse(pass?.end_time || '');

    const altitudeScore = Number.isFinite(peakAltitudeDeg)
        ? clamp(peakAltitudeDeg / 90, 0, 1)
        : 0;

    const durationMinutes = Number.isFinite(startMs) && Number.isFinite(endMs) && endMs >= startMs
        ? (endMs - startMs) / 60000
        : 0;
    const durationScore = clamp(durationMinutes / 8, 0, 1);

    const score = Math.round(((altitudeScore * 0.7) + (durationScore * 0.3)) * 100);
    return clamp(score, 0, 100);
}

function createVisibilityGauge(scorePercent) {
    const container = document.createElement('div');
    container.className = 'iss-score';

    const label = document.createElement('div');
    label.className = 'iss-score-label';
    label.textContent = `${scorePercent}%`;

    const track = document.createElement('div');
    track.className = 'iss-score-track';

    const fill = document.createElement('div');
    fill.className = 'iss-score-fill';
    fill.style.width = `${scorePercent}%`;
    fill.setAttribute('role', 'progressbar');
    fill.setAttribute('aria-valuemin', '0');
    fill.setAttribute('aria-valuemax', '100');
    fill.setAttribute('aria-valuenow', String(scorePercent));
    fill.setAttribute('aria-label', `Visibility score ${scorePercent}%`);

    track.appendChild(fill);
    container.appendChild(label);
    container.appendChild(track);

    return container;
}

function _appendCelestrakStatusBanner(container, celestrakStatus) {
    if (!celestrakStatus || celestrakStatus.blocked !== true) {
        return;
    }

    const blockedAt = Number(celestrakStatus.blocked_at || 0);
    const dismissedKey = 'iss.celestrak.dismissed_blocked_at';
    if (blockedAt > 0 && localStorage.getItem(dismissedKey) === String(blockedAt)) {
        return;
    }

    const alert = document.createElement('div');
    alert.className = 'alert alert-warning alert-dismissible fade show mb-3';
    alert.setAttribute('role', 'alert');

    const title = document.createElement('div');
    title.className = 'fw-bold mb-1';
    title.textContent = i18n.t('iss.celestrak_blocked_title');
    alert.appendChild(title);

    const description = document.createElement('div');
    description.className = 'mb-2';
    description.textContent = i18n.t('iss.celestrak_blocked_description');
    alert.appendChild(description);

    const linksWrap = document.createElement('div');
    linksWrap.className = 'mb-2';

    const checkLink = document.createElement('a');
    checkLink.href = celestrakStatus.manual_check_url || 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE';
    checkLink.target = '_blank';
    checkLink.rel = 'noopener noreferrer';
    checkLink.className = 'btn btn-outline-secondary btn-sm me-2';
    checkLink.textContent = i18n.t('iss.celestrak_check_link');
    linksWrap.appendChild(checkLink);

    const policyLink = document.createElement('a');
    policyLink.href = celestrakStatus.policy_url || 'https://celestrak.org/usage-policy.php';
    policyLink.target = '_blank';
    policyLink.rel = 'noopener noreferrer';
    policyLink.className = 'btn btn-outline-secondary btn-sm';
    policyLink.textContent = i18n.t('iss.celestrak_policy_link');
    linksWrap.appendChild(policyLink);

    alert.appendChild(linksWrap);

    const hint = document.createElement('div');
    hint.className = 'small text-muted mb-2';
    hint.textContent = i18n.t('iss.celestrak_restart_hint');
    alert.appendChild(hint);

    const restartButton = document.createElement('button');
    restartButton.type = 'button';
    restartButton.className = 'btn btn-warning btn-sm';
    restartButton.textContent = i18n.t('iss.celestrak_restart_button');
    restartButton.disabled = true;
    alert.appendChild(restartButton);

    checkLink.addEventListener('click', () => {
        restartButton.disabled = false;
    });

    restartButton.addEventListener('click', async () => {
        const confirmed = window.confirm(i18n.t('iss.celestrak_restart_confirm'));
        if (!confirmed) {
            return;
        }

        restartButton.disabled = true;
        try {
            const resp = await fetch('/api/iss/celestrak/restart', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirmed: true }),
            });
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}`);
            }
            await loadIss();
        } catch (_) {
            restartButton.disabled = false;
        }
    });

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn-close';
    closeButton.setAttribute('aria-label', i18n.t('common.close'));
    closeButton.addEventListener('click', () => {
        if (blockedAt > 0) {
            localStorage.setItem(dismissedKey, String(blockedAt));
        }
        if (alert.parentNode) {
            alert.parentNode.removeChild(alert);
        }
    });
    alert.appendChild(closeButton);

    container.appendChild(alert);
}

/**
 * Load ISS upcoming passes for current location (next 20 days).
 */
async function loadIss() {
    // Stop any running map refresh from a previous load
    _stopIssMapRefresh();
    _issMap = null;
    _issMarker = null;
    _userLocationMarker = null;
    _issPastLines = [];
    _issFutureLines = [];

    const container = document.getElementById('iss-display');
    const data = await fetchJSONWithUI('/api/iss/passes?days=20', container, i18n.t('iss.loading_passes'));
    if (!data) return;

    const nextVisible = data.next_visible_passage;
    const passes = Array.isArray(data.passes) ? data.passes : [];

    DOMUtils.clear(container);

    _appendCelestrakStatusBanner(container, data.celestrak_status);

    const infoAlert = document.createElement('div');
    infoAlert.className = 'alert alert-info';
    infoAlert.setAttribute('role', 'alert');
    infoAlert.textContent = i18n.t('iss.info_tab', { days: Number(data.window_days || 20) });
    container.appendChild(infoAlert);

    if (nextVisible) {
        const row = document.createElement('div');
        row.className = 'row row-cols-1 mb-3';
        const col = document.createElement('div');
        col.className = 'col';
        const card = document.createElement('div');
        card.className = 'card h-100 border-success';
        const cardHeader = document.createElement('div');
        cardHeader.className = 'card-header fw-bold';
        cardHeader.innerHTML = `<i class="bi bi-check-circle-fill text-success icon-inline" aria-hidden="true"></i>${i18n.t('iss.next_visible_passage')}`;
        const cardBody = document.createElement('div');
        cardBody.className = 'card-body';
        const bodyRow = document.createElement('div');
        bodyRow.className = 'row row-cols-1 row-cols-lg-2';

        const createInfoColumn = (items) => {
            const infoCol = document.createElement('div');
            infoCol.className = 'col mb-2';
            items.forEach(({ label, value }) => {
                const line = document.createElement('div');
                const strong = document.createElement('strong');
                strong.innerHTML = label;
                line.appendChild(strong);
                line.append(' ');
                line.append(value);
                infoCol.appendChild(line);
            });
            return infoCol;
        };

        bodyRow.appendChild(createInfoColumn([
            { label: `<i class="bi bi-clock icon-inline" aria-hidden="true"></i>${i18n.t('iss.start')}`, value: formatTimeThenDateWithSeconds(nextVisible.start_time) },
            { label: `<i class="bi bi-stopwatch icon-inline" aria-hidden="true"></i>${i18n.t('iss.culmination')}`, value: formatTimeThenDateWithSeconds(nextVisible.peak_time) },
            { label: `<i class="bi bi-clock-history icon-inline" aria-hidden="true"></i>${i18n.t('iss.end')}`, value: formatTimeThenDateWithSeconds(nextVisible.end_time) }
        ]));

        bodyRow.appendChild(createInfoColumn([
            { label: `<i class="bi bi-compass icon-inline" aria-hidden="true"></i>${i18n.t('iss.start_alt_az')}`, value: formatAltAz(nextVisible.start_altitude_deg, nextVisible.start_azimuth_cardinal, nextVisible.start_azimuth_deg) },
            { label: `<i class="bi bi-compass icon-inline" aria-hidden="true"></i>${i18n.t('iss.peak_alt_az')}`, value: formatAltAz(nextVisible.peak_altitude_deg, nextVisible.peak_azimuth_cardinal, nextVisible.peak_azimuth_deg) },
            { label: `<i class="bi bi-compass icon-inline" aria-hidden="true"></i>${i18n.t('iss.end_alt_az')}`, value: formatAltAz(nextVisible.end_altitude_deg, nextVisible.end_azimuth_cardinal, nextVisible.end_azimuth_deg) }
        ]));

        cardBody.appendChild(bodyRow);
        card.appendChild(cardHeader);
        card.appendChild(cardBody);
        col.appendChild(card);
        row.appendChild(col);
        container.appendChild(row);
    } else {
        const warning = document.createElement('div');
        warning.className = 'alert alert-warning';
        warning.setAttribute('role', 'alert');
        warning.textContent = i18n.t('iss.no_passes');
        container.appendChild(warning);
    }

    // ---- Real-time ISS map (between next-pass card and passes table) ----
    await _createIssMapCard(container);

    const tableRow = document.createElement('div');
    tableRow.className = 'row row-cols-1';
    const tableCol = document.createElement('div');
    tableCol.className = 'col';
    const tableCard = document.createElement('div');
    tableCard.className = 'card h-100';
    const tableHeader = document.createElement('div');
    tableHeader.className = 'card-header fw-bold';
    tableHeader.innerHTML = `<i class="bi bi-calendar-event text-danger icon-inline" aria-hidden="true"></i>${i18n.t('iss.upcoming_passages')}`;
    const tableResponsive = document.createElement('div');
    tableResponsive.className = 'table-responsive';
    const table = document.createElement('table');
    table.className = 'table table-striped table-hover mb-0 iss-pass-table';
    const thead = document.createElement('thead');
    const headRowTop = document.createElement('tr');
    [
        { text: i18n.t('iss.table_date'), rowSpan: 2 },
        { text: i18n.t('iss.table_visibility'), rowSpan: 2 },
        { text: i18n.t('iss.table_start'), colSpan: 2, className: 'iss-group-head' },
        { text: i18n.t('iss.table_culmination'), colSpan: 2, className: 'iss-group-head' },
        { text: i18n.t('iss.table_end'), colSpan: 2, className: 'iss-group-head' }
    ].forEach((headerConfig) => {
        const th = document.createElement('th');
        th.textContent = headerConfig.text;
        if (headerConfig.rowSpan) th.rowSpan = headerConfig.rowSpan;
        if (headerConfig.colSpan) th.colSpan = headerConfig.colSpan;
        if (headerConfig.className) th.className = headerConfig.className;
        headRowTop.appendChild(th);
    });

    const headRowBottom = document.createElement('tr');
    [i18n.t('iss.table_time'), i18n.t('iss.table_elev'), i18n.t('iss.table_time'), i18n.t('iss.table_elev'), i18n.t('iss.table_time'), i18n.t('iss.table_elev')].forEach((headerText) => {
        const th = document.createElement('th');
        th.className = 'text-center';
        th.textContent = headerText;
        headRowBottom.appendChild(th);
    });

    thead.appendChild(headRowTop);
    thead.appendChild(headRowBottom);

    const tbody = document.createElement('tbody');
    if (passes.length > 0) {
        passes.forEach((pass) => {
            const row = document.createElement('tr');

            const dateCell = document.createElement('td');
            dateCell.textContent = formatDateFull(pass.peak_time);
            row.appendChild(dateCell);

            const visibilityCell = document.createElement('td');
            const visibilityScore = computeVisibilityScore(pass);
            visibilityCell.appendChild(createVisibilityGauge(visibilityScore));
            row.appendChild(visibilityCell);

            [
                formatTimeThenDateWithSeconds(pass.start_time),
                formatAltAz(pass.start_altitude_deg, pass.start_azimuth_cardinal, pass.start_azimuth_deg),
                formatTimeThenDateWithSeconds(pass.peak_time),
                formatAltAz(pass.peak_altitude_deg, pass.peak_azimuth_cardinal, pass.peak_azimuth_deg),
                formatTimeThenDateWithSeconds(pass.end_time),
                formatAltAz(pass.end_altitude_deg, pass.end_azimuth_cardinal, pass.end_azimuth_deg)
            ].forEach((value) => {
                const td = document.createElement('td');
                td.className = 'text-center';
                td.textContent = value;
                row.appendChild(td);
            });
            tbody.appendChild(row);
        });
    } else {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'text-center text-muted';
        cell.textContent = i18n.t('iss.not_found');
        row.appendChild(cell);
        tbody.appendChild(row);
    }

    table.appendChild(thead);
    table.appendChild(tbody);
    tableResponsive.appendChild(table);
    tableCard.appendChild(tableHeader);
    tableCard.appendChild(tableResponsive);
    tableCol.appendChild(tableCard);
    tableRow.appendChild(tableCol);
    container.appendChild(tableRow);

    const tleSource = data.tle_source || {};
    const sourceName = (tleSource.name || '').trim() || i18n.t('iss.footer_unknown_source');
    const sourceUrl = (tleSource.url || '').trim();
    const sourceText = i18n.t('iss.footer_source', { source: sourceName });
    appendDataSourceFooter(container, {
        text: sourceText,
        links: sourceUrl ? [{ href: sourceUrl, label: sourceName }] : []
    });
}
