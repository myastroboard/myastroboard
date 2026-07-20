// Equipment Profiles functionality
// Telescope, Camera, Mount, Filter, Accessory, and Combination management

let equipmentData = {
    telescopes: [],
    cameras: [],
    mounts: [],
    filters: [],
    accessories: [],
    combinations: [],
    sharedTelescopes: [],
    sharedCameras: [],
    sharedMounts: [],
    sharedFilters: [],
    sharedAccessories: [],
    sharedCombinations: []
};

let equipmentFilters = {
    search: '',
    type: 'all'
};

// ============================================
// Equipment Presets (static/data/equipment_presets.json)
// ============================================

let _equipmentPresetsCache = null;

async function _loadEquipmentPresets() {
    if (_equipmentPresetsCache) return _equipmentPresetsCache;
    try {
        const resp = await fetch('/static/data/equipment_presets.json', { credentials: 'same-origin' });
        _equipmentPresetsCache = resp.ok ? await resp.json() : {};
    } catch (_) {
        _equipmentPresetsCache = {};
    }
    return _equipmentPresetsCache;
}

const _TELESCOPE_PRESET_TYPE_MAP = {
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

const _CAMERA_PRESET_SENSOR_TYPE_MAP = {
    cmos_color: 'CMOS Color',
    dslr_color: 'CMOS Color',
    mirrorless_color: 'CMOS Color',
    cmos_mono: 'CMOS Mono',
    ccd_color: 'CCD Color',
    ccd_mono: 'CCD Mono',
};

/** Build <option> markup for a preset list, sorted alphabetically by manufacturer then label. */
function _buildPresetOptionsHtml(presets) {
    const ordered = [...presets].sort((a, b) => {
        return (a.manufacturer || '').localeCompare(b.manufacturer || '') || a.label.localeCompare(b.label);
    });
    return ordered.map((preset) => {
        const alreadyPrefixed = preset.manufacturer
            && preset.label.toLowerCase().startsWith(preset.manufacturer.toLowerCase());
        const text = preset.manufacturer && !alreadyPrefixed
            ? `${preset.manufacturer} - ${preset.label}`
            : preset.label;
        return `<option value="${escapeHtml(preset.id)}">${escapeHtml(text)}</option>`;
    }).join('');
}

/** Build the "Start from a preset" picker block shown at the top of an "add new" form.
 * Pass wrapInRow for forms that aren't themselves a `.row` (e.g. the accessory form,
 * which nests `.row` blocks internally instead of being one). */
function _buildPresetPickerHtml(kind, presets, { wrapInRow = false } = {}) {
    if (!presets || presets.length === 0) return '';
    const field = `
        <div class="col-md-12">
            <label for="${kind}-preset-select" class="form-label">${i18n.t('equipment.preset_label')}</label>
            <select class="form-select" id="${kind}-preset-select">
                <option value="">${i18n.t('equipment.preset_placeholder')}</option>
                ${_buildPresetOptionsHtml(presets)}
            </select>
        </div>
    `;
    return wrapInRow ? `<div class="row mb-3">${field}</div>` : field;
}

function _applyTelescopePreset(preset) {
    document.getElementById('telescope-name').value = preset.label || '';
    document.getElementById('telescope-manufacturer').value = preset.manufacturer || '';
    document.getElementById('telescope-type').value = _TELESCOPE_PRESET_TYPE_MAP[preset.type] || 'Refractor';
    document.getElementById('telescope-aperture').value = preset.aperture_mm ?? '';
    document.getElementById('telescope-focal-length').value = preset.focal_length_mm ?? '';
    document.getElementById('telescope-weight').value = preset.weight_kg ?? '';
}

function _applyCameraPreset(preset) {
    document.getElementById('camera-name').value = preset.label || '';
    document.getElementById('camera-manufacturer').value = preset.manufacturer || '';
    document.getElementById('camera-sensor-type').value = _CAMERA_PRESET_SENSOR_TYPE_MAP[preset.type] || 'CMOS Color';
    document.getElementById('camera-pixel-size').value = preset.pixel_size_um ?? '';
    document.getElementById('camera-sensor-width').value = preset.sensor_width_mm ?? '';
    document.getElementById('camera-sensor-height').value = preset.sensor_height_mm ?? '';
    document.getElementById('camera-resolution-width').value = preset.resolution_w ?? '';
    document.getElementById('camera-resolution-height').value = preset.resolution_h ?? '';
    document.getElementById('camera-cooling-supported').value = preset.cooling_supported ? 'true' : 'false';
    document.getElementById('camera-min-temperature').value = preset.min_temperature_c ?? '';
    document.getElementById('camera-weight').value = preset.weight_kg ?? '';
}

function _applyMountPreset(preset) {
    document.getElementById('mount-name').value = preset.label || '';
    document.getElementById('mount-manufacturer').value = preset.manufacturer || '';
    document.getElementById('mount-type').value = preset.mount_type || 'Equatorial';
    document.getElementById('mount-payload-capacity').value = preset.payload_capacity_kg ?? '';
    document.getElementById('mount-tracking-accuracy').value = preset.tracking_accuracy_arcsec ?? '';
    document.getElementById('mount-guiding-supported').value = preset.guiding_supported ? 'true' : 'false';
}

function _applyFilterPreset(preset) {
    document.getElementById('filter-name').value = preset.label || '';
    document.getElementById('filter-manufacturer').value = preset.manufacturer || '';
    document.getElementById('filter-type').value = preset.filter_type || 'Other';
    document.getElementById('filter-wavelength').value = preset.central_wavelength_nm ?? '';
    document.getElementById('filter-bandwidth').value = preset.bandwidth_nm ?? '';
    document.getElementById('filter-intended-use').value = preset.intended_use || '';
}

function _applyAccessoryPreset(preset) {
    document.getElementById('accessory-name').value = preset.label || '';
    document.getElementById('accessory-manufacturer').value = preset.manufacturer || '';
    document.getElementById('accessory-type').value = preset.accessory_type || '';
    document.getElementById('accessory-weight').value = preset.weight_kg ?? '';
}

/** Wire the preset <select> in an "add new" form to prefill fields via applyFn on change. */
function _wirePresetSelect(kind, presets, applyFn) {
    const select = document.getElementById(`${kind}-preset-select`);
    if (!select) return;
    select.addEventListener('change', () => {
        const preset = (presets || []).find(p => p.id === select.value);
        if (preset) applyFn(preset);
    });
}

// ============================================
// Initialize Equipment Module
// ============================================

async function initializeEquipment() {
    // Get role user
    const roleUser = await getUserRole();

    // If user is not admin, not user, we don't load equipment management features
    if (roleUser !== 'admin' && roleUser !== 'user') {
        return;
    }

    loadAllEquipment();
    setupEquipmentEventListeners();
    setupEquipmentSharedRefresh();
}

function setupEquipmentSharedRefresh() {
    // Case 1: admin switches back to Equipment from another main tab.
    // MutationObserver detects 'active' being added to #equipment-tab.
    // Skip the very first activation (already loaded above at init).
    const equipmentTabEl = document.getElementById('equipment-tab');
    if (equipmentTabEl) {
        let initialActivation = true;
        new MutationObserver(() => {
            if (equipmentTabEl.classList.contains('active')) {
                if (initialActivation) { initialActivation = false; return; }
                loadAllEquipment();
            }
        }).observe(equipmentTabEl, { attributes: true, attributeFilter: ['class'] });
    }

    // Case 2: admin clicks any subtab within Equipment (Filters, Mounts, etc.).
    // Click events on .sub-tab-btn inside #equipment-tab trigger a reload.
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.sub-tab-btn');
        if (!btn) return;
        if (btn.closest('#equipment-tab')) loadAllEquipment();
    });
}

function setupEquipmentEventListeners() {
    // Main equipment buttons
    document.addEventListener('click', (e) => {
        // Resolve the actual button even when clicking an inner icon element
        const btn = e.target.closest('button');
        if (!btn) return;

        // New equipment buttons
        if (btn.classList.contains('btn-new-telescope')) showTelescopeModal();
        if (btn.classList.contains('btn-new-camera')) showCameraModal();
        if (btn.classList.contains('btn-new-mount')) showMountModal();
        if (btn.classList.contains('btn-new-filter')) showFilterModal();
        if (btn.classList.contains('btn-new-accessory')) showAccessoryModal();
        if (btn.classList.contains('btn-new-combination')) showCombinationModal();

        // Edit buttons
        if (btn.classList.contains('btn-edit-telescope')) showTelescopeModal(btn.dataset.id);
        if (btn.classList.contains('btn-edit-camera')) showCameraModal(btn.dataset.id);
        if (btn.classList.contains('btn-edit-mount')) showMountModal(btn.dataset.id);
        if (btn.classList.contains('btn-edit-filter')) showFilterModal(btn.dataset.id);
        if (btn.classList.contains('btn-edit-accessory')) showAccessoryModal(btn.dataset.id);
        if (btn.classList.contains('btn-edit-combination')) showCombinationModal(btn.dataset.id);

        // Delete buttons
        if (btn.classList.contains('btn-delete-telescope')) deleteEquipment('telescopes', btn.dataset.id);
        if (btn.classList.contains('btn-delete-camera')) deleteEquipment('cameras', btn.dataset.id);
        if (btn.classList.contains('btn-delete-mount')) deleteEquipment('mounts', btn.dataset.id);
        if (btn.classList.contains('btn-delete-filter')) deleteEquipment('filters', btn.dataset.id);
        if (btn.classList.contains('btn-delete-accessory')) deleteEquipment('accessories', btn.dataset.id);
        if (btn.classList.contains('btn-delete-combination')) deleteEquipment('combinations', btn.dataset.id);
    });
}

// ============================================
// Load Equipment Data
// ============================================

async function loadAllEquipment() {
   
    try {
        await fetchJSON('/api/equipment/summary');
        
        // Load each equipment type
        await loadEquipmentType('telescopes');
        await loadEquipmentType('cameras');
        await loadEquipmentType('mounts');
        await loadEquipmentType('filters');
        await loadEquipmentType('accessories');
        await loadEquipmentType('combinations');
        
        renderAllEquipmentTabs();
    } catch (error) {
        console.error('Error loading equipment:', error);
        showMessage('error', i18n.t('equipment.failed_to_load_equipment'));
    }
}

async function loadEquipmentType(type) {
    try {
        const response = await fetchJSON(`/api/equipment/${type}`);
        equipmentData[type] = response.data || [];
        const sharedKey = 'shared' + type.charAt(0).toUpperCase() + type.slice(1);
        equipmentData[sharedKey] = response.shared_from_others || [];
    } catch (error) {
        console.error(`Error loading ${type}:`, error);
        equipmentData[type] = [];
    }
}

function findEquipmentById(type, id) {
    const sharedKey = 'shared' + type.charAt(0).toUpperCase() + type.slice(1);
    return equipmentData[type].find(e => e.id === id)
        || equipmentData[sharedKey]?.find(e => e.id === id)
        || null;
}

// ============================================
// Render Equipment Tabs
// ============================================

// Per-tab "Show hidden" state - disabled items are excluded from each list by default.
const equipmentShowHidden = {
    telescopes: false,
    cameras: false,
    mounts: false,
    filters: false,
    accessories: false,
    combinations: false,
};

/** Build a "Show hidden (N)" / "Hide hidden items" toggle for a list tab.
 * Returns null (nothing to render) when there is nothing hidden and the toggle isn't
 * already active - a tab with no disabled items never shows the control. */
function _buildShowHiddenToggle(kind, hiddenCount, rerenderFn) {
    if (hiddenCount === 0 && !equipmentShowHidden[kind]) return null;
    const wrap = document.createElement('div');
    wrap.className = 'mb-3';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm btn-outline-secondary d-inline-flex align-items-center gap-1';
    const label = document.createElement('span');
    label.textContent = equipmentShowHidden[kind]
        ? i18n.t('equipment.hide_hidden_items')
        : i18n.t('equipment.show_hidden_items', { count: hiddenCount });
    btn.appendChild(DOMUtils.createIcon(equipmentShowHidden[kind] ? 'bi bi-eye-slash' : 'bi bi-eye'));
    btn.appendChild(label);
    btn.addEventListener('click', () => {
        equipmentShowHidden[kind] = !equipmentShowHidden[kind];
        rerenderFn();
    });
    wrap.appendChild(btn);
    return wrap;
}

