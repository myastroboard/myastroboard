// ======================
// Orbital Stations (ISS + CSS) – Passes, Real-time Map
// ======================

// ---- Shared map state ----
let _orbMap = null;
let _issMarker = null;
let _cssMarker = null;
let _userLocationMarker = null;
let _issPastLines  = [];
let _issFutureLines = [];
let _cssPastLines  = [];
let _cssFutureLines = [];
let _orbMapInterval = null;

const ISS_PAST_COLOR    = '#f97316'; // orange
const ISS_FUTURE_COLOR  = '#6366f1'; // indigo
const CSS_PAST_COLOR    = '#ef4444'; // red
const CSS_FUTURE_COLOR  = '#8b5cf6'; // violet

const _leafletLoadState = { promise: null };

/** Lazily load the Leaflet library (only needed for the orbital stations map) so it isn't fetched on every page load. */
function _ensureLeafletLoaded() {
    return ensureVendorScriptLoaded(
        () => typeof L !== 'undefined',
        '/static/vendor/leaflet/dist/leaflet.min.js?v=1.9.4',
        '/static/vendor/leaflet/dist/leaflet.min.css?v=1.9.4',
        _leafletLoadState,
        'Leaflet'
    );
}

// ---- Active passes tab ('iss' | 'css') ----
let _activePassesStation = 'iss';

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

function _clearTrackLines(pastArr, futureArr) {
    pastArr.forEach(l => { if (_orbMap) _orbMap.removeLayer(l); });
    futureArr.forEach(l => { if (_orbMap) _orbMap.removeLayer(l); });
    pastArr.length = 0;
    futureArr.length = 0;
}

function _updateStationMapContent(data, marker, pastArr, futureArr, pastColor, futureColor, labelKey) {
    if (!_orbMap || !marker) return;
    const lat = Number(data.latitude);
    const lon = Number(data.longitude);
    marker.setLatLng([lat, lon]);

    const obs = data.observer;
    const stationLabel = i18n.t(labelKey);
    let popupHtml = `<b>${stationLabel}</b><br>${i18n.t('iss.map_altitude_label')}: ${data.altitude_km} km`;
    if (obs) {
        const altKey = data.station === 'CSS' ? 'css_altitude_deg' : 'iss_altitude_deg';
        const visLabel = obs.is_visible
            ? `<span style="color:#22c55e">&#9679; ${i18n.t('iss.map_visible')}</span>`
            : `<span style="color:#6b7280">&#9675; ${i18n.t('iss.map_not_visible')}</span>`;
        popupHtml += `<br>${visLabel}`;
        if ((obs[altKey] || 0) > 0) {
            const azKey = data.station === 'CSS' ? 'css_azimuth_deg' : 'iss_azimuth_deg';
            popupHtml += `<br>Alt: ${obs[altKey]}° Az: ${obs[azKey]}°`;
        }
    }
    marker.getPopup().setContent(popupHtml);

    const markerEl = marker.getElement();
    if (markerEl) {
        const ring = markerEl.querySelector('.iss-visibility-ring');
        if (ring) {
            ring.className = 'iss-visibility-ring ' + (obs && obs.is_visible ? 'iss-visible' : 'iss-not-visible');
        }
    }

    _clearTrackLines(pastArr, futureArr);
    _splitAtAntimeridian(data.past_track || []).forEach(seg => {
        pastArr.push(L.polyline(seg, { color: pastColor, weight: 2, opacity: 0.55, dashArray: '5,6' }).addTo(_orbMap));
    });
    _splitAtAntimeridian(data.future_track || []).forEach(seg => {
        futureArr.push(L.polyline(seg, { color: futureColor, weight: 2, opacity: 0.85 }).addTo(_orbMap));
    });
}

