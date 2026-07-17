// Multi-location profiles (v1.2)
// - Admin management UI (Parameters -> Locations): card grid + edit modal + attribution
// - Per-user location preferences (My Settings -> Location): default + order
// - Quick switcher data layer used by the sky status widget

let _locationsAdminCache = [];
let _locationsMaxCount = 5;
let _locationEditingId = null; // null = creating a new preset
let _myLocationsCache = null; // /api/locations/mine payload (switcher + my-settings)

// Leaflet minimaps on the admin location cards - keyed by location id so a
// re-render can tear the old map instances down before the DOM nodes go away.
let _locationCardMaps = {};
let _locationCardMapsGeneration = 0;
const _locationsLeafletLoadState = { promise: null };

function _ensureLocationsLeafletLoaded() {
    return ensureVendorScriptLoaded(
        () => typeof L !== 'undefined',
        '/static/vendor/leaflet/dist/leaflet.min.js?v=1.9.4',
        '/static/vendor/leaflet/dist/leaflet.min.css?v=1.9.4',
        _locationsLeafletLoadState,
        'Leaflet'
    );
}

// ======================
// Shared helpers
// ======================

async function fetchMyLocations(force = false) {
    if (_myLocationsCache && !force) return _myLocationsCache;
    try {
        _myLocationsCache = await fetchJSON('/api/locations/mine');
    } catch (error) {
        console.error('Error loading my locations:', error);
        _myLocationsCache = { locations: [], active_location_id: null, default_location_id: null };
    }
    return _myLocationsCache;
}

function invalidateMyLocationsCache() {
    _myLocationsCache = null;
}

async function setActiveLocation(locationId) {
    const result = await fetchJSON('/api/locations/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ location_id: locationId })
    });
    invalidateMyLocationsCache();
    return result;
}

// ======================
// Admin management UI (Parameters -> Locations)
// ======================

async function loadLocationsAdmin() {
    const grid = document.getElementById('locations-grid');
    if (!grid) return;
    try {
        const data = await fetchJSON('/api/locations');
        _locationsAdminCache = data.locations || [];
        _locationsMaxCount = data.max_locations || 5;
        renderLocationsGrid();
    } catch (error) {
        console.error('Error loading locations:', error);
        showMessage('error', i18n.t('settings.locations_load_failed'));
    }
}

function renderLocationsGrid() {
    const grid = document.getElementById('locations-grid');
    if (!grid) return;

    // Tear down any previous card maps before their containers are discarded -
    // Leaflet keeps window/document listeners alive otherwise.
    Object.values(_locationCardMaps).forEach(map => { try { map.remove(); } catch (_) { /* already gone */ } });
    _locationCardMaps = {};

    DOMUtils.clear(grid);

    const badge = document.getElementById('locations-count-badge');
    if (badge) badge.textContent = `${_locationsAdminCache.length} / ${_locationsMaxCount}`;

    const newBtn = document.getElementById('btn-new-location');
    if (newBtn) {
        const maxReached = _locationsAdminCache.length >= _locationsMaxCount;
        newBtn.disabled = maxReached;
        newBtn.title = maxReached ? i18n.t('settings.location_max_reached', { max: _locationsMaxCount }) : '';
    }

    _locationsAdminCache.forEach(loc => grid.appendChild(_buildLocationCard(loc)));
    _initLocationCardMaps();
}