/** Render one equipment list tab, applying the "Show hidden" filter and toggle.
 * `rerenderFn` must be the tab's own render function (e.g. renderTelescopesTab), passed by
 * the caller so the toggle can re-render just this tab after flipping the state. */
function _renderEquipmentListTab(containerId, kind, ownItems, sharedItems, emptyMessageKey, renderCard, rerenderFn) {
    const container = document.getElementById(containerId);
    if (!container) return;
    DOMUtils.clear(container);

    if (ownItems.length === 0 && sharedItems.length === 0) {
        container.appendChild(createEmptyStateCard(i18n.t(emptyMessageKey)));
        return;
    }

    const hiddenCount = [...ownItems, ...sharedItems].filter(item => item.is_disabled).length;
    const toggle = _buildShowHiddenToggle(kind, hiddenCount, rerenderFn);
    if (toggle) container.appendChild(toggle);

    const showHidden = equipmentShowHidden[kind];
    const visibleOwn = showHidden ? ownItems : ownItems.filter(item => !item.is_disabled);
    const visibleShared = showHidden ? sharedItems : sharedItems.filter(item => !item.is_disabled);

    renderEquipmentSection(container, visibleOwn, false, renderCard);
    renderEquipmentSection(container, visibleShared, true, renderCard);
}

/** Append a muted "Hidden" badge to a card's title row when the item is disabled. */
function appendHiddenBadge(titleRow, item) {
    if (!item.is_disabled) return;
    const badge = document.createElement('span');
    badge.className = 'badge bg-secondary';
    badge.textContent = i18n.t('equipment.hidden_badge');
    titleRow.appendChild(badge);
}

function renderAllEquipmentTabs() {
    renderCombinationsTab();
    renderFOVCalculatorTab();
    renderExposureCalcTab();
    renderTelescopesTab();
    renderCamerasTab();
    renderMountsTab();
    renderFiltersTab();
    renderAccessoriesTab();
}

function createEmptyStateCard(message) {
    const row = document.createElement('div');
    row.className = 'row';

    const col = document.createElement('div');
    col.className = 'col mb-3';

    const card = document.createElement('div');
    card.className = 'card h-100';

    const body = document.createElement('div');
    body.className = 'card-body';

    const p = document.createElement('p');
    p.className = 'card-text';
    p.textContent = message;

    body.appendChild(p);
    card.appendChild(body);
    col.appendChild(card);
    row.appendChild(col);
    return row;
}

function appendInfoLine(container, label, value) {
    if (value === null || value === undefined || value === '') {
        return;
    }
    const strong = document.createElement('strong');
    strong.textContent = `${label}:`;
    container.appendChild(strong);
    container.appendChild(document.createTextNode(` ${value}`));
    container.appendChild(document.createElement('br'));
}


function createCardFooter(editClass, deleteClass, id) {
    const footer = document.createElement('div');
    footer.className = 'card-footer text-center';

    const placeholder = document.createElement('span');
    placeholder.className = 'btn-icon-placeholder';

    const editButton = document.createElement('button');
    editButton.className = `btn btn-outline-secondary ${editClass}`;
    editButton.setAttribute('data-id', id);
    editButton.setAttribute('title', i18n.t('equipment.edit'));
    editButton.appendChild(DOMUtils.createIcon('bi bi-pencil-square'));

    const deleteButton = document.createElement('button');
    deleteButton.className = `btn btn-outline-danger ${deleteClass}`;
    deleteButton.setAttribute('data-id', id);
    deleteButton.setAttribute('title', i18n.t('equipment.delete'));
    deleteButton.appendChild(DOMUtils.createIcon('bi bi-trash'));

    footer.appendChild(placeholder);
    footer.appendChild(editButton);
    footer.appendChild(deleteButton);
    return footer;
}

function createSharedBadge(ownerUsername) {
    const badge = document.createElement('span');
    badge.className = 'badge bg-info text-dark ms-1';
    badge.title = i18n.t('equipment.shared_readonly_hint');
    badge.textContent = ownerUsername
        ? i18n.t('equipment.shared_by', { username: ownerUsername })
        : i18n.t('equipment.shared_badge');
    return badge;
}

function createReadOnlyFooter(ownerUsername) {
    const footer = document.createElement('div');
    footer.className = 'card-footer text-center';
    const hint = document.createElement('small');
    hint.className = 'text-body-secondary';
    hint.textContent = i18n.t('equipment.shared_readonly_hint');
    footer.appendChild(hint);
    return footer;
}

// --- Combinations Tab (Position 1) ---

function renderCombinationCard(combo, isReadOnly) {
    const telescope = combo.telescope_id ? findEquipmentById('telescopes', combo.telescope_id) : null;
    const camera = combo.camera_id ? findEquipmentById('cameras', combo.camera_id) : null;
    const guideCamera = combo.guide_camera_id ? findEquipmentById('cameras', combo.guide_camera_id) : null;
    const mount = combo.mount_id ? findEquipmentById('mounts', combo.mount_id) : null;

    const telescopeWeight = telescope?.weight_kg || 0;
    const cameraWeight = camera?.weight_kg || 0;
    const allAccessories = [...(equipmentData.accessories || []), ...(equipmentData.sharedAccessories || [])];
    const accessoriesWeight = combo.accessory_ids
        ? allAccessories.filter(a => combo.accessory_ids.includes(a.id)).reduce((sum, a) => sum + (a.weight_kg || 0), 0)
        : 0;
    const totalWeight = telescopeWeight + cameraWeight + accessoriesWeight;
    const mountCapacity = mount?.payload_capacity_kg || 0;
    const mountRecommended = mount?.recommended_payload_kg || 0;
    const isOverCapacity = mount && totalWeight > mountCapacity;
    const isOverRecommended = mount && totalWeight > mountRecommended;

    let payloadAlert = '';
    if (isOverCapacity) {
        payloadAlert = i18n.t('equipment.overweight', { totalweight: totalWeight.toFixed(1), mountcapacity: mountCapacity });
    } else if (isOverRecommended) {
        payloadAlert = i18n.t('equipment.recommanded_max_payload', { totalweight: totalWeight.toFixed(1), mountrecommended: mountRecommended });
    } else if (mount) {
        payloadAlert = i18n.t('equipment.payload', { totalweight: totalWeight.toFixed(1), mountcapacity: mountCapacity });
    }

    const col = document.createElement('div');
    col.className = 'col mb-3';
    const card = document.createElement('div');
    card.className = 'card h-100';
    const body = document.createElement('div');
    body.className = 'card-body';

    const titleRow = document.createElement('div');
    titleRow.className = 'd-flex align-items-center mb-1 gap-2 flex-wrap';
    const title = document.createElement('h5');
    title.className = 'card-title mb-0';
    title.textContent = combo.name;
    titleRow.appendChild(title);
    if (combo.is_shared) {
        const sharedBadge = document.createElement('span');
        sharedBadge.className = 'badge bg-info text-dark';
        sharedBadge.textContent = i18n.t('equipment.shared_badge');
        titleRow.appendChild(sharedBadge);
    }
    if (isReadOnly && combo.owner_username) {
        titleRow.appendChild(createSharedBadge(combo.owner_username));
    }
    if (combo.has_broken_share) {
        const brokenBadge = document.createElement('span');
        brokenBadge.className = 'badge bg-warning text-dark';
        brokenBadge.title = i18n.t('equipment.combination_broken_share');
        brokenBadge.textContent = '⚠ ' + i18n.t('equipment.combination_broken_share');
        titleRow.appendChild(brokenBadge);
    }
    if (combo.is_valid === false) {
        const invalidBadge = document.createElement('span');
        invalidBadge.className = 'badge bg-danger';
        invalidBadge.title = i18n.t('equipment.combination_invalid_hint');
        invalidBadge.textContent = '⚠ ' + i18n.t('equipment.combination_invalid');
        titleRow.appendChild(invalidBadge);
    }
    appendHiddenBadge(titleRow, combo);
    if (combo.photo_count > 0) {
        const photoBadge = document.createElement('span');
        photoBadge.className = 'badge bg-secondary';
        photoBadge.style.cursor = 'pointer';
        photoBadge.title = i18n.t('equipment.combination_photo_count_hint');
        DOMUtils.append(photoBadge, DOMUtils.createIcon('bi bi-camera'), ` ${combo.photo_count}`);
        photoBadge.addEventListener('click', () => {
            if (typeof showPictureSlideshowFromPictures === 'function' && Array.isArray(combo.picture_refs)) {
                showPictureSlideshowFromPictures(combo.picture_refs, { title: combo.name });
            }
        });
        titleRow.appendChild(photoBadge);
    }
    if (combo.average_rating != null) {
        const ratingBadge = document.createElement('span');
        ratingBadge.className = 'badge bg-warning text-dark';
        ratingBadge.title = i18n.t('equipment.combination_average_rating_hint');
        DOMUtils.append(ratingBadge, DOMUtils.createIcon('bi bi-star-fill'), ` ${combo.average_rating.toFixed(1)}`);
        titleRow.appendChild(ratingBadge);
    }
    body.appendChild(titleRow);

    const p = document.createElement('p');
    p.className = 'card-text';
    if (telescope) appendInfoLine(p, i18n.t('equipment.telescope'), `${telescope.name}${telescopeWeight > 0 ? ` (${telescopeWeight}${i18n.t('units.kg')})` : ''}`);
    if (camera) appendInfoLine(p, i18n.t('equipment.camera'), `${camera.name}${cameraWeight > 0 ? ` (${cameraWeight}${i18n.t('units.kg')})` : ''}`);
    if (!telescope && (combo.lens_focal_length_mm || combo.lens_focal_ratio)) {
        const lensParts = [];
        if (combo.lens_focal_length_mm) lensParts.push(`${combo.lens_focal_length_mm}${i18n.t('units.mm')}`);
        if (combo.lens_focal_ratio) lensParts.push(`f/${combo.lens_focal_ratio}`);
        appendInfoLine(p, i18n.t('equipment.form_lens_focal_length'), lensParts.join(' '));
    }
    if (guideCamera) appendInfoLine(p, i18n.t('equipment.form_guide_camera'), guideCamera.name);
    if (mount) appendInfoLine(p, i18n.t('equipment.mount'), mount.name);
    if (combo.filter_ids && combo.filter_ids.length > 0) {
        const allFilters = [...(equipmentData.filters || []), ...(equipmentData.sharedFilters || [])];
        const filterNames = allFilters.filter(f => combo.filter_ids.includes(f.id)).map(f => f.name).join(', ');
        appendInfoLine(p, i18n.t('equipment.filters'), filterNames);
    }
    if (combo.accessory_ids && combo.accessory_ids.length > 0) {
        const accessoryNames = allAccessories.filter(a => combo.accessory_ids.includes(a.id)).map(a => a.name).join(', ');
        appendInfoLine(p, i18n.t('equipment.accessories'), `${accessoryNames}${accessoriesWeight > 0 ? ` (${accessoriesWeight}${i18n.t('units.kg')})` : ''}`);
    }
    body.appendChild(p);

    if (payloadAlert) {
        const payloadInfo = document.createElement('div');
        payloadInfo.className = `alert alert-sm py-1 px-2 mt-2 fw-light ${isOverCapacity ? 'alert-danger' : isOverRecommended ? 'alert-info' : 'alert-success'}`;
        payloadInfo.textContent = payloadAlert;
        body.appendChild(payloadInfo);
    }

    card.appendChild(body);
    card.appendChild(isReadOnly
        ? createReadOnlyFooter(combo.owner_username)
        : createCardFooter('btn-edit-combination', 'btn-delete-combination', combo.id));
    col.appendChild(card);
    return col;
}

