// Guided Setup Wizard
// Multi-step onboarding wizard shown once per user, controlled by the
// `wizard: {completed, skipped}` user preference (not `location_configured`).
// Two flows:
//   'full' (Context A - admin + fresh install): location, sky_quality, equipment, notifications, tonight
//   'user' (Context B - everyone else, excluding read-only): welcome, equipment, notifications, tonight

const WIZARD_STEPS_FULL = ['location', 'sky_quality', 'equipment', 'notifications', 'tonight'];
const WIZARD_STEPS_USER = ['welcome', 'equipment', 'notifications', 'tonight'];

const _wizard = {
    modal: null,
    flow: null,
    steps: [],
    stepIndex: 0,
    saving: false,
    presets: { telescopes: [], cameras: [] },
    existingTelescopes: [],
    existingCameras: [],
    existingMounts: [],
    existingCombinations: [],
};

/**
 * Determine which wizard flow to show. Only branches on admin-vs-not, per the
 * spec's own pseudocode - the read-only exclusion is enforced separately in
 * checkFirstRun() as a trigger-level guard, not here.
 */
function _getWizardFlow(config, user) {
    const locationSet = config?.location_configured === true;
    const isAdmin = user?.role === 'admin';
    if (!locationSet && isAdmin) return 'full';
    return 'user';
}

async function checkFirstRun() {
    if (!currentConfig || !currentUser) return;
    if (currentUser.role === 'read-only') return; // read-only users never see the wizard

    const wizardState = currentUserPreferences?.wizard || { completed: false, skipped: false };
    if (wizardState.completed || wizardState.skipped) return;

    const modalEl = document.getElementById('wizard-modal');
    if (!modalEl) return;

    _wizard.flow = _getWizardFlow(currentConfig, currentUser);
    _wizard.steps = _wizard.flow === 'full' ? WIZARD_STEPS_FULL : WIZARD_STEPS_USER;
    _wizard.stepIndex = 0;

    await _wizardLoadEquipmentData();

    const wizardLangSelect = document.getElementById('wizard-language-select');
    if (wizardLangSelect) wizardLangSelect.value = i18n.getCurrentLanguage();

    _wizard.modal = new bootstrap.Modal(modalEl, { backdrop: 'static', keyboard: false });
    _renderWizardStep();
    _wizard.modal.show();
}

function initFirstRun() {
    document.getElementById('wizard-back-btn')?.addEventListener('click', _wizardBack);
    document.getElementById('wizard-next-btn')?.addEventListener('click', _wizardNext);
    document.getElementById('wizard-skip-btn')?.addEventListener('click', (e) => {
        e.preventDefault();
        _wizardSkip(false);
    });
    document.getElementById('wizard-skip-all-btn')?.addEventListener('click', (e) => {
        e.preventDefault();
        _wizardSkip(true);
    });

    // The footer language selector sits behind the wizard's static backdrop and can't be
    // clicked while the modal is open. Unlike the footer selector (which reloads the page),
    // switch in place here so in-progress wizard step/state isn't lost - mirrors the
    // no-reload language-apply logic loadUserPreferences() uses on initial page load.
    document.getElementById('wizard-language-select')?.addEventListener('change', async (e) => {
        const selectedLang = e.target.value;
        if (typeof i18n === 'undefined' || selectedLang === i18n.getCurrentLanguage()) return;
        localStorage.setItem('myastroboard_language', selectedLang);
        await i18n.setLanguage(selectedLang);
        if (window.languageSelector) {
            window.languageSelector.setCurrentLanguage();
            window.languageSelector.updatePageTranslations();
        }
        fetch('/api/auth/preferences', {
            method: 'PUT',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preferences: { language: selectedLang } }),
        }).catch(() => {});
    });

    // The wizard's step content is built once via direct i18n.t() calls (not
    // data-i18n attributes), so it does not auto-refresh like the rest of the
    // page when the language finishes switching after the modal is already
    // open (e.g. server-preference language load completing after render).
    window.addEventListener('i18nLanguageChanged', () => {
        if (document.getElementById('wizard-modal')?.classList.contains('show')) {
            _renderWizardStep();
        }
        const wizardLangSelect = document.getElementById('wizard-language-select');
        if (wizardLangSelect) wizardLangSelect.value = i18n.getCurrentLanguage();
    });
}

/** Reset the wizard preference and re-trigger it - used by the "Redo Wizard" button in My Settings. */
async function restartWizard() {
    await _wizardPersist({ completed: false, skipped: false });
    await checkFirstRun();
}
window.restartWizard = restartWizard;

// ── Step navigation ─────────────────────────────────────────────────────────

function _renderWizardStep() {
    _wizardUpdateProgressBar();
    _wizardUpdateFooterButtons();
    const container = document.getElementById('wizard-step-content');
    if (!container) return;
    DOMUtils.clear(container);
    const stepKey = _wizard.steps[_wizard.stepIndex];
    const buildFn = _WIZARD_STEP_BUILDERS[stepKey];
    if (buildFn) buildFn(container);
}

function _wizardUpdateProgressBar() {
    const total = _wizard.steps.length;
    const current = _wizard.stepIndex + 1;
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    const bar = document.getElementById('wizard-progress-bar');
    if (bar) bar.style.width = `${pct}%`;
    const label = document.getElementById('wizard-progress-label');
    if (label) label.textContent = i18n.t('wizard.step_progress', { current, total });
}

function _wizardUpdateFooterButtons() {
    const backBtn = document.getElementById('wizard-back-btn');
    const nextLabel = document.getElementById('wizard-next-btn-label');
    if (backBtn) backBtn.style.display = _wizard.stepIndex === 0 ? 'none' : '';
    if (nextLabel) {
        const isLast = _wizard.stepIndex === _wizard.steps.length - 1;
        nextLabel.textContent = isLast ? i18n.t('wizard.finish') : i18n.t('wizard.next');
    }
}

async function _wizardNext() {
    if (_wizard.saving) return; // guard against double-clicks re-submitting the current step
    _wizard.saving = true;
    const nextBtn = document.getElementById('wizard-next-btn');
    if (nextBtn) nextBtn.disabled = true;
    try {
        const stepKey = _wizard.steps[_wizard.stepIndex];
        const saveFn = _WIZARD_STEP_SAVE[stepKey];
        if (saveFn) {
            const ok = await saveFn();
            if (!ok) return; // validation failed - stay on this step
        }
        if (_wizard.stepIndex >= _wizard.steps.length - 1) {
            await _wizardFinish();
            return;
        }
        _wizard.stepIndex += 1;
        _renderWizardStep();
    } finally {
        _wizard.saving = false;
        if (nextBtn) nextBtn.disabled = false;
    }
}