async function _initLocationCardMaps() {
    // Bumped on every render so a slow-to-load Leaflet from a PREVIOUS render
    // (e.g. two rapid saves before the script first finishes loading) can tell
    // it's obsolete and bail out instead of racing the current one for the
    // same map containers.
    const generation = ++_locationCardMapsGeneration;

    const withCoords = _locationsAdminCache.filter(loc => (
        Number.isFinite(Number(loc.latitude)) && Number.isFinite(Number(loc.longitude))
    ));
    if (withCoords.length === 0) return;

    try {
        await _ensureLocationsLeafletLoaded();
    } catch (error) {
        console.warn('Leaflet failed to load; location cards fall back to text-only coordinates', error);
        return;
    }
    if (generation !== _locationCardMapsGeneration) return;

    withCoords.forEach(loc => {
        const container = document.getElementById(`location-map-${loc.id}`);
        // The grid may have been re-rendered again (fast repeated saves) while
        // Leaflet was loading - skip stale containers no longer in the DOM.
        if (!container || !document.body.contains(container)) return;

        const lat = Number(loc.latitude);
        const lon = Number(loc.longitude);
        const map = L.map(container, {
            scrollWheelZoom: false, // a card grid must not trap page scroll
            zoomControl: false,
            keyboard: false, // container is aria-hidden (decorative); Leaflet's
            // keyboard handler would otherwise add tabindex="0" and make a
            // hidden element focusable
        }).setView([lat, lon], 9);

        // CartoDB Voyager, not the orbital stations map's dark_all basemap:
        // dark_all only renders roads/labels over solid black, so remote
        // sites (volcano summits, rural areas) with little infrastructure
        // show up as a near-blank black card. Voyager fills in land/water/
        // terrain colour so every card stays legible regardless of location.
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            maxZoom: 18,
            attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>',
        }).addTo(map);
        L.marker([lat, lon]).addTo(map);

        _locationCardMaps[loc.id] = map;
    });
}