function renderCombinationsTab() {
    const container = document.getElementById('equipment-combinations-display');
    if (!container) return;

    DOMUtils.clear(container);

    const allOwn = equipmentData.combinations;
    const allShared = equipmentData.sharedCombinations;

    if (allOwn.length === 0 && allShared.length === 0) {
        container.appendChild(createEmptyStateCard(i18n.t('equipment.no_equipment_yet')));
        return;
    }

    const hiddenCount = [...allOwn, ...allShared].filter(combo => combo.is_disabled).length;
    const toggle = _buildShowHiddenToggle('combinations', hiddenCount, renderCombinationsTab);
    if (toggle) container.appendChild(toggle);

    const showHidden = equipmentShowHidden.combinations;
    const ownCombos = showHidden ? allOwn : allOwn.filter(combo => !combo.is_disabled);
    const sharedCombos = showHidden ? allShared : allShared.filter(combo => !combo.is_disabled);

    const hasOwn = ownCombos.length > 0;
    const hasShared = sharedCombos.length > 0;

    if (hasOwn) {
        if (hasShared) {
            const hdr = document.createElement('h6');
            hdr.className = 'text-body-secondary mb-1';
            hdr.textContent = i18n.t('equipment.my_equipment_section');
            container.appendChild(hdr);
        }
        const row = document.createElement('div');
        row.className = 'row row-cols-1 row-cols-md-2 row-cols-lg-3';
        ownCombos.forEach(combo => row.appendChild(renderCombinationCard(combo, false)));
        container.appendChild(row);
    }

    if (hasShared) {
        const hdr = document.createElement('h6');
        hdr.className = 'text-body-secondary mb-1 mt-3';
        hdr.textContent = i18n.t('equipment.shared_by_others_section');
        container.appendChild(hdr);
        const row = document.createElement('div');
        row.className = 'row row-cols-1 row-cols-md-2 row-cols-lg-3';
        sharedCombos.forEach(combo => row.appendChild(renderCombinationCard(combo, true)));
        container.appendChild(row);
    }
}

// --- FOV Calculator Tab (Position 2) ---

function renderFOVCalculatorTab() {
    const container = document.getElementById('equipment-fov-display');
    if (!container) return;

    const telescopes = [...equipmentData.telescopes, ...equipmentData.sharedTelescopes];
    const cameras = [...equipmentData.cameras, ...equipmentData.sharedCameras];
    
    DOMUtils.clear(container);

    const card = document.createElement('div');
    card.className = 'card';
    const body = document.createElement('div');
    body.className = 'card-body';
    const title = document.createElement('h5');
    title.className = 'card-title';
    DOMUtils.append(title, DOMUtils.createIcon('bi bi-binoculars icon-inline'), i18n.t('equipment.fov_calculator'));
    body.appendChild(title);

    const row1 = document.createElement('div');
    row1.className = 'row mb-3';
    const tCol = document.createElement('div');
    tCol.className = 'col-md-6';
    const tLabel = document.createElement('label');
    tLabel.className = 'form-label';
    tLabel.setAttribute('for', 'fov-telescope-select');
    tLabel.textContent = i18n.t('equipment.telescope');
    const tSelect = document.createElement('select');
    tSelect.id = 'fov-telescope-select';
    tSelect.className = 'form-select';
    const tDefault = document.createElement('option');
    tDefault.value = '';
    tDefault.textContent = i18n.t('equipment.select_telescope');
    tSelect.appendChild(tDefault);
    telescopes.forEach((t) => {
        const option = document.createElement('option');
        option.value = t.id;
        const suffix = t.owner_username ? ` ${i18n.t('equipment.shared_fov_suffix', { username: t.owner_username })}` : '';
        option.textContent = `${t.name} (${t.effective_focal_length}${i18n.t('units.mm')} f/${t.effective_focal_ratio})${suffix}`;
        tSelect.appendChild(option);
    });
    tCol.appendChild(tLabel);
    tCol.appendChild(tSelect);

    const cCol = document.createElement('div');
    cCol.className = 'col-md-6';
    const cLabel = document.createElement('label');
    cLabel.className = 'form-label';
    cLabel.setAttribute('for', 'fov-camera-select');
    cLabel.textContent = i18n.t('equipment.camera');
    const cSelect = document.createElement('select');
    cSelect.id = 'fov-camera-select';
    cSelect.className = 'form-select';
    const cDefault = document.createElement('option');
    cDefault.value = '';
    cDefault.textContent = i18n.t('equipment.select_camera');
    cSelect.appendChild(cDefault);
    cameras.forEach((c) => {
        const option = document.createElement('option');
        option.value = c.id;
        const suffix = c.owner_username ? ` ${i18n.t('equipment.shared_fov_suffix', { username: c.owner_username })}` : '';
        option.textContent = `${c.name} (${c.pixel_size_um}${i18n.t('units.um')})${suffix}`;
        cSelect.appendChild(option);
    });
    cCol.appendChild(cLabel);
    cCol.appendChild(cSelect);

    row1.appendChild(tCol);
    row1.appendChild(cCol);

    const row2 = document.createElement('div');
    row2.className = 'row mb-3';
    const seeingCol = document.createElement('div');
    seeingCol.className = 'col-md-6';
    const seeingLabel = document.createElement('label');
    seeingLabel.className = 'form-label';
    seeingLabel.setAttribute('for', 'fov-seeing');
    seeingLabel.textContent = i18n.t('equipment.seeing_cdt');
    const seeingInput = document.createElement('input');
    seeingInput.type = 'number';
    seeingInput.id = 'fov-seeing';
    seeingInput.className = 'form-control';
    seeingInput.value = '2.0';
    seeingInput.min = '0.5';
    seeingInput.max = '5';
    seeingInput.step = '0.1';
    seeingCol.appendChild(seeingLabel);
    seeingCol.appendChild(seeingInput);

    const buttonCol = document.createElement('div');
    buttonCol.className = 'col-md-6 d-flex align-items-end';
    const button = document.createElement('button');
    button.className = 'btn btn-primary w-100 mt-2';
    button.textContent = i18n.t('equipment.calculate_fov');
    button.addEventListener('click', calculateFOVFromUI);
    buttonCol.appendChild(button);

    row2.appendChild(seeingCol);
    row2.appendChild(buttonCol);

    const results = document.createElement('div');
    results.id = 'fov-results';

    body.appendChild(row1);
    body.appendChild(row2);
    body.appendChild(results);
    card.appendChild(body);
    container.appendChild(card);
}

async function calculateFOVFromUI() {
    const telescopeId = document.getElementById('fov-telescope-select')?.value;
    const cameraId = document.getElementById('fov-camera-select')?.value;
    const seeing = parseFloat(document.getElementById('fov-seeing')?.value || 2.0);
    
    if (!telescopeId || !cameraId) {
        showMessage('warning', i18n.t('equipment.please_select_telescope_camera'));
        return;
    }

    const telescope = findEquipmentById('telescopes', telescopeId);
    const camera = findEquipmentById('cameras', cameraId);
    if (!telescope || !camera) {
        showMessage('warning', i18n.t('equipment.selected_equipment_not_found'));
        return;
    }
    
    try {
        const response = await fetchJSON('/api/equipment/fov-calculator', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                telescope_focal_length_mm: telescope.effective_focal_length,
                camera_sensor_width_mm: camera.sensor_width_mm,
                camera_sensor_height_mm: camera.sensor_height_mm,
                camera_pixel_size_um: camera.pixel_size_um,
                seeing_arcsec: seeing
            })
        });
        
        const fov = response;
        const resultsDiv = document.getElementById('fov-results');

        DOMUtils.clear(resultsDiv);
        const alert = document.createElement('div');
        alert.className = 'alert alert-success';

        const h6 = document.createElement('h6');
        h6.textContent = i18n.t('equipment.fov_results');
        alert.appendChild(h6);

        const table = document.createElement('table');
        table.className = 'table table-sm table-borderless';

        const rows = [
            [i18n.t('equipment.horizontal_fov'), `${fov.horizontal_fov_deg.toFixed(3)}${i18n.t('units.degrees')}`],
            [i18n.t('equipment.vertical_fov'), `${fov.vertical_fov_deg.toFixed(3)}${i18n.t('units.degrees')}`],
            [i18n.t('equipment.diagonal_fov'), `${fov.diagonal_fov_deg.toFixed(3)}${i18n.t('units.degrees')}`],
            [i18n.t('equipment.image_scale'), `${fov.image_scale_arcsec_per_px.toFixed(4)} ${i18n.t('units.arcsec_per_pixel')}`]
        ];

        rows.forEach(([label, value]) => {
            const tr = document.createElement('tr');
            const td1 = document.createElement('td');
            const strong = document.createElement('strong');
            strong.textContent = `${label}`;
            td1.appendChild(strong);
            const td2 = document.createElement('td');
            td2.textContent = value;
            tr.appendChild(td1);
            tr.appendChild(td2);
            table.appendChild(tr);
        });

        const trSampling = document.createElement('tr');
        const tdSamplingLabel = document.createElement('td');
        const strongSampling = document.createElement('strong');
        strongSampling.textContent = i18n.t('equipment.sampling');
        tdSamplingLabel.appendChild(strongSampling);
        const tdSamplingValue = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = 'badge bg-info';
        badge.textContent = fov.sampling_classification;
        tdSamplingValue.appendChild(badge);
        trSampling.appendChild(tdSamplingLabel);
        trSampling.appendChild(tdSamplingValue);
        table.appendChild(trSampling);

        alert.appendChild(table);
        resultsDiv.appendChild(alert);
    } catch (error) {
        console.error('Error calculating FOV:', error);
        showMessage('error', i18n.t('equipment.failed_to_calculate_fov'));
    }
}

function renderEquipmentSection(container, items, isReadOnly, renderCard) {
    const hasAnyShared = equipmentData.sharedTelescopes.length + equipmentData.sharedCameras.length
        + equipmentData.sharedMounts.length + equipmentData.sharedFilters.length
        + equipmentData.sharedAccessories.length > 0;

    if (items.length === 0) return;

    if (isReadOnly || (!isReadOnly && hasAnyShared)) {
        const hdr = document.createElement('h6');
        hdr.className = 'text-body-secondary mb-1' + (isReadOnly ? ' mt-3' : '');
        hdr.textContent = isReadOnly
            ? i18n.t('equipment.shared_by_others_section')
            : i18n.t('equipment.my_equipment_section');
        container.appendChild(hdr);
    }

    const row = document.createElement('div');
    row.className = 'row row-cols-1 row-cols-md-2 row-cols-lg-3';
    items.forEach(item => row.appendChild(renderCard(item, isReadOnly)));
    container.appendChild(row);
}

// --- Telescopes Tab (Position 3) ---

function renderTelescopeCard(scope, isReadOnly) {
    const col = document.createElement('div');
    col.className = 'col mb-3';
    const card = document.createElement('div');
    card.className = 'card h-100';
    const body = document.createElement('div');
    body.className = 'card-body';

    const titleRow = document.createElement('div');
    titleRow.className = 'd-flex align-items-center mb-1 gap-2 flex-wrap';
    const title = document.createElement('h5');
    title.className = 'card-title mb-0';
    title.textContent = scope.name;
    titleRow.appendChild(title);
    if (scope.is_shared && !isReadOnly) {
        const b = document.createElement('span');
        b.className = 'badge bg-info text-dark';
        b.textContent = i18n.t('equipment.shared_badge');
        titleRow.appendChild(b);
    }
    if (isReadOnly) titleRow.appendChild(createSharedBadge(scope.owner_username));
    appendHiddenBadge(titleRow, scope);
    body.appendChild(titleRow);

    if (scope.manufacturer) {
        const subtitle = document.createElement('h6');
        subtitle.className = 'card-subtitle mb-2 text-body-secondary';
        subtitle.textContent = scope.manufacturer;
        body.appendChild(subtitle);
    }

    const p = document.createElement('p');
    p.className = 'card-text';
    appendInfoLine(p, i18n.t('equipment.type'), scope.telescope_type);
    appendInfoLine(p, i18n.t('equipment.aperture'), `${scope.aperture_mm}${i18n.t('units.mm')}`);
    appendInfoLine(p, i18n.t('equipment.native_f'), scope.native_focal_ratio);
    appendInfoLine(p, i18n.t('equipment.effective_f'), scope.effective_focal_ratio);
    if (scope.weight_kg > 0) appendInfoLine(p, i18n.t('equipment.weight'), `${scope.weight_kg}${i18n.t('units.kg')}`);
    body.appendChild(p);

    card.appendChild(body);
    card.appendChild(isReadOnly
        ? createReadOnlyFooter(scope.owner_username)
        : createCardFooter('btn-edit-telescope', 'btn-delete-telescope', scope.id));
    col.appendChild(card);
    return col;
}

function renderTelescopesTab() {
    _renderEquipmentListTab(
        'equipment-telescopes-display', 'telescopes',
        equipmentData.telescopes, equipmentData.sharedTelescopes,
        'equipment.no_telescopes_created_yet', renderTelescopeCard,
        renderTelescopesTab
    );
}

// --- Cameras Tab (Position 4) ---