function _wizardBack() {
    if (_wizard.stepIndex <= 0) return;
    _wizard.stepIndex -= 1;
    _renderWizardStep();
}

async function _wizardFinish() {
    await _wizardPersist({ completed: true, skipped: false });
    _wizard.modal?.hide();
    if (typeof SkyWidget !== 'undefined') SkyWidget.refresh();
}

/**
 * Skip handler for both the per-step Skip link (advances without saving the
 * current step) and the global Skip All link (exits the wizard entirely).
 * Both display the required "configuration will be done manually" alert.
 */
async function _wizardSkip(all) {
    if (all && !window.confirm(i18n.t('wizard.confirm_skip_all'))) {
        return;
    }

    showMessage('info', i18n.t('wizard.skip_alert'));

    if (all) {
        await _wizardPersist({ completed: false, skipped: true });
        _wizard.modal?.hide();
        return;
    }

    _wizard.stepIndex += 1;
    if (_wizard.stepIndex >= _wizard.steps.length) {
        await _wizardPersist({ completed: false, skipped: true });
        _wizard.modal?.hide();
        return;
    }
    _renderWizardStep();
}

/** Persist the wizard preference. Always sends the full 2-key object - the
 * backend does a shallow merge, so a partial object would drop the other key. */
async function _wizardPersist(wizardState) {
    try {
        setCurrentUserPreferences(await saveUserPreferences({ wizard: wizardState }));
        window.myastroboardUserPreferences = { ...currentUserPreferences };
    } catch (err) {
        console.error('Error saving wizard state:', err);
    }
}

// ── Step: location (Context A only) ─────────────────────────────────────────

function _buildLocationStep(container) {
    const intro = document.createElement('p');
    intro.className = 'text-muted mb-3';
    intro.textContent = i18n.t('first_run.intro');
    container.appendChild(intro);

    const row = document.createElement('div');
    row.className = 'row g-3';

    const nameCol = document.createElement('div');
    nameCol.className = 'col-12';
    const nameLabel = document.createElement('label');
    nameLabel.className = 'form-label';
    nameLabel.htmlFor = 'setup-location-name';
    nameLabel.textContent = i18n.t('settings.location_name');
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.id = 'setup-location-name';
    nameInput.className = 'form-control';
    nameInput.placeholder = i18n.t('settings.location_name_placeholder');
    nameCol.appendChild(nameLabel);
    nameCol.appendChild(nameInput);
    row.appendChild(nameCol);

    const latCol = document.createElement('div');
    latCol.className = 'col-md-6';
    const latLabel = document.createElement('label');
    latLabel.className = 'form-label';
    latLabel.htmlFor = 'setup-latitude-input';
    latLabel.textContent = i18n.t('first_run.latitude');
    const latGroup = document.createElement('div');
    latGroup.className = 'input-group';
    const latInput = document.createElement('input');
    latInput.type = 'number';
    latInput.id = 'setup-latitude-input';
    latInput.className = 'form-control';
    latInput.step = '0.000001';
    latInput.min = '-90';
    latInput.max = '90';
    latInput.inputMode = 'decimal';
    latInput.placeholder = i18n.t('first_run.latitude_placeholder');
    const geoBtn = document.createElement('button');
    geoBtn.type = 'button';
    geoBtn.className = 'btn btn-secondary';
    geoBtn.id = 'setup-geolocate-btn';
    geoBtn.title = i18n.t('settings.geolocation_btn_title');
    geoBtn.appendChild(DOMUtils.createIcon('bi bi-pin-map'));
    latGroup.appendChild(latInput);
    latGroup.appendChild(geoBtn);
    const latErr = document.createElement('div');
    latErr.id = 'setup-lat-error';
    latErr.className = 'invalid-feedback';
    latCol.appendChild(latLabel);
    latCol.appendChild(latGroup);
    latCol.appendChild(latErr);
    row.appendChild(latCol);

    const lonCol = document.createElement('div');
    lonCol.className = 'col-md-6';
    const lonLabel = document.createElement('label');
    lonLabel.className = 'form-label';
    lonLabel.htmlFor = 'setup-longitude-input';
    lonLabel.textContent = i18n.t('first_run.longitude');
    const lonInput = document.createElement('input');
    lonInput.type = 'number';
    lonInput.id = 'setup-longitude-input';
    lonInput.className = 'form-control';
    lonInput.step = '0.000001';
    lonInput.min = '-180';
    lonInput.max = '180';
    lonInput.inputMode = 'decimal';
    lonInput.placeholder = i18n.t('first_run.longitude_placeholder');
    const lonErr = document.createElement('div');
    lonErr.id = 'setup-lon-error';
    lonErr.className = 'invalid-feedback';
    lonCol.appendChild(lonLabel);
    lonCol.appendChild(lonInput);
    lonCol.appendChild(lonErr);
    row.appendChild(lonCol);

    const tzCol = document.createElement('div');
    tzCol.className = 'col-md-6';
    const tzLabel = document.createElement('label');
    tzLabel.className = 'form-label';
    tzLabel.htmlFor = 'setup-timezone';
    tzLabel.textContent = i18n.t('settings.timezone');
    const tzSelect = document.createElement('select');
    tzSelect.id = 'setup-timezone';
    tzSelect.className = 'form-select';
    tzCol.appendChild(tzLabel);
    tzCol.appendChild(tzSelect);
    row.appendChild(tzCol);

    const elevCol = document.createElement('div');
    elevCol.className = 'col-md-6';
    const elevLabel = document.createElement('label');
    elevLabel.className = 'form-label';
    elevLabel.htmlFor = 'setup-elevation';
    elevLabel.textContent = i18n.t('first_run.elevation_optional');
    const elevInput = document.createElement('input');
    elevInput.type = 'number';
    elevInput.id = 'setup-elevation';
    elevInput.className = 'form-control';
    elevInput.step = '1';
    elevInput.min = '0';
    elevInput.inputMode = 'numeric';
    elevInput.placeholder = i18n.t('settings.elevation_placeholder');
    elevCol.appendChild(elevLabel);
    elevCol.appendChild(elevInput);
    row.appendChild(elevCol);

    container.appendChild(row);

    const hint = document.createElement('div');
    hint.className = 'mt-3 form-text';
    hint.textContent = i18n.t('first_run.hint');
    container.appendChild(hint);

    _syncFirstRunTimezones();
    _initFirstRunGeolocate();
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
        }, () => {
            btn.disabled = false;
            showMessage('warning', i18n.t('settings.geolocation_error'));
        });
    });
}