async function _pollOrbitalLocations() {
    try {
        const [issResp, cssResp] = await Promise.all([
            fetch('/api/iss/location', { credentials: 'same-origin', cache: 'no-store' }),
            fetch('/api/css/location', { credentials: 'same-origin', cache: 'no-store' }),
        ]);
        if (issResp.ok) {
            const d = await issResp.json();
            if (d && d.latitude !== undefined)
                _updateStationMapContent(d, _issMarker, _issPastLines, _issFutureLines, ISS_PAST_COLOR, ISS_FUTURE_COLOR, 'orbital_stations.iss_label');
        }
        if (cssResp.ok) {
            const d = await cssResp.json();
            if (d && d.latitude !== undefined)
                _updateStationMapContent(d, _cssMarker, _cssPastLines, _cssFutureLines, CSS_PAST_COLOR, CSS_FUTURE_COLOR, 'orbital_stations.css_label');
        }
    } catch (_) { /* silent */ }
}

function _stopOrbMapRefresh() {
    if (_orbMapInterval !== null) {
        clearInterval(_orbMapInterval);
        _orbMapInterval = null;
    }
}

function _makeStationIcon(color, ringClass) {
    return L.divIcon({
        className: '',
        html: `<span class="iss-marker-icon"><span class="iss-visibility-ring ${ringClass}"></span><i class="bi bi-iss" style="font-size:1.6rem;color:${color};text-shadow:0 0 4px #000a"></i></span>`,
        iconSize: [44, 44],
        iconAnchor: [22, 22],
    });
}

async function _createOrbitalMapCard(container) {
    const row = document.createElement('div');
    row.className = 'row row-cols-1 mb-3';
    const col = document.createElement('div');
    col.className = 'col';
    const card = document.createElement('div');
    card.className = 'card h-100';

    const cardHeader = document.createElement('div');
    cardHeader.className = 'card-header fw-bold d-flex align-items-center gap-2 flex-wrap';
    DOMUtils.append(cardHeader, DOMUtils.createIcon('bi bi-globe-americas icon-inline'), i18n.t('orbital_stations.map_title'));
    const _legend = document.createElement('span');
    _legend.className = 'ms-auto iss-map-legend d-flex gap-3 flex-wrap';
    const _mkLegendItem = (color, opacity, label) => {
        const s = document.createElement('span');
        const dot = document.createElement('span');
        dot.className = 'iss-legend-dot';
        dot.style.background = color;
        if (opacity) dot.style.opacity = String(opacity);
        s.appendChild(dot);
        s.appendChild(document.createTextNode(label));
        return s;
    };
    _legend.appendChild(_mkLegendItem(ISS_PAST_COLOR, 0.6, `ISS ${i18n.t('iss.map_past_track')}`));
    _legend.appendChild(_mkLegendItem(ISS_FUTURE_COLOR, null, `ISS ${i18n.t('iss.map_future_track')}`));
    _legend.appendChild(_mkLegendItem(CSS_PAST_COLOR, 0.6, `CSS ${i18n.t('iss.map_past_track')}`));
    _legend.appendChild(_mkLegendItem(CSS_FUTURE_COLOR, null, `CSS ${i18n.t('iss.map_future_track')}`));
    cardHeader.appendChild(_legend);

    const metaBar = document.createElement('div');
    metaBar.id = 'orb-map-meta';
    metaBar.className = 'iss-map-meta text-muted';
    metaBar.textContent = i18n.t('iss.map_loading');

    const mapEl = document.createElement('div');
    mapEl.id = 'orb-map';
    mapEl.className = 'iss-map';

    card.appendChild(cardHeader);
    card.appendChild(metaBar);
    card.appendChild(mapEl);
    col.appendChild(card);
    row.appendChild(col);
    container.appendChild(row);

    await new Promise(r => setTimeout(r, 50));

    try {
        await _ensureLeafletLoaded();
    } catch (_) {
        metaBar.textContent = i18n.t('iss.map_error');
        return;
    }

    _orbMap = L.map('orb-map', { zoomControl: true, scrollWheelZoom: false, touchZoom: false });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 7,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(_orbMap);

    _issMarker = L.marker([0, 0], { icon: _makeStationIcon(ISS_PAST_COLOR, 'iss-not-visible') })
        .addTo(_orbMap).bindPopup('<b>ISS</b>');
    _cssMarker = L.marker([0, 0], { icon: _makeStationIcon(CSS_PAST_COLOR, 'iss-not-visible') })
        .addTo(_orbMap).bindPopup('<b>CSS</b>');

    try {
        const [issResp, cssResp] = await Promise.all([
            fetch('/api/iss/location', { credentials: 'same-origin', cache: 'no-store' }),
            fetch('/api/css/location', { credentials: 'same-origin', cache: 'no-store' }),
        ]);

        let firstLat = null, firstLon = null;

        if (issResp.ok) {
            const d = await issResp.json();
            if (d && d.latitude !== undefined) {
                _updateStationMapContent(d, _issMarker, _issPastLines, _issFutureLines, ISS_PAST_COLOR, ISS_FUTURE_COLOR, 'orbital_stations.iss_label');
                firstLat = d.latitude; firstLon = d.longitude;
                if (d.observer && d.observer.latitude !== undefined && !_userLocationMarker) {
                    const userIcon = L.divIcon({
                        className: '',
                        html: `<span class="iss-user-location-pin" title="${i18n.t('iss.map_your_location')}"></span>`,
                        iconSize: [20, 20], iconAnchor: [10, 10],
                    });
                    _userLocationMarker = L.marker([d.observer.latitude, d.observer.longitude], { icon: userIcon, zIndexOffset: 500 })
                        .addTo(_orbMap).bindPopup(`<b>${i18n.t('iss.map_your_location')}</b>`);
                }
            }
        }
        if (cssResp.ok) {
            const d = await cssResp.json();
            if (d && d.latitude !== undefined)
                _updateStationMapContent(d, _cssMarker, _cssPastLines, _cssFutureLines, CSS_PAST_COLOR, CSS_FUTURE_COLOR, 'orbital_stations.css_label');
        }

        if (firstLat !== null) _orbMap.setView([firstLat, firstLon], 2);
        metaBar.textContent = i18n.t('orbital_stations.map_live');
    } catch (_) {
        metaBar.textContent = i18n.t('iss.map_error');
    }

    _stopOrbMapRefresh();
    _orbMapInterval = setInterval(_pollOrbitalLocations, 15000);
}