function renderCameraCard(cam, isReadOnly) {
    const col = document.createElement('div');
    col.className = 'col mb-3';
    const card = document.createElement('div');
    card.className = 'card h-100';
    const body = document.createElement('div');
    body.className = 'card-body';

    const titleRow = document.createElement('div');
    titleRow.className = 'd-flex align-items-center mb-1 gap-2 flex-wrap';
    const title = document.createElement('h5');
    title.className = 'card-title mb-0';
    title.textContent = cam.name;
    titleRow.appendChild(title);
    if (cam.is_shared && !isReadOnly) {
        const b = document.createElement('span');
        b.className = 'badge bg-info text-dark';
        b.textContent = i18n.t('equipment.shared_badge');
        titleRow.appendChild(b);
    }
    if (isReadOnly) titleRow.appendChild(createSharedBadge(cam.owner_username));
    appendHiddenBadge(titleRow, cam);
    body.appendChild(titleRow);

    if (cam.manufacturer) {
        const subtitle = document.createElement('h6');
        subtitle.className = 'card-subtitle mb-2 text-body-secondary';
        subtitle.textContent = cam.manufacturer;
        body.appendChild(subtitle);
    }

    const p = document.createElement('p');
    p.className = 'card-text';
    appendInfoLine(p, i18n.t('equipment.type'), cam.sensor_type);
    appendInfoLine(p, i18n.t('equipment.resolution'), `${cam.resolution_width_px}x${cam.resolution_height_px}`);
    appendInfoLine(p, i18n.t('equipment.pixel_size'), `${cam.pixel_size_um}${i18n.t('units.um')}`);
    appendInfoLine(p, i18n.t('equipment.diagonal'), `${cam.sensor_diagonal_mm.toFixed(2)}${i18n.t('units.mm')}`);
    if (cam.weight_kg > 0) appendInfoLine(p, i18n.t('equipment.weight'), `${cam.weight_kg}${i18n.t('units.kg')}`);
    body.appendChild(p);

    card.appendChild(body);
    card.appendChild(isReadOnly
        ? createReadOnlyFooter(cam.owner_username)
        : createCardFooter('btn-edit-camera', 'btn-delete-camera', cam.id));
    col.appendChild(card);
    return col;
}

function renderCamerasTab() {
    _renderEquipmentListTab(
        'equipment-cameras-display', 'cameras',
        equipmentData.cameras, equipmentData.sharedCameras,
        'equipment.no_cameras_created_yet', renderCameraCard,
        renderCamerasTab
    );
}

// --- Mounts Tab (Position 5) ---

function renderMountCard(mount, isReadOnly) {
    const col = document.createElement('div');
    col.className = 'col mb-3';
    const card = document.createElement('div');
    card.className = 'card h-100';
    const body = document.createElement('div');
    body.className = 'card-body';

    const titleRow = document.createElement('div');
    titleRow.className = 'd-flex align-items-center mb-1 gap-2 flex-wrap';
    const title = document.createElement('h5');
    title.className = 'card-title mb-0';
    title.textContent = mount.name;
    titleRow.appendChild(title);
    if (mount.is_shared && !isReadOnly) {
        const b = document.createElement('span');
        b.className = 'badge bg-info text-dark';
        b.textContent = i18n.t('equipment.shared_badge');
        titleRow.appendChild(b);
    }
    if (isReadOnly) titleRow.appendChild(createSharedBadge(mount.owner_username));
    appendHiddenBadge(titleRow, mount);
    body.appendChild(titleRow);

    if (mount.manufacturer) {
        const subtitle = document.createElement('h6');
        subtitle.className = 'card-subtitle mb-2 text-body-secondary';
        subtitle.textContent = mount.manufacturer;
        body.appendChild(subtitle);
    }

    const p = document.createElement('p');
    p.className = 'card-text';
    appendInfoLine(p, i18n.t('equipment.type'), mount.mount_type);
    appendInfoLine(p, i18n.t('equipment.max_payload'), `${mount.payload_capacity_kg}${i18n.t('units.kg')}`);
    appendInfoLine(p, i18n.t('equipment.guiding'), mount.guiding_supported ? i18n.t('equipment.yes') : i18n.t('equipment.no'));
    body.appendChild(p);

    card.appendChild(body);
    card.appendChild(isReadOnly
        ? createReadOnlyFooter(mount.owner_username)
        : createCardFooter('btn-edit-mount', 'btn-delete-mount', mount.id));
    col.appendChild(card);
    return col;
}

function renderMountsTab() {
    _renderEquipmentListTab(
        'equipment-mounts-display', 'mounts',
        equipmentData.mounts, equipmentData.sharedMounts,
        'equipment.no_mounts_created_yet', renderMountCard,
        renderMountsTab
    );
}

// --- Filters Tab (Position 6) ---

function renderFilterCard(filter, isReadOnly) {
    const col = document.createElement('div');
    col.className = 'col mb-3';
    const card = document.createElement('div');
    card.className = 'card h-100';
    const body = document.createElement('div');
    body.className = 'card-body';

    const titleRow = document.createElement('div');
    titleRow.className = 'd-flex align-items-center mb-1 gap-2 flex-wrap';
    const title = document.createElement('h5');
    title.className = 'card-title mb-0';
    title.textContent = filter.name;
    titleRow.appendChild(title);
    if (filter.is_shared && !isReadOnly) {
        const b = document.createElement('span');
        b.className = 'badge bg-info text-dark';
        b.textContent = i18n.t('equipment.shared_badge');
        titleRow.appendChild(b);
    }
    if (isReadOnly) titleRow.appendChild(createSharedBadge(filter.owner_username));
    appendHiddenBadge(titleRow, filter);
    body.appendChild(titleRow);

    if (filter.manufacturer) {
        const subtitle = document.createElement('h6');
        subtitle.className = 'card-subtitle mb-2 text-body-secondary';
        subtitle.textContent = filter.manufacturer;
        body.appendChild(subtitle);
    }

    const p = document.createElement('p');
    p.className = 'card-text';
    appendInfoLine(p, i18n.t('equipment.type'), filter.filter_type);
    if (filter.central_wavelength_nm) appendInfoLine(p, i18n.t('equipment.wavelength'), `${filter.central_wavelength_nm}${i18n.t('units.nm')}`);
    if (filter.bandwidth_nm) appendInfoLine(p, i18n.t('equipment.bandwidth'), `${filter.bandwidth_nm}${i18n.t('units.nm')}`);
    appendInfoLine(p, i18n.t('equipment.use'), filter.intended_use || i18n.t('equipment.general'));
    body.appendChild(p);

    card.appendChild(body);
    card.appendChild(isReadOnly
        ? createReadOnlyFooter(filter.owner_username)
        : createCardFooter('btn-edit-filter', 'btn-delete-filter', filter.id));
    col.appendChild(card);
    return col;
}

function renderFiltersTab() {
    _renderEquipmentListTab(
        'equipment-filters-display', 'filters',
        equipmentData.filters, equipmentData.sharedFilters,
        'equipment.no_filters_created_yet', renderFilterCard,
        renderFiltersTab
    );
}

// --- Accessories Tab (Position 7) ---

function renderAccessoryCard(accessory, isReadOnly) {
    const col = document.createElement('div');
    col.className = 'col mb-3';
    const card = document.createElement('div');
    card.className = 'card h-100';
    const body = document.createElement('div');
    body.className = 'card-body';

    const titleRow = document.createElement('div');
    titleRow.className = 'd-flex align-items-center mb-1 gap-2 flex-wrap';
    const title = document.createElement('h5');
    title.className = 'card-title mb-0';
    title.textContent = accessory.name;
    titleRow.appendChild(title);
    if (accessory.is_shared && !isReadOnly) {
        const b = document.createElement('span');
        b.className = 'badge bg-info text-dark';
        b.textContent = i18n.t('equipment.shared_badge');
        titleRow.appendChild(b);
    }
    if (isReadOnly) titleRow.appendChild(createSharedBadge(accessory.owner_username));
    appendHiddenBadge(titleRow, accessory);
    body.appendChild(titleRow);

    if (accessory.manufacturer) {
        const subtitle = document.createElement('h6');
        subtitle.className = 'card-subtitle mb-2 text-body-secondary';
        subtitle.textContent = accessory.manufacturer;
        body.appendChild(subtitle);
    }

    const p = document.createElement('p');
    p.className = 'card-text';
    appendInfoLine(p, i18n.t('equipment.type'), accessory.accessory_type);
    if (accessory.weight_kg > 0) appendInfoLine(p, i18n.t('equipment.weight'), `${accessory.weight_kg}${i18n.t('units.kg')}`);
    body.appendChild(p);

    card.appendChild(body);
    card.appendChild(isReadOnly
        ? createReadOnlyFooter(accessory.owner_username)
        : createCardFooter('btn-edit-accessory', 'btn-delete-accessory', accessory.id));
    col.appendChild(card);
    return col;
}

function renderAccessoriesTab() {
    _renderEquipmentListTab(
        'equipment-accessories-display', 'accessories',
        equipmentData.accessories, equipmentData.sharedAccessories,
        'equipment.no_accessories_created_yet', renderAccessoryCard,
        renderAccessoriesTab
    );
}

// ============================================
// CRUD Operations
// ============================================

// --- Telescope Operations ---

async function showTelescopeModal(id = null) {
    const telescope = id ? equipmentData.telescopes.find(t => t.id === id) : null;
    const title = telescope ? i18n.t('equipment.edit_telescope') : i18n.t('equipment.new_telescope');
    const presets = telescope ? [] : (await _loadEquipmentPresets())?.telescopes || [];

    const modalContent = `
        <form id="telescopeForm" class="form row g-3">
            ${_buildPresetPickerHtml('telescope', presets)}
            <div class="col-md-6">
                <label for="telescope-name" class="form-label">${i18n.t('equipment.form_name')} *</label>
                <input type="text" class="form-control" id="telescope-name" name="name" value="${escapeHtml(telescope?.name || '')}" required>
            </div>
            <div class="col-md-6">
                <label for="telescope-manufacturer" class="form-label">${i18n.t('equipment.form_manufacturer')} *</label>
                <input type="text" class="form-control" id="telescope-manufacturer" name="manufacturer" value="${escapeHtml(telescope?.manufacturer || '')}" required placeholder="${i18n.t('equipment.form_manufacturer_placeholder_telescope')}">
            </div>
            <div class="col-md-12">
                <label for="telescope-type" class="form-label">${i18n.t('equipment.form_type')} *</label>
                <select class="form-select" id="telescope-type" name="telescope_type" required>
                    <option value="Refractor" ${telescope?.telescope_type === 'Refractor' ? 'selected' : ''}>${i18n.t('equipment.form_refractor')}</option>
                    <option value="Apochromatic Refractor (APO)" ${telescope?.telescope_type === 'Apochromatic Refractor (APO)' ? 'selected' : ''}>${i18n.t('equipment.form_apo')}</option>
                    <option value="Reflector" ${telescope?.telescope_type === 'Reflector' ? 'selected' : ''}>${i18n.t('equipment.form_reflector')}</option>
                    <option value="Schmidt-Cassegrain (SCT)" ${telescope?.telescope_type === 'Schmidt-Cassegrain (SCT)' ? 'selected' : ''}>${i18n.t('equipment.form_sct')}</option>
                    <option value="EdgeHD" ${telescope?.telescope_type === 'EdgeHD' ? 'selected' : ''}>${i18n.t('equipment.form_edgehd')}</option>
                    <option value="Rowe Ackerman Schmidt Astrograph (RASA)" ${telescope?.telescope_type === 'Rowe Ackerman Schmidt Astrograph (RASA)' ? 'selected' : ''}>${i18n.t('equipment.form_rasa')}</option>
                    <option value="Ritchey-Chrétien (RC)" ${telescope?.telescope_type === 'Ritchey-Chrétien (RC)' ? 'selected' : ''}>${i18n.t('equipment.form_rc')}</option>
                    <option value="Newtonian" ${telescope?.telescope_type === 'Newtonian' ? 'selected' : ''}>${i18n.t('equipment.form_newtonian')}</option>
                    <option value="Maksutov-Cassegrain" ${telescope?.telescope_type === 'Maksutov-Cassegrain' ? 'selected' : ''}>${i18n.t('equipment.form_maksutov')}</option>
                    <option value="Cassegrain" ${telescope?.telescope_type === 'Cassegrain' ? 'selected' : ''}>${i18n.t('equipment.form_cassegrain')}</option>
                    <option value="Dobsonian" ${telescope?.telescope_type === 'Dobsonian' ? 'selected' : ''}>${i18n.t('equipment.form_dobsonian')}</option>
                </select>
            </div>
            <div class="col-md-6">
                <label for="telescope-aperture" class="form-label">${i18n.t('equipment.form_aperture')} *</label>
                <input type="number" class="form-control" id="telescope-aperture" name="aperture_mm" value="${telescope?.aperture_mm || ''}" required min="10" max="5000" inputmode="numeric">
            </div>
            <div class="col-md-6">
                <label for="telescope-focal-length" class="form-label">${i18n.t('equipment.form_focal_length')} *</label>
                <input type="number" class="form-control" id="telescope-focal-length" name="focal_length_mm" value="${telescope?.focal_length_mm || ''}" required min="100" max="50000" inputmode="numeric">
            </div>
            <div class="col-md-6">
                <label for="telescope-reducer-barlow-factor" class="form-label">${i18n.t('equipment.form_reducer_barlow_factor')}</label>
                <input type="number" class="form-control" id="telescope-reducer-barlow-factor" name="reducer_barlow_factor" value="${telescope?.reducer_barlow_factor || 1.0}" min="0.1" max="3" step="0.01" inputmode="decimal">
                <small class="form-text text-muted">${i18n.t('equipment.form_reducer_barlow_text')}</small>
            </div>
            <div class="col-md-6">
                <label for="telescope-weight" class="form-label">${i18n.t('equipment.form_weight')}</label>
                <input type="number" class="form-control" id="telescope-weight" name="weight_kg" value="${telescope?.weight_kg || ''}" min="0" max="100" step="0.1" inputmode="decimal">
            </div>
            <div class="col-md-12">
                <label for="telescope-notes" class="form-label">${i18n.t('equipment.form_notes')}</label>
                <textarea class="form-control" id="telescope-notes" name="notes" rows="2">${escapeHtml(telescope?.notes || '')}</textarea>
            </div>
            <div class="col-md-12">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="telescope-is-shared" name="is_shared" value="true" ${telescope?.is_shared ? 'checked' : ''}>
                    <label class="form-check-label" for="telescope-is-shared">${i18n.t('equipment.is_shared')}</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="telescope-is-disabled" name="is_disabled" value="true" ${telescope?.is_disabled ? 'checked' : ''}>
                    <label class="form-check-label" for="telescope-is-disabled">${i18n.t('equipment.is_disabled')}</label>
                </div>
            </div>
            <div class="text-end mt-3">
                <button type="submit" class="btn btn-primary">${i18n.t('equipment.form_save')}</button>
            </div>
        </form>
    `;

    if (typeof closeModal === 'function') {
        closeModal();
    }
    createModal(title, modalContent, 'lg');

    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();

    _wirePresetSelect('telescope', presets, _applyTelescopePreset);

    document.getElementById('telescopeForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveTelescope(telescope?.id || '');
    });
}