async function _saveLocationStep() {
    const nameVal = document.getElementById('setup-location-name')?.value.trim();
    const latVal = document.getElementById('setup-latitude-input')?.value;
    const lonVal = document.getElementById('setup-longitude-input')?.value;
    const elevVal = document.getElementById('setup-elevation')?.value;
    const timezoneVal = document.getElementById('setup-timezone')?.value;

    const lat = parseFloat(latVal);
    const lon = parseFloat(lonVal);
    const elev = elevVal !== '' && elevVal != null ? parseFloat(elevVal) : 0;

    const latErrEl = document.getElementById('setup-lat-error');
    const lonErrEl = document.getElementById('setup-lon-error');
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
    if (!valid) return false;

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
            if (typeof loadConfiguration === 'function') loadConfiguration();
            // The persistent sky widget only re-fetches every 5 minutes on its own timer,
            // so it would otherwise keep showing the pre-wizard default location.
            if (typeof SkyWidget !== 'undefined') SkyWidget.refresh();
            return true;
        }
        showMessage('error', result.message || i18n.t('settings.failed_to_save_config'));
        return false;
    } catch (err) {
        console.error('Wizard location save error:', err);
        showMessage('error', i18n.t('settings.failed_to_save_config'));
        return false;
    }
}

// ── Step: sky quality (Context A only) ──────────────────────────────────────

function _buildSkyQualityStep(container) {
    const intro = document.createElement('p');
    intro.className = 'text-muted mb-3';
    intro.textContent = i18n.t('wizard.bortle_intro');
    container.appendChild(intro);

    const row = document.createElement('div');
    row.className = 'row g-3';

    const bortleCol = document.createElement('div');
    bortleCol.className = 'col-md-6';
    const bortleLabel = document.createElement('label');
    bortleLabel.className = 'form-label';
    bortleLabel.htmlFor = 'wizard-bortle-select';
    bortleLabel.textContent = i18n.t('settings.sky_quality_bortle');
    const bortleSelect = document.createElement('select');
    bortleSelect.id = 'wizard-bortle-select';
    bortleSelect.className = 'form-select';
    const noneOpt = document.createElement('option');
    noneOpt.value = '';
    noneOpt.textContent = i18n.t('settings.sky_quality_bortle_disabled');
    bortleSelect.appendChild(noneOpt);
    for (let i = 1; i <= 9; i++) {
        const opt = document.createElement('option');
        opt.value = String(i);
        opt.textContent = i18n.t(`settings.sky_quality_bortle_${i}`);
        bortleSelect.appendChild(opt);
    }
    bortleSelect.value = currentConfig?.location?.bortle != null ? String(currentConfig.location.bortle) : '';
    bortleCol.appendChild(bortleLabel);
    bortleCol.appendChild(bortleSelect);
    row.appendChild(bortleCol);

    const sqmCol = document.createElement('div');
    sqmCol.className = 'col-md-6';
    const sqmLabel = document.createElement('label');
    sqmLabel.className = 'form-label';
    sqmLabel.htmlFor = 'wizard-sqm-input';
    sqmLabel.textContent = i18n.t('settings.sky_quality_sqm');
    const sqmInput = document.createElement('input');
    sqmInput.type = 'number';
    sqmInput.id = 'wizard-sqm-input';
    sqmInput.className = 'form-control';
    sqmInput.step = '0.1';
    sqmInput.placeholder = i18n.t('settings.sky_quality_sqm_placeholder');
    if (currentConfig?.location?.sqm != null) sqmInput.value = currentConfig.location.sqm;
    sqmCol.appendChild(sqmLabel);
    sqmCol.appendChild(sqmInput);
    row.appendChild(sqmCol);

    container.appendChild(row);

    // External link only - never embedded, per spec.
    const link = document.createElement('a');
    link.href = 'https://www.lightpollutionmap.info/';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.className = 'd-inline-block mt-3';
    link.textContent = i18n.t('wizard.bortle_link_label');
    container.appendChild(link);
}

async function _saveSkyQualityStep() {
    const bortleVal = document.getElementById('wizard-bortle-select')?.value;
    const sqmVal = document.getElementById('wizard-sqm-input')?.value;
    try {
        const payload = {
            ...currentConfig,
            location: {
                ...currentConfig?.location,
                bortle: bortleVal ? parseInt(bortleVal, 10) : null,
                sqm: sqmVal ? parseFloat(sqmVal) : null,
            },
        };
        const result = await fetchJSON('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (result.status === 'success') {
            currentConfig = result.config || payload;
            return true;
        }
        showMessage('error', result.message || i18n.t('settings.failed_to_save_config'));
        return false;
    } catch (err) {
        console.error('Wizard sky quality save error:', err);
        showMessage('error', i18n.t('settings.failed_to_save_config'));
        return false;
    }
}

// ── Step: welcome (Context B only, read-only) ───────────────────────────────

function _buildWelcomeStep(container) {
    const intro = document.createElement('p');
    intro.className = 'mb-3';
    intro.textContent = i18n.t('wizard.welcome_location_intro');
    container.appendChild(intro);

    const list = document.createElement('dl');
    list.className = 'row mb-0';

    const addRow = (labelKey, value) => {
        const dt = document.createElement('dt');
        dt.className = 'col-sm-4';
        dt.textContent = i18n.t(labelKey);
        const dd = document.createElement('dd');
        dd.className = 'col-sm-8';
        dd.textContent = value;
        list.appendChild(dt);
        list.appendChild(dd);
    };

    addRow('settings.location_name', currentConfig?.location?.name || '-');
    const bortle = currentConfig?.location?.bortle;
    addRow(
        'settings.sky_quality_bortle',
        bortle != null ? i18n.t(`settings.sky_quality_bortle_${bortle}`) : i18n.t('settings.sky_quality_bortle_disabled')
    );

    container.appendChild(list);
}