// ---- Altitude graph helpers ----

// ---- Celestrak status banner ----
function _appendCelestrakBanner(container, celestrakStatus, station) {
    if (!celestrakStatus || celestrakStatus.blocked !== true) return;

    const blockedAt = Number(celestrakStatus.blocked_at || 0);
    const dismissedKey = `orbital_stations.celestrak.${station}.dismissed_blocked_at`;
    if (blockedAt > 0 && localStorage.getItem(dismissedKey) === String(blockedAt)) return;

    const alert = document.createElement('div');
    alert.className = 'alert alert-warning alert-dismissible fade show mb-3';
    alert.setAttribute('role', 'alert');

    const title = document.createElement('div');
    title.className = 'fw-bold mb-1';
    title.textContent = `${station.toUpperCase()}: ${i18n.t('iss.celestrak_blocked_title')}`;
    alert.appendChild(title);

    const description = document.createElement('div');
    description.className = 'mb-2';
    description.textContent = i18n.t('iss.celestrak_blocked_description');
    alert.appendChild(description);

    const linksWrap = document.createElement('div');
    linksWrap.className = 'mb-2';

    const checkLink = document.createElement('a');
    checkLink.href = celestrakStatus.manual_check_url || '#';
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

    const restartBtn = document.createElement('button');
    restartBtn.type = 'button';
    restartBtn.className = 'btn btn-warning btn-sm';
    restartBtn.textContent = i18n.t('iss.celestrak_restart_button');
    restartBtn.disabled = true;
    alert.appendChild(restartBtn);

    checkLink.addEventListener('click', () => { restartBtn.disabled = false; });
    restartBtn.addEventListener('click', async () => {
        if (!window.confirm(i18n.t('iss.celestrak_restart_confirm'))) return;
        restartBtn.disabled = true;
        try {
            const endpoint = station === 'css' ? '/api/css/celestrak/restart' : '/api/iss/celestrak/restart';
            const resp = await fetch(endpoint, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true }) });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            await loadOrbitalStations();
        } catch (_) {
            restartBtn.disabled = false;
        }
    });

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'btn-close';
    closeBtn.setAttribute('aria-label', i18n.t('common.close'));
    closeBtn.addEventListener('click', () => {
        if (blockedAt > 0) localStorage.setItem(dismissedKey, String(blockedAt));
        if (alert.parentNode) alert.parentNode.removeChild(alert);
    });
    alert.appendChild(closeBtn);

    container.appendChild(alert);
}