async function saveTelescope(id) {
    const form = document.getElementById('telescopeForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    data.is_shared = form.querySelector('#telescope-is-shared')?.checked ?? false;
    data.is_disabled = form.querySelector('#telescope-is-disabled')?.checked ?? false;

    try {
        const url = id ? `/api/equipment/telescopes/${id}` : '/api/equipment/telescopes';
        const method = id ? 'PUT' : 'POST';

        await fetchJSON(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('modal_lg_close'));
        if (modal) {
            document.activeElement?.blur();
            modal.hide();
        }
        await loadEquipmentType('telescopes');
        await loadEquipmentType('combinations');
        renderTelescopesTab();
        renderFOVCalculatorTab();
        renderCombinationsTab();
        showMessage('success', id ? i18n.t('equipment.telescope_updated') : i18n.t('equipment.telescope_created'));
    } catch (error) {
        console.error('Error saving telescope:', error);
        showMessage('error', i18n.t('equipment.failed_to_save_telescope'));
    }
}

// --- Camera Operations ---

async function showCameraModal(id = null) {
    const camera = id ? equipmentData.cameras.find(c => c.id === id) : null;
    const title = camera ? i18n.t('equipment.edit_camera') : i18n.t('equipment.new_camera');
    const presets = camera ? [] : (await _loadEquipmentPresets())?.cameras || [];

    const modalContent = `
        <form id="cameraForm" class="form row g-3">
            ${_buildPresetPickerHtml('camera', presets)}
            <div class="col-md-6">
                <label for="camera-name" class="form-label">${i18n.t('equipment.form_name')} *</label>
                <input type="text" class="form-control" id="camera-name" name="name" value="${escapeHtml(camera?.name || '')}" required>
            </div>
            <div class="col-md-6">
                <label for="camera-manufacturer" class="form-label">${i18n.t('equipment.form_manufacturer')} *</label>
                <input type="text" class="form-control" id="camera-manufacturer" name="manufacturer" value="${escapeHtml(camera?.manufacturer || '')}" required>
            </div>
            <div class="col-md-6">
                <label for="camera-sensor-type" class="form-label">${i18n.t('equipment.form_sensor_type')} *</label>
                <select class="form-select" id="camera-sensor-type" name="sensor_type" required>
                    <option value="CMOS Color" ${camera?.sensor_type === 'CMOS Color' ? 'selected' : ''}>${i18n.t('equipment.form_cmos_color')}</option>
                    <option value="CMOS Mono" ${camera?.sensor_type === 'CMOS Mono' ? 'selected' : ''}>${i18n.t('equipment.form_cmos_mono')}</option>
                    <option value="CCD Color" ${camera?.sensor_type === 'CCD Color' ? 'selected' : ''}>${i18n.t('equipment.form_ccd_color')}</option>
                    <option value="CCD Mono" ${camera?.sensor_type === 'CCD Mono' ? 'selected' : ''}>${i18n.t('equipment.form_ccd_mono')}</option>
                </select>
            </div>
            <div class="col-md-6">
                <label for="camera-pixel-size" class="form-label">${i18n.t('equipment.form_pixel_size')} *</label>
                <input type="number" class="form-control" id="camera-pixel-size" name="pixel_size_um" value="${camera?.pixel_size_um || ''}" required min="1" max="10" step="0.01" inputmode="decimal">
            </div>
            <div class="col-md-6">
                <label for="camera-sensor-width" class="form-label">${i18n.t('equipment.form_sensor_width')} *</label>
                <input type="number" class="form-control" id="camera-sensor-width" name="sensor_width_mm" value="${camera?.sensor_width_mm || ''}" required min="1" max="100" step="0.01" inputmode="decimal">
            </div>
            <div class="col-md-6">
                <label for="camera-sensor-height" class="form-label">${i18n.t('equipment.form_sensor_height')} *</label>
                <input type="number" class="form-control" id="camera-sensor-height" name="sensor_height_mm" value="${camera?.sensor_height_mm || ''}" required min="1" max="100" step="0.01" inputmode="decimal">
            </div>
            <div class="col-md-6">
                <label for="camera-resolution-width" class="form-label">${i18n.t('equipment.form_resolution_width')} *</label>
                <input type="number" class="form-control" id="camera-resolution-width" name="resolution_width_px" value="${camera?.resolution_width_px || ''}" required min="640" max="16000" inputmode="numeric">
            </div>
            <div class="col-md-6">
                <label for="camera-resolution-height" class="form-label">${i18n.t('equipment.form_resolution_height')} *</label>
                <input type="number" class="form-control" id="camera-resolution-height" name="resolution_height_px" value="${camera?.resolution_height_px || ''}" required min="480" max="12000" inputmode="numeric">
            </div>
            <div class="col-md-6">
                <label for="camera-cooling-supported" class="form-label">${i18n.t('equipment.form_cooling_supported')}</label>
                <select class="form-select" id="camera-cooling-supported" name="cooling_supported">
                    <option value="false" ${camera?.cooling_supported === false ? 'selected' : ''}>${i18n.t('equipment.no')}</option>
                    <option value="true" ${camera?.cooling_supported === true ? 'selected' : ''}>${i18n.t('equipment.yes')}</option>
                </select>
            </div>
            <div class="col-md-6">
                <label for="camera-min-temperature" class="form-label">${i18n.t('equipment.form_min_temperature')}</label>
                <input type="number" class="form-control" id="camera-min-temperature" name="min_temperature_c" value="${camera?.min_temperature_c || ''}" min="-50" max="0" inputmode="numeric">
            </div>
            <div class="col-md-6">
                <label for="camera-weight" class="form-label">${i18n.t('equipment.form_weight')}</label>
                <input type="number" class="form-control" id="camera-weight" name="weight_kg" value="${camera?.weight_kg || ''}" min="0" max="50" step="0.1" inputmode="decimal">
            </div>
            <div class="col-md-12">
                <label for="camera-notes" class="form-label">${i18n.t('equipment.form_notes')}</label>
                <textarea class="form-control" id="camera-notes" name="notes" rows="2">${escapeHtml(camera?.notes || '')}</textarea>
            </div>
            <div class="col-md-12">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="camera-is-shared" name="is_shared" value="true" ${camera?.is_shared ? 'checked' : ''}>
                    <label class="form-check-label" for="camera-is-shared">${i18n.t('equipment.is_shared')}</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="camera-is-disabled" name="is_disabled" value="true" ${camera?.is_disabled ? 'checked' : ''}>
                    <label class="form-check-label" for="camera-is-disabled">${i18n.t('equipment.is_disabled')}</label>
                </div>
            </div>
            <div class="text-end mt-3">
                <button type="submit" class="btn btn-primary">${i18n.t('equipment.form_save')}</button>
            </div>
        </form>
    `;

    if (typeof closeModal === 'function') {
        closeModal();
    }
    createModal(title, modalContent, 'lg');

    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();

    _wirePresetSelect('camera', presets, _applyCameraPreset);

    document.getElementById('cameraForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveCamera(camera?.id || '');
    });
}

async function saveCamera(id) {
    const form = document.getElementById('cameraForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    data.cooling_supported = data.cooling_supported === 'true';
    data.is_shared = form.querySelector('#camera-is-shared')?.checked ?? false;
    data.is_disabled = form.querySelector('#camera-is-disabled')?.checked ?? false;
    
    try {
        const url = id ? `/api/equipment/cameras/${id}` : '/api/equipment/cameras';
        const method = id ? 'PUT' : 'POST';
        
        await fetchJSON(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('modal_lg_close'));
        if (modal) {
            document.activeElement?.blur();
            modal.hide();
        }
        await loadEquipmentType('cameras');
        await loadEquipmentType('combinations');
        renderCamerasTab();
        renderFOVCalculatorTab();
        renderCombinationsTab();
        showMessage('success', id ? i18n.t('equipment.camera_updated') : i18n.t('equipment.camera_created'));
    } catch (error) {
        console.error('Error saving camera:', error);
        showMessage('error', i18n.t('equipment.failed_to_save_camera'));
    }
}

// --- Mount Operations ---

async function showMountModal(id = null) {
    const mount = id ? equipmentData.mounts.find(m => m.id === id) : null;
    const title = mount ? i18n.t('equipment.edit_mount') : i18n.t('equipment.new_mount');
    const presets = mount ? [] : (await _loadEquipmentPresets())?.mounts || [];

    const modalContent = `
        <form id="mountForm" class="form row g-3">
            ${_buildPresetPickerHtml('mount', presets)}
            <div class="col-md-6">
                <label for="mount-name" class="form-label">${i18n.t('equipment.form_name')} *</label>
                <input type="text" class="form-control" id="mount-name" name="name" value="${escapeHtml(mount?.name || '')}" required>
            </div>
            <div class="col-md-6">
                <label for="mount-manufacturer" class="form-label">${i18n.t('equipment.form_manufacturer')}</label>
                <input type="text" class="form-control" id="mount-manufacturer" name="manufacturer" value="${escapeHtml(mount?.manufacturer || '')}" placeholder="${i18n.t('equipment.form_manufacturer_placeholder_telescope')}">
            </div>
           <div class="col-md-6">
                <label for="mount-type" class="form-label">${i18n.t('equipment.form_type')} *</label>
                <select class="form-select" id="mount-type" name="mount_type" required>
                    <option value="Equatorial" ${mount?.mount_type === 'Equatorial' ? 'selected' : ''}>${i18n.t('equipment.form_equatorial')}</option>
                    <option value="Alt-Azimuth" ${mount?.mount_type === 'Alt-Azimuth' ? 'selected' : ''}>${i18n.t('equipment.form_altazimuth')}</option>
                    <option value="Dobsonian" ${mount?.mount_type === 'Dobsonian' ? 'selected' : ''}>${i18n.t('equipment.form_dobsonian')}</option>
                    <option value="Fork Mount" ${mount?.mount_type === 'Fork Mount' ? 'selected' : ''}>${i18n.t('equipment.form_fork_mount')}</option>
                </select>
            </div>
            <div class="col-md-6">
                <label for="mount-payload-capacity" class="form-label">${i18n.t('equipment.form_payload_capacity')} *</label>
                <input type="number" class="form-control" id="mount-payload-capacity" name="payload_capacity_kg" value="${mount?.payload_capacity_kg || ''}" required min="0.1" max="100" step="0.1" inputmode="decimal">
            </div>
            <div class="col-md-6">
                <label for="mount-tracking-accuracy" class="form-label">${i18n.t('equipment.form_tracking_accuracy')}</label>
                <input type="number" class="form-control" id="mount-tracking-accuracy" name="tracking_accuracy_arcsec" value="${mount?.tracking_accuracy_arcsec || ''}" min="0.1" max="10" step="0.1" inputmode="decimal">
            </div>
            <div class="col-md-6">
                <label for="mount-guiding-supported" class="form-label">${i18n.t('equipment.form_guiding_support')}</label>
                <select class="form-select" id="mount-guiding-supported" name="guiding_supported">
                    <option value="false" ${mount?.guiding_supported === false ? 'selected' : ''}>${i18n.t('equipment.no')}</option>
                    <option value="true" ${mount?.guiding_supported === true ? 'selected' : ''}>${i18n.t('equipment.yes')}</option>
                </select>
            </div>
            <div class="col-md-12">
                <label for="mount-notes" class="form-label">${i18n.t('equipment.form_notes')}</label>
                <textarea class="form-control" id="mount-notes" name="notes" rows="2">${escapeHtml(mount?.notes || '')}</textarea>
            </div>
            <div class="col-md-12">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="mount-is-shared" name="is_shared" value="true" ${mount?.is_shared ? 'checked' : ''}>
                    <label class="form-check-label" for="mount-is-shared">${i18n.t('equipment.is_shared')}</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="mount-is-disabled" name="is_disabled" value="true" ${mount?.is_disabled ? 'checked' : ''}>
                    <label class="form-check-label" for="mount-is-disabled">${i18n.t('equipment.is_disabled')}</label>
                </div>
            </div>
            <div class="text-end mt-3">
                <button type="submit" class="btn btn-primary">${i18n.t('equipment.form_save')}</button>
            </div>
        </form>
    `;

    if (typeof closeModal === 'function') {
        closeModal();
    }
    createModal(title, modalContent, 'lg');

    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();

    _wirePresetSelect('mount', presets, _applyMountPreset);

    document.getElementById('mountForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveMount(mount?.id || '');
    });
}