// ── Step: equipment (all contexts) ──────────────────────────────────────────

const _WIZARD_TELESCOPE_TYPE_MAP = {
    refractor: 'Refractor',
    apo: 'Apochromatic Refractor (APO)',
    reflector: 'Reflector',
    sct: 'Schmidt-Cassegrain (SCT)',
    edgehd: 'EdgeHD',
    rasa: 'Rowe Ackerman Schmidt Astrograph (RASA)',
    rc: 'Ritchey-Chrétien (RC)',
    newtonian: 'Newtonian',
    maksutov: 'Maksutov-Cassegrain',
    cassegrain: 'Cassegrain',
    dobsonian: 'Dobsonian',
};
// Preset payloads may include more specific color-camera types (e.g. DSLR/mirrorless),
// but the manual wizard camera form intentionally normalizes to canonical sensor options:
// CMOS Color, CMOS Mono, CCD Color, CCD Mono.
const _WIZARD_CAMERA_SENSOR_TYPE_MAP = {
    cmos_color: 'CMOS Color',
    dslr_color: 'CMOS Color',
    mirrorless_color: 'CMOS Color',
    cmos_mono: 'CMOS Mono',
    ccd_color: 'CCD Color',
    ccd_mono: 'CCD Mono',
};

async function _wizardLoadEquipmentData() {
    try {
        const resp = await fetch('/static/data/equipment_presets.json', { credentials: 'same-origin' });
        _wizard.presets = resp.ok ? await resp.json() : { telescopes: [], cameras: [] };
    } catch (_) {
        _wizard.presets = { telescopes: [], cameras: [] };
    }
    try {
        const telResp = await fetchJSON('/api/equipment/telescopes');
        _wizard.existingTelescopes = [...(telResp.data || []), ...(telResp.shared_from_others || [])];
    } catch (_) {
        _wizard.existingTelescopes = [];
    }
    try {
        const camResp = await fetchJSON('/api/equipment/cameras');
        _wizard.existingCameras = [...(camResp.data || []), ...(camResp.shared_from_others || [])];
    } catch (_) {
        _wizard.existingCameras = [];
    }
    try {
        const mountResp = await fetchJSON('/api/equipment/mounts');
        _wizard.existingMounts = [...(mountResp.data || []), ...(mountResp.shared_from_others || [])];
    } catch (_) {
        _wizard.existingMounts = [];
    }
    try {
        const comboResp = await fetchJSON('/api/equipment/combinations');
        _wizard.existingCombinations = [...(comboResp.data || []), ...(comboResp.shared_from_others || [])];
    } catch (_) {
        _wizard.existingCombinations = [];
    }
}

/** Find an equipment item's display name by id in one of the wizard's already-loaded lists. */
function _wizardFindEquipmentName(list, id) {
    if (!id) return '';
    const found = (list || []).find((item) => item.id === id);
    return found ? found.name : '';
}

/** Build the "existing combinations" summary list - shown instead of a raw equipment list
 * since the combination is now the key unit (feature.md). Shows each combination's name plus
 * a telescope/camera/mount detail line resolved from the wizard's already-loaded equipment lists. */
function _buildExistingCombinationsList(container) {
    const title = document.createElement('h6');
    title.textContent = i18n.t('wizard.equipment_existing_title');
    container.appendChild(title);

    const wrap = document.createElement('div');
    wrap.className = 'mb-3';
    const combos = _wizard.existingCombinations || [];
    if (combos.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'text-muted small';
        empty.textContent = i18n.t('wizard.equipment_existing_empty');
        wrap.appendChild(empty);
    } else {
        const ul = document.createElement('ul');
        ul.className = 'list-unstyled small text-muted mb-0';
        combos.forEach((combo) => {
            const li = document.createElement('li');
            li.className = 'mb-2';

            const nameLine = document.createElement('div');
            nameLine.className = 'd-flex align-items-center flex-wrap gap-1';
            nameLine.appendChild(document.createTextNode(`• ${combo.name}`));
            if (combo.owner_username) {
                const sharedBadge = document.createElement('span');
                sharedBadge.className = 'badge bg-info text-dark';
                sharedBadge.textContent = i18n.t('equipment.shared_fov_suffix', { username: combo.owner_username });
                nameLine.appendChild(sharedBadge);
            }
            li.appendChild(nameLine);

            const detailParts = [
                _wizardFindEquipmentName(_wizard.existingTelescopes, combo.telescope_id),
                _wizardFindEquipmentName(_wizard.existingCameras, combo.camera_id),
                _wizardFindEquipmentName(_wizard.existingMounts, combo.mount_id),
            ].filter(Boolean);
            if (detailParts.length > 0) {
                const detail = document.createElement('div');
                detail.className = 'ps-3';
                detail.textContent = detailParts.join(' + ');
                li.appendChild(detail);
            }
            ul.appendChild(li);
        });
        wrap.appendChild(ul);
    }
    container.appendChild(wrap);
}

function _buildEquipmentStep(container) {
    _buildExistingCombinationsList(container);

    const telescopeBlock = _buildEquipmentPickerBlock('telescope', i18n.t('wizard.equipment_telescope_label'), _wizard.presets?.telescopes || []);
    container.appendChild(telescopeBlock);

    // Shown instead of the camera picker when the selected telescope preset already bundles
    // its own camera (smart telescopes like Seestar/Dwarf/Vespera) - picking a second camera
    // there would be meaningless since the combination can only have one imaging camera.
    const bundledNote = document.createElement('p');
    bundledNote.id = 'wizard-camera-bundled-note';
    bundledNote.className = 'text-muted small mt-2 mb-0';
    bundledNote.style.display = 'none';
    bundledNote.textContent = i18n.t('wizard.equipment_camera_bundled_note');
    container.appendChild(bundledNote);

    const cameraBlock = _buildEquipmentPickerBlock('camera', i18n.t('wizard.equipment_camera_label'), _wizard.presets?.cameras || []);
    container.appendChild(cameraBlock);

    const telescopeSelect = document.getElementById('wizard-telescope-preset');
    const _updateCameraBlockVisibility = () => {
        const preset = (_wizard.presets?.telescopes || []).find((p) => p.id === telescopeSelect?.value);
        const isBundling = !!(preset?.bundle && preset.bundle.length > 0);
        cameraBlock.style.display = isBundling ? 'none' : '';
        bundledNote.style.display = isBundling ? '' : 'none';
    };
    telescopeSelect?.addEventListener('change', _updateCameraBlockVisibility);
    _updateCameraBlockVisibility();

    const expWrap = document.createElement('div');
    expWrap.className = 'mt-3';
    const expLabel = document.createElement('label');
    expLabel.className = 'form-label';
    expLabel.htmlFor = 'wizard-experience-level';
    expLabel.textContent = i18n.t('wizard.experience_level_label');
    const expSelect = document.createElement('select');
    expSelect.id = 'wizard-experience-level';
    expSelect.className = 'form-select';
    [
        ['beginner', 'settings.experience_level_beginner'],
        ['intermediate', 'settings.experience_level_intermediate'],
        ['advanced', 'settings.experience_level_advanced'],
    ].forEach(([value, key]) => {
        const opt = document.createElement('option');
        opt.value = value;
        opt.textContent = i18n.t(key);
        expSelect.appendChild(opt);
    });
    expSelect.value = currentUserPreferences?.experience_level || 'advanced';
    expWrap.appendChild(expLabel);
    expWrap.appendChild(expSelect);
    container.appendChild(expWrap);
}