// ---- Visibility score helpers (unchanged from iss.js) ----
function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function computeOrbVisibilityScore(pass) {
    const peakAlt = Number(pass?.peak_altitude_deg);
    const startMs = Date.parse(pass?.start_time || '');
    const endMs   = Date.parse(pass?.end_time   || '');
    const altScore = Number.isFinite(peakAlt) ? clamp(peakAlt / 90, 0, 1) : 0;
    const durMin   = (Number.isFinite(startMs) && Number.isFinite(endMs) && endMs >= startMs) ? (endMs - startMs) / 60000 : 0;
    const durScore = clamp(durMin / 8, 0, 1);
    return clamp(Math.round(((altScore * 0.7) + (durScore * 0.3)) * 100), 0, 100);
}

function createOrbVisibilityGauge(scorePercent) {
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
    track.appendChild(fill);
    container.appendChild(label);
    container.appendChild(track);
    return container;
}

// ---- Next visible passage card ----
function _createNextPassCard(passData, stationKey, borderClass) {
    const col = document.createElement('div');
    col.className = 'col';
    const card = document.createElement('div');
    card.className = `card h-100 ${borderClass}`;
    const cardHeader = document.createElement('div');
    cardHeader.className = 'card-header fw-bold';
    const stationLabel = i18n.t(`orbital_stations.${stationKey}_label`);
    if (passData) {
        DOMUtils.append(cardHeader, DOMUtils.createIcon('bi bi-check-circle-fill text-success icon-inline'), i18n.t(`${stationKey}.next_visible_passage`));
        const cardBody = document.createElement('div');
        cardBody.className = 'card-body';
        const bodyRow = document.createElement('div');
        bodyRow.className = 'row row-cols-1 row-cols-lg-2';
        const createInfoCol = (items) => {
            const c = document.createElement('div');
            c.className = 'col mb-2';
            items.forEach(({ iconClass, labelText, value }) => {
                const line = document.createElement('div');
                const strong = document.createElement('strong');
                DOMUtils.append(strong, DOMUtils.createIcon(iconClass), labelText);
                line.appendChild(strong);
                line.append(' ');
                line.append(value);
                c.appendChild(line);
            });
            return c;
        };
        bodyRow.appendChild(createInfoCol([
            { iconClass: 'bi bi-clock icon-inline', labelText: i18n.t('iss.start'), value: formatTimeThenDateWithSeconds(passData.start_time) },
            { iconClass: 'bi bi-stopwatch icon-inline', labelText: i18n.t('iss.culmination'), value: formatTimeThenDateWithSeconds(passData.peak_time) },
            { iconClass: 'bi bi-clock-history icon-inline', labelText: i18n.t('iss.end'), value: formatTimeThenDateWithSeconds(passData.end_time) },
        ]));
        bodyRow.appendChild(createInfoCol([
            { iconClass: 'bi bi-compass icon-inline', labelText: i18n.t('iss.start_alt_az'), value: formatAltAz(passData.start_altitude_deg, passData.start_azimuth_cardinal, passData.start_azimuth_deg) },
            { iconClass: 'bi bi-compass icon-inline', labelText: i18n.t('iss.peak_alt_az'),  value: formatAltAz(passData.peak_altitude_deg,  passData.peak_azimuth_cardinal,  passData.peak_azimuth_deg)  },
            { iconClass: 'bi bi-compass icon-inline', labelText: i18n.t('iss.end_alt_az'),  value: formatAltAz(passData.end_altitude_deg,  passData.end_azimuth_cardinal,  passData.end_azimuth_deg)  },
        ]));
        cardBody.appendChild(bodyRow);
        card.appendChild(cardHeader);
        card.appendChild(cardBody);
    } else {
        DOMUtils.append(cardHeader, DOMUtils.createIcon('bi bi-question-circle icon-inline'), stationLabel);
        card.appendChild(cardHeader);
        const cardBody = document.createElement('div');
        cardBody.className = 'card-body text-muted';
        cardBody.textContent = i18n.t(`${stationKey}.no_passes`);
        card.appendChild(cardBody);
    }
    col.appendChild(card);
    return col;
}

