// Configuration Management

let configsData = [];

// ======================
// Timezone Management
// ======================

async function loadTimezones() {
    try {
        const timezones = await fetchJSON('/api/timezones');

        //console.log(`Loaded ${timezones.length} timezones from API`);
        
        const select = document.getElementById('timezone');
        if (!select) return; // Element doesn't exist on this page view
        
        DOMUtils.clear(select);
        
        timezones.forEach(tz => {
            const option = document.createElement('option');
            option.value = tz.name;
            option.textContent = `${tz.name} (UTC${tz.offset})`;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading timezones:', error);
    }
}

// ======================
// Configuration Load/Save
// ======================

async function loadConfiguration() {
    try {
        const config = await fetchJSON('/api/config');
        currentConfig = config;
        
        // Populate basic fields - check if elements exist before setting values
        const locationName = document.getElementById('location-name');
        if (locationName) locationName.value = config.location?.name || '';
        
        const latInput = document.getElementById('latitude-input');
        if (latInput) latInput.value = config.location?.latitude || '';
        
        const lonInput = document.getElementById('longitude-input');
        if (lonInput) lonInput.value = config.location?.longitude || '';
        
        const elevation = document.getElementById('elevation');
        if (elevation) elevation.value = config.location?.elevation || 0;
        
        const timezone = document.getElementById('timezone');
        if (timezone) timezone.value = config.location?.timezone || 'UTC';

        // Sky quality (light pollution)
        const bortleSelect = document.getElementById('bortle-class');
        if (bortleSelect) bortleSelect.value = config.location?.bortle != null ? String(config.location.bortle) : '';

        const sqmInput = document.getElementById('sqm-value');
        if (sqmInput) sqmInput.value = config.location?.sqm != null ? config.location.sqm : '';

        // Astrodex options
        const astrodexPrivate = document.getElementById('astrodex-private');
        if (astrodexPrivate) astrodexPrivate.checked = config.astrodex?.private !== false;
        
        const constraints = config.skytonight?.constraints || {};
        
        const altMin = document.getElementById('altitude-min');
        if (altMin) altMin.value = constraints.altitude_constraint_min || 30;
        
        const altMax = document.getElementById('altitude-max');
        if (altMax) altMax.value = constraints.altitude_constraint_max || 80;
        
        const airmass = document.getElementById('airmass');
        if (airmass) airmass.value = constraints.airmass_constraint || 2;
        
        const sizeMin = document.getElementById('size-min');
        if (sizeMin) sizeMin.value = constraints.size_constraint_min || 10;
        
        const sizeMax = document.getElementById('size-max');
        if (sizeMax) sizeMax.value = constraints.size_constraint_max || 300;
        
        const moonSep = document.getElementById('moon-sep');
        if (moonSep) moonSep.value = constraints.moon_separation_min || 45;
        
        const timeThreshold = document.getElementById('time-threshold');
        if (timeThreshold) timeThreshold.value = constraints.fraction_of_time_observable_threshold || 0.5;
        
        const moonIllumination = document.getElementById('moon-illumination');
        if (moonIllumination) moonIllumination.checked = constraints.moon_separation_use_illumination !== false;
        
        const northCCW = document.getElementById('north-ccw');
        if (northCCW) northCCW.checked = constraints.north_to_east_ccw === true;

        // Horizon profile
        loadHorizonProfileTable(constraints.horizon_profile || []);
                
    } catch (error) {
        console.error('Error loading configuration:', error);
        showMessage('error', i18n.t('settings.failed_to_load_config'));
    }
}

async function saveConfiguration() {
    
    const config = {
        location: {
            name: document.getElementById('location-name').value,
            latitude: parseFloat(document.getElementById('latitude-input').value),
            longitude: parseFloat(document.getElementById('longitude-input').value),
            elevation: parseFloat(document.getElementById('elevation').value || 0),
            timezone: document.getElementById('timezone').value,
            bortle: (() => { const v = document.getElementById('bortle-class')?.value; return v ? parseInt(v, 10) : null; })(),
            sqm: (() => { const v = document.getElementById('sqm-value')?.value; return v !== '' && v != null ? parseFloat(v) : null; })(),
        },
        astrodex: {
            private: document.getElementById('astrodex-private').checked
        },
        skytonight: {
            constraints: {
                altitude_constraint_min: parseFloat(document.getElementById('altitude-min').value),
                altitude_constraint_max: parseFloat(document.getElementById('altitude-max').value),
                airmass_constraint: parseFloat(document.getElementById('airmass').value),
                size_constraint_min: parseFloat(document.getElementById('size-min').value),
                size_constraint_max: parseFloat(document.getElementById('size-max').value),
                moon_separation_min: parseFloat(document.getElementById('moon-sep').value),
                moon_separation_use_illumination: document.getElementById('moon-illumination').checked,
                fraction_of_time_observable_threshold: parseFloat(document.getElementById('time-threshold').value),
                north_to_east_ccw: document.getElementById('north-ccw').checked,
                horizon_profile: readHorizonProfile(),
                _horizon_cleared: _horizonExplicitlyCleared,
            }
        }
    };

    // Coherence check: validate horizon profile before saving
    const horizonCheck = validateHorizonProfile();
    if (!horizonCheck.valid) {
        showMessage('error', horizonCheck.errors.join(' '));
        return;
    }
    if (horizonCheck.warnings.length > 0) {
        showMessage('warning', horizonCheck.warnings.join(' '));
    }

    try {
        const result = await fetchJSON('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        if (result.status === 'success') {
            showMessage('success', i18n.t('settings.config_saved'));
            currentConfig = config;
        } else {
            showMessage('error', result.message || i18n.t('settings.failed_to_save_config'));
        }
    } catch (error) {
        console.error('Error saving configuration:', error);
        showMessage('error', i18n.t('settings.failed_to_save_config'));
    }
}

// ======================
// Horizon Profile Editor
// ======================

let _horizonExplicitlyCleared = false;

function _updateHorizonTableVisibility() {
    const wrapper = document.getElementById('horizon-profile-table-wrapper');
    const tbody   = document.getElementById('horizon-profile-tbody');
    if (!wrapper || !tbody) return;
    wrapper.style.display = tbody.children.length > 0 ? '' : 'none';
}

function loadHorizonProfileTable(profile) {
    const tbody = document.getElementById('horizon-profile-tbody');
    if (!tbody) return;
    DOMUtils.clear(tbody);
    _horizonExplicitlyCleared = false;
    (profile || []).forEach(pt => addHorizonRow(pt.az, pt.alt));
    _updateHorizonTableVisibility();
}

function addHorizonRow(az = '', alt = '') {
    const tbody = document.getElementById('horizon-profile-tbody');
    if (!tbody) return;
    const tr = document.createElement('tr');

    const tdAz = document.createElement('td');
    const inputAz = document.createElement('input');
    inputAz.type = 'number';
    inputAz.className = 'form-control form-control-sm horizon-az';
    inputAz.value = az;
    inputAz.min = '0';
    inputAz.max = '360';
    inputAz.step = '1';
    inputAz.setAttribute('inputmode', 'numeric');
    inputAz.placeholder = '0-360';
    tdAz.appendChild(inputAz);

    const tdAlt = document.createElement('td');
    const inputAlt = document.createElement('input');
    inputAlt.type = 'number';
    inputAlt.className = 'form-control form-control-sm horizon-alt';
    inputAlt.value = alt;
    inputAlt.min = '0';
    inputAlt.max = '90';
    inputAlt.step = '1';
    inputAlt.setAttribute('inputmode', 'numeric');
    inputAlt.placeholder = '0-90';
    tdAlt.appendChild(inputAlt);

    const tdDel = document.createElement('td');
    const btnDel = document.createElement('button');
    btnDel.type = 'button';
    btnDel.className = 'btn btn-sm btn-danger';
    btnDel.setAttribute('data-action', 'delete-horizon-row');
    btnDel.appendChild(DOMUtils.createIcon('bi bi-trash icon-inline'));
    tdDel.appendChild(btnDel);

    tr.appendChild(tdAz);
    tr.appendChild(tdAlt);
    tr.appendChild(tdDel);
    tbody.appendChild(tr);
    _updateHorizonTableVisibility();
}

function clearHorizonProfile() {
    const tbody = document.getElementById('horizon-profile-tbody');
    if (tbody) DOMUtils.clear(tbody);
    _horizonExplicitlyCleared = true;
    _updateHorizonTableVisibility();
}

function readHorizonProfile() {
    const rows = document.querySelectorAll('#horizon-profile-tbody tr');
    const profile = [];
    rows.forEach(row => {
        const az = parseFloat(row.querySelector('.horizon-az')?.value);
        const alt = parseFloat(row.querySelector('.horizon-alt')?.value);
        if (!isNaN(az) && !isNaN(alt) && az >= 0 && az <= 360 && alt >= 0 && alt <= 90) {
            profile.push({ az, alt });
        }
    });
    return profile;
}

/**
 * Validate horizon profile rows before saving.
 * Returns { errors: string[], warnings: string[], valid: boolean }
 * - errors:   blocking issues (must be fixed before saving)
 * - warnings: non-blocking notices (row skipped, too few points)
 */
function validateHorizonProfile() {
    const rows = document.querySelectorAll('#horizon-profile-tbody tr');
    let invalidCount = 0;
    const validPoints = [];

    rows.forEach(row => {
        const azRaw  = row.querySelector('.horizon-az')?.value  ?? '';
        const altRaw = row.querySelector('.horizon-alt')?.value ?? '';
        // Completely empty rows are ignored silently
        if (azRaw === '' && altRaw === '') return;
        const az  = parseFloat(azRaw);
        const alt = parseFloat(altRaw);
        if (isNaN(az) || isNaN(alt) || az < 0 || az > 360 || alt < 0 || alt > 90) {
            invalidCount++;
        } else {
            validPoints.push({ az, alt });
        }
    });

    const errors   = [];
    const warnings = [];

    if (invalidCount > 0) {
        warnings.push(i18n.t('settings.horizon_profile_warn_invalid_rows', { count: invalidCount }));
    }

    // Detect duplicate azimuth values (0° and 360° are allowed to coexist as loop-close convention)
    const azCounts = {};
    validPoints.forEach(p => { azCounts[p.az] = (azCounts[p.az] || 0) + 1; });
    const dupAz = Object.entries(azCounts)
        .filter(([, n]) => n > 1)
        .map(([az]) => parseFloat(az))
        .sort((a, b) => a - b);
    if (dupAz.length > 0) {
        errors.push(i18n.t('settings.horizon_profile_err_duplicate_az', { list: dupAz.join(', ') }));
    }

    if (validPoints.length === 1) {
        warnings.push(i18n.t('settings.horizon_profile_warn_too_few'));
    }

    return { errors, warnings, valid: errors.length === 0 };
}

// ======================
// Coordinate Conversion
// ======================

async function convertCoordinate(type) {

    const inputId = `${type}-input`;
    const convertedId = `${type}-converted`;
    const errorId = `${type}-error`;
    
    const input = document.getElementById(inputId);
    const value = input.value.trim();
    
    const convertedEl = document.getElementById(convertedId);
    const errorEl = document.getElementById(errorId);
    
    // Clear previous messages
    convertedEl.textContent = '';
    errorEl.textContent = '';
    
    if (!value) return;
    
    // Check if it's already decimal
    if (!isNaN(value)) {
        convertedEl.textContent = `${i18n.t('settings.decimal')}${parseFloat(value).toFixed(6)}`;
        input.classList.add('is-valid');
        input.classList.remove('is-invalid');
        return;
    }
    
    // Try to convert DMS
    try {
        const data = await fetchJSON('/api/convert-coordinates', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dms: value })
        });
        
        if (data.status === 'success') {
            convertedEl.textContent = `${i18n.t('settings.decimal')}${data.decimal}`;
            input.value = data.decimal;
            input.classList.add('is-valid');
            input.classList.remove('is-invalid');
        } else {
            errorEl.textContent = data.message;
            input.classList.add('is-invalid');
            input.classList.remove('is-valid');
        }
    } catch (error) {
        errorEl.textContent = i18n.t('settings.invalid_format');
        input.classList.add('is-invalid');
        input.classList.remove('is-valid');
    }
}