function _buildEquipmentPickerBlock(kind, labelText, presets) {
    const wrap = document.createElement('div');
    wrap.className = 'mt-3';

    const label = document.createElement('label');
    label.className = 'form-label';
    label.htmlFor = `wizard-${kind}-preset`;
    label.textContent = `${labelText} - ${i18n.t('wizard.equipment_preset_label')}`;
    wrap.appendChild(label);

    const select = document.createElement('select');
    select.id = `wizard-${kind}-preset`;
    select.className = 'form-select';
    const noneOpt = document.createElement('option');
    noneOpt.value = '';
    noneOpt.textContent = i18n.t('wizard.equipment_preset_placeholder');
    select.appendChild(noneOpt);

    // Presets tagged for the user's current experience level are surfaced first and
    // labelled, so e.g. a beginner sees beginner-friendly gear at the top of the list.
    const currentLevel = currentUserPreferences?.experience_level || 'advanced';
    const orderedPresets = [...presets].sort((a, b) => {
        const aMatch = a.suggests_experience === currentLevel ? 0 : 1;
        const bMatch = b.suggests_experience === currentLevel ? 0 : 1;
        if (aMatch !== bMatch) return aMatch - bMatch;
        return (a.manufacturer || '').localeCompare(b.manufacturer || '') || a.label.localeCompare(b.label);
    });
    orderedPresets.forEach((preset) => {
        const opt = document.createElement('option');
        opt.value = preset.id;
        const alreadyPrefixed = preset.manufacturer
            && preset.label.toLowerCase().startsWith(preset.manufacturer.toLowerCase());
        let text = preset.manufacturer && !alreadyPrefixed
            ? `${preset.manufacturer} ${preset.label}`
            : preset.label;
        if (preset.suggests_experience === currentLevel) {
            const levelLabel = i18n.t(`settings.experience_level_${preset.suggests_experience}`);
            text += ` (${levelLabel})`;
        }
        opt.textContent = text;
        select.appendChild(opt);
    });
    const manualOpt = document.createElement('option');
    manualOpt.value = '__manual__';
    manualOpt.textContent = i18n.t('wizard.equipment_manual');
    select.appendChild(manualOpt);
    wrap.appendChild(select);

    const manualWrap = document.createElement('div');
    manualWrap.id = `wizard-${kind}-manual`;
    manualWrap.className = 'row g-2 mt-2';
    manualWrap.style.display = 'none';
    wrap.appendChild(manualWrap);

    select.addEventListener('change', () => {
        DOMUtils.clear(manualWrap);
        if (select.value === '__manual__') {
            manualWrap.style.display = '';
            _buildManualEquipmentFields(kind, manualWrap);
        } else {
            manualWrap.style.display = 'none';
        }
    });

    return wrap;
}

function _buildManualEquipmentFields(kind, container) {
    const nameCol = document.createElement('div');
    nameCol.className = 'col-12';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.id = `wizard-${kind}-manual-name`;
    nameInput.className = 'form-control form-control-sm';
    nameInput.placeholder = i18n.t(`equipment.${kind}_name`) || 'Name';
    nameCol.appendChild(nameInput);
    container.appendChild(nameCol);

    const addNumberField = (id, placeholder, colClass = 'col-6') => {
        const col = document.createElement('div');
        col.className = colClass;
        const input = document.createElement('input');
        input.type = 'number';
        input.id = id;
        input.className = 'form-control form-control-sm';
        input.placeholder = placeholder;
        col.appendChild(input);
        container.appendChild(col);
    };

    if (kind === 'telescope') {
        const typeCol = document.createElement('div');
        typeCol.className = 'col-12';
        const typeSelect = document.createElement('select');
        typeSelect.id = 'wizard-telescope-manual-type';
        typeSelect.className = 'form-select form-select-sm';
        [
            ['Refractor', 'equipment.form_refractor'],
            ['Newtonian', 'equipment.form_newtonian'],
            ['Schmidt-Cassegrain (SCT)', 'equipment.form_sct'],
            ['Maksutov-Cassegrain', 'equipment.form_maksutov'],
            ['Dobsonian', 'equipment.form_dobsonian'],
        ].forEach(([value, key]) => {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = i18n.t(key, value);
            typeSelect.appendChild(opt);
        });
        typeCol.appendChild(typeSelect);
        container.appendChild(typeCol);

        addNumberField('wizard-telescope-manual-aperture', i18n.t('equipment.form_aperture', 'Aperture (mm)'));
        addNumberField('wizard-telescope-manual-focal', i18n.t('equipment.form_focal_length', 'Focal length (mm)'));
    } else {
        const sensorTypeCol = document.createElement('div');
        sensorTypeCol.className = 'col-12';
        const sensorTypeSelect = document.createElement('select');
        sensorTypeSelect.id = 'wizard-camera-manual-sensor-type';
        sensorTypeSelect.className = 'form-select form-select-sm';
        [
            ['CMOS Color', 'equipment.form_cmos_color'],
            ['CMOS Mono', 'equipment.form_cmos_mono'],
            ['CCD Color', 'equipment.form_ccd_color'],
            ['CCD Mono', 'equipment.form_ccd_mono'],
        ].forEach(([value, key]) => {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = i18n.t(key, value);
            sensorTypeSelect.appendChild(opt);
        });
        sensorTypeCol.appendChild(sensorTypeSelect);
        container.appendChild(sensorTypeCol);

        addNumberField('wizard-camera-manual-width', i18n.t('equipment.form_sensor_width', 'Sensor width (mm)'));
        addNumberField('wizard-camera-manual-height', i18n.t('equipment.form_sensor_height', 'Sensor height (mm)'));
        addNumberField('wizard-camera-manual-res-w', i18n.t('equipment.form_resolution_width', 'Resolution width (px)'));
        addNumberField('wizard-camera-manual-res-h', i18n.t('equipment.form_resolution_height', 'Resolution height (px)'));
        addNumberField('wizard-camera-manual-pixel', i18n.t('equipment.form_pixel_size', 'Pixel size (µm)'));
    }
}