async function saveMount(id) {
    const form = document.getElementById('mountForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    data.guiding_supported = data.guiding_supported === 'true';
    data.is_shared = form.querySelector('#mount-is-shared')?.checked ?? false;
    data.is_disabled = form.querySelector('#mount-is-disabled')?.checked ?? false;
    
    try {
        const url = id ? `/api/equipment/mounts/${id}` : '/api/equipment/mounts';
        const method = id ? 'PUT' : 'POST';
        
        await fetchJSON(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('modal_lg_close'));
        if (modal) {
            document.activeElement?.blur();
            modal.hide();
        }
        await loadEquipmentType('mounts');
        await loadEquipmentType('combinations');
        renderMountsTab();
        renderCombinationsTab();
        showMessage('success', id ? i18n.t('equipment.mount_updated') : i18n.t('equipment.mount_created'));
    } catch (error) {
        console.error('Error saving mount:', error);
        showMessage('error', i18n.t('equipment.failed_to_save_mount'));
    }
}

// --- Filter Operations ---

async function showFilterModal(id = null) {
    const filter = id ? equipmentData.filters.find(f => f.id === id) : null;
    const title = filter ? i18n.t('equipment.edit_filter') : i18n.t('equipment.new_filter');
    const presets = filter ? [] : (await _loadEquipmentPresets())?.filters || [];

    const modalContent = `
        <form id="filterForm" class="form row g-3">
            ${_buildPresetPickerHtml('filter', presets)}
            <div class="col-md-6">
                <label for="filter-name" class="form-label">${i18n.t('equipment.form_name')} *</label>
                <input type="text" class="form-control" id="filter-name" name="name" value="${escapeHtml(filter?.name || '')}" required>
            </div>
            <div class="col-md-6">
                <label for="filter-manufacturer" class="form-label">${i18n.t('equipment.form_manufacturer')}</label>
                <input type="text" class="form-control" id="filter-manufacturer" name="manufacturer" value="${escapeHtml(filter?.manufacturer || '')}" placeholder="${i18n.t('equipment.form_manufacturer_placeholder_filter')}">
            </div>
            <div class="col-md-12">
                <label for="filter-type" class="form-label">${i18n.t('equipment.form_type')} *</label>
                <select class="form-select" id="filter-type" name="filter_type" required>
                    <option value="LRGB" ${filter?.filter_type === 'LRGB' ? 'selected' : ''}>${i18n.t('equipment.form_lrgb')}</option>
                    <option value="Narrowband" ${filter?.filter_type === 'Narrowband' ? 'selected' : ''}>${i18n.t('equipment.form_narrowband')}</option>
                    <option value="Broadband" ${filter?.filter_type === 'Broadband' ? 'selected' : ''}>${i18n.t('equipment.form_broadband')}</option>
                    <option value="Luminance" ${filter?.filter_type === 'Luminance' ? 'selected' : ''}>${i18n.t('equipment.form_luminance')}</option>
                    <option value="RGB" ${filter?.filter_type === 'RGB' ? 'selected' : ''}>${i18n.t('equipment.form_rgb')}</option>
                    <option value="H-Alpha" ${filter?.filter_type === 'H-Alpha' ? 'selected' : ''}>${i18n.t('equipment.form_h_alpha')}</option>
                    <option value="OIII" ${filter?.filter_type === 'OIII' ? 'selected' : ''}>${i18n.t('equipment.form_oiii')}</option>
                    <option value="SII" ${filter?.filter_type === 'SII' ? 'selected' : ''}>${i18n.t('equipment.form_sii')}</option>
                    <option value="UHC" ${filter?.filter_type === 'UHC' ? 'selected' : ''}>${i18n.t('equipment.form_uhc')}</option>
                    <option value="Light Pollution Reduction" ${filter?.filter_type === 'Light Pollution Reduction' ? 'selected' : ''}>${i18n.t('equipment.form_lpr')}</option>
                    <option value="Solar" ${filter?.filter_type === 'Solar' ? 'selected' : ''}>${i18n.t('equipment.form_solar')}</option>
                    <option value="Other" ${filter?.filter_type === 'Other' ? 'selected' : ''}>${i18n.t('equipment.form_other')}</option>
                </select>
            </div>
            <div class="col-md-6">
                <label for="filter-wavelength" class="form-label">${i18n.t('equipment.form_wavelength')}</label>
                <input type="number" class="form-control" id="filter-wavelength" name="central_wavelength_nm" value="${filter?.central_wavelength_nm || ''}" min="300" max="2000" inputmode="numeric">
            </div>
            <div class="col-md-6">
                <label for="filter-bandwidth" class="form-label">${i18n.t('equipment.form_bandwidth')}</label>
                <input type="number" class="form-control" id="filter-bandwidth" name="bandwidth_nm" value="${filter?.bandwidth_nm || ''}" min="1" max="1000" inputmode="numeric">
            </div>
            <div class="col-md-12">
                <label for="filter-intended-use" class="form-label">${i18n.t('equipment.form_intended_use')}</label>
                <input type="text" class="form-control" id="filter-intended-use" name="intended_use" value="${escapeHtml(filter?.intended_use || '')}" placeholder="${i18n.t('equipment.form_intended_use_placeholder')}">
            </div>
            <div class="col-md-12">
                <label for="filter-notes" class="form-label">${i18n.t('equipment.form_notes')}</label>
                <textarea class="form-control" id="filter-notes" name="notes" rows="2">${escapeHtml(filter?.notes || '')}</textarea>
            </div>
            <div class="col-md-12">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="filter-is-shared" name="is_shared" value="true" ${filter?.is_shared ? 'checked' : ''}>
                    <label class="form-check-label" for="filter-is-shared">${i18n.t('equipment.is_shared')}</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="filter-is-disabled" name="is_disabled" value="true" ${filter?.is_disabled ? 'checked' : ''}>
                    <label class="form-check-label" for="filter-is-disabled">${i18n.t('equipment.is_disabled')}</label>
                </div>
            </div>
            <div class="text-end mt-3">
                <button type="submit" class="btn btn-primary">${i18n.t('equipment.form_save')}</button>
            </div>
        </form>
    `;

    if (typeof closeModal === 'function') {
        closeModal();
    }
    createModal(title, modalContent, 'lg');

    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();

    _wirePresetSelect('filter', presets, _applyFilterPreset);

    document.getElementById('filterForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveFilter(filter?.id || '');
    });
}

async function saveFilter(id) {
    const form = document.getElementById('filterForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    data.is_shared = form.querySelector('#filter-is-shared')?.checked ?? false;
    data.is_disabled = form.querySelector('#filter-is-disabled')?.checked ?? false;
    
    try {
        const url = id ? `/api/equipment/filters/${id}` : '/api/equipment/filters';
        const method = id ? 'PUT' : 'POST';
        
        await fetchJSON(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('modal_lg_close'));
        if (modal) {
            document.activeElement?.blur();
            modal.hide();
        }
        await loadEquipmentType('filters');
        renderFiltersTab();
        showMessage('success', id ? i18n.t('equipment.filter_updated') : i18n.t('equipment.filter_created'));
    } catch (error) {
        console.error('Error saving filter:', error);
        showMessage('error', i18n.t('equipment.failed_to_save_filter'));
    }
}

// --- Accessory Operations ---

async function showAccessoryModal(id = null) {
    const accessory = id ? equipmentData.accessories.find(a => a.id === id) : null;
    const title = accessory ? i18n.t('equipment.edit_accessory') : i18n.t('equipment.new_accessory');
    const presets = accessory ? [] : (await _loadEquipmentPresets())?.accessories || [];

    const modalContent = `
        <form id="accessoryForm" class="form">
            ${_buildPresetPickerHtml('accessory', presets, { wrapInRow: true })}
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label for="accessory-name" class="form-label">${i18n.t('equipment.form_name')} *</label>
                    <input type="text" class="form-control" id="accessory-name" name="name" value="${escapeHtml(accessory?.name || '')}" required>
                </div>
                <div class="col-md-6 mb-3">
                    <label for="accessory-manufacturer" class="form-label">${i18n.t('equipment.form_manufacturer')}</label>
                    <input type="text" class="form-control" id="accessory-manufacturer" name="manufacturer" value="${escapeHtml(accessory?.manufacturer || '')}">
                </div>
            </div>
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label for="accessory-type" class="form-label">${i18n.t('equipment.form_type')} *</label>
                    <input type="text" class="form-control" id="accessory-type" name="accessory_type" value="${escapeHtml(accessory?.accessory_type || '')}" required placeholder="${i18n.t('equipment.form_type_accessory_placeholder')}">
                </div>
                <div class="col-md-6 mb-3">
                    <label for="accessory-weight" class="form-label">${i18n.t('equipment.form_weight')}</label>
                    <input type="number" class="form-control" id="accessory-weight" name="weight_kg" value="${accessory?.weight_kg || ''}" min="0" max="50" step="0.1" inputmode="decimal">
                </div>
            </div>
            <div class="mb-3">
                <label for="accessory-notes" class="form-label">${i18n.t('equipment.form_notes')}</label>
                <textarea class="form-control" id="accessory-notes" name="notes" rows="2">${escapeHtml(accessory?.notes || '')}</textarea>
            </div>
            <div class="mb-3">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="accessory-is-shared" name="is_shared" value="true" ${accessory?.is_shared ? 'checked' : ''}>
                    <label class="form-check-label" for="accessory-is-shared">${i18n.t('equipment.is_shared')}</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="accessory-is-disabled" name="is_disabled" value="true" ${accessory?.is_disabled ? 'checked' : ''}>
                    <label class="form-check-label" for="accessory-is-disabled">${i18n.t('equipment.is_disabled')}</label>
                </div>
            </div>
            <div class="text-end mt-3">
                <button type="submit" class="btn btn-primary">${i18n.t('equipment.form_save')}</button>
            </div>
        </form>
    `;

    if (typeof closeModal === 'function') {
        closeModal();
    }
    createModal(title, modalContent, 'lg');

    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();

    _wirePresetSelect('accessory', presets, _applyAccessoryPreset);

    document.getElementById('accessoryForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveAccessory(accessory?.id || '');
    });
}