// ---- Passes table for one station ----
function _createPassesTableCard(passes, stationLabel, stationKey) {
    const card = document.createElement('div');
    card.className = 'card h-100';
    const tableHeader = document.createElement('div');
    tableHeader.className = 'card-header fw-bold';
    DOMUtils.append(tableHeader, DOMUtils.createIcon('bi bi-calendar-event text-danger icon-inline'), `${stationLabel} – ${i18n.t(`${stationKey}.upcoming_passages`)}`);
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
        { text: i18n.t('iss.table_end'), colSpan: 2, className: 'iss-group-head' },
    ].forEach(hc => {
        const th = document.createElement('th');
        th.textContent = hc.text;
        if (hc.rowSpan) th.rowSpan = hc.rowSpan;
        if (hc.colSpan) th.colSpan = hc.colSpan;
        if (hc.className) th.className = hc.className;
        headRowTop.appendChild(th);
    });
    const headRowBottom = document.createElement('tr');
    [i18n.t('iss.table_time'), i18n.t('iss.table_elev'), i18n.t('iss.table_time'), i18n.t('iss.table_elev'), i18n.t('iss.table_time'), i18n.t('iss.table_elev')].forEach(ht => {
        const th = document.createElement('th');
        th.className = 'text-center';
        th.textContent = ht;
        headRowBottom.appendChild(th);
    });
    thead.appendChild(headRowTop);
    thead.appendChild(headRowBottom);

    const tbody = document.createElement('tbody');
    if (Array.isArray(passes) && passes.length > 0) {
        passes.forEach(p => {
            const row = document.createElement('tr');
            const dateCell = document.createElement('td');
            dateCell.textContent = formatDateFull(p.peak_time);
            row.appendChild(dateCell);
            const visCell = document.createElement('td');
            visCell.appendChild(createOrbVisibilityGauge(computeOrbVisibilityScore(p)));
            row.appendChild(visCell);
            [
                formatTimeThenDateWithSeconds(p.start_time), formatAltAz(p.start_altitude_deg, p.start_azimuth_cardinal, p.start_azimuth_deg),
                formatTimeThenDateWithSeconds(p.peak_time),  formatAltAz(p.peak_altitude_deg,  p.peak_azimuth_cardinal,  p.peak_azimuth_deg),
                formatTimeThenDateWithSeconds(p.end_time),   formatAltAz(p.end_altitude_deg,   p.end_azimuth_cardinal,   p.end_azimuth_deg),
            ].forEach(v => {
                const td = document.createElement('td');
                td.className = 'text-center';
                td.textContent = v;
                row.appendChild(td);
            });
            tbody.appendChild(row);
        });
    } else {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'text-center text-muted';
        cell.textContent = i18n.t(`${stationKey}.not_found`);
        row.appendChild(cell);
        tbody.appendChild(row);
    }

    table.appendChild(thead);
    table.appendChild(tbody);
    tableResponsive.appendChild(table);
    card.appendChild(tableHeader);
    card.appendChild(tableResponsive);
    return card;
}