function _mapTelescopePresetToPayload(preset) {
    return {
        name: preset.label,
        manufacturer: preset.manufacturer || '',
        telescope_type: _WIZARD_TELESCOPE_TYPE_MAP[preset.type] || 'Refractor',
        aperture_mm: preset.aperture_mm,
        focal_length_mm: preset.focal_length_mm,
        weight_kg: preset.weight_kg || 0,
    };
}

function _mapCameraPresetToPayload(preset) {
    return {
        name: preset.label,
        manufacturer: preset.manufacturer || '',
        sensor_width_mm: preset.sensor_width_mm,
        sensor_height_mm: preset.sensor_height_mm,
        resolution_width_px: preset.resolution_w,
        resolution_height_px: preset.resolution_h,
        pixel_size_um: preset.pixel_size_um,
        sensor_type: _WIZARD_CAMERA_SENSOR_TYPE_MAP[preset.type] || 'CMOS Color',
        weight_kg: preset.weight_kg || 0,
        cooling_supported: preset.cooling_supported || false,
        min_temperature_c: preset.min_temperature_c ?? null,
    };
}

// Per-kind config driving _saveEquipmentOfKind() - keeps the telescope/camera save
// flow as a single code path instead of two near-identical copies.
const _WIZARD_EQUIPMENT_KIND_CONFIG = {
    telescope: {
        endpoint: '/api/equipment/telescopes',
        selectId: 'wizard-telescope-preset',
        presetsKey: 'telescopes',
        mapPreset: _mapTelescopePresetToPayload,
        buildManualPayload: (name) => ({
            name,
            telescope_type: document.getElementById('wizard-telescope-manual-type')?.value || 'Refractor',
            aperture_mm: parseFloat(document.getElementById('wizard-telescope-manual-aperture')?.value) || 0,
            focal_length_mm: parseFloat(document.getElementById('wizard-telescope-manual-focal')?.value) || 0,
        }),
    },
    camera: {
        endpoint: '/api/equipment/cameras',
        selectId: 'wizard-camera-preset',
        presetsKey: 'cameras',
        mapPreset: _mapCameraPresetToPayload,
        buildManualPayload: (name) => ({
            name,
            manufacturer: '',
            sensor_type: document.getElementById('wizard-camera-manual-sensor-type')?.value || 'CMOS Color',
            sensor_width_mm: parseFloat(document.getElementById('wizard-camera-manual-width')?.value) || 0,
            sensor_height_mm: parseFloat(document.getElementById('wizard-camera-manual-height')?.value) || 0,
            resolution_width_px: parseInt(document.getElementById('wizard-camera-manual-res-w')?.value, 10) || 0,
            resolution_height_px: parseInt(document.getElementById('wizard-camera-manual-res-h')?.value, 10) || 0,
            pixel_size_um: parseFloat(document.getElementById('wizard-camera-manual-pixel')?.value) || 0,
        }),
    },
};

/** Create one piece of equipment for `kind` from whatever the wizard's picker is currently set
 * to (a preset or manual entry). Returns the created item's id, or null if nothing was created
 * (picker left on "none"). */
async function _saveEquipmentOfKind(kind) {
    const config = _WIZARD_EQUIPMENT_KIND_CONFIG[kind];
    const select = document.getElementById(config.selectId);

    if (select?.value === '__manual__') {
        const name = document.getElementById(`wizard-${kind}-manual-name`)?.value.trim();
        if (name) {
            const result = await fetchJSON(config.endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config.buildManualPayload(name)),
            });
            return result?.data?.id || null;
        }
    } else if (select?.value) {
        const preset = (_wizard.presets?.[config.presetsKey] || []).find((p) => p.id === select.value);
        if (preset) {
            const result = await fetchJSON(config.endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config.mapPreset(preset)),
            });
            return result?.data?.id || null;
        }
    }
    return null;
}

const _WIZARD_BUNDLE_ENDPOINT_BY_KIND = {
    camera: '/api/equipment/cameras',
    mount: '/api/equipment/mounts',
    filter: '/api/equipment/filters',
    accessory: '/api/equipment/accessories',
};

/** Map a bundle sub-item (same field shape as a standalone preset of that kind, see
 * docs/EQUIPMENT.md#presets) to its create payload. */
function _mapBundleItemToPayload(kind, item) {
    if (kind === 'camera') return _mapCameraPresetToPayload(item);
    if (kind === 'mount') {
        return {
            name: item.label,
            manufacturer: item.manufacturer || '',
            mount_type: item.mount_type || 'Alt-Azimuth',
            payload_capacity_kg: item.payload_capacity_kg || 0,
            guiding_supported: item.guiding_supported || false,
        };
    }
    if (kind === 'filter') {
        return {
            name: item.label,
            manufacturer: item.manufacturer || '',
            filter_type: item.filter_type || 'Other',
            central_wavelength_nm: item.central_wavelength_nm ?? null,
            bandwidth_nm: item.bandwidth_nm ?? null,
            intended_use: item.intended_use || '',
        };
    }
    if (kind === 'accessory') {
        return {
            name: item.label,
            manufacturer: item.manufacturer || '',
            accessory_type: item.accessory_type || '',
            weight_kg: item.weight_kg || 0,
        };
    }
    return null;
}

/** Create every item in a bundling telescope preset's `bundle` array (e.g. a Seestar's built-in
 * camera + mount + solar filter). Returns the created ids grouped by combination field, so the
 * caller can link them all into one auto-created combination. Best-effort: one failed item logs
 * and is skipped rather than aborting the rest of the bundle. */