async function saveAccessory(id) {
    const form = document.getElementById('accessoryForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    data.is_shared = form.querySelector('#accessory-is-shared')?.checked ?? false;
    data.is_disabled = form.querySelector('#accessory-is-disabled')?.checked ?? false;

    try {
        const url = id ? `/api/equipment/accessories/${id}` : '/api/equipment/accessories';
        const method = id ? 'PUT' : 'POST';
        
        await fetchJSON(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('modal_lg_close'));
        if (modal) {
            document.activeElement?.blur();
            modal.hide();
        }
        await loadEquipmentType('accessories');
        await loadEquipmentType('combinations');
        renderAccessoriesTab();
        renderCombinationsTab();
        showMessage('success', id ? i18n.t('equipment.accessory_updated') : i18n.t('equipment.accessory_created'));
    } catch (error) {
        console.error('Error saving accessory:', error);
        showMessage('error', i18n.t('equipment.failed_to_save_accessory'));
    }
}

// --- Combination Operations ---

async function showCombinationModal(id = null) {
    const combination = id ? equipmentData.combinations.find(c => c.id === id) : null;
    const title = combination ? i18n.t('equipment.edit_combination') : i18n.t('equipment.new_combination');

    // Disabled equipment is excluded from these pickers unless it's already selected on the
    // combination being edited - it must stay visible there so an existing combination never
    // silently drops a component from the editor UI.
    const telescopes = [...equipmentData.telescopes, ...equipmentData.sharedTelescopes]
        .filter(t => !t.is_disabled || t.id === combination?.telescope_id);
    const cameras = [...equipmentData.cameras, ...equipmentData.sharedCameras]
        .filter(c => !c.is_disabled || c.id === combination?.camera_id || c.id === combination?.guide_camera_id);
    const mounts = [...equipmentData.mounts, ...equipmentData.sharedMounts]
        .filter(m => !m.is_disabled || m.id === combination?.mount_id);
    const filters = [...equipmentData.filters, ...equipmentData.sharedFilters]
        .filter(f => !f.is_disabled || (combination?.filter_ids || []).includes(f.id));
    const accessories = [...equipmentData.accessories, ...equipmentData.sharedAccessories]
        .filter(a => !a.is_disabled || (combination?.accessory_ids || []).includes(a.id));

    const sharedSuffix = (item) => {
        let suffix = '';
        if (item.owner_username) {
            suffix += ` ${i18n.t('equipment.shared_fov_suffix', { username: item.owner_username })}`;
        } else if (item.is_shared) {
            suffix += ` (${i18n.t('equipment.shared_badge').toLowerCase()})`;
        }
        if (item.is_disabled) {
            suffix += ` (${i18n.t('equipment.hidden_badge').toLowerCase()})`;
        }
        return suffix;
    };

    const modalContent = `
        <form id="combinationForm" class="form">
            <div class="mb-3">
                <label class="form-label">Name *</label>
                <input type="text" class="form-control" name="name" value="${escapeHtml(combination?.name || '')}" required>
            </div>
            <div class="mb-3">
                <label for="combination-telescope" class="form-label">${i18n.t('equipment.form_telescope')}</label>
                <select class="form-select" id="combination-telescope" name="telescope_id">
                    <option value="">${i18n.t('equipment.none')}</option>
                    ${telescopes.map(t => `<option value="${t.id}" ${combination?.telescope_id === t.id ? 'selected' : ''}>${escapeHtml(t.name)}${escapeHtml(sharedSuffix(t))}</option>`).join('')}
                </select>
            </div>
            <div class="mb-3">
                <label for="combination-camera" class="form-label">${i18n.t('equipment.form_camera')}</label>
                <select class="form-select" id="combination-camera" name="camera_id">
                    <option value="">${i18n.t('equipment.none')}</option>
                    ${cameras.map(c => `<option value="${c.id}" ${combination?.camera_id === c.id ? 'selected' : ''}>${escapeHtml(c.name)}${escapeHtml(sharedSuffix(c))}</option>`).join('')}
                </select>
            </div>
            <div class="row mb-3">
                <div class="col-md-6">
                    <label for="combination-lens-focal-length" class="form-label">${i18n.t('equipment.form_lens_focal_length')}</label>
                    <input type="number" class="form-control" id="combination-lens-focal-length" name="lens_focal_length_mm" value="${combination?.lens_focal_length_mm ?? ''}" min="1" max="2000" step="0.1" inputmode="decimal">
                </div>
                <div class="col-md-6">
                    <label for="combination-lens-focal-ratio" class="form-label">${i18n.t('equipment.form_lens_focal_ratio')}</label>
                    <input type="number" class="form-control" id="combination-lens-focal-ratio" name="lens_focal_ratio" value="${combination?.lens_focal_ratio ?? ''}" min="0.5" max="32" step="0.1" inputmode="decimal">
                </div>
                <small class="form-text text-muted">${i18n.t('equipment.form_lens_focal_help')}</small>
            </div>
            <div class="mb-3">
                <label for="combination-guide-camera" class="form-label">${i18n.t('equipment.form_guide_camera')}</label>
                <select class="form-select" id="combination-guide-camera" name="guide_camera_id">
                    <option value="">${i18n.t('equipment.none')}</option>
                    ${cameras.map(c => `<option value="${c.id}" ${combination?.guide_camera_id === c.id ? 'selected' : ''}>${escapeHtml(c.name)}${escapeHtml(sharedSuffix(c))}</option>`).join('')}
                </select>
            </div>
            <div class="mb-3">
                <label for="combination-mount" class="form-label">${i18n.t('equipment.form_mount')}</label>
                <select class="form-select" id="combination-mount" name="mount_id">
                    <option value="">${i18n.t('equipment.none')}</option>
                    ${mounts.map(m => `<option value="${m.id}" ${combination?.mount_id === m.id ? 'selected' : ''}>${escapeHtml(m.name)}${escapeHtml(sharedSuffix(m))}</option>`).join('')}
                </select>
            </div>
            <div class="mb-3">
                <label for="combination-filters" class="form-label">${i18n.t('equipment.form_filters')}</label>
                <div class="checkbox-popup-box overflow-y-auto rounded" id="combination-filters">
                    ${filters.length === 0 ? `<div class="alert alert-info fw-light">${i18n.t('equipment.form_no_filters_created')}</div>` : ''}
                    ${filters.map(f => `
                        <div class="form-check">
                            <input class="form-check-input filter-checkbox" type="checkbox" value="${f.id}"
                                ${combination?.filter_ids?.includes(f.id) ? 'checked' : ''}>
                            <label class="form-check-label">${escapeHtml(f.name)}${escapeHtml(sharedSuffix(f))}</label>
                        </div>
                    `).join('')}
                </div>
            </div>
            <div class="mb-3">
                <label for="combination-accessories" class="form-label">${i18n.t('equipment.form_accessories')}</label>
                <div class="checkbox-popup-box overflow-y-auto rounded" id="combination-accessories">
                    ${accessories.length === 0 ? `<div class="alert alert-info fw-light">${i18n.t('equipment.form_no_accessories_created')}</div>` : ''}
                    ${accessories.map(a => `
                        <div class="form-check">
                            <input class="form-check-input accessory-checkbox" type="checkbox" value="${a.id}"
                                ${combination?.accessory_ids?.includes(a.id) ? 'checked' : ''}>
                            <label class="form-check-label">${escapeHtml(a.name)}${escapeHtml(sharedSuffix(a))}</label>
                        </div>
                    `).join('')}
                </div>
            </div>
            <div class="mb-3">
                <label for="combination-notes" class="form-label">${i18n.t('equipment.form_notes')}</label>
                <textarea class="form-control" id="combination-notes" name="notes" rows="2">${escapeHtml(combination?.notes || '')}</textarea>
            </div>
            <div class="mb-3">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="combination-is-disabled" name="is_disabled" value="true" ${combination?.is_disabled ? 'checked' : ''}>
                    <label class="form-check-label" for="combination-is-disabled">${i18n.t('equipment.is_disabled')}</label>
                </div>
            </div>
            <div class="text-end mt-3">
                <button type="submit" class="btn btn-primary">${i18n.t('equipment.form_save')}</button>
            </div>
        </form>
    `;

    if (typeof closeModal === 'function') {
        closeModal();
    }
    createModal(title, modalContent, 'lg');

    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();

    document.getElementById('combinationForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveCombination(combination?.id || '');
    });
}