// ======================
// Configuration View/Export
// ======================

//Export general configuration
async function exportConfiguration() {
    try {
        window.location.href = `${API_BASE}/api/config/export`;
        showMessage('success', 'Configuration exported');
    } catch (error) {
        console.error('Error exporting configuration:', error);
        showMessage('error', i18n.t('settings.failed_export_config'));
    }
}

// ======================
// Backup / Restore
// ======================

function downloadBackup() {
    window.location.href = `${API_BASE}/api/backup/download`;
    showMessage('success', i18n.t('settings.backup_started'));
}

async function restoreBackup() {
    const fileInput = document.getElementById('restore-file-input');
    const msgEl = document.getElementById('backup-restore-message');

    if (!fileInput || !fileInput.files.length) {
        _showInlineMessage(msgEl, 'warning', i18n.t('settings.restore_no_file'));
        return;
    }

    const confirmed = window.confirm(i18n.t('settings.restore_confirm'));
    if (!confirmed) return;

    const btn = document.getElementById('backup-restore-btn');
    if (btn) btn.disabled = true;

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const resp = await fetch(`${API_BASE}/api/backup/restore`, {
            method: 'POST',
            body: formData
        });
        const data = await resp.json();

        if (resp.ok && data.status === 'success') {
            _showInlineMessage(msgEl, 'success', (data.message || i18n.t('settings.restore_success')) + ' ' + i18n.t('settings.restore_reloading'));
            setTimeout(() => window.location.reload(), 2000);
        } else {
            _showInlineMessage(msgEl, 'danger', data.error || i18n.t('settings.restore_failed'));
            if (btn) btn.disabled = false;
        }
    } catch (error) {
        console.error('Error restoring backup:', error);
        _showInlineMessage(msgEl, 'danger', i18n.t('settings.restore_failed'));
        if (btn) btn.disabled = false;
    }
}