async function _createBundleItems(bundle) {
    const created = { camera_id: null, mount_id: null, filter_ids: [] };
    for (const item of bundle || []) {
        const endpoint = _WIZARD_BUNDLE_ENDPOINT_BY_KIND[item.kind];
        const payload = _mapBundleItemToPayload(item.kind, item);
        if (!endpoint || !payload) continue;
        try {
            const result = await fetchJSON(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const id = result?.data?.id;
            if (!id) continue;
            if (item.kind === 'camera') created.camera_id = id;
            else if (item.kind === 'mount') created.mount_id = id;
            else if (item.kind === 'filter') created.filter_ids.push(id);
        } catch (err) {
            console.error(`Wizard bundle item (${item.kind}) create error:`, err);
        }
    }
    return created;
}

async function _saveEquipmentStep() {
    const expSelect = document.getElementById('wizard-experience-level');
    const telescopeSelect = document.getElementById('wizard-telescope-preset');
    const telescopePreset = (_wizard.presets?.telescopes || []).find((p) => p.id === telescopeSelect?.value);
    const isBundling = !!(telescopePreset?.bundle && telescopePreset.bundle.length > 0);

    try {
        const telescopeId = await _saveEquipmentOfKind('telescope');

        let cameraId = null;
        let mountId = null;
        let filterIds = [];
        if (isBundling) {
            const created = await _createBundleItems(telescopePreset.bundle);
            cameraId = created.camera_id;
            mountId = created.mount_id;
            filterIds = created.filter_ids;
        } else {
            cameraId = await _saveEquipmentOfKind('camera');
        }

        // Goal (feature.md): every time the wizard creates equipment, a combination links it.
        if (telescopeId || cameraId) {
            const comboName = telescopePreset?.label
                || document.getElementById('wizard-telescope-manual-name')?.value.trim()
                || document.getElementById('wizard-camera-manual-name')?.value.trim()
                || i18n.t('wizard.equipment_default_combination_name');
            try {
                await fetchJSON('/api/equipment/combinations', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: comboName,
                        telescope_id: telescopeId || null,
                        camera_id: cameraId || null,
                        mount_id: mountId || null,
                        filter_ids: filterIds,
                    }),
                });
            } catch (err) {
                console.error('Wizard combination create error:', err);
            }
        }

        if (expSelect?.value) {
            setCurrentUserPreferences(await saveUserPreferences({ experience_level: expSelect.value }));
            window.myastroboardUserPreferences = { ...currentUserPreferences };
        }

        return true;
    } catch (err) {
        console.error('Wizard equipment save error:', err);
        showMessage('error', i18n.t('equipment.failed_to_save_equipment'));
        return false;
    }
}

// ── Step: notifications (all contexts) ──────────────────────────────────────

function _buildNotificationsStep(container) {
    const intro = document.createElement('p');
    intro.className = 'text-muted mb-3';
    intro.textContent = i18n.t('wizard.notifications_intro');
    container.appendChild(intro);

    // Notifications silently fail to enable on an insecure origin (plain HTTP) or an
    // unsupported browser - warn explicitly rather than letting the Enable button appear
    // to do nothing.
    const notifBlocked = (typeof window !== 'undefined' && window.isSecureContext === false)
        || (typeof notificationManager !== 'undefined' && !notificationManager.isSupported);
    if (notifBlocked && typeof _notifPermissionBannerState === 'function') {
        const state = _notifPermissionBannerState();
        const warning = document.createElement('div');
        warning.className = `alert ${state.cls} mb-3`;
        warning.textContent = i18n.has(state.i18n) ? i18n.t(state.i18n) : state.fallback;
        container.appendChild(warning);
    }

    const enableBtn = document.createElement('button');
    enableBtn.type = 'button';
    enableBtn.className = 'btn btn-outline-primary btn-sm mb-3';
    enableBtn.textContent = i18n.t('wizard.notifications_enable_btn');
    enableBtn.disabled = notifBlocked;
    enableBtn.addEventListener('click', async () => {
        enableBtn.disabled = true;
        await notificationManager.requestPermission();
        enableBtn.disabled = false;
    });
    container.appendChild(enableBtn);

    const prefs = notificationManager.getPrefs();
    const list = document.createElement('div');
    list.className = 'row g-2';
    Object.keys(NOTIF_TRIGGERS).forEach((id) => {
        list.appendChild(_buildWizardNotifRow(id, prefs));
    });
    container.appendChild(list);

    if (_wizard.flow === 'full') {
        const vapidWrap = document.createElement('div');
        vapidWrap.className = 'mt-3';
        const vapidLabel = document.createElement('label');
        vapidLabel.className = 'form-label';
        vapidLabel.htmlFor = 'wizard-vapid-email';
        vapidLabel.textContent = i18n.t('wizard.notifications_vapid_label');
        const vapidInput = document.createElement('input');
        vapidInput.type = 'email';
        vapidInput.id = 'wizard-vapid-email';
        vapidInput.className = 'form-control';
        vapidInput.placeholder = i18n.t('wizard.notifications_vapid_placeholder');
        const vapidErr = document.createElement('div');
        vapidErr.id = 'wizard-vapid-email-error';
        vapidErr.className = 'invalid-feedback';
        vapidWrap.appendChild(vapidLabel);
        vapidWrap.appendChild(vapidInput);
        vapidWrap.appendChild(vapidErr);
        container.appendChild(vapidWrap);
    }
}

