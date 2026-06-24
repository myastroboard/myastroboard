// First-run onboarding wizard
// Shows a location setup modal when location_configured === false in config

let _firstRunModal = null;

async function checkFirstRun() {
    if (!currentConfig || currentConfig.location_configured || sessionStorage.getItem('first_run_skipped')) {
        return;
    }

    const modalEl = document.getElementById('first-run-modal');
    if (!modalEl) return;

    // Copy timezone options from the already-loaded main select
    _syncFirstRunTimezones();

    _firstRunModal = new bootstrap.Modal(modalEl, { backdrop: 'static', keyboard: false });
    _firstRunModal.show();
}

function _syncFirstRunTimezones() {
    const source = document.getElementById('timezone');
    const target = document.getElementById('setup-timezone');
    if (!source || !target) return;
    DOMUtils.clear(target);
    for (const opt of Array.from(source.options)) {
        target.appendChild(opt.cloneNode(true));
    }
    target.value = currentConfig?.location?.timezone || 'UTC';
}

async function _saveFirstRunLocation() {
    const nameVal    = document.getElementById('setup-location-name')?.value.trim();
    const latVal     = document.getElementById('setup-latitude-input')?.value;
    const lonVal     = document.getElementById('setup-longitude-input')?.value;
    const elevVal    = document.getElementById('setup-elevation')?.value;
    const timezoneVal = document.getElementById('setup-timezone')?.value;

    const lat = parseFloat(latVal);
    const lon = parseFloat(lonVal);
    const elev = elevVal !== '' && elevVal != null ? parseFloat(elevVal) : 0;

    const latErrEl = document.getElementById('setup-lat-error');
    const lonErrEl = document.getElementById('setup-lon-error');

    // Reset validation state
    document.getElementById('setup-latitude-input')?.classList.remove('is-invalid');
    document.getElementById('setup-longitude-input')?.classList.remove('is-invalid');
    if (latErrEl) latErrEl.textContent = '';
    if (lonErrEl) lonErrEl.textContent = '';

    let valid = true;

    if (isNaN(lat) || lat < -90 || lat > 90) {
        document.getElementById('setup-latitude-input')?.classList.add('is-invalid');
        if (latErrEl) latErrEl.textContent = i18n.t('first_run.lat_invalid');
        valid = false;
    }
    if (isNaN(lon) || lon < -180 || lon > 180) {
        document.getElementById('setup-longitude-input')?.classList.add('is-invalid');
        if (lonErrEl) lonErrEl.textContent = i18n.t('first_run.lon_invalid');
        valid = false;
    }
    if (!valid) return;

    const saveBtn = document.getElementById('setup-save-btn');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.classList.add('loading'); }

    try {
        const payload = {
            ...currentConfig,
            location: {
                ...currentConfig?.location,
                name: nameVal || i18n.t('first_run.default_location_name'),
                latitude: lat,
                longitude: lon,
                elevation: isNaN(elev) ? 0 : elev,
                timezone: timezoneVal || 'UTC',
            },
            location_configured: true,
        };

        const result = await fetchJSON('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (result.status === 'success') {
            currentConfig = result.config || payload;
            // Sync the main settings form with the new values
            if (typeof loadConfiguration === 'function') loadConfiguration();
            _firstRunModal?.hide();
        } else {
            showMessage('error', result.message || i18n.t('settings.failed_to_save_config'));
        }
    } catch (err) {
        console.error('First-run save error:', err);
        showMessage('error', i18n.t('settings.failed_to_save_config'));
    } finally {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.classList.remove('loading'); }
    }
}

function _initFirstRunGeolocate() {
    const btn = document.getElementById('setup-geolocate-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
        if (!navigator.geolocation) {
            showMessage('warning', i18n.t('settings.geolocation_unsupported'));
            return;
        }
        btn.disabled = true;
        navigator.geolocation.getCurrentPosition(async (pos) => {
            btn.disabled = false;
            const lat = pos.coords.latitude.toFixed(6);
            const lon = pos.coords.longitude.toFixed(6);

            let locationName = null;
            try {
                const resp = await fetch(
                    `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
                    { headers: { 'Accept-Language': i18n.currentLocale || 'en' } }
                );
                const geo = await resp.json();
                locationName = geo.address?.city || geo.address?.town || geo.address?.village || geo.address?.county || null;
            } catch (_) { /* reverse geocoding is optional */ }

            document.getElementById('setup-latitude-input').value = lat;
            document.getElementById('setup-longitude-input').value = lon;
            const nameInput = document.getElementById('setup-location-name');
            if (nameInput && !nameInput.value && locationName) nameInput.value = locationName;

            // Try to detect timezone from coordinates via browser API or just leave as-is
        }, () => {
            btn.disabled = false;
            showMessage('warning', i18n.t('settings.geolocation_error'));
        });
    });
}

function initFirstRun() {
    _initFirstRunGeolocate();
    document.getElementById('setup-save-btn')?.addEventListener('click', _saveFirstRunLocation);
    document.getElementById('setup-skip-btn')?.addEventListener('click', (e) => {
        e.preventDefault();
        sessionStorage.setItem('first_run_skipped', '1');
        _firstRunModal?.hide();
    });
}