function _buildLocationCard(loc) {
    const col = document.createElement('div');
    col.className = 'col';

    const card = document.createElement('div');
    card.className = 'card h-100';

    const header = document.createElement('div');
    header.className = 'card-header d-flex align-items-center justify-content-between';
    const title = document.createElement('h5');
    title.className = 'mb-0 text-truncate';
    title.textContent = loc.name || '?';
    header.appendChild(title);
    if (loc.is_install_default) {
        const ribbon = document.createElement('span');
        ribbon.className = 'badge bg-primary ms-2 flex-shrink-0';
        ribbon.textContent = i18n.t('settings.location_default_badge');
        header.appendChild(ribbon);
    }

    const body = document.createElement('div');
    body.className = 'card-body';

    const mapEl = document.createElement('div');
    mapEl.className = 'location-card-map mb-2 rounded';
    mapEl.id = `location-map-${loc.id}`;
    mapEl.setAttribute('aria-hidden', 'true'); // decorative preview - coordinates below are the accessible source
    body.appendChild(mapEl);

    const coords = document.createElement('p');
    coords.className = 'mb-1 small text-muted font-monospace';
    const lat = Number(loc.latitude);
    const lon = Number(loc.longitude);
    coords.textContent = `${isNaN(lat) ? '?' : lat.toFixed(4)}, ${isNaN(lon) ? '?' : lon.toFixed(4)} · ${loc.elevation ?? 0} m`;
    body.appendChild(coords);

    const tz = document.createElement('p');
    tz.className = 'mb-1 small text-muted';
    tz.textContent = formatTimezoneWithOffset(loc.timezone);
    body.appendChild(tz);

    if (loc.bortle != null || loc.sqm != null) {
        const sky = document.createElement('p');
        sky.className = 'mb-1 small';
        const skyBadge = document.createElement('span');
        skyBadge.className = 'badge bg-info text-dark';
        const parts = [];
        if (loc.bortle != null) parts.push(`Bortle ${loc.bortle}`);
        if (loc.sqm != null) parts.push(`SQM ${loc.sqm}`);
        skyBadge.textContent = parts.join(' · ');
        sky.appendChild(skyBadge);
        body.appendChild(sky);
    }

    if (Array.isArray(loc.horizon_profile) && loc.horizon_profile.length > 0) {
        const horizon = document.createElement('p');
        horizon.className = 'mb-1 small text-muted';
        horizon.textContent = i18n.t('settings.location_horizon_points', { count: loc.horizon_profile.length });
        body.appendChild(horizon);
    }

    // Compact counts instead of naming every user - "Attributed to: admin,
    // john, jane, ..." becomes unusable past a handful of users (e.g. an
    // astro club with 100+ members, where new locations attribute to
    // everyone by default and only a few get manually excluded).
    const attribution = document.createElement('p');
    attribution.className = 'mb-0 small d-flex align-items-center flex-wrap gap-1';
    const attributedCount = (loc.attributed_to || []).length;
    const totalUsers = Number.isFinite(loc.total_users) ? loc.total_users : attributedCount;
    const excludedCount = Math.max(0, totalUsers - attributedCount);

    const attributedBadge = document.createElement('span');
    attributedBadge.className = 'badge bg-success-subtle text-success-emphasis';
    attributedBadge.textContent = i18n.t('settings.location_attributed_badge', { count: attributedCount });
    attribution.appendChild(attributedBadge);

    if (excludedCount > 0) {
        const excludedBadge = document.createElement('span');
        excludedBadge.className = 'badge bg-secondary-subtle text-secondary-emphasis';
        excludedBadge.textContent = i18n.t('settings.location_excluded_badge', { count: excludedCount });
        attribution.appendChild(excludedBadge);
    }
    body.appendChild(attribution);

    const footer = document.createElement('div');
    footer.className = 'card-footer d-flex gap-2';

    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'btn btn-sm btn-outline-primary';
    editBtn.appendChild(DOMUtils.createIcon('bi bi-pencil icon-inline'));
    const editLabel = document.createElement('span');
    editLabel.textContent = i18n.t('settings.location_edit_btn');
    editBtn.appendChild(editLabel);
    editBtn.addEventListener('click', () => openLocationModal(loc.id));
    footer.appendChild(editBtn);

    if (!loc.is_install_default) {
        const defaultBtn = document.createElement('button');
        defaultBtn.type = 'button';
        defaultBtn.className = 'btn btn-sm btn-outline-secondary';
        defaultBtn.appendChild(DOMUtils.createIcon('bi bi-star icon-inline'));
        const defLabel = document.createElement('span');
        defLabel.textContent = i18n.t('settings.location_set_default');
        defaultBtn.appendChild(defLabel);
        defaultBtn.addEventListener('click', () => promoteInstallDefault(loc.id));
        footer.appendChild(defaultBtn);

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'btn btn-sm btn-outline-danger ms-auto';
        deleteBtn.appendChild(DOMUtils.createIcon('bi bi-trash icon-inline'));
        deleteBtn.addEventListener('click', () => deleteLocationWithConfirm(loc));
        footer.appendChild(deleteBtn);
    } else {
        const lockedBtn = document.createElement('button');
        lockedBtn.type = 'button';
        lockedBtn.className = 'btn btn-sm btn-outline-danger ms-auto';
        lockedBtn.disabled = true;
        lockedBtn.title = i18n.t('settings.location_cannot_delete_default');
        lockedBtn.appendChild(DOMUtils.createIcon('bi bi-trash icon-inline'));
        footer.appendChild(lockedBtn);
    }

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);
    col.appendChild(card);
    return col;
}