function _buildWizardNotifRow(id, prefs) {
    const col = document.createElement('div');
    col.className = 'col-12';
    const rowWrap = document.createElement('div');
    rowWrap.className = 'bg-features rounded p-2 d-flex flex-wrap align-items-center gap-3';

    const switchWrap = document.createElement('div');
    switchWrap.className = 'form-check form-switch mb-0 flex-shrink-0';
    const toggle = document.createElement('input');
    toggle.className = 'form-check-input';
    toggle.type = 'checkbox';
    toggle.id = `wizard-notif-trigger-${id}`;
    toggle.checked = prefs.triggers?.[id]?.enabled ?? true;
    toggle.setAttribute('role', 'switch');
    const label = document.createElement('label');
    label.className = 'form-check-label';
    label.htmlFor = `wizard-notif-trigger-${id}`;
    label.textContent = i18n.t(`settings.notifications_${id.toLowerCase()}`);
    switchWrap.appendChild(toggle);
    switchWrap.appendChild(label);
    rowWrap.appendChild(switchWrap);

    if (id === 'N7') {
        const kpWrap = document.createElement('div');
        kpWrap.className = 'd-flex align-items-center gap-2 ms-auto';
        const kpLabel = document.createElement('label');
        kpLabel.className = 'form-label mb-0 text-muted small';
        kpLabel.textContent = i18n.t('settings.notifications_kp_label');
        const kpSelect = document.createElement('select');
        kpSelect.className = 'form-select form-select-sm';
        kpSelect.id = 'wizard-notif-kp-threshold';
        kpSelect.style.width = 'auto';
        for (let kp = 3; kp <= 9; kp++) {
            const opt = document.createElement('option');
            opt.value = String(kp);
            opt.textContent = String(kp);
            kpSelect.appendChild(opt);
        }
        kpSelect.value = String(prefs.triggers?.N7?.kp_threshold ?? 6);
        kpWrap.appendChild(kpLabel);
        kpWrap.appendChild(kpSelect);
        rowWrap.appendChild(kpWrap);
    } else {
        const leadWrap = document.createElement('div');
        leadWrap.className = 'd-flex align-items-center gap-2 ms-auto';
        const leadLabel = document.createElement('label');
        leadLabel.className = 'form-label mb-0 text-muted small';
        leadLabel.textContent = i18n.t('settings.notifications_lead_label');
        const leadSelect = document.createElement('select');
        leadSelect.className = 'form-select form-select-sm';
        leadSelect.id = `wizard-notif-lead-${id}`;
        leadSelect.style.width = 'auto';

        // N9's lead is day-granularity (stored as day-equivalent minutes), unlike every
        // other trigger's minute-granularity lead - see the equivalent select in the
        // Settings UI (templates/index.html #notif-lead-N9).
        const defaultLead = id === 'N9' ? 2880 : 15;
        if (id === 'N9') {
            [
                [1440, '1 day'], [2880, '2 days'], [4320, '3 days'], [7200, '5 days'], [10080, '7 days'],
            ].forEach(([minutes, label]) => {
                const opt = document.createElement('option');
                opt.value = String(minutes);
                opt.textContent = label;
                leadSelect.appendChild(opt);
            });
        } else {
            [5, 10, 15, 20, 30, 45, 60].forEach((min) => {
                const opt = document.createElement('option');
                opt.value = String(min);
                opt.textContent = `${min} ${i18n.t('settings.notifications_minutes')}`;
                leadSelect.appendChild(opt);
            });
        }
        leadSelect.value = String(prefs.triggers?.[id]?.lead_minutes ?? defaultLead);
        leadWrap.appendChild(leadLabel);
        leadWrap.appendChild(leadSelect);
        rowWrap.appendChild(leadWrap);
    }

    col.appendChild(rowWrap);
    return col;
}

async function _saveNotificationsStep() {
    const prefs = notificationManager._mergeWithDefaults(notificationManager.getPrefs());
    Object.keys(NOTIF_TRIGGERS).forEach((id) => {
        const toggle = document.getElementById(`wizard-notif-trigger-${id}`);
        if (toggle) prefs.triggers[id].enabled = toggle.checked;
        const lead = document.getElementById(`wizard-notif-lead-${id}`);
        if (lead && prefs.triggers[id].lead_minutes !== undefined) {
            prefs.triggers[id].lead_minutes = parseInt(lead.value, 10);
        }
    });
    const kp = document.getElementById('wizard-notif-kp-threshold');
    if (kp) prefs.triggers.N7.kp_threshold = parseInt(kp.value, 10);

    try {
        await notificationManager.savePrefs(prefs);
    } catch (err) {
        console.error('Wizard notifications save error:', err);
    }

    if (_wizard.flow === 'full') {
        const vapidInput = document.getElementById('wizard-vapid-email');
        const vapidVal = vapidInput?.value.trim();
        const vapidErrEl = document.getElementById('wizard-vapid-email-error');
        vapidInput?.classList.remove('is-invalid');
        if (vapidErrEl) vapidErrEl.textContent = '';

        if (vapidVal) {
            const hasNativeValidity = vapidInput && typeof vapidInput.checkValidity === 'function';
            const isValidEmail = hasNativeValidity
                ? vapidInput.checkValidity()
                : /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(vapidVal);
            if (!isValidEmail) {
                vapidInput?.classList.add('is-invalid');
                if (vapidErrEl) vapidErrEl.textContent = i18n.t('wizard.notifications_vapid_invalid');
                return false;
            }

            try {
                await fetchJSON('/api/admin/app-settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vapid_contact_email: vapidVal }),
                });
            } catch (err) {
                console.error('Wizard VAPID email save error:', err);
            }
        }
    }

    return true;
}

// ── Step: tonight (all contexts) ────────────────────────────────────────────

function _buildTonightStep(container) {
    const heading = document.createElement('h6');
    heading.textContent = i18n.t('wizard.tonight_intro');
    container.appendChild(heading);

    const panelContainer = document.createElement('div');
    panelContainer.className = 'mt-2';
    container.appendChild(panelContainer);
    if (typeof renderSkyTonightRecommendationsPanel === 'function') {
        renderSkyTonightRecommendationsPanel(panelContainer);
    }

    const goBtn = document.createElement('button');
    goBtn.type = 'button';
    goBtn.className = 'btn btn-primary mt-3';
    goBtn.textContent = i18n.t('wizard.go_to_skytonight');
    goBtn.addEventListener('click', async () => {
        await _wizardFinish();
        if (typeof switchMainTab === 'function') switchMainTab('skytonight');
    });
    container.appendChild(goBtn);
}

// ── Step dispatch tables ─────────────────────────────────────────────────────

const _WIZARD_STEP_BUILDERS = {
    location: _buildLocationStep,
    sky_quality: _buildSkyQualityStep,
    welcome: _buildWelcomeStep,
    equipment: _buildEquipmentStep,
    notifications: _buildNotificationsStep,
    tonight: _buildTonightStep,
};

const _WIZARD_STEP_SAVE = {
    location: _saveLocationStep,
    sky_quality: _saveSkyQualityStep,
    equipment: _saveEquipmentStep,
    notifications: _saveNotificationsStep,
};