function _showInlineMessage(el, type, text) {
    if (!el) return;
    el.className = `alert alert-${type}`;
    el.textContent = text;
    el.style.display = '';
}

// ======================
// Log Export
// ======================

function downloadLogExport() {
    window.location.href = `${API_BASE}/api/logs/export`;
    showMessage('success', i18n.t('settings.log_export_started'));
}

async function loadLogLevel() {
    const badge = document.getElementById('log-export-current-level');
    if (!badge) return;
    try {
        const data = await fetchJSON('/api/logs/level');
        const level = data.level || '-';
        badge.textContent = level;
        // Color the badge per level
        const colorMap = {
            DEBUG:    'bg-secondary',
            INFO:     'bg-info text-dark',
            WARNING:  'bg-warning text-dark',
            ERROR:    'bg-danger',
            CRITICAL: 'bg-danger'
        };
        badge.className = `badge fs-6 ${colorMap[level] || 'bg-secondary'}`;
    } catch (err) {
        console.error('Could not load log level:', err);
        badge.textContent = '-';
    }
}

// Enable/disable the restore button based on file selection
function initRestoreFileInput() {
    const fileInput = document.getElementById('restore-file-input');
    const btn = document.getElementById('backup-restore-btn');
    if (!fileInput || !btn) return;
    fileInput.addEventListener('change', () => {
        btn.disabled = !fileInput.files.length;
    });
}