async function promoteInstallDefault(locationId) {
    try {
        const result = await fetchJSON(`/api/locations/${encodeURIComponent(locationId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_install_default: true })
        });
        if (result.status === 'success') {
            showMessage('success', i18n.t('settings.location_default_changed'));
            await loadLocationsAdmin();
        }
    } catch (error) {
        console.error('Error promoting install default:', error);
        showMessage('error', i18n.t('settings.location_save_failed'));
    }
}

async function deleteLocationWithConfirm(loc) {
    try {
        const refs = await fetchJSON(`/api/locations/${encodeURIComponent(loc.id)}/references`);
        const plansCount = refs.plan_my_night_plans || 0;

        const confirmText = document.getElementById('location-delete-confirm-text');
        const refsText = document.getElementById('location-delete-refs-text');
        const plansChoice = document.getElementById('location-delete-plans-choice');
        const orphanBtn = document.getElementById('location-delete-orphan-btn');
        const cascadeBtn = document.getElementById('location-delete-cascade-btn');
        const plainBtn = document.getElementById('location-delete-plain-btn');
        const modalEl = document.getElementById('location-delete-modal');
        if (!confirmText || !refsText || !modalEl) return;

        confirmText.textContent = i18n.t('settings.location_delete_confirm', { name: loc.name });
        refsText.textContent = i18n.t('settings.location_delete_refs', {
            users: (refs.attributed_users || []).length,
            astrodex: refs.astrodex_items || 0,
            plans: plansCount,
        });

        // Cascade-vs-orphan is only a real choice when plans actually reference
        // this location; with zero, either delete mode behaves identically.
        const hasPlans = plansCount > 0;
        if (plansChoice) plansChoice.style.display = hasPlans ? '' : 'none';
        if (orphanBtn) orphanBtn.style.display = hasPlans ? '' : 'none';
        if (cascadeBtn) cascadeBtn.style.display = hasPlans ? '' : 'none';
        if (plainBtn) plainBtn.style.display = hasPlans ? 'none' : '';

        const runDelete = async (plansMode) => {
            try {
                const result = await fetchJSON(
                    `/api/locations/${encodeURIComponent(loc.id)}?plans=${plansMode}`,
                    { method: 'DELETE' }
                );
                if (result.status === 'success') {
                    showMessage('success', i18n.t('settings.location_deleted'));
                    invalidateMyLocationsCache();
                    await loadLocationsAdmin();
                    if (typeof SkyWidget !== 'undefined') SkyWidget.refresh();
                }
            } catch (error) {
                console.error('Error deleting location:', error);
                showMessage('error', i18n.t('settings.location_delete_failed'));
            } finally {
                bootstrap.Modal.getInstance(modalEl)?.hide();
            }
        };

        // Plain property assignment (not addEventListener) so re-opening this
        // modal for a different location rebinds instead of stacking handlers.
        if (orphanBtn) orphanBtn.onclick = () => runDelete('orphan');
        if (cascadeBtn) cascadeBtn.onclick = () => runDelete('cascade');
        if (plainBtn) plainBtn.onclick = () => runDelete('cascade'); // no plans referenced - mode is moot

        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } catch (error) {
        console.error('Error loading location references:', error);
        showMessage('error', i18n.t('settings.location_delete_failed'));
    }
}

async function openLocationModal(locationId = null) {
    _locationEditingId = locationId;
    const loc = locationId ? _locationsAdminCache.find(l => l.id === locationId) : null;

    const title = document.getElementById('location-edit-modal-title');
    if (title) {
        title.textContent = loc
            ? i18n.t('settings.location_edit_title_named', { name: loc.name })
            : i18n.t('settings.location_new');
    }

    const setValue = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    };
    setValue('location-name', loc?.name || '');
    setValue('latitude-input', loc?.latitude ?? '');
    setValue('longitude-input', loc?.longitude ?? '');
    setValue('elevation', loc?.elevation ?? 0);
    setValue('timezone', loc?.timezone || 'UTC');
    setValue('bortle-class', loc?.bortle != null ? String(loc.bortle) : '');
    setValue('sqm-value', loc?.sqm != null ? loc.sqm : '');

    // Horizon profile editor (shared helpers from config.js, ids live in this modal)
    if (typeof loadHorizonProfileTable === 'function') {
        loadHorizonProfileTable(loc?.horizon_profile || []);
    }

    await _renderAttributionList(loc);

    const modalEl = document.getElementById('location-edit-modal');
    if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

async function _renderAttributionList(loc) {
    const container = document.getElementById('location-attribution-list');
    if (!container) return;
    DOMUtils.clear(container);

    let users = [];
    try {
        const data = await fetchJSON('/api/users');
        users = data.users || data || [];
    } catch (error) {
        console.error('Error loading users for attribution:', error);
    }

    const attributedIds = new Set((loc?.attributed_to || []).map(u => u.user_id));

    users.forEach(user => {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check';

        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'form-check-input location-attribution-check';
        input.id = `loc-attr-${user.user_id}`;
        input.value = user.user_id;
        input.checked = attributedIds.has(user.user_id);

        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.setAttribute('for', input.id);
        label.textContent = `${user.username} (${user.role})`;

        wrapper.appendChild(input);
        wrapper.appendChild(label);
        container.appendChild(wrapper);
    });
}

async function saveLocationFromModal() {
    const getValue = (id) => document.getElementById(id)?.value;

    const payload = {
        name: getValue('location-name'),
        latitude: parseFloat(getValue('latitude-input')),
        longitude: parseFloat(getValue('longitude-input')),
        elevation: parseFloat(getValue('elevation') || 0),
        timezone: getValue('timezone'),
        bortle: (() => { const v = getValue('bortle-class'); return v ? parseInt(v, 10) : null; })(),
        sqm: (() => { const v = getValue('sqm-value'); return v !== '' && v != null ? parseFloat(v) : null; })(),
        horizon_profile: typeof readHorizonProfile === 'function' ? readHorizonProfile() : [],
    };

    if (typeof validateHorizonProfile === 'function') {
        const horizonCheck = validateHorizonProfile();
        if (!horizonCheck.valid) {
            showMessage('error', horizonCheck.errors.join(' '));
            return;
        }
        if (horizonCheck.warnings.length > 0) {
            showMessage('warning', horizonCheck.warnings.join(' '));
        }
    }

    try {
        let result;
        if (_locationEditingId) {
            result = await fetchJSON(`/api/locations/${encodeURIComponent(_locationEditingId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            result = await fetchJSON('/api/locations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        if (result.status !== 'success') {
            showMessage('error', result.error || i18n.t('settings.location_save_failed'));
            return;
        }

        // Attribution (checkbox list) - applies to the saved/created preset
        const savedId = result.location?.id || _locationEditingId;
        if (savedId) {
            const userIds = Array.from(document.querySelectorAll('.location-attribution-check'))
                .filter(cb => cb.checked)
                .map(cb => cb.value);
            await fetchJSON(`/api/locations/${encodeURIComponent(savedId)}/attribute`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_ids: userIds })
            });
        }

        showMessage('success', i18n.t('settings.location_saved'));
        const modalEl = document.getElementById('location-edit-modal');
        if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        invalidateMyLocationsCache();
        await loadLocationsAdmin();
        if (typeof SkyWidget !== 'undefined') SkyWidget.refresh();
    } catch (error) {
        console.error('Error saving location:', error);
        showMessage('error', error?.message || i18n.t('settings.location_save_failed'));
    }
}