// ---- Main load function ----
async function loadOrbitalStations() {
    _stopOrbMapRefresh();
    _orbMap = null;
    _issMarker = null;
    _cssMarker = null;
    _userLocationMarker = null;
    _issPastLines = [];
    _issFutureLines = [];
    _cssPastLines = [];
    _cssFutureLines = [];
    const container = document.getElementById('orbital-stations-display');
    if (!container) return;

    DOMUtils.clear(container);

    const loadingEl = document.createElement('div');
    loadingEl.className = 'text-center text-muted py-3';
    loadingEl.appendChild(DOMUtils.createSpinnerWrapper(i18n.t('iss.loading_passes')));
    container.appendChild(loadingEl);

    const [issResp, cssResp] = await Promise.all([
        fetch('/api/iss/passes?days=20', { credentials: 'same-origin' }).catch(() => null),
        fetch('/api/css/passes?days=20', { credentials: 'same-origin' }).catch(() => null),
    ]);

    const issData = (issResp && issResp.ok) ? await issResp.json().catch(() => null) : null;
    const cssData = (cssResp && cssResp.ok) ? await cssResp.json().catch(() => null) : null;

    DOMUtils.clear(container);

    // Celestrak banners
    if (issData && issData.celestrak_status) _appendCelestrakBanner(container, issData.celestrak_status, 'iss');
    if (cssData && cssData.celestrak_status) _appendCelestrakBanner(container, cssData.celestrak_status, 'css');

    // Info alert
    const infoAlert = document.createElement('div');
    infoAlert.className = 'alert alert-info';
    infoAlert.setAttribute('role', 'alert');
    infoAlert.textContent = i18n.t('orbital_stations.info_tab', { days: 20 });
    container.appendChild(infoAlert);

    // Next visible passage – 2 cards side by side
    const passRow = document.createElement('div');
    passRow.className = 'row row-cols-1 row-cols-md-2 mb-3 g-3';
    passRow.appendChild(_createNextPassCard(issData?.next_visible_passage, 'iss', 'border-warning'));
    passRow.appendChild(_createNextPassCard(cssData?.next_visible_passage, 'css', 'border-danger'));
    container.appendChild(passRow);

    // Real-time dual map
    await _createOrbitalMapCard(container);

    // Altitude chart
    // Passes table with ISS/CSS toggle
    const tableRow = document.createElement('div');
    tableRow.className = 'row row-cols-1 mb-3';
    const tableCol = document.createElement('div');
    tableCol.className = 'col';

    // Toggle nav-pills (matches app-wide selector style)
    const toggleBar = document.createElement('ul');
    toggleBar.className = 'nav nav-pills mb-2';

    const _makeNavItem = (station, iconClass, colorClass, label) => {
        const li = document.createElement('li');
        li.className = 'nav-item';
        const a = document.createElement('a');
        a.className = 'nav-link' + (_activePassesStation === station ? ' active' : '');
        a.href = '#';
        DOMUtils.append(a, DOMUtils.createIcon(`bi ${iconClass} ${colorClass} icon-inline`), ` ${label}`);
        a.addEventListener('click', (e) => { e.preventDefault(); renderTable(station); });
        li.appendChild(a);
        return { li, a };
    };

    const { li: issLi, a: issLink } = _makeNavItem('iss', 'bi-iss', 'text-warning', 'ISS');
    const { li: cssLi, a: cssLink } = _makeNavItem('css', 'bi-iss', 'text-danger', 'CSS');

    const tableWrap = document.createElement('div');

    const renderTable = (station) => {
        _activePassesStation = station;
        issLink.className = 'nav-link' + (station === 'iss' ? ' active' : '');
        cssLink.className = 'nav-link' + (station === 'css' ? ' active' : '');
        DOMUtils.clear(tableWrap);
        const label = station === 'iss' ? 'ISS' : 'CSS';
        const passes = station === 'iss' ? issData?.passes : cssData?.passes;
        tableWrap.appendChild(_createPassesTableCard(passes, label, station));
    };

    toggleBar.appendChild(issLi);
    toggleBar.appendChild(cssLi);
    tableCol.appendChild(toggleBar);
    tableCol.appendChild(tableWrap);
    tableRow.appendChild(tableCol);
    container.appendChild(tableRow);
    renderTable(_activePassesStation);

    // TLE source footers
    const tleRow = document.createElement('div');
    tleRow.className = 'row row-cols-1 row-cols-md-2 g-2';
    for (const [data, station] of [[issData, 'ISS'], [cssData, 'CSS']]) {
        if (!data) continue;
        const src = data.tle_source || {};
        const name = (src.name || '').trim() || i18n.t('iss.footer_unknown_source');
        const url  = (src.url  || '').trim();
        const col = document.createElement('div');
        col.className = 'col';
        const footerEl = document.createElement('div');
        footerEl.className = 'text-muted small mt-1';
        const sentinel = '\x00SOURCE\x00';
        const translated = `${station}: ${i18n.t('iss.footer_source', { source: sentinel })}`;
        const parts = translated.split(sentinel);
        footerEl.appendChild(document.createTextNode(parts[0]));
        if (url) {
            const link = document.createElement('a');
            link.href = url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = name;
            footerEl.appendChild(link);
        } else {
            footerEl.appendChild(document.createTextNode(name));
        }
        if (parts[1]) footerEl.appendChild(document.createTextNode(parts[1]));
        col.appendChild(footerEl);
        tleRow.appendChild(col);
    }
    container.appendChild(tleRow);

    // Run notification checks
    if (issData) _checkIssN3(issData);
    if (cssData) _checkCssN8(cssData);
}