async function saveCombination(id) {
    const form = document.getElementById('combinationForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    data.is_disabled = form.querySelector('#combination-is-disabled')?.checked ?? false;

    // Collect filter checkboxes
    const filterCheckboxes = form.querySelectorAll('.filter-checkbox:checked');
    data.filter_ids = Array.from(filterCheckboxes).map(cb => cb.value);

    // Collect accessory checkboxes
    const accessoryCheckboxes = form.querySelectorAll('.accessory-checkbox:checked');
    data.accessory_ids = Array.from(accessoryCheckboxes).map(cb => cb.value);

    try {
        const url = id ? `/api/equipment/combinations/${id}` : '/api/equipment/combinations';
        const method = id ? 'PUT' : 'POST';
        
        await fetchJSON(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('modal_lg_close'));
        if (modal) {
            document.activeElement?.blur();
            modal.hide();
        }
        await loadEquipmentType('combinations');
        renderCombinationsTab();
        showMessage('success', id ? i18n.t('equipment.combination_updated') : i18n.t('equipment.combination_created'));
    } catch (error) {
        console.error('Error saving combination:', error);
        showMessage('error', i18n.t('equipment.failed_to_save_combination'));
    }
}

// ============================================
// Analysis
// ============================================

// ============================================
// Delete Equipment
// ============================================

async function deleteEquipment(type, id) {
    if (!confirm(i18n.t('equipment.confirm_delete_item'))) return;

    try {
        const typeMap = {
            'telescopes': 'telescopes',
            'cameras': 'cameras',
            'mounts': 'mounts',
            'filters': 'filters',
            'accessories': 'accessories',
            'combinations': 'combinations'
        };

        // Raw fetch (not fetchJSON) so a blocked-delete 409's body is readable - fetchJSON
        // throws before parsing the response on any non-2xx status.
        const response = await fetch(`${API_BASE}/api/equipment/${typeMap[type]}/${id}`, { method: 'DELETE' });
        const result = await response.json().catch(() => ({}));

        if (!response.ok) {
            if (response.status === 409 && result.error === 'in_use_by_combination') {
                showMessage('error', i18n.t('equipment.delete_blocked_by_combination', {
                    combinations: (result.combinations || []).join(', ')
                }));
            } else if (response.status === 409 && result.error === 'in_use_by_picture') {
                showMessage('error', i18n.t('equipment.delete_blocked_by_picture'));
            } else if (response.status === 409 && result.error === 'in_use_by_plan') {
                showMessage('error', i18n.t('equipment.delete_blocked_by_plan'));
            } else {
                showMessage('error', i18n.t('equipment.failed_to_delete_item'));
            }
            return;
        }

        await loadEquipmentType(type);
        
        // Reload combinations if deleting equipment that affects payload or names
        if (['telescopes', 'cameras', 'mounts', 'accessories'].includes(type)) {
            await loadEquipmentType('combinations');
        }
        
        if (type === 'telescopes') {
            renderTelescopesTab();
            renderFOVCalculatorTab();
            renderCombinationsTab();
        } else if (type === 'cameras') {
            renderCamerasTab();
            renderFOVCalculatorTab();
            renderCombinationsTab();
        } else if (type === 'mounts') {
            renderMountsTab();
            renderCombinationsTab();
        } else if (type === 'filters') {
            renderFiltersTab();
        } else if (type === 'accessories') {
            renderAccessoriesTab();
            renderCombinationsTab();
        } else if (type === 'combinations') {
            renderCombinationsTab();
        }
        
        showMessage('success', i18n.t('equipment.item_deleted'));
    } catch (error) {
        console.error('Error deleting equipment:', error);
        showMessage('error', i18n.t('equipment.failed_to_delete_item'));
    }
}

// ── Exposure Calculator ────────────────────────────────────────────────────────

// Bortle class → SQM (mag/arcsec², V-band)
const BORTLE_SQM = {
    1: 22.0, 2: 21.5, 3: 21.2, 4: 20.8, 5: 20.3,
    6: 19.5, 7: 18.8, 8: 18.3, 9: 17.5
};

// Reference photon flux for 0-mag Vega in V-band at aperture (photons/m²/s/arcsec²)
// Derived from Vega V-band flux ~9×10^9 photons/m²/s integrated, referenced to 1 arcsec².
const VEGA_PHOTONS_M2_S_ARCSEC2 = 9e9;

function _computeExposure({ aperture_mm, focal_length_mm, pixel_size_um, read_noise_e, qe, bortle, total_hours }) {
    const sqm      = BORTLE_SQM[bortle] ?? 20.3;
    const D_m      = aperture_mm / 1000;
    const area_m2  = Math.PI / 4 * D_m * D_m;

    // Plate scale (arcsec/px)
    const plate_scale = 206.265 * pixel_size_um / focal_length_mm;

    // Sky background photon rate (e/px/s) using SQM-referenced Vega flux
    const sky_flux = VEGA_PHOTONS_M2_S_ARCSEC2 * Math.pow(10, -sqm / 2.5);
    const B_sky    = sky_flux * qe * area_m2 * plate_scale * plate_scale;

    // Optimal sub-exposure: sky contributes 5× more noise variance than read noise
    // B × t = 5 × RN²  →  t = 5 × RN² / B
    const t_sub_s = 5 * read_noise_e * read_noise_e / B_sky;

    const total_s = total_hours * 3600;
    const n_subs  = Math.max(1, Math.round(total_s / t_sub_s));
    const actual_total_s = n_subs * t_sub_s;

    return { plate_scale, sqm, B_sky, t_sub_s, n_subs, actual_total_s };
}

function _fmtDuration(seconds) {
    if (seconds >= 3600) {
        const h = Math.floor(seconds / 3600);
        const m = Math.round((seconds % 3600) / 60);
        return m > 0 ? `${h}h ${m}min` : `${h}h`;
    }
    if (seconds >= 60) {
        const m = Math.floor(seconds / 60);
        const s = Math.round(seconds % 60);
        return s > 0 ? `${m}min ${s}s` : `${m}min`;
    }
    return `${Math.round(seconds)}s`;
}

function _expRow(label, value, note) {
    const tr = document.createElement('tr');
    const td1 = document.createElement('td');
    td1.className = 'text-muted small';
    td1.textContent = label;
    const td2 = document.createElement('td');
    td2.className = 'fw-semibold';
    td2.textContent = value;
    tr.appendChild(td1);
    tr.appendChild(td2);
    if (note) {
        const td3 = document.createElement('td');
        td3.className = 'text-muted small';
        td3.textContent = note;
        tr.appendChild(td3);
    }
    return tr;
}

function renderExposureCalcTab() {
    const container = document.getElementById('equipment-exposure-calc-display');
    if (!container) return;

    const telescopes = [...equipmentData.telescopes, ...equipmentData.sharedTelescopes];
    const cameras    = [...equipmentData.cameras,    ...equipmentData.sharedCameras];

    DOMUtils.clear(container);

    if (telescopes.length === 0 || cameras.length === 0) {
        const alert = document.createElement('div');
        alert.className = 'alert alert-info';
        alert.textContent = i18n.t('equipment.exposure_calc_no_equipment');
        container.appendChild(alert);
        return;
    }

    const card = document.createElement('div');
    card.className = 'card';
    const body = document.createElement('div');
    body.className = 'card-body';

    // ── Inputs ──────────────────────────────────────────────────────────────
    const mkLabel = (forId, key) => {
        const l = document.createElement('label');
        l.className = 'form-label';
        l.setAttribute('for', forId);
        l.textContent = i18n.t(key);
        return l;
    };
    const mkHelp = (key) => {
        const d = document.createElement('div');
        d.className = 'form-text';
        d.textContent = i18n.t(key);
        return d;
    };

    // Row 1: telescope + camera
    const row1 = document.createElement('div');
    row1.className = 'row g-3 mb-3';

    const tCol = document.createElement('div');
    tCol.className = 'col-md-6';
    tCol.appendChild(mkLabel('exc-telescope', 'equipment.telescope'));
    const tSel = document.createElement('select');
    tSel.id = 'exc-telescope';
    tSel.className = 'form-select';
    const tDef = new Option(i18n.t('equipment.select_telescope'), '');
    tSel.appendChild(tDef);
    telescopes.forEach(t => {
        const suffix = t.owner_username ? ` (${t.owner_username})` : '';
        tSel.appendChild(new Option(`${t.name} - f/${t.effective_focal_ratio}  ${t.effective_focal_length}mm${suffix}`, t.id));
    });
    tCol.appendChild(tSel);
    tCol.appendChild(mkHelp('equipment.exposure_calc_help_telescope'));

    const cCol = document.createElement('div');
    cCol.className = 'col-md-6';
    cCol.appendChild(mkLabel('exc-camera', 'equipment.camera'));
    const cSel = document.createElement('select');
    cSel.id = 'exc-camera';
    cSel.className = 'form-select';
    const cDef = new Option(i18n.t('equipment.select_camera'), '');
    cSel.appendChild(cDef);
    cameras.forEach(c => {
        const suffix = c.owner_username ? ` (${c.owner_username})` : '';
        cSel.appendChild(new Option(`${c.name} - ${c.pixel_size_um}µm${suffix}`, c.id));
    });
    cCol.appendChild(cSel);
    cCol.appendChild(mkHelp('equipment.exposure_calc_help_camera'));

    row1.appendChild(tCol);
    row1.appendChild(cCol);

    // Row 2: read noise + QE
    const row2 = document.createElement('div');
    row2.className = 'row g-3 mb-3';

    const rnCol = document.createElement('div');
    rnCol.className = 'col-md-4';
    rnCol.appendChild(mkLabel('exc-read-noise', 'equipment.exposure_calc_read_noise'));
    const rnInput = document.createElement('input');
    rnInput.type = 'number'; rnInput.id = 'exc-read-noise';
    rnInput.className = 'form-control'; rnInput.min = '0.5'; rnInput.max = '30'; rnInput.step = '0.1';
    rnInput.value = '4'; rnInput.inputMode = 'decimal';
    rnCol.appendChild(rnInput);
    rnCol.appendChild(mkHelp('equipment.exposure_calc_help_read_noise'));

    const qeCol = document.createElement('div');
    qeCol.className = 'col-md-4';
    qeCol.appendChild(mkLabel('exc-qe', 'equipment.exposure_calc_qe'));
    const qeInput = document.createElement('input');
    qeInput.type = 'number'; qeInput.id = 'exc-qe';
    qeInput.className = 'form-control'; qeInput.min = '10'; qeInput.max = '100'; qeInput.step = '1';
    qeInput.value = '65'; qeInput.inputMode = 'decimal';
    qeCol.appendChild(qeInput);
    qeCol.appendChild(mkHelp('equipment.exposure_calc_help_qe'));

    const hoursCol = document.createElement('div');
    hoursCol.className = 'col-md-4';
    hoursCol.appendChild(mkLabel('exc-hours', 'equipment.exposure_calc_total_hours'));
    const hoursInput = document.createElement('input');
    hoursInput.type = 'number'; hoursInput.id = 'exc-hours';
    hoursInput.className = 'form-control'; hoursInput.min = '0.25'; hoursInput.max = '20'; hoursInput.step = '0.25';
    hoursInput.value = '3'; hoursInput.inputMode = 'decimal';
    hoursCol.appendChild(hoursInput);
    hoursCol.appendChild(mkHelp('equipment.exposure_calc_help_hours'));

    row2.appendChild(rnCol);
    row2.appendChild(qeCol);
    row2.appendChild(hoursCol);

    // Row 3: Bortle + calculate button
    const row3 = document.createElement('div');
    row3.className = 'row g-3 mb-3';

    const borCol = document.createElement('div');
    borCol.className = 'col-md-6';
    borCol.appendChild(mkLabel('exc-bortle', 'equipment.exposure_calc_bortle'));
    const borSel = document.createElement('select');
    borSel.id = 'exc-bortle';
    borSel.className = 'form-select';
    [
        [1, 'Bortle 1 - 22.0 mag/arcsec²'], [2, 'Bortle 2 - 21.5'],
        [3, 'Bortle 3 - 21.2'], [4, 'Bortle 4 - 20.8'],
        [5, 'Bortle 5 - 20.3'], [6, 'Bortle 6 - 19.5'],
        [7, 'Bortle 7 - 18.8'], [8, 'Bortle 8 - 18.3'],
        [9, 'Bortle 9 - 17.5'],
    ].forEach(([v, lbl]) => borSel.appendChild(new Option(lbl, v)));
    borSel.value = '5';
    borCol.appendChild(borSel);
    borCol.appendChild(mkHelp('equipment.exposure_calc_help_bortle'));

    const btnCol = document.createElement('div');
    btnCol.className = 'col-md-6 d-flex align-items-end';
    const calcBtn = document.createElement('button');
    calcBtn.className = 'btn btn-success w-100';
    DOMUtils.append(calcBtn, DOMUtils.createIcon('bi bi-calculator icon-inline'), i18n.t('equipment.exposure_calc_calculate'));
    btnCol.appendChild(calcBtn);

    row3.appendChild(borCol);
    row3.appendChild(btnCol);

    // Results placeholder
    const results = document.createElement('div');
    results.id = 'exc-results';

    body.appendChild(row1);
    body.appendChild(row2);
    body.appendChild(row3);
    body.appendChild(results);
    card.appendChild(body);
    container.appendChild(card);

    // Auto-fill read noise when camera changes
    cSel.addEventListener('change', () => {
        const cam = [...equipmentData.cameras, ...equipmentData.sharedCameras].find(c => c.id === cSel.value);
        if (cam?.read_noise_e != null) rnInput.value = cam.read_noise_e;
    });

    calcBtn.addEventListener('click', () => {
        const tel = [...equipmentData.telescopes, ...equipmentData.sharedTelescopes].find(t => t.id === tSel.value);
        const cam = [...equipmentData.cameras,    ...equipmentData.sharedCameras].find(c => c.id === cSel.value);
        if (!tel || !cam) { showMessage('warning', i18n.t('equipment.please_select_telescope_camera')); return; }

        const read_noise_e = parseFloat(rnInput.value);
        const qe           = parseFloat(qeInput.value) / 100;
        const total_hours  = parseFloat(hoursInput.value);
        const bortle       = parseInt(borSel.value);

        if (!Number.isFinite(read_noise_e) || read_noise_e <= 0) { showMessage('warning', i18n.t('equipment.exposure_calc_invalid_rn')); return; }

        const r = _computeExposure({
            aperture_mm:     tel.aperture_mm,
            focal_length_mm: tel.effective_focal_length || tel.focal_length_mm,
            pixel_size_um:   cam.pixel_size_um,
            read_noise_e,
            qe,
            bortle,
            total_hours,
        });

        DOMUtils.clear(results);
        const hr = document.createElement('hr');
        results.appendChild(hr);

        const h6 = document.createElement('h6');
        h6.className = 'fw-bold mb-3';
        h6.textContent = i18n.t('equipment.exposure_calc_results');
        results.appendChild(h6);

        const table = document.createElement('table');
        table.className = 'table table-sm mb-3';
        const tbody = document.createElement('tbody');

        tbody.appendChild(_expRow(i18n.t('equipment.exposure_calc_plate_scale'), `${r.plate_scale.toFixed(2)} "/px`));
        tbody.appendChild(_expRow(i18n.t('equipment.exposure_calc_sky_bg'), `${r.B_sky.toFixed(3)} e⁻/px/s`, `SQM ${r.sqm.toFixed(1)}`));
        tbody.appendChild(_expRow(i18n.t('equipment.exposure_calc_sub_exposure'), _fmtDuration(r.t_sub_s), i18n.t('equipment.exposure_calc_sub_note')));
        tbody.appendChild(_expRow(i18n.t('equipment.exposure_calc_n_subs'), `${r.n_subs}`, `≈ ${_fmtDuration(r.actual_total_s)} ${i18n.t('equipment.exposure_calc_total')}`));

        table.appendChild(tbody);
        results.appendChild(table);

        const note = document.createElement('p');
        note.className = 'text-muted small';
        note.textContent = i18n.t('equipment.exposure_calc_method_note');
        results.appendChild(note);
    });
}

// ─────────────────────────────────────────────────────────────────────────────

// Initialize when module loads
document.addEventListener('DOMContentLoaded', initializeEquipment);