// ======================
// My Settings -> Location (per-user default + order)
// ======================

let _myLocationOrder = [];

async function loadMyLocationSettings() {
    const select = document.getElementById('pref-default-location');
    const orderList = document.getElementById('my-location-order-list');
    if (!select || !orderList) return;

    const data = await fetchMyLocations(true);
    const locations = data.locations || [];

    DOMUtils.clear(select);
    locations.forEach(loc => {
        const option = document.createElement('option');
        option.value = loc.id;
        option.textContent = loc.name || '?';
        select.appendChild(option);
    });
    if (data.default_location_id) select.value = data.default_location_id;

    _myLocationOrder = locations.map(loc => loc.id);
    _renderMyLocationOrderList(locations);
}

function _renderMyLocationOrderList(locations) {
    const orderList = document.getElementById('my-location-order-list');
    if (!orderList) return;
    DOMUtils.clear(orderList);

    const byId = {};
    locations.forEach(loc => { byId[loc.id] = loc; });

    _myLocationOrder.forEach((locId, index) => {
        const loc = byId[locId];
        if (!loc) return;

        const li = document.createElement('li');
        li.className = 'list-group-item d-flex align-items-center gap-2';

        const name = document.createElement('span');
        name.className = 'flex-grow-1 text-truncate';
        name.textContent = loc.name || '?';
        li.appendChild(name);

        const upBtn = document.createElement('button');
        upBtn.type = 'button';
        upBtn.className = 'btn btn-sm btn-outline-secondary';
        upBtn.disabled = index === 0;
        upBtn.setAttribute('aria-label', 'Move up');
        upBtn.appendChild(DOMUtils.createIcon('bi bi-arrow-up'));
        upBtn.addEventListener('click', () => {
            [_myLocationOrder[index - 1], _myLocationOrder[index]] = [_myLocationOrder[index], _myLocationOrder[index - 1]];
            _renderMyLocationOrderList(locations);
        });
        li.appendChild(upBtn);

        const downBtn = document.createElement('button');
        downBtn.type = 'button';
        downBtn.className = 'btn btn-sm btn-outline-secondary';
        downBtn.disabled = index === _myLocationOrder.length - 1;
        downBtn.setAttribute('aria-label', 'Move down');
        downBtn.appendChild(DOMUtils.createIcon('bi bi-arrow-down'));
        downBtn.addEventListener('click', () => {
            [_myLocationOrder[index], _myLocationOrder[index + 1]] = [_myLocationOrder[index + 1], _myLocationOrder[index]];
            _renderMyLocationOrderList(locations);
        });
        li.appendChild(downBtn);

        orderList.appendChild(li);
    });
}