// ---- Notification checks ----
function _checkIssN3(data) {
    if (typeof notificationManager === 'undefined') return;
    if (!notificationManager.isTriggerEnabled('N3')) return;

    const leadMs = notificationManager.getLeadMinutes('N3') * 60 * 1000;
    const now = Date.now();
    const candidates = [];
    for (const t of (data.solar_transits || [])) {
        const ms = t.start_time ? new Date(t.start_time).getTime() : null;
        if (ms && ms > now) candidates.push({ ms, type: 'solar' });
    }
    for (const t of (data.lunar_transits || [])) {
        const ms = t.start_time ? new Date(t.start_time).getTime() : null;
        if (ms && ms > now) candidates.push({ ms, type: 'lunar' });
    }
    if (!candidates.length) return;
    candidates.sort((a, b) => a.ms - b.ms);
    const next = candidates[0];
    const msUntil = next.ms - now;
    if (msUntil > leadMs) return;
    if (notificationManager.wasRecentlyNotified('N3', 60 * 60 * 1000)) return;
    const minutes = Math.round(msUntil / 60000);
    const bodyKey = next.type === 'solar' ? 'notifications.n3_body_solar' : 'notifications.n3_body_lunar';
    notificationManager.notify('N3', i18n.t('notifications.n3_title'), i18n.t(bodyKey, { minutes }), { url: '#spaceflight/orbital-stations' });
}

function _checkCssN8(data) {
    if (typeof notificationManager === 'undefined') return;
    if (!notificationManager.isTriggerEnabled('N8')) return;

    const leadMs = notificationManager.getLeadMinutes('N8') * 60 * 1000;
    const now = Date.now();
    const candidates = [];
    for (const t of (data.solar_transits || [])) {
        const ms = t.start_time ? new Date(t.start_time).getTime() : null;
        if (ms && ms > now) candidates.push({ ms, type: 'solar' });
    }
    for (const t of (data.lunar_transits || [])) {
        const ms = t.start_time ? new Date(t.start_time).getTime() : null;
        if (ms && ms > now) candidates.push({ ms, type: 'lunar' });
    }
    if (!candidates.length) return;
    candidates.sort((a, b) => a.ms - b.ms);
    const next = candidates[0];
    const msUntil = next.ms - now;
    if (msUntil > leadMs) return;
    if (notificationManager.wasRecentlyNotified('N8', 60 * 60 * 1000)) return;
    const minutes = Math.round(msUntil / 60000);
    const bodyKey = next.type === 'solar' ? 'notifications.n8_body_solar' : 'notifications.n8_body_lunar';
    notificationManager.notify('N8', i18n.t('notifications.n8_title'), i18n.t(bodyKey, { minutes }), { url: '#spaceflight/orbital-stations' });
}