async function saveMyLocationPreferences() {
    const select = document.getElementById('pref-default-location');
    const msgEl = document.getElementById('my-location-message');
    if (!select) return;

    try {
        const currentPrefs = await fetchJSON('/api/auth/preferences');
        const prefs = currentPrefs.preferences || currentPrefs || {};
        const locationBlock = Object.assign(
            { attributed_location_ids: [], default_location_id: null, active_location_id: null, order: [] },
            prefs.location || {}
        );
        locationBlock.default_location_id = select.value || null;
        locationBlock.order = _myLocationOrder.slice();

        const result = await fetchJSON('/api/auth/preferences', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preferences: { location: locationBlock } })
        });

        if (result.status === 'success' || result.preferences) {
            if (msgEl) {
                msgEl.className = 'alert alert-success';
                msgEl.textContent = i18n.t('settings.my_location_saved');
                msgEl.style.display = '';
                setTimeout(() => { msgEl.style.display = 'none'; }, 4000);
            }
            invalidateMyLocationsCache();
            if (typeof SkyWidget !== 'undefined') SkyWidget.refresh();
        }
    } catch (error) {
        console.error('Error saving location preferences:', error);
        if (msgEl) {
            msgEl.className = 'alert alert-danger';
            msgEl.textContent = i18n.t('settings.my_location_save_failed');
            msgEl.style.display = '';
        }
    }
}

// ======================
// Wiring
// ======================

function initLocationsUI() {
    document.getElementById('btn-new-location')?.addEventListener('click', () => openLocationModal(null));
    document.getElementById('location-modal-save-btn')?.addEventListener('click', saveLocationFromModal);
    document.getElementById('save-my-location-btn')?.addEventListener('click', saveMyLocationPreferences);
}

window.loadLocationsAdmin = loadLocationsAdmin;
window.loadMyLocationSettings = loadMyLocationSettings;
window.fetchMyLocations = fetchMyLocations;
window.setActiveLocation = setActiveLocation;
window.invalidateMyLocationsCache = invalidateMyLocationsCache;
window.initLocationsUI = initLocationsUI;
