// Astrodex functionality
// Pokédex-style collection system for astrophotography objects

let astrodexData = {
    items: [],
    stats: {},
    privateMode: true,
    currentUserId: null
};

// Standard ISO full-stop series (ISO 12232) - always offered as a baseline
// so the ISO field has useful suggestions even before the user has logged
// any photos of their own.
const STANDARD_ISO_VALUES = ['100', '200', '400', '800', '1600', '3200', '6400', '12800'];

let currentAstrodexItem = null;
let astrodexFilters = {
    search: '',
    type: 'all',
    hasPhotos: 'all',
    sortBy: 'name',
    sortOrder: 'asc'
};

// Fixed object-type list shared by Astrodex and the Observation Log. [value, i18n key].
const OBJECT_TYPE_OPTIONS = [
    ['Galaxy', 'type_galaxy'],
    ['Nebula', 'type_nebula'],
    ['Planetary Nebula', 'type_planetary_nebula'],
    ['Star Cluster', 'type_star_cluster'],
    ['Open Cluster', 'type_open_cluster'],
    ['Globular Cluster', 'type_globular_cluster'],
    ['Planet', 'type_planet'],
    ['Moon', 'type_moon'],
    ['Sun', 'type_sun'],
    ['Comet', 'type_comet'],
    ['Milky Way', 'type_milky_way'],
    ['Nightscape', 'type_nightscape'],
    ['Star Trail', 'type_star_trail'],
    ['Other', 'type_other'],
];

function getObjectTypeOptionsHtml(selectedType = '') {
    return OBJECT_TYPE_OPTIONS
        .map(([value, key]) => `<option value="${value}" ${selectedType === value ? 'selected' : ''}>${tSkyTonightCompat(key)}</option>`)
        .join('');
}

/** Append the fixed object-type <option> nodes to a <select>, using DOM APIs
 * (no HTML sink). Mirrors getObjectTypeOptionsHtml() for callers bound by the
 * frontend XSS rules. */
function populateObjectTypeSelect(selectEl, selectedType = '') {
    OBJECT_TYPE_OPTIONS.forEach(([value, key]) => {
        const opt = document.createElement('option');
        opt.value = value;
        opt.textContent = tSkyTonightCompat(key);
        if (selectedType === value) opt.selected = true;
        selectEl.appendChild(opt);
    });
}

/** Map a free-text catalogue object_type onto one of getObjectTypeOptionsHtml()'s fixed
 * options. Shared by Astrodex's and the Observation Log's "add item" catalogue search. */
function mapCatalogueObjectType(rawType) {
    if (!rawType) return '';
    const t = rawType.toLowerCase();
    if (t.includes('open cluster')) return 'Open Cluster';
    if (t.includes('globular')) return 'Globular Cluster';
    if (t.includes('galaxy')) return 'Galaxy';
    if (t.includes('planetary nebula')) return 'Planetary Nebula';
    if (t.includes('nebula') || t.includes('supernova') || t.includes('remnant')) return 'Nebula';
    if (t.includes('ionized region') || t.includes('molecular cloud')) return 'Nebula';
    if (t.includes('star cluster') || t.includes('cluster')) return 'Star Cluster';
    if (t.includes('planet')) return 'Planet';
    if (t.includes('moon')) return 'Moon';
    if (t.includes('comet')) return 'Comet';
    return 'Other';
}

// Catalogue priority used to order/dedupe the object-name picker below - mirrors
// backend's SKYTONIGHT_PREFERRED_NAME_ORDER (backend/utils/constants.py) so the
// default selection matches what the "preferred_name" field already resolves to.
const ASTRODEX_CATALOGUE_NAME_PRIORITY = [
    'CommonName', 'Messier', 'OpenNGC', 'OpenIC', 'Caldwell', 'LBN',
    'Herschel400', 'Pensack500', 'GaryImm', 'Arp', 'Sharpless', 'Barnard', 'vdB',
    'AbellPNe', 'AbellClusters',
];

/** Turn a catalogue-lookup response's {catalogue: name} map into a deduplicated,
 * priority-ordered list of {value, label, catalogue} choices for the object-name
 * picker in the Add-to-Astrodex modal. Names shared by several catalogues (e.g. an
 * IC number reused by OpenIC/OpenNGC/GaryImm) collapse into a single choice, keeping
 * the highest-priority catalogue as its label. */
function buildAstrodexNameChoices(catalogueNames) {
    const entries = Object.entries(catalogueNames || {}).filter(([, name]) => !!name);
    entries.sort(([catA], [catB]) => {
        const rankA = ASTRODEX_CATALOGUE_NAME_PRIORITY.indexOf(catA);
        const rankB = ASTRODEX_CATALOGUE_NAME_PRIORITY.indexOf(catB);
        return (rankA === -1 ? ASTRODEX_CATALOGUE_NAME_PRIORITY.length : rankA)
            - (rankB === -1 ? ASTRODEX_CATALOGUE_NAME_PRIORITY.length : rankB);
    });

    const choices = [];
    const seenValues = new Set();
    for (const [catalogue, name] of entries) {
        if (seenValues.has(name)) continue;
        seenValues.add(name);
        const catalogueLabel = catalogue === 'CommonName' ? i18n.t('astrodex.catalogue_label_commonname') : catalogue;
        choices.push({ value: name, label: `${name} (${catalogueLabel})`, catalogue });
    }
    return choices;
}

/** Render the "Nom de l'objet" field either as a free-text input (default, and for
 * manual entry) or - once a catalogue search resolves several alternate names - as a
 * <select> so the user can pick which designation to keep, instead of always getting
 * whichever one choose_preferred_catalogue_name() favors server-side. Keeps the same
 * #item-name id/`.value` contract either way so the rest of the form is unaffected. */
function setAstrodexNameField(choices, selectedValue) {
    const wrapper = document.getElementById('item-name-field');
    if (!wrapper) return;

    if (!choices || choices.length < 2) {
        DOMUtils.clear(wrapper);
        const input = document.createElement('input');
        input.type = 'text';
        input.id = 'item-name';
        input.className = 'form-control';
        input.required = true;
        input.autocomplete = 'off';
        input.value = selectedValue || '';
        wrapper.appendChild(input);
        return;
    }

    DOMUtils.clear(wrapper);
    const select = document.createElement('select');
    select.id = 'item-name';
    select.className = 'form-select';
    select.required = true;

    for (const choice of choices) {
        const option = document.createElement('option');
        option.value = choice.value;
        option.dataset.catalogue = choice.catalogue;
        option.textContent = choice.label;
        if (choice.value === selectedValue) option.selected = true;
        select.appendChild(option);
    }

    const customOption = document.createElement('option');
    customOption.value = '__custom__';
    customOption.textContent = i18n.t('astrodex.form_object_name_custom');
    select.appendChild(customOption);

    select.addEventListener('change', () => {
        const catInput = document.getElementById('item-catalogue');
        if (select.value === '__custom__') {
            setAstrodexNameField([], '');
            return;
        }
        if (catInput) catInput.value = select.selectedOptions[0]?.dataset.catalogue || '';
    });

    wrapper.appendChild(select);
}

/** Bidirectional frames <-> integration-minutes calculator pivoting on sub-exposure
 * seconds (any two of the three determine the third). Shared by the Observation Log's
 * Add Target form and Astrodex's own Add/Edit Photo forms - whichever of
 * frames/integration the user hasn't typed by hand gets derived from the other two. */
function recomputeCaptureTriad(framesId, subExposureSecondsId, integrationMinutesId) {
    const framesInput = document.getElementById(framesId);
    const subExposureInput = document.getElementById(subExposureSecondsId);
    const integrationInput = document.getElementById(integrationMinutesId);
    if (!framesInput || !subExposureInput || !integrationInput) return;

    const subExposure = Number(subExposureInput.value);
    if (!subExposureInput.value || !Number.isFinite(subExposure) || subExposure <= 0) return;

    const framesValue = Number(framesInput.value);
    const hasFrames = framesInput.value !== '' && Number.isFinite(framesValue);
    const integrationValue = Number(integrationInput.value);
    const hasIntegration = integrationInput.value !== '' && Number.isFinite(integrationValue);

    if (integrationInput.dataset.userEdited !== 'true' && hasFrames) {
        integrationInput.value = String(Math.round((framesValue * subExposure / 60) * 100) / 100);
    } else if (framesInput.dataset.userEdited !== 'true' && hasIntegration) {
        framesInput.value = String(Math.round((integrationValue * 60) / subExposure));
    }
}

/** Wire up recomputeCaptureTriad() on a `${prefix}-frames`/`${prefix}-exposition`/
 * `${prefix}-integration` input trio (Astrodex's Add/Edit Photo forms). */
function _wireCaptureTriadInputs(prefix) {
    const framesInput = document.getElementById(`${prefix}-frames`);
    const expositionInput = document.getElementById(`${prefix}-exposition`);
    const integrationInput = document.getElementById(`${prefix}-integration`);
    if (!framesInput || !expositionInput || !integrationInput) return;

    const recompute = () => recomputeCaptureTriad(`${prefix}-frames`, `${prefix}-exposition`, `${prefix}-integration`);
    framesInput.addEventListener('input', () => { framesInput.dataset.userEdited = 'true'; recompute(); });
    expositionInput.addEventListener('input', recompute);
    integrationInput.addEventListener('input', () => { integrationInput.dataset.userEdited = 'true'; recompute(); });
}

/** A picture's exposition_time is a plain integer number of seconds (v1.3+). Older
 * pictures may still carry a pre-v1.3 free-text value (e.g. "1h (10sec)") - shown
 * as-is, since it can't be reinterpreted as seconds without the uploader's input. */
function formatPictureExpositionTime(value) {
    if (value === null || value === undefined || value === '') return '';
    if (typeof value === 'number' || /^\d+$/.test(String(value).trim())) {
        return `${value}s`;
    }
    return String(value);
}

// ============================================
// Equipment Integration
// ============================================

let astrodexEquipmentCache = {
    combinations: [],
    sharedCombinations: [],
    filters: [],
    sharedFilters: [],
    telescopes: [],
    sharedTelescopes: [],
    cameras: [],
    sharedCameras: [],
};

async function loadEquipmentForAstrodex() {
    try {
        const [combosRes, filtersRes, telescopesRes, camerasRes] = await Promise.all([
            fetchJSON('/api/equipment/combinations'),
            fetchJSON('/api/equipment/filters'),
            fetchJSON('/api/equipment/telescopes'),
            fetchJSON('/api/equipment/cameras'),
        ]);
        astrodexEquipmentCache.combinations = combosRes.data || [];
        astrodexEquipmentCache.sharedCombinations = combosRes.shared_from_others || [];
        astrodexEquipmentCache.filters = filtersRes.data || [];
        astrodexEquipmentCache.sharedFilters = filtersRes.shared_from_others || [];
        astrodexEquipmentCache.telescopes = telescopesRes.data || [];
        astrodexEquipmentCache.sharedTelescopes = telescopesRes.shared_from_others || [];
        astrodexEquipmentCache.cameras = camerasRes.data || [];
        astrodexEquipmentCache.sharedCameras = camerasRes.shared_from_others || [];
    } catch (error) {
        console.error('Error loading equipment for Astrodex:', error);
    }
}

/** Find an equipment item's display name by id across a cached own+shared pool.
 * `kind` is 'telescopes' | 'cameras' | 'filters' | 'combinations'. */
function _findAstrodexEquipmentName(kind, id) {
    if (!id) return '';
    const sharedKey = 'shared' + kind.charAt(0).toUpperCase() + kind.slice(1);
    const found = (astrodexEquipmentCache[kind] || []).find(item => item.id === id)
        || (astrodexEquipmentCache[sharedKey] || []).find(item => item.id === id);
    return found ? found.name : '';
}

const _OTHER_EQUIPMENT_VALUE = '__other__';

/** Build <option> markup for the picture Equipment combination select: enabled combinations
 * (own + shared) only, unless `forceIncludeId` (the picture's own already-saved combination) is
 * disabled - it stays visible then so an existing selection never silently disappears (same rule
 * as the Equipment tab's combination-editor pickers). Sorted alphabetically by name so the list
 * stays predictable as combinations are added. */
function _buildPictureCombinationOptions(forceIncludeId, selectedId) {
    const all = [...astrodexEquipmentCache.combinations, ...astrodexEquipmentCache.sharedCombinations];
    const visible = all
        .filter(combo => !combo.is_disabled || combo.id === forceIncludeId)
        .sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    return visible.map(combo => {
        const label = combo.owner_username
            ? `${escapeHtml(combo.name)} ${i18n.t('equipment.shared_fov_suffix', { username: escapeHtml(combo.owner_username) })}`
            : escapeHtml(combo.name);
        return `<option value="${combo.id}" ${combo.id === selectedId ? 'selected' : ''}>${label}</option>`;
    }).join('');
}

/** Build the per-component checkbox area for a selected combination - lets the user mark which
 * parts were actually used for this specific photo (purely informational; combination_id itself
 * is what drives the "best combination" stats). Prechecks whatever `usedComponents` (a
 * previously-saved combination_used_components snapshot) recorded, defaulting to all-checked for
 * a freshly-selected combination, except filters which default to unchecked. */
function _buildCombinationComponentsChecklist(prefix, combo, usedComponents) {
    const wrap = document.createElement('div');
    wrap.className = 'd-flex flex-wrap gap-3 mt-1';
    if (!combo) return wrap;
    const used = usedComponents || {};

    const addCheckbox = (id, checked, labelText) => {
        const div = document.createElement('div');
        div.className = 'form-check';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'form-check-input';
        input.id = id;
        input.checked = checked;
        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.htmlFor = id;
        label.textContent = labelText;
        div.appendChild(input);
        div.appendChild(label);
        wrap.appendChild(div);
    };

    if (combo.telescope_id) {
        const name = _findAstrodexEquipmentName('telescopes', combo.telescope_id);
        addCheckbox(`${prefix}-combo-used-telescope`, used.telescope !== false, name || i18n.t('equipment.telescope'));
    }
    if (combo.camera_id) {
        const name = _findAstrodexEquipmentName('cameras', combo.camera_id);
        addCheckbox(`${prefix}-combo-used-camera`, used.camera !== false, name || i18n.t('equipment.camera'));
    }
    if (combo.guide_camera_id) {
        const name = _findAstrodexEquipmentName('cameras', combo.guide_camera_id);
        addCheckbox(`${prefix}-combo-used-guide-camera`, used.guide_camera !== false, name || i18n.t('equipment.form_guide_camera'));
    }
    const usedFilterIds = used.filter_ids || [];
    (combo.filter_ids || []).forEach((filterId) => {
        const name = _findAstrodexEquipmentName('filters', filterId);
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = `form-check-input ${prefix}-combo-used-filter-cb`;
        input.dataset.filterId = filterId;
        input.id = `${prefix}-combo-used-filter-${filterId}`;
        input.checked = usedFilterIds.includes(filterId);
        const div = document.createElement('div');
        div.className = 'form-check';
        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.htmlFor = input.id;
        label.textContent = name || filterId;
        div.appendChild(input);
        div.appendChild(label);
        wrap.appendChild(div);
    });
    return wrap;
}

/** Collect the current checklist state back into a combination_used_components snapshot. */
function _collectCombinationUsedComponents(prefix) {
    const result = {};
    const telescopeCb = document.getElementById(`${prefix}-combo-used-telescope`);
    const cameraCb = document.getElementById(`${prefix}-combo-used-camera`);
    const guideCameraCb = document.getElementById(`${prefix}-combo-used-guide-camera`);
    if (telescopeCb) result.telescope = telescopeCb.checked;
    if (cameraCb) result.camera = cameraCb.checked;
    if (guideCameraCb) result.guide_camera = guideCameraCb.checked;
    const filterCbs = document.querySelectorAll(`.${prefix}-combo-used-filter-cb`);
    if (filterCbs.length > 0) {
        result.filter_ids = Array.from(filterCbs).filter(cb => cb.checked).map(cb => cb.dataset.filterId);
    }
    return result;
}

/** Wire the picture Equipment section's combination select: toggles between the per-component
 * checklist (real combination picked) and the free-text "Other equipment" fallback fields, and
 * (re)builds the checklist whenever the selection changes. Call once after the modal is mounted.
 * `existingCombinationId`/`existingUsedComponents` seed the initial render when editing a picture
 * that already has a saved combination link. */
function _wirePictureEquipmentSection(prefix, existingCombinationId, existingUsedComponents) {
    const select = document.getElementById(`${prefix}-combination-select`);
    const checklistWrap = document.getElementById(`${prefix}-combo-checklist-wrap`);
    const checklistContainer = document.getElementById(`${prefix}-combo-checklist`);
    const deviceWrap = document.getElementById(`${prefix}-other-device-wrap`);
    const filtersWrap = document.getElementById(`${prefix}-other-filters-wrap`);
    if (!select || !checklistWrap || !checklistContainer || !deviceWrap || !filtersWrap) return;

    const allCombos = [...astrodexEquipmentCache.combinations, ...astrodexEquipmentCache.sharedCombinations];

    const applySelection = (usedComponents) => {
        const isOther = select.value === _OTHER_EQUIPMENT_VALUE || select.value === '';
        deviceWrap.style.display = isOther ? '' : 'none';
        filtersWrap.style.display = isOther ? '' : 'none';
        DOMUtils.clear(checklistContainer);

        if (isOther) {
            checklistWrap.style.display = 'none';
            return;
        }
        const combo = allCombos.find(c => c.id === select.value);
        if (combo) {
            checklistContainer.appendChild(_buildCombinationComponentsChecklist(prefix, combo, usedComponents));
            checklistWrap.style.display = '';
        } else {
            checklistWrap.style.display = 'none';
        }
    };

    select.addEventListener('change', () => applySelection(null));
    applySelection(select.value && select.value === existingCombinationId ? existingUsedComponents : null);
}

/** Bootstrap icon class for star `i` (1-5) of a 0-5, 0.5-step rating `value` - shared by the
 * read-only display and the interactive widget so a rounding/threshold fix only needs one edit. */
function _starIconClass(value, i) {
    if (value >= i) return 'bi bi-star-fill text-warning';
    if (value >= i - 0.5) return 'bi bi-star-half text-warning';
    return 'bi bi-star text-warning';
}

/** Build a read-only star-rating display (used in the slideshow/detail view). */
function _buildStarRatingDisplayHtml(rating) {
    const value = Number(rating) || 0;
    let icons = '';
    for (let i = 1; i <= 5; i++) {
        icons += `<i class="${_starIconClass(value, i)}" aria-hidden="true"></i>`;
    }
    return `${icons} <span class="ms-1">${value.toFixed(1)}</span>`;
}

/** Build an interactive 0-5 (half-star step) rating widget. Clicking the left half of a star
 * sets a .5 value, the right half sets the full integer; clicking the star that already matches
 * the current rating clears it back to "not rated". Read back with _getRatingWidgetValue(). */
function _buildRatingWidget(prefix, currentRating) {
    const wrap = document.createElement('div');
    wrap.className = 'd-flex align-items-center gap-1';
    wrap.id = `${prefix}-rating-widget`;
    wrap.dataset.rating = currentRating != null ? String(currentRating) : '';

    const renderStars = () => {
        DOMUtils.clear(wrap);
        const value = parseFloat(wrap.dataset.rating) || 0;
        for (let i = 1; i <= 5; i++) {
            // Sized to a full 44x44px touch target (not just the glyph) so left-half/right-half
            // (half-star vs full-star) selection stays reachable on a touchscreen.
            const starWrap = document.createElement('span');
            starWrap.className = 'd-inline-flex align-items-center justify-content-center';
            starWrap.style.cursor = 'pointer';
            starWrap.style.fontSize = '1.75rem';
            starWrap.style.minWidth = '44px';
            starWrap.style.minHeight = '44px';
            starWrap.style.touchAction = 'manipulation';
            starWrap.style.userSelect = 'none';
            starWrap.title = i18n.t('astrodex.rating');

            const icon = document.createElement('i');
            icon.className = _starIconClass(value, i);
            icon.setAttribute('aria-hidden', 'true');
            starWrap.appendChild(icon);

            starWrap.addEventListener('click', (event) => {
                const rect = starWrap.getBoundingClientRect();
                const clickedHalf = (event.clientX - rect.left) < (rect.width / 2);
                const newValue = clickedHalf ? i - 0.5 : i;
                wrap.dataset.rating = (value === newValue) ? '' : String(newValue);
                renderStars();
            });
            wrap.appendChild(starWrap);
        }
        const label = document.createElement('span');
        label.className = 'text-muted small ms-1';
        label.textContent = value > 0 ? value.toFixed(1) : i18n.t('astrodex.not_rated');
        wrap.appendChild(label);
    };

    renderStars();
    return wrap;
}

/** Read the current value set on a widget built by _buildRatingWidget(), or null if unrated. */
function _getRatingWidgetValue(prefix) {
    const wrap = document.getElementById(`${prefix}-rating-widget`);
    const raw = wrap?.dataset.rating;
    return raw ? parseFloat(raw) : null;
}

// ============================================
// Astrodex Data Loading
// ============================================

async function loadAstrodex() {
    try {

        // Re-check the MyAstroShine integration state on each tab entry so enabling
        // it in Parameters shows the "Send to MyAstroShine" button without a reload.
        _myAstroShineStatusChecked = false;

        // Get role user
        const roleUser = await getUserRole();
        // Display Astrodex if roleUser is user or admin
        const isAllowedAstrodex = roleUser === 'user' || roleUser === 'admin';

        const response = await fetchJSON('/api/astrodex');
        astrodexData.items = response.items || [];
        astrodexData.stats = response.stats || {};
        astrodexData.privateMode = response.private_mode !== false;
        astrodexData.currentUserId = response.current_user_id || null;

        // Load equipment data for Astrodex integration
        if (isAllowedAstrodex) {
            await loadEquipmentForAstrodex();
        }

        renderAstrodexView(isAllowedAstrodex);
    } catch (error) {
        console.error('Error loading astrodex:', error);
        showMessage('error', i18n.t('astrodex.failed_to_load_astrodex'));
    }
}

async function getConstellationsList() {
    try {
        const response = await fetchJSON('/api/astrodex/constellations');
        return response.constellations || [];
    } catch (error) {
        console.error('Error fetching constellations list:', error);
        return [];
    }
}

function getConstellationDisplayName(value) {
    const normalizedValue = (value || '').toString().trim();
    if (!normalizedValue) {
        return '';
    }

    const translationKey = 'constellations.' + strToTranslateKey(normalizedValue);
    if (i18n.has(translationKey)) {
        return i18n.t(translationKey);
    }

    return capitalizeWords(normalizedValue);
}

function normalizeConstellationValue(value) {
    return (value || '').toString().trim().toLowerCase();
}

function isConstellationOptionSelected(currentValue, constellationOption) {
    const normalizedCurrentValue = normalizeConstellationValue(currentValue);
    if (!normalizedCurrentValue) {
        return false;
    }

    const normalizedOptionValue = normalizeConstellationValue(constellationOption);
    if (normalizedCurrentValue === normalizedOptionValue) {
        return true;
    }

    const normalizedTranslatedOption = normalizeConstellationValue(
        getConstellationDisplayName(constellationOption)
    );
    return normalizedCurrentValue === normalizedTranslatedOption;
}

// ============================================
// Astrodex Rendering
// ============================================

function renderAstrodexView(isAllowedAstrodex) {
    const container = document.getElementById('astrodex-content');
    if (!container) return;

    updateAstrodexCollectionTitle();

    // Render stats
    renderAstrodexStats();

    // Apply filters and sorting
    const filteredItems = filterAndSortAstrodexItems();

    // Render items grid
    renderAstrodexGrid(filteredItems, isAllowedAstrodex);
}

function updateAstrodexCollectionTitle() {
    const title = document.getElementById('astrodex-collection-title');
    const subtitle = document.getElementById('astrodex-collection-subtitle');
    if (!title) return;

    if (astrodexData.privateMode) {
        DOMUtils.clear(title);
        DOMUtils.append(title, DOMUtils.createIcon('bi bi-galaxy text-warning icon-inline'), i18n.t('astrodex.my_collection'));
        if (subtitle) {
            subtitle.textContent = i18n.t('astrodex.your_collection');
        }
    } else {
        DOMUtils.clear(title);
        DOMUtils.append(title, DOMUtils.createIcon('bi bi-galaxy text-warning icon-inline'), i18n.t('astrodex.common_collection'));
        if (subtitle) {
            subtitle.textContent = i18n.t('astrodex.shared_collection');
        }
    }
}

function getPersonalAstrodexStats() {
    const personalItems = (astrodexData.items || []).filter(item => item.is_owned_by_current_user !== false);
    const personalTypes = new Set();
    const personalConstellations = new Set();

    personalItems.forEach(item => {
        const itemType = (item.type || i18n.t('astrodex.unknown')).toString().trim();
        if (itemType) {
            personalTypes.add(itemType);
        }

        const constellation = (item.constellation || '').toString().trim().toLowerCase();
        if (constellation) {
            personalConstellations.add(constellation);
        }
    });

    const itemsWithPictures = personalItems.filter(item => {
        const ownPicturesCount = Array.isArray(item.own_pictures)
            ? item.own_pictures.length
            : (item.pictures ? item.pictures.length : 0);
        return ownPicturesCount > 0;
    }).length;
    const totalPictures = personalItems.reduce((count, item) => {
        const ownPicturesCount = Array.isArray(item.own_pictures)
            ? item.own_pictures.length
            : (item.pictures ? item.pictures.length : 0);
        return count + ownPicturesCount;
    }, 0);

    return {
        totalItems: personalItems.length,
        itemsWithPictures,
        totalPictures,
        objectTypesCount: personalTypes.size,
        constellationsCount: personalConstellations.size
    };
}

function renderAstrodexStats() {
    const statsContainer = document.getElementById('astrodex-stats');
    if (!statsContainer) return;

    const stats = astrodexData.stats;
    const totalItems = Number(stats.total_items || 0);
    const itemsWithPictures = Number(stats.items_with_pictures || 0);
    const totalPictures = Number(stats.total_pictures || 0);
    const objectTypesCount = Number(Object.keys(stats.types || {}).length || 0);
    const constellationCount = new Set(
        (astrodexData.items || [])
            .map(item => (item.constellation || '').toString().trim().toLowerCase())
            .filter(value => value)
    ).size;

    const personalStats = getPersonalAstrodexStats();
    const personalSuffix = astrodexData.privateMode
        ? ''
        : ` (${i18n.t('astrodex.personal')}${personalStats.totalItems})`;
    const personalPicturesSuffix = astrodexData.privateMode
        ? ''
        : ` (${i18n.t('astrodex.personal')}${personalStats.itemsWithPictures})`;
    const personalTotalPhotosSuffix = astrodexData.privateMode
        ? ''
        : ` (${i18n.t('astrodex.personal')}${personalStats.totalPictures})`;
    const personalObjectTypesSuffix = astrodexData.privateMode
        ? ''
        : ` (${i18n.t('astrodex.personal')}${personalStats.objectTypesCount})`;
    const personalConstellationsSuffix = astrodexData.privateMode
        ? ''
        : ` (${i18n.t('astrodex.personal')}${personalStats.constellationsCount})`;

    DOMUtils.clear(statsContainer);
    const statItems = [
        { value: totalItems.toFixed(0), label: `${i18n.t('astrodex.total_objects')}${personalSuffix}` },
        { value: itemsWithPictures.toFixed(0), label: `${i18n.t('astrodex.with_photos')}${personalPicturesSuffix}` },
        { value: totalPictures.toFixed(0), label: `${i18n.t('astrodex.total_photos')}${personalTotalPhotosSuffix}` },
        { value: objectTypesCount.toFixed(0), label: `${i18n.t('astrodex.object_types')}${personalObjectTypesSuffix}` },
        { value: constellationCount.toFixed(0), label: `${i18n.t('astrodex.constellations')}${personalConstellationsSuffix}` }
    ];

    statItems.forEach((statItem) => {
        const col = document.createElement('div');
        col.className = 'col';
        const card = document.createElement('div');
        card.className = 'card h-100';
        const body = document.createElement('div');
        body.className = 'card-body text-center';
        const value = document.createElement('div');
        value.className = 'astrodex-insight-value text-primary';
        value.textContent = statItem.value;
        const label = document.createElement('div');
        label.className = 'fw-light fst-italic';
        label.textContent = statItem.label;
        body.appendChild(value);
        body.appendChild(label);
        card.appendChild(body);
        col.appendChild(card);
        statsContainer.appendChild(col);
    });
}

function renderAstrodexGrid(items, isAllowedAstrodex) {
    const gridContainer = document.getElementById('astrodex-grid');
    if (!gridContainer) return;

    if (items.length === 0) {
        DOMUtils.clear(gridContainer);
        if (isAllowedAstrodex) {
            const col = document.createElement('div');
            col.className = 'col';
            const card = document.createElement('div');
            card.className = 'card h-100';
            const body = document.createElement('div');
            body.className = 'card-body text-center';
            const title = document.createElement('b');
            DOMUtils.append(title, DOMUtils.createIcon('bi bi-journal-bookmark icon-inline'), i18n.t('astrodex.astrodex_empty'));
            body.appendChild(title);
            body.appendChild(document.createElement('br'));
            body.append(i18n.t('astrodex.start_adding'));

            const footer = document.createElement('div');
            footer.className = 'card-footer text-center';
            const button = document.createElement('button');
            button.className = 'btn btn-primary';
            button.setAttribute('data-action', 'add-astrodex-item');
            DOMUtils.append(button, DOMUtils.createIcon('bi bi-plus-circle icon-inline'), i18n.t('astrodex.add_object'));
            footer.appendChild(button);

            card.appendChild(body);
            card.appendChild(footer);
            col.appendChild(card);
            gridContainer.appendChild(col);
        } else {
            const col = document.createElement('div');
            col.className = 'col';
            const card = document.createElement('div');
            card.className = 'card h-100';
            const body = document.createElement('div');
            body.className = 'card-body text-center';
            const title = document.createElement('b');
            DOMUtils.append(title, DOMUtils.createIcon('bi bi-journal-bookmark icon-inline'), 'Astrodex is empty');
            body.appendChild(title);
            body.appendChild(document.createElement('br'));
            body.append(i18n.t('astrodex.read_only_user'));
            card.appendChild(body);
            col.appendChild(card);
            gridContainer.appendChild(col);
        }
        return;
    }

    DOMUtils.clear(gridContainer);
    items.forEach((item) => {
        const isOwnedByCurrentUser = item.is_owned_by_current_user !== false;
        const mainPicture = getCardMainPicture(item);
        const imageUrl = mainPicture
            ? `/api/astrodex/images/${mainPicture.filename}`
            : '/static/img/default_astro_object.svg';

        const photoCount = Number(item.total_pictures ?? (item.pictures ? item.pictures.length : 0));
        const canOpenSharedSlideshow = photoCount > 0;

        const col = document.createElement('div');
        col.className = 'col mb-3';
        const card = document.createElement('div');
        card.className = 'card h-100';

        const imageWrap = document.createElement('div');
        imageWrap.className = 'astrodex-card-image rounded';
        imageWrap.setAttribute('data-item-id', String(item.id));
        imageWrap.tabIndex = 0;
        imageWrap.setAttribute('role', 'button');
        imageWrap.setAttribute('aria-label', `View ${item.name} photos`);
        imageWrap.style.cursor = 'pointer';
        imageWrap.title = i18n.t('astrodex.click_to_view_photos');

        const img = document.createElement('img');
        img.src = imageUrl;
        img.alt = item.name;
        img.loading = 'lazy';
        img.className = 'card-img-top';
        imageWrap.appendChild(img);

        if (photoCount > 0) {
            const badge = document.createElement('div');
            badge.className = 'photo-badge';
            badge.appendChild(document.createTextNode(`${photoCount} `));
            badge.appendChild(DOMUtils.createIcon('bi bi-camera'));
            imageWrap.appendChild(badge);
        }

        const body = document.createElement('div');
        body.className = 'card-body astrodex-card-body';
        body.setAttribute('data-item-id', String(item.id));
        body.tabIndex = 0;
        body.setAttribute('role', 'button');
        body.setAttribute('aria-label', isOwnedByCurrentUser ? `View ${item.name} details` : `View ${item.name} photos`);
        body.style.cursor = (isOwnedByCurrentUser || canOpenSharedSlideshow) ? 'pointer' : 'default';

        const title = document.createElement('div');
        title.className = 'astrodex-card-title';
        title.textContent = item.name;
        const type = document.createElement('div');
        type.className = 'astrodex-card-type';
        let translationKey = 'type_' + strToTranslateKey(item.type);
        const skytonightKey = `skytonight.${translationKey}`;
        if (i18n.has(skytonightKey)) {
            type.textContent = tSkyTonightCompat(translationKey);
        } else {
            type.textContent = item.type || i18n.t('astrodex.unknown');
        }
        body.appendChild(title);
        body.appendChild(type);

        if (item.difficulty && typeof createDifficultyBadgeNode === 'function') {
            body.appendChild(createDifficultyBadgeNode(item.difficulty));
        }

        if (item.constellation) {
            const constellationLabel = getConstellationDisplayName(item.constellation);

            const constellation = document.createElement('div');
            constellation.className = 'astrodex-card-constellation';
            DOMUtils.append(constellation, DOMUtils.createIcon('bi bi-geo-alt text-danger icon-inline'), constellationLabel);
            body.appendChild(constellation);
        }

        if (!isOwnedByCurrentUser) {
            const owner = document.createElement('div');
            owner.className = 'astrodex-card-constellation';
            DOMUtils.append(owner, DOMUtils.createIcon('bi bi-person text-primary icon-inline'), item.owner_username || 'Shared');
            body.appendChild(owner);
        }

        card.appendChild(imageWrap);
        card.appendChild(body);
        col.appendChild(card);
        gridContainer.appendChild(col);
    });
}

function getMainPicture(item) {
    if (!item.pictures || item.pictures.length === 0) {
        return null;
    }

    // Find main picture
    for (const picture of item.pictures) {
        if (picture.is_main) {
            return picture;
        }
    }

    // If no main picture is set, return first picture
    return item.pictures[0];
}

function parsePictureDateTimestamp(picture) {
    if (!picture) {
        return Number.NEGATIVE_INFINITY;
    }

    const dateCandidates = [picture.date, picture.created_at];
    for (const dateValue of dateCandidates) {
        if (!dateValue) {
            continue;
        }
        const timestamp = Date.parse(dateValue);
        if (!Number.isNaN(timestamp)) {
            return timestamp;
        }
    }

    return Number.NEGATIVE_INFINITY;
}

function getLatestPictureFromAllUsers(item) {
    if (!item?.pictures || item.pictures.length === 0) {
        return null;
    }

    const sortedPictures = [...item.pictures].sort((pictureA, pictureB) => {
        const timestampA = parsePictureDateTimestamp(pictureA);
        const timestampB = parsePictureDateTimestamp(pictureB);
        return timestampB - timestampA;
    });

    return sortedPictures[0] || null;
}

function getCardMainPicture(item) {
    if (!item?.pictures || item.pictures.length === 0) {
        return null;
    }

    if (astrodexData.privateMode) {
        return getMainPicture(item);
    }

    const currentUserMainPicture = item.pictures.find(picture =>
        picture?.is_main && picture?.is_owned_by_current_user === true
    );
    if (currentUserMainPicture) {
        return currentUserMainPicture;
    }

    const latestPicture = getLatestPictureFromAllUsers(item);
    if (latestPicture) {
        return latestPicture;
    }

    return null;
}

// ============================================
// Filtering and Sorting
// ============================================

function filterAndSortAstrodexItems() {
    let items = [...astrodexData.items];

    // Apply search filter
    if (astrodexFilters.search) {
        const searchLower = astrodexFilters.search.toLowerCase();
        items = items.filter(item =>
            item.name.toLowerCase().includes(searchLower) ||
            (item.type && item.type.toLowerCase().includes(searchLower)) ||
            (item.constellation && item.constellation.toLowerCase().includes(searchLower))
        );
    }

    // Apply type filter
    if (astrodexFilters.type !== 'all') {
        items = items.filter(item => item.type === astrodexFilters.type);
    }

    // Apply photo filter
    if (astrodexFilters.hasPhotos === 'yes') {
        items = items.filter(item => item.pictures && item.pictures.length > 0);
    } else if (astrodexFilters.hasPhotos === 'no') {
        items = items.filter(item => !item.pictures || item.pictures.length === 0);
    }

    // Apply sorting. Names and types are compared with a numeric-aware collator so
    // catalogue identifiers order the way they read ("M 3" < "M 31" < "M 100")
    // instead of as plain strings ("M 1", "M 10", "M 100", "M 3", "M 31", "M 4").
    const naturalCompare = (x, y) =>
        String(x || '').localeCompare(String(y || ''), undefined, { numeric: true, sensitivity: 'base' });
    const direction = astrodexFilters.sortOrder === 'asc' ? 1 : -1;

    items.sort((a, b) => {
        let comparison;

        switch (astrodexFilters.sortBy) {
            case 'name':
                comparison = naturalCompare(a.name, b.name);
                break;
            case 'type':
                comparison = naturalCompare(a.type, b.type);
                break;
            case 'date':
                comparison = new Date(a.created_at || 0) - new Date(b.created_at || 0);
                break;
            case 'photos':
                comparison = (a.pictures ? a.pictures.length : 0) - (b.pictures ? b.pictures.length : 0);
                break;
            default:
                return 0;
        }

        // Objects level on the chosen field fall back to natural name order, so the
        // grid stays readable instead of dropping back to insertion order.
        if (comparison === 0 && astrodexFilters.sortBy !== 'name') {
            comparison = naturalCompare(a.name, b.name);
        }

        return direction * comparison;
    });

    return items;
}

function updateAstrodexFilter(filterName, value, isAllowedAstrodex) {
    astrodexFilters[filterName] = value;
    renderAstrodexView(isAllowedAstrodex);
}

// ============================================
// Add Item to Astrodex
// ============================================

/** Create an Astrodex item. Returns the created item object on success (falls back to `true`
 * if the server response omits it), or `false` on failure / duplicate. */
async function addToAstrodex(itemData) {
    try {
        const resp = await fetch('/api/astrodex/items', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(itemData)
        });
        const data = await resp.json();

        if (resp.status === 409 && data.error === 'duplicate' && data.existing_item) {
            showMessage('warning', i18n.t('astrodex.item_already_exists'));
            await loadAstrodex();
            showAstrodexItemDetail(data.existing_item.id);
            return false;
        }

        if (!resp.ok) {
            showMessage('error', data.error || i18n.t('astrodex.failed_to_add_item'));
            return false;
        }

        if (data.status === 'success') {
            await loadAstrodex();
            if (typeof updateCatalogueCapturedBadge === 'function') {
                updateCatalogueCapturedBadge(data.item || itemData, true);
            }
            return data.item || true;
        } else {
            showMessage('error', data.error || i18n.t('astrodex.failed_to_add_item'));
            return false;
        }
    } catch (error) {
        console.error('Error adding to astrodex:', error);
        showMessage('error', i18n.t('astrodex.failed_to_add_astrodex_item'));
        return false;
    }
}

async function addFromCatalogue(catalogueItem) {
    // Extract item name from catalogue data
    const itemName = catalogueItem.id || catalogueItem['target name'] || catalogueItem.name;

    if (!itemName) {
        showMessage('error', i18n.t('astrodex.invalid_item_data'));
        return;
    }

    // Detect type properly - check for comet designation patterns
    let itemType = catalogueItem.type || catalogueItem.targettype || 'Unknown';

    // If type is still Unknown, try to detect from catalogue or name patterns
    if (itemType === 'Unknown' || !itemType) {
        const catalogue = catalogueItem.catalogue || currentCatalogueTab || '';
        const catalogueLower = catalogue.toLowerCase();

        // Force comet type if from comets catalogue
        if (catalogueLower.includes('comet')) {
            itemType = 'Comet';
        } else if (itemName.match(/^C\/\d{4}\s+[A-Z]\d+/i) || itemName.match(/^\d+P\//i)) {
            // Comet designation like C/2023 A1 or 24P/Schaumasse
            itemType = 'Comet';
        }
    }

    const itemData = {
        name: itemName,
        type: itemType,
        catalogue: catalogueItem.catalogue || currentCatalogueTab || '',
        constellation: catalogueItem.constellation || catalogueItem.const || ''
    };

    const success = await addToAstrodex(itemData);

    // On success, switch to Astrodex tab and explicitly activate the astrodex sub-tab
    if (success) {
        switchMainTab('astrodex');
        switchSubTab('astrodex', 'astrodex', { syncHistory: false });
        // Wait for tab to switch and data to reload
        await new Promise(resolve => {
            const checkInterval = setInterval(() => {
                const addedItem = astrodexData.items.find(item => item.name === itemName);
                if (addedItem) {
                    clearInterval(checkInterval);
                    resolve();
                }
            }, 50);
            // Timeout after 2 seconds
            setTimeout(() => {
                clearInterval(checkInterval);
                resolve();
            }, 2000);
        });

        const addedItem = astrodexData.items.find(item => item.name === itemName);
        if (addedItem) {
            showAstrodexItemDetail(addedItem.id);
        }
    }
}

async function showAddAstrodexItemModal() {
    //console.log("Opening Add to Astrodex modal");

    // Get list of constellations for select options
    const constellations = await getConstellationsList();
    //console.log("Fetched constellations for select options:", constellations);

    createModal(i18n.t('astrodex.add_to_astrodex'), `
        <form id="add-astrodex-form" class="form row g-3">
            <div class="col-12">
                <div class="input-group">
                    <input type="text" id="catalogue-search-input" class="form-control"
                        placeholder="${escapeHtml(i18n.t('astrodex.search_catalogue_placeholder'))}"
                        autocomplete="off">
                    <button type="button" id="catalogue-search-btn" class="btn btn-secondary"
                        title="${escapeHtml(i18n.t('astrodex.search_catalogue_btn'))}">
                        <i class="bi bi-search"></i>
                    </button>
                </div>
                <div id="catalogue-search-feedback" class="mt-1 small d-none"></div>
            </div>
            <div class="col-12"><hr class="my-1 opacity-25"></div>
            <div class="col-md-12">
                <label for="item-name" class="form-label">${i18n.t('astrodex.form_object_name')} *</label>
                <div id="item-name-field">
                    <input type="text" id="item-name" class="form-control" required autocomplete="off">
                </div>
                <input type="hidden" id="item-catalogue" value="">
                <input type="hidden" id="item-external-aliases" value="">
            </div>
            <div class="col-md-6">
                <label for="item-type" class="form-label">${i18n.t('astrodex.form_object_type')}</label>
                <select id="item-type" class="form-select">
                    ${getObjectTypeOptionsHtml()}
                </select>
            </div>
            <div class="col-md-6">
                <label for="item-constellation" class="form-label">${i18n.t('astrodex.form_constellation')}</label>
                <select id="item-constellation" class="form-select">
                    <option value=""></option>
                    ${constellations.map(c => `<option value="${escapeHtml(c.toLowerCase())}">${escapeHtml(getConstellationDisplayName(c))}</option>`).join('')}
                </select>
            </div>
            <div class="col-md-12">
                <label for="item-notes" class="form-label">${i18n.t('astrodex.form_notes')}</label>
                <textarea id="item-notes" class="form-control" rows="3" placeholder="${i18n.t('astrodex.form_notes_placeholder')}"></textarea>
            </div>
            <div class="text-end">
                <button type="submit" class="btn btn-primary">${i18n.t('astrodex.form_add_to_astrodex')}</button>
            </div>
        </form>
    `, 'lg');

    // --- Catalogue search row ---
    const searchInput = document.getElementById('catalogue-search-input');
    const searchBtn = document.getElementById('catalogue-search-btn');
    const feedbackEl = document.getElementById('catalogue-search-feedback');

    async function _triggerCatalogueSearch() {
        const val = (searchInput?.value || '').trim();
        if (!val) return;

        if (searchBtn) {
            searchBtn.disabled = true;
            DOMUtils.clear(searchBtn);
            const _spinner = document.createElement('span');
            _spinner.className = 'spinner-border spinner-border-sm';
            _spinner.setAttribute('role', 'status');
            _spinner.setAttribute('aria-hidden', 'true');
            searchBtn.appendChild(_spinner);
        }
        if (feedbackEl) feedbackEl.classList.add('d-none');

        try {
            const res = await fetchJSON(`/api/astrodex/catalogue-lookup?name=${encodeURIComponent(val)}`);

            if (!res || !res.found) {
                if (feedbackEl) {
                    DOMUtils.clear(feedbackEl);
                    const _badgeWarn = document.createElement('span');
                    _badgeWarn.className = 'badge bg-warning text-dark';
                    DOMUtils.append(_badgeWarn, DOMUtils.createIcon('bi bi-exclamation-circle me-1'), i18n.t('astrodex.catalogue_not_found'));
                    feedbackEl.appendChild(_badgeWarn);
                    feedbackEl.classList.remove('d-none');
                }
                return;
            }

            const typeSelect = document.getElementById('item-type');
            const constSelect = document.getElementById('item-constellation');
            const catInput = document.getElementById('item-catalogue');
            const extAliasesInput = document.getElementById('item-external-aliases');

            // Offer every alternate designation the catalogue knows about (common name,
            // OpenNGC/OpenIC, LBN...) as a picker instead of silently locking the name
            // to whichever one choose_preferred_catalogue_name() favors server-side.
            const nameChoices = buildAstrodexNameChoices(res.catalogue_names);
            const selectedName = res.preferred_name || val;
            setAstrodexNameField(nameChoices, selectedName);

            const matchedChoice = nameChoices.find((choice) => choice.value === selectedName);
            if (catInput) catInput.value = matchedChoice?.catalogue || '';

            // Stash the resolved alternate names so the item's "Catalogue names" popup
            // section still has something to show for objects the local SkyTonight DSO
            // dataset doesn't cover (mainly stars) - only needed for the SIMBAD fallback
            // path, since local (DSO) objects already get this live from that dataset.
            if (extAliasesInput) {
                extAliasesInput.value = res.source === 'simbad' && res.catalogue_names
                    ? JSON.stringify(res.catalogue_names)
                    : '';
            }

            if (typeSelect) {
                const mappedType = mapCatalogueObjectType(res.object_type);
                if (mappedType) {
                    for (const opt of typeSelect.options) {
                        if (opt.value === mappedType) { typeSelect.value = mappedType; break; }
                    }
                }
            }
            if (constSelect && res.constellation) {
                const constLower = res.constellation.toLowerCase();
                for (const opt of constSelect.options) {
                    if (opt.value === constLower) { constSelect.value = constLower; break; }
                }
            }

            if (feedbackEl) {
                DOMUtils.clear(feedbackEl);
                const _badgeOk = document.createElement('span');
                _badgeOk.className = 'badge bg-success';
                DOMUtils.append(_badgeOk, DOMUtils.createIcon('bi bi-check-circle me-1'), i18n.t('astrodex.catalogue_found'));
                feedbackEl.appendChild(_badgeOk);
                feedbackEl.classList.remove('d-none');
            }
        } catch (_) { /* silent - lookup is best-effort */ }
        finally {
            if (searchBtn) {
                searchBtn.disabled = false;
                DOMUtils.clear(searchBtn);
                searchBtn.appendChild(DOMUtils.createIcon('bi bi-search'));
            }
        }
    }

    if (searchBtn) searchBtn.addEventListener('click', _triggerCatalogueSearch);
    if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); _triggerCatalogueSearch(); }
        });
    }
    // --- end catalogue search ---

    const submitHandler = async (e) => {
        e.preventDefault();

        const itemData = {
            name: document.getElementById('item-name').value,
            type: document.getElementById('item-type').value,
            catalogue: document.getElementById('item-catalogue')?.value || '',
            constellation: document.getElementById('item-constellation').value,
            notes: document.getElementById('item-notes').value
        };

        const rawExternalAliases = document.getElementById('item-external-aliases')?.value || '';
        if (rawExternalAliases) {
            try {
                itemData.external_aliases = JSON.parse(rawExternalAliases);
            } catch (_) { /* stale/invalid stash - just omit it */ }
        }

        const created = await addToAstrodex(itemData);
        if (created) {
            // Resolve the new item against the freshly reloaded list so we only hand
            // showAstrodexItemDetail() an id it can actually render (otherwise it would
            // bail early and leave this add-item modal stuck open).
            const newId = created.id || astrodexData.items.find(item => item.name === itemData.name)?.id;
            const newItem = newId && astrodexData.items.find(item => item.id === newId);
            if (newItem) {
                // Jump straight into the new object's detail modal so a photo can be
                // added right away - openModal() closes this add-item modal first.
                await showAstrodexItemDetail(newItem.id);
            } else {
                closeModal('#modal_lg_close');
            }
        }
    };
    document.getElementById('add-astrodex-form').addEventListener('submit', submitHandler);

    openModal('#modal_lg_close', {
        backdrop: 'static',
        onHidden: () => {
            document.getElementById('add-astrodex-form')?.removeEventListener('submit', submitHandler);
        },
    });
}

// ============================================
// Item Detail View
// ============================================

async function showAstrodexItemDetail(itemId) {
    const item = astrodexData.items.find(i => i.id === itemId);
    if (!item) return;

    if (item.is_owned_by_current_user === false) {
        showPictureSlideshow(itemId);
        return;
    }

    currentAstrodexItem = item;

    // Resolve the MyAstroShine integration state before building the modal -
    // renderPicturesGrid() reads _myAstroShineEnabled synchronously.
    await _ensureMyAstroShineStatus();

    // Get list of constellations for select options
    const constellations = await getConstellationsList();

    const catalogueAliasesSection = renderCatalogueAliasesSection(item);
    const ownPicturesCount = Array.isArray(item.own_pictures)
        ? item.own_pictures.length
        : (item.pictures ? item.pictures.length : 0);
    const totalPicturesCount = Number(item.total_pictures ?? ownPicturesCount);
    const picturesTitle = totalPicturesCount > ownPicturesCount
        ? i18n.t('astrodex.my_photos', { ownPicturesCount, totalPicturesCount })
        : i18n.t('astrodex.all_photos', { ownPicturesCount });

    // No location on the item itself (v1.2) - the same object commonly gets
    // re-photographed from different sites over its lifetime, so this is a
    // live summary of the distinct locations across the item's own pictures
    // rather than one frozen value.
    const observedLocationNames = [...new Set(
        (item.own_pictures || []).map(picture => picture.location_name).filter(Boolean)
    )];
    const locationBadge = observedLocationNames.length > 0 ? `
        <div class="alert alert-light border d-flex align-items-center gap-2 py-2 mb-3">
            <i class="bi bi-pin-map icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.observed_location', { name: escapeHtml(observedLocationNames.join(', ')) })}
        </div>
    ` : '';

    // Reverse link into the Observation Log: which session(s) logged this item's
    // capture. One entry per distinct session (an item can be logged across several
    // nights); the forward link (entry -> item) is automatic, this is purely display.
    const sessionMatches = item.observation_sessions || [];
    const uniqueSessionIds = [...new Set(sessionMatches.map(match => match.session_id))];
    const observationLogBadge = uniqueSessionIds.length > 0 ? `
        <div class="d-flex flex-wrap gap-2 mb-3">
            ${uniqueSessionIds.map(sessionId => {
        const match = sessionMatches.find(candidate => candidate.session_id === sessionId);
        return `
                    <button type="button" class="btn btn-sm btn-outline-secondary" data-action="view-observation-session" data-session-id="${escapeHtml(sessionId)}">
                        <i class="bi bi-journal-text icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.observation_log_link', { date: escapeHtml(match?.session_date || '') })}
                    </button>
                `;
    }).join('')}
        </div>
    ` : '';

    createModal(item.name, `
        <h3>${i18n.t('astrodex.object_info')}</h3>
        ${locationBadge}
        ${observationLogBadge}
        <form id="edit-item-form-${escapeHtml(item.id)}" class="form row g-3">
            <div class="col-md-6">
                <label for="edit-type-${escapeHtml(item.id)}" class="col form-label">${i18n.t('astrodex.form_object_type')}</label>
                <select id="edit-type-${escapeHtml(item.id)}" class="form-select" data-action="update-field" data-item-id="${escapeHtml(item.id)}" data-field="type">
                    ${getObjectTypeOptionsHtml(item.type)}
                    <option value="Unknown" ${item.type === 'Unknown' || !item.type ? 'selected' : ''}>${i18n.t('astrodex.unknown')}</option>
                </select>
            </div>

            <div class="col-md-6">
                <label for="edit-constellation-${escapeHtml(item.id)}" class="form-label">${i18n.t('astrodex.constellations')}</label>
                <select id="edit-constellation-${escapeHtml(item.id)}" class="form-select" data-action="update-field" data-item-id="${escapeHtml(item.id)}" data-field="constellation">
                    <option value=""></option>
                    ${constellations.map(c => `<option value="${escapeHtml(c.toLowerCase())}" ${isConstellationOptionSelected(item.constellation, c) ? 'selected' : ''}>${escapeHtml(getConstellationDisplayName(c))}</option>`).join('')}
                </select>
            </div>

            ${catalogueAliasesSection}

            <div class="col-md-12">
                <label for="edit-notes-${escapeHtml(item.id)}" class="form-label">${i18n.t('astrodex.form_notes')}</label>
                <textarea id="edit-notes-${escapeHtml(item.id)}" class="form-control" rows="3" data-action="update-field" data-item-id="${escapeHtml(item.id)}" data-field="notes" placeholder="${i18n.t('astrodex.form_notes_placeholder')}">${escapeHtml(item.notes || '')}</textarea>
            </div>
        </form>

        <div class="mt-3 mb-3 text-end">
            <button class="btn btn-sm btn-primary me-3" data-action="add-picture" data-item-id="${escapeHtml(item.id)}"><i class="bi bi-camera icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.add_picture')}</button>
            <button class="btn btn-sm btn-danger" data-action="delete-item" data-item-id="${escapeHtml(item.id)}"><i class="bi bi-trash icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.remove')}</button>
        </div>

        <h3>${escapeHtml(picturesTitle)}</h3>
        <div class="astrodex-pictures row row-cols-2 row-cols-md-4 g-4">
            ${renderPicturesGrid(item)}
        </div>

    `, 'xl');

    // openModal() no-ops the show when this shell is already on screen (e.g. opening
    // a second item straight from the first): createModal() above already refreshed
    // the body, so nothing else to do.
    openModal('#modal_xl_close', { backdrop: 'static' });
}

function renderCatalogueAliasesSection(item) {
    const aliases = item.catalogue_aliases;
    if (!aliases || typeof aliases !== 'object' || Object.keys(aliases).length === 0) {
        return '';
    }

    const rows = Object.entries(aliases)
        .sort(([catalogueA], [catalogueB]) => catalogueA.localeCompare(catalogueB))
        .map(([catalogueName, objectName]) => {
            const isCurrent = (item.catalogue || '') === catalogueName;
            const catalogueLabel = catalogueName === 'CommonName'
                ? i18n.t('astrodex.catalogue_label_commonname')
                : catalogueName;
            return `
                <div class="astrodex-catalogue-alias-row">
                    <div class="astrodex-catalogue-alias-label">${escapeHtml(catalogueLabel)}:</div>
                    <div class="astrodex-catalogue-alias-value">${escapeHtml(objectName)}</div>
                    <button
                        type="button"
                        class="btn btn-sm btn-outline-primary"
                        data-action="switch-catalogue-name"
                        data-item-id="${escapeForJs(item.id)}"
                        data-catalogue="${escapeForJs(catalogueName)}"
                        ${isCurrent ? 'disabled' : ''}
                        title="${i18n.t('astrodex.use_this_name')}"
                    ><i class="bi bi-pencil-square" aria-hidden="true"></i></button>
                </div>
            `;
        })
        .join('');

    return `
        <div class="col-md-12">
            <label class="form-label">${i18n.t('astrodex.catalogue_names')}</label>
            <div class="astrodex-catalogue-alias-list">
                ${rows}
            </div>
        </div>
    `;
}

// Whether the MyAstroShine integration is configured and enabled - drives the
// per-photo "Send to MyAstroShine" button. Fetched once per Astrodex session
// (renderPicturesGrid is synchronous, so this must already be resolved by the
// time an item detail modal is built).
let _myAstroShineEnabled = false;
let _myAstroShineStatusChecked = false;

async function _ensureMyAstroShineStatus() {
    if (_myAstroShineStatusChecked) return _myAstroShineEnabled;
    const status = await fetchJSONOnce('/api/astrodex/integration/status').catch(() => null);
    _myAstroShineEnabled = !!(status && status.enabled);
    _myAstroShineStatusChecked = true;
    return _myAstroShineEnabled;
}

// After "Send to MyAstroShine", MyAstroShine calls the board back server-to-server
// to add the enhanced duplicate - the browser gets no push. So when the board tab
// regains focus (the user coming back from MyAstroShine), re-fetch and, if the
// item detail modal is still open, re-render it. Cleared once the new picture is
// seen, or after 30 min.
let _myAstroShineReturn = { itemId: null, expires: 0, lastCheck: 0 };

async function _checkMyAstroShineReturn() {
    const pending = _myAstroShineReturn;
    if (!pending.itemId || Date.now() > pending.expires) return;
    if (document.visibilityState === 'hidden') return;
    if (Date.now() - pending.lastCheck < 8000) return;
    pending.lastCheck = Date.now();

    const itemId = pending.itemId;
    const countPictures = (it) => it
        ? Number(it.total_pictures ?? (Array.isArray(it.own_pictures) ? it.own_pictures : (it.pictures || [])).length)
        : 0;
    const beforeCount = countPictures(astrodexData.items.find(i => i.id === itemId));

    await loadAstrodex();

    const after = astrodexData.items.find(i => i.id === itemId);
    const modalEl = document.getElementById('modal_xl_close');
    if (after && modalEl && modalEl.classList.contains('show')) {
        showAstrodexItemDetail(itemId);
    }
    if (countPictures(after) > beforeCount) {
        if (_myAstroShineReturn.itemId === itemId) {
            _myAstroShineReturn = { itemId: null, expires: 0, lastCheck: 0 };
        }
        showMessage('success', i18n.t('astrodex.enhanced_photo_received'));
    }
}

document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') _checkMyAstroShineReturn();
});
window.addEventListener('focus', _checkMyAstroShineReturn);

function renderPicturesGrid(item) {
    const editablePictures = Array.isArray(item.own_pictures) ? item.own_pictures : (item.pictures || []);

    if (!editablePictures || editablePictures.length === 0) {
        return `
            <div class="col">
                <div class="card h-100">
                    <div class="card-body text-center">
                        <p>${i18n.t('astrodex.no_personal_photos_yet')}</p>
                        <button class="btn btn-primary" data-action="add-picture" data-item-id="${item.id}">${i18n.t('astrodex.add_first_picture')}</button>
                    </div>
                </div>
            </div>
        `;
    }

    return editablePictures.map(picture => {
        const imageUrl = `/api/astrodex/images/${picture.filename}`;
        const escapedImageUrl = escapeHtml(imageUrl);

        // Equipment line: a linked combination wins over the free-text device
        // field (they are mutually exclusive in the model, but legacy/seed
        // pictures can still carry a stale device string alongside a combination).
        const equipmentLabel = picture.combination_id
            ? (_findAstrodexEquipmentName('combinations', picture.combination_id) || i18n.t('astrodex.combination_unavailable'))
            : (picture.device || '');

        return `
            <div class="col">
                <div class="card h-100">
                    <div class="astrodex-card-image-no-hover rounded">
                        <img src="${escapedImageUrl}" class="card-img-top" alt="Photo" >
                        ${picture.is_main ? `<div class="main-badge"><i class="bi bi-star-fill text-warning icon-inline" aria-hidden="true"></i> ${i18n.t('astrodex.main_picture')}</div>` : ''}
                    </div>
                    <div class="card-body">
                        <p class="card-text">
                            ${picture.date ? `<div><i class="bi bi-calendar-event text-danger icon-inline" aria-hidden="true"></i>${escapeHtml(formatStringToDate(picture.date))}</div>` : ''}
                            ${picture.exposition_time ? `<div><i class="bi bi-stopwatch icon-inline" aria-hidden="true"></i>${escapeHtml(formatPictureExpositionTime(picture.exposition_time))}</div>` : ''}
                            ${equipmentLabel ? `<div><i class="bi bi-binoculars icon-inline" aria-hidden="true"></i>${escapeHtml(equipmentLabel)}</div>` : ''}
                            ${picture.location_name ? `<div><i class="bi bi-pin-map icon-inline" aria-hidden="true"></i>${escapeHtml(picture.location_name)}</div>` : ''}
                        </p>
                    </div>
                    <div class="card-footer astrodex-picture-actions">
                        ${picture.observation_session ? `<button class="btn btn-outline-secondary" data-action="view-observation-session" data-session-id="${escapeForJs(picture.observation_session.session_id)}" title="${i18n.t('astrodex.observation_log_picture_tooltip', { date: escapeHtml(picture.observation_session.session_date || '') })}"><i class="bi bi-journal-text" aria-hidden="true"></i></button>` : ''}
                        ${!picture.is_main ? `<button class="btn btn-outline-secondary" data-action="set-main-picture" data-item-id="${escapeForJs(item.id)}" data-picture-id="${escapeForJs(picture.id)}" title="${i18n.t('astrodex.set_as_main')}"><i class="bi bi-star text-warning" aria-hidden="true"></i></button>` : ''}
                        ${_myAstroShineEnabled ? `<button class="btn btn-outline-secondary" data-action="send-to-myastroshine" data-item-id="${escapeForJs(item.id)}" data-picture-id="${escapeForJs(picture.id)}" title="${i18n.t('astrodex.send_to_myastroshine')}"><i class="bi bi-stars text-info" aria-hidden="true"></i></button>` : ''}
                        <button class="btn btn-outline-secondary" data-action="edit-picture" data-item-id="${escapeForJs(item.id)}" data-picture-id="${escapeForJs(picture.id)}" title="${i18n.t('astrodex.edit')}"><i class="bi bi-pencil-square" aria-hidden="true"></i></button>
                        <button class="btn btn-danger" data-action="delete-picture" data-item-id="${escapeForJs(item.id)}" data-picture-id="${escapeForJs(picture.id)}" title="${i18n.t('astrodex.delete')}"><i class="bi bi-trash" aria-hidden="true"></i></button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ============================================
// Picture Management
// ============================================

// Sentinel <option> value for "somewhere else" - a free-text label + optional
// manual coordinates, for one-off trips that aren't worth turning into an
// admin-managed location preset (v1.2).
const _CUSTOM_LOCATION_VALUE = '__other__';

// The user's own attributed locations (with coordinates), cached by the most
// recent _buildPictureLocationOptions() call so the minimap can look up a
// selected preset's lat/lon without a second fetch.
let _pictureLocationChoices = [];

// Shared <option> list for the picture location picker (add + edit forms).
// selectedId omitted -> pre-select the current active location (add-picture
// default). selectedId passed explicitly (including '', null, or
// _CUSTOM_LOCATION_VALUE) -> pre-select exactly that.
async function _buildPictureLocationOptions(selectedId) {
    let locations = [];
    let activeId = null;
    if (typeof fetchMyLocations === 'function') {
        try {
            const data = await fetchMyLocations();
            locations = (data && data.locations) || [];
            activeId = data?.active_location_id ?? null;
        } catch (_) {
            locations = []; // picker degrades to "no location" only - not fatal
        }
    }
    _pictureLocationChoices = locations;
    const effectiveSelected = (selectedId === undefined ? activeId : selectedId) || '';
    const noneSelected = !effectiveSelected ? ' selected' : '';
    const options = [`<option value=""${noneSelected}>${i18n.t('astrodex.no_location')}</option>`];
    locations.forEach(loc => {
        const isSelected = loc.id === effectiveSelected ? ' selected' : '';
        options.push(`<option value="${escapeHtml(loc.id)}"${isSelected}>${escapeHtml(loc.name || '?')}</option>`);
    });
    const otherSelected = effectiveSelected === _CUSTOM_LOCATION_VALUE ? ' selected' : '';
    options.push(`<option value="${_CUSTOM_LOCATION_VALUE}"${otherSelected}>${i18n.t('astrodex.other_location')}</option>`);
    return options.join('');
}

// Location <select> alone (col-md-6, paired with the date field in the same
// row). prefix distinguishes DOM ids ('picture' for add, 'edit-picture' for
// edit). picture omitted -> add form (defaults to the active location);
// picture passed -> edit form (pre-selects whatever the picture already has).
async function _renderLocationSelectField(prefix, picture) {
    const hasPreset = !!picture?.location_id;
    const hasCustom = !!picture && !hasPreset && !!picture.location_name;
    const selectedValue = picture === undefined
        ? undefined
        : (hasPreset ? picture.location_id : (hasCustom ? _CUSTOM_LOCATION_VALUE : ''));
    const options = await _buildPictureLocationOptions(selectedValue);
    return `
        <div class="col-md-6">
            <label for="${prefix}-location" class="form-label">${i18n.t('astrodex.location')}</label>
            <select class="form-select" id="${prefix}-location" onchange="_onPictureLocationChanged('${prefix}')">
                ${options}
            </select>
        </div>
    `;
}

// "Somewhere else" free-text name + optional manual coordinates - its own
// row, only visible while _CUSTOM_LOCATION_VALUE is selected.
function _renderLocationCustomFields(prefix, picture) {
    const hasPreset = !!picture?.location_id;
    const hasCustom = !!picture && !hasPreset && !!picture.location_name;
    const customName = hasCustom ? (picture.location_name || '') : '';
    const customLat = hasCustom && picture.latitude != null ? picture.latitude : '';
    const customLng = hasCustom && picture.longitude != null ? picture.longitude : '';
    const display = hasCustom ? '' : 'none';

    return `
        <div class="col-md-6" id="${prefix}-location-custom-name-block" style="display:${display};">
            <label for="${prefix}-location-custom-name" class="form-label">${i18n.t('astrodex.custom_location_name')}</label>
            <input type="text" class="form-control" id="${prefix}-location-custom-name" placeholder="${i18n.t('astrodex.custom_location_placeholder')}" value="${escapeHtml(customName)}" oninput="_onPictureCoordinatesChanged('${prefix}')">
        </div>
        <div class="col-md-3" id="${prefix}-location-custom-lat-block" style="display:${display};">
            <label for="${prefix}-location-custom-lat" class="form-label">${i18n.t('astrodex.custom_location_lat')}</label>
            <input type="number" step="any" min="-90" max="90" class="form-control" id="${prefix}-location-custom-lat" placeholder="48.85" value="${escapeHtml(String(customLat))}" oninput="_onPictureCoordinatesChanged('${prefix}')">
        </div>
        <div class="col-md-3" id="${prefix}-location-custom-lng-block" style="display:${display};">
            <label for="${prefix}-location-custom-lng" class="form-label">${i18n.t('astrodex.custom_location_lng')}</label>
            <input type="number" step="any" min="-180" max="180" class="form-control" id="${prefix}-location-custom-lng" placeholder="2.35" value="${escapeHtml(String(customLng))}" oninput="_onPictureCoordinatesChanged('${prefix}')">
        </div>
    `;
}

// Minimap row - its own row, only visible while an effective coordinate is
// resolvable (a preset with coordinates, or valid manual lat/lon).
function _renderLocationMapField(prefix) {
    return `
        <div class="col-12" id="${prefix}-location-map-block" style="display:none;">
            <div id="${prefix}-location-map" class="rounded" style="height:200px;"></div>
        </div>
    `;
}

function _toggleCustomLocationFields(prefix) {
    const select = document.getElementById(`${prefix}-location`);
    const isOther = select?.value === _CUSTOM_LOCATION_VALUE;
    ['name', 'lat', 'lng'].forEach(part => {
        const block = document.getElementById(`${prefix}-location-custom-${part}-block`);
        if (block) block.style.display = isOther ? '' : 'none';
    });
}

function _onPictureLocationChanged(prefix) {
    _toggleCustomLocationFields(prefix);
    _updatePictureLocationMap(prefix);
}

let _pictureCoordinatesDebounce = null;
function _onPictureCoordinatesChanged(prefix) {
    clearTimeout(_pictureCoordinatesDebounce);
    _pictureCoordinatesDebounce = setTimeout(() => _updatePictureLocationMap(prefix), 400);
}

// Resolves what the location picker currently implies as a coordinate, or
// null if nothing renderable is selected/typed yet.
function _effectivePictureCoordinates(prefix) {
    const value = document.getElementById(`${prefix}-location`)?.value || '';
    if (!value) return null; // "no location"
    if (value === _CUSTOM_LOCATION_VALUE) {
        const lat = parseFloat(document.getElementById(`${prefix}-location-custom-lat`)?.value);
        const lng = parseFloat(document.getElementById(`${prefix}-location-custom-lng`)?.value);
        return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null;
    }
    const loc = _pictureLocationChoices.find(l => l.id === value);
    const lat = Number(loc?.latitude);
    const lng = Number(loc?.longitude);
    return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null;
}

let _pictureLocationMap = null;

// Shows/hides/re-renders the picture-location minimap for whatever the
// picker currently implies. Only one picture modal is ever open at a time,
// so a single shared map instance (torn down and rebuilt on change) is
// simpler than trying to update an existing one in place.
async function _updatePictureLocationMap(prefix) {
    const block = document.getElementById(`${prefix}-location-map-block`);
    const container = document.getElementById(`${prefix}-location-map`);
    if (!block || !container) return;

    const coords = _effectivePictureCoordinates(prefix);
    if (!coords) {
        block.style.display = 'none';
        if (_pictureLocationMap) {
            try { _pictureLocationMap.remove(); } catch (_) { /* already gone */ }
            _pictureLocationMap = null;
        }
        return;
    }

    block.style.display = '';
    if (typeof _ensureLocationsLeafletLoaded === 'function') {
        try {
            await _ensureLocationsLeafletLoaded();
        } catch (error) {
            console.warn('Leaflet failed to load; picture location map unavailable', error);
            block.style.display = 'none';
            return;
        }
    }
    if (!document.body.contains(container)) return; // modal closed while Leaflet was loading
    if (typeof L === 'undefined') return; // vendor script unavailable - map stays hidden

    if (_pictureLocationMap) {
        try { _pictureLocationMap.remove(); } catch (_) { /* already gone */ }
        _pictureLocationMap = null;
    }
    _pictureLocationMap = L.map(container, { scrollWheelZoom: false, zoomControl: false })
        .setView([coords.lat, coords.lng], 9);
    // Light basemap stays legible for remote sites with little infrastructure.
    addLeafletBasemap(_pictureLocationMap, 'light', { maxZoom: 18 });
    L.marker([coords.lat, coords.lng]).addTo(_pictureLocationMap);
}

// Reads the location picker's current state into the fields the backend
// expects. For a preset, only location_id matters (coordinates are resolved
// server-side). For "somewhere else", sends the typed name + optional
// coordinates as-is - the server treats them as a free-text label, same
// trust level as notes/exposition_time.
function _collectPictureLocationFields(prefix) {
    const value = document.getElementById(`${prefix}-location`)?.value || '';
    if (value === _CUSTOM_LOCATION_VALUE) {
        const lat = document.getElementById(`${prefix}-location-custom-lat`)?.value;
        const lng = document.getElementById(`${prefix}-location-custom-lng`)?.value;
        return {
            location_id: null,
            location_name: document.getElementById(`${prefix}-location-custom-name`)?.value.trim() || '',
            latitude: lat === '' || lat === undefined ? null : lat,
            longitude: lng === '' || lng === undefined ? null : lng,
        };
    }
    return { location_id: value || null, location_name: null };
}

function buildPictureAutocompleteDatalists() {
    // Get autocomplete suggestions from user's previous photos
    const allPictures = [];
    astrodexData.items.forEach(item => {
        if (item.pictures) {
            allPictures.push(...item.pictures);
        }
    });

    // Extract unique values for autocomplete: names from the user's saved
    // equipment/filter library (own + shared) plus whatever free text has
    // actually been typed into past photos, so gear that's set up but not
    // yet used in a photo still shows up as a suggestion.
    const equipmentNames = [
        ...astrodexEquipmentCache.combinations.map(c => c.name),
        ...astrodexEquipmentCache.sharedCombinations.map(c => c.name),
    ];
    const filterNames = [
        ...astrodexEquipmentCache.filters.map(f => f.name),
        ...astrodexEquipmentCache.sharedFilters.map(f => f.name),
    ];
    const devices = [...new Set([...equipmentNames, ...allPictures.map(p => p.device).filter(d => d)])];
    const filters = [...new Set([...filterNames, ...allPictures.map(p => p.filters).filter(f => f)])];
    // Always offer the standard ISO series, plus anything else the user has
    // actually logged (e.g. non-standard values from third-party software).
    const isos = [...new Set([...STANDARD_ISO_VALUES, ...allPictures.map(p => p.iso).filter(i => i)])];

    return {
        deviceOptions: devices.map(d => `<option value="${escapeHtml(d)}">`).join(''),
        filterOptions: filters.map(f => `<option value="${escapeHtml(f)}">`).join(''),
        isoOptions: isos.map(i => `<option value="${escapeHtml(i)}">`).join(''),
    };
}

/** Build a section header row (feature.md's Add/Edit Picture modal sections: File / Date &
 * Location / Equipment / Photo informations). */
function _buildPictureSectionHeaderHtml(labelText) {
    return `
        <div class="col-12 mt-3">
            <h6 class="text-body-secondary mb-0">${escapeHtml(labelText)}</h6>
            <hr class="mt-1 mb-2">
        </div>
    `;
}

/** Build the shared Equipment section markup (add + edit forms): one combination select
 * (enabled combinations + "Other equipment") plus the free-text fallback fields and a checklist
 * placeholder - see _wirePictureEquipmentSection() for the behavior wired in after mount. */
function _buildPictureEquipmentSectionHtml(prefix, picture, deviceOptions, filterOptions) {
    const forceIncludeId = picture?.combination_id || null;
    const selectedComboId = picture ? (picture.combination_id || '') : '';
    const selectedIsOther = !!picture && !picture.combination_id;
    return `
        ${_buildPictureSectionHeaderHtml(i18n.t('astrodex.section_equipment'))}
        <div class="col-md-12">
            <label for="${prefix}-combination-select" class="form-label">${i18n.t('astrodex.equipment_combinations')}</label>
            <select class="form-select" id="${prefix}-combination-select">
                <option value="">${i18n.t('astrodex.select_combination_placeholder')}</option>
                ${_buildPictureCombinationOptions(forceIncludeId, selectedComboId)}
                <option value="${_OTHER_EQUIPMENT_VALUE}" ${selectedIsOther ? 'selected' : ''}>${i18n.t('astrodex.other_equipment')}</option>
            </select>
        </div>
        <div class="col-md-12" id="${prefix}-combo-checklist-wrap" style="display: none;">
            <label class="form-label">${i18n.t('astrodex.combination_used_components_label')}</label>
            <div id="${prefix}-combo-checklist"></div>
        </div>
        <div class="col-md-6" id="${prefix}-other-device-wrap" style="display: none;">
            <label for="${prefix}-device" class="form-label">${i18n.t('astrodex.custom_equipment')}</label>
            <input type="text" class="form-control" id="${prefix}-device" list="device-list" autocomplete="off" value="${escapeHtml(picture?.device || '')}">
            <datalist id="device-list">${deviceOptions}</datalist>
        </div>
        <div class="col-md-6" id="${prefix}-other-filters-wrap" style="display: none;">
            <label for="${prefix}-filters" class="form-label">${i18n.t('astrodex.custom_filters')}</label>
            <input type="text" class="form-control" id="${prefix}-filters" placeholder="${i18n.t('astrodex.filters_placeholder')}" list="filters-list" autocomplete="off" value="${escapeHtml(picture?.filters || '')}">
            <datalist id="filters-list">${filterOptions}</datalist>
        </div>
    `;
}

/** Collect the Equipment section's fields back into a picture payload fragment.
 * `existingCombinationId` (edits only) lets a save preserve a combination link the select
 * couldn't render as an option - e.g. a shared combination whose sharing broke after this
 * picture was tagged with it. Omitting the equipment keys entirely in that case mirrors the
 * backend's "only touched if explicitly included" contract for combination_id (see
 * update_picture_api), instead of the empty/placeholder select value silently clearing the link
 * on an edit that never touched the Equipment section. */
function _collectPictureEquipmentFields(prefix, existingCombinationId) {
    const select = document.getElementById(`${prefix}-combination-select`);
    const isOther = !select || select.value === _OTHER_EQUIPMENT_VALUE || select.value === '';
    if (isOther) {
        if (select && select.value === '' && existingCombinationId
            && !Array.from(select.options).some(o => o.value === existingCombinationId)) {
            return {
                device: document.getElementById(`${prefix}-device`)?.value || '',
                filters: document.getElementById(`${prefix}-filters`)?.value || '',
            };
        }
        return {
            combination_id: null,
            combination_used_components: null,
            device: document.getElementById(`${prefix}-device`)?.value || '',
            filters: document.getElementById(`${prefix}-filters`)?.value || '',
        };
    }
    return {
        combination_id: select.value,
        combination_used_components: _collectCombinationUsedComponents(prefix),
        device: '',
        filters: '',
    };
}

async function showAddPictureModal(itemId) {
    // Get current date in YYYY-MM-DD format
    const today = new Date().toISOString().split('T')[0];

    const { deviceOptions, filterOptions, isoOptions } = buildPictureAutocompleteDatalists();
    const equipmentSectionHtml = _buildPictureEquipmentSectionHtml('picture', null, deviceOptions, filterOptions);

    // Location picker (v1.2) - defaults to the active location but the
    // uploader can change/clear it, since a photo is often uploaded well
    // after the session (stacking/processing takes time) and may not have
    // been taken wherever the browser's active location currently is.
    const locationSelectField = await _renderLocationSelectField('picture');
    const locationCustomFields = _renderLocationCustomFields('picture');
    const locationMapField = _renderLocationMapField('picture');

    createModal(`${i18n.t('astrodex.add_picture')}`, `
        <form id="add-picture-form" class="form row g-3 align-items-end">
            ${_buildPictureSectionHeaderHtml(i18n.t('astrodex.section_file'))}
            <div class="col-md-12">
                <label for="picture-file" class="form-label">${i18n.t('astrodex.image_file')} *</label>
                <input type="file" class="form-control" id="picture-file" accept="image/*" required>
            </div>
            ${_buildPictureSectionHeaderHtml(i18n.t('astrodex.section_date_location'))}
            <div class="col-md-6">
                <label for="picture-date" class="form-label">${i18n.t('astrodex.observation_date')}</label>
                <input type="date" class="form-control" id="picture-date" value="${escapeHtml(today)}">
            </div>
            ${locationSelectField}
            ${locationCustomFields}
            ${locationMapField}
            ${equipmentSectionHtml}
            ${_buildPictureSectionHeaderHtml(i18n.t('astrodex.section_photo_info'))}
            <div class="col-md-6">
                <label for="picture-exposition" class="form-label">${i18n.t('astrodex.exposition_time')}</label>
                <input type="number" class="form-control" id="picture-exposition" min="0" step="1">
            </div>
            <div class="col-md-6">
                <label for="picture-frames" class="form-label">${i18n.t('astrodex.number_of_frames')}</label>
                <input type="number" class="form-control" id="picture-frames" min="0" step="1">
            </div>
            <div class="col-md-6">
                <label for="picture-integration" class="form-label">${i18n.t('astrodex.integration_minutes')}</label>
                <input type="number" class="form-control" id="picture-integration" min="0" step="any">
            </div>
            <div class="col-md-6">
                <label for="picture-iso" class="form-label">${i18n.t('astrodex.iso')}</label>
                <input type="text" class="form-control" id="picture-iso" list="iso-list" autocomplete="off">
                <datalist id="iso-list">
                    ${isoOptions}
                </datalist>
            </div>
            <div class="col-md-12">
                <label class="form-label d-block">${i18n.t('astrodex.rating')}</label>
                <div id="picture-rating-container"></div>
            </div>
            <div class="col-md-12">
                <label for="picture-notes" class="form-label">${i18n.t('astrodex.form_notes')}</label>
                <textarea id="picture-notes" class="form-control" rows="3"></textarea>
            </div>
            <div class="form-actions text-end">
                <button type="submit" class="btn btn-primary">${i18n.t('astrodex.upload_photo')}</button>
            </div>
        </form>
    `, 'lg');

    openModal('#modal_lg_close', {
        backdrop: 'static',
        // Leaflet must measure a fully laid-out, visible container - initializing
        // while the modal is still mid fade-in gives it the wrong size and only the
        // top-left tile renders. Wait for shown.bs.modal.
        onShown: () => _updatePictureLocationMap('picture'),
    });

    document.getElementById('picture-rating-container')?.appendChild(_buildRatingWidget('picture', null));
    _wirePictureEquipmentSection('picture', null, null);
    _wireCaptureTriadInputs('picture');

    document.getElementById('add-picture-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await uploadPicture(itemId);
    });
}

async function uploadPicture(itemId) {
    const fileInput = document.getElementById('picture-file');
    const file = fileInput.files[0];

    if (!file) {
        showMessage('error', i18n.t('astrodex.please_select_image'));
        return;
    }

    // Find the submit button and disable it to prevent multiple submissions
    const submitButton = document.querySelector('#add-picture-form button[type="submit"]');
    const originalButtonText = submitButton.textContent;

    try {
        // Disable button and show loading state
        submitButton.disabled = true;
        submitButton.textContent = i18n.t('astrodex.uploading');

        // Upload file first
        const formData = new FormData();
        formData.append('file', file);

        const uploadResponse = await fetchWithRetry('/api/astrodex/upload', {
            method: 'POST',
            body: formData,
            credentials: 'include'
        }, {
            maxAttempts: 1,
            timeoutMs: 30000
        });

        if (!uploadResponse.ok) {
            throw new Error('Upload failed');
        }

        const uploadResult = await uploadResponse.json();

        // Add picture metadata
        const pictureData = {
            filename: uploadResult.filename,
            date: document.getElementById('picture-date').value,
            exposition_time: document.getElementById('picture-exposition').value,
            iso: document.getElementById('picture-iso').value,
            frames: document.getElementById('picture-frames').value,
            integration_minutes: document.getElementById('picture-integration').value,
            rating: _getRatingWidgetValue('picture'),
            notes: document.getElementById('picture-notes').value,
            ..._collectPictureEquipmentFields('picture'),
            ..._collectPictureLocationFields('picture')
        };

        const response = await fetchJSON(`/api/astrodex/items/${itemId}/pictures`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(pictureData)
        });

        if (response.status === 'success') {
            // No alert on success
            await loadAstrodex();
            // showAstrodexItemDetail() -> openModal() closes the upload modal, waits
            // for it to finish, then swaps in the detail view (no stacked-modal race).
            showAstrodexItemDetail(itemId);
            // Modal closes, so no need to re-enable button
        }
    } catch (error) {
        console.error('Error uploading picture:', error);
        showMessage('error', i18n.t('astrodex.failed_to_upload_photo'));
        // Re-enable button on error so user can retry
        submitButton.disabled = false;
        submitButton.textContent = originalButtonText;
    }
}

async function setMainPicture(itemId, pictureId) {
    try {
        await fetchJSON(`/api/astrodex/items/${itemId}/pictures/${pictureId}/main`, {
            method: 'POST'
        });

        // No alert on success
        await loadAstrodex();
        closeModal();
        //showAstrodexItemDetail(itemId);
    } catch (error) {
        console.error('Error setting main picture:', error);
        showMessage('error', i18n.t('astrodex.failed_to_update_main_photo'));
    }
}

async function sendPictureToMyAstroShine(itemId, pictureId) {
    try {
        const result = await fetchJSONOnce('/api/astrodex/integration/handoff', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_id: itemId, picture_id: pictureId }),
        });
        if (result && result.open_url) {
            window.open(result.open_url, '_blank', 'noopener');
            // Arm the "refresh when the user comes back" check (see _checkMyAstroShineReturn).
            _myAstroShineReturn = { itemId, expires: Date.now() + 30 * 60 * 1000, lastCheck: Date.now() };
        } else {
            showMessage('error', i18n.t('astrodex.send_to_myastroshine_error'));
        }
    } catch (error) {
        console.error('Error opening MyAstroShine:', error);
        showMessage('error', i18n.t('astrodex.send_to_myastroshine_error'));
    }
}

async function deletePicture(itemId, pictureId) {
    if (window.confirm(i18n.t('astrodex.confirm_delete_photo'))) {
        try {
            await fetchJSON(`/api/astrodex/items/${itemId}/pictures/${pictureId}`, {
                method: 'DELETE'
            });

            showMessage('success', i18n.t('astrodex.photo_deleted'));
            await loadAstrodex();
            showAstrodexItemDetail(itemId);
        } catch (error) {
            console.error('Error deleting picture:', error);
            showMessage('error', i18n.t('astrodex.failed_to_delete_photo'));
        }
    }
}

// ============================================
// Item Management
// ============================================

async function deleteAstrodexItem(itemId) {
    // Get the item name before deleting
    const item = astrodexData.items.find(i => i.id === itemId);
    const itemPayload = item ? item : null;

    if (window.confirm(i18n.t('astrodex.confirm_delete_item'))) {
        try {
            await fetchJSON(`/api/astrodex/items/${itemId}`, {
                method: 'DELETE'
            });

            showMessage('success', i18n.t('astrodex.item_deleted'));
            await loadAstrodex();

            // Update catalogue badges if the function exists (from app.js)
            if (itemPayload && typeof updateCatalogueCapturedBadge === 'function') {
                updateCatalogueCapturedBadge(itemPayload, false);
            }

            closeModal();
        } catch (error) {
            console.error('Error deleting item:', error);
            showMessage('error', i18n.t('astrodex.failed_to_delete_item'));
        }
    }
}

async function switchItemCatalogueName(itemId, catalogue) {
    try {
        const response = await fetchJSON(`/api/astrodex/items/${itemId}/catalogue-name`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ catalogue })
        });

        if (response.status === 'success') {
            await loadAstrodex();
            showAstrodexItemDetail(itemId);
            showMessage('success', i18n.t('astrodex.object_name_updated'));
        } else {
            showMessage('error', response.error || i18n.t('astrodex.failed_to_update_object_name'));
        }
    } catch (error) {
        console.error('Error switching catalogue name:', error);
        showMessage('error', i18n.t('astrodex.failed_to_update_object_name'));
    }
}

async function updateItemField(itemId, field, value) {
    try {
        const updates = {};
        updates[field] = value;

        await fetchJSON(`/api/astrodex/items/${itemId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(updates)
        });

        // Update local data
        const item = astrodexData.items.find(i => i.id === itemId);
        if (item) {
            item[field] = value;
        }

        showMessage('success', i18n.t('astrodex.updated_successfully'));
    } catch (error) {
        console.error('Error updating item:', error);
        showMessage('error', i18n.t('astrodex.failed_to_update_item'));
    }
}

async function showEditPictureModal(itemId, pictureId) {
    const item = astrodexData.items.find(i => i.id === itemId);
    if (!item) return;

    const picture = item.pictures.find(p => p.id === pictureId);
    if (!picture) return;

    const { deviceOptions, filterOptions, isoOptions } = buildPictureAutocompleteDatalists();
    const equipmentSectionHtml = _buildPictureEquipmentSectionHtml('edit-picture', picture, deviceOptions, filterOptions);

    // Pre-select whatever location this picture already has (preset, custom
    // free-text label, or "no location" for old pictures that predate this
    // field entirely) - never silently overridden by the active location.
    const locationSelectField = await _renderLocationSelectField('edit-picture', picture);
    const locationCustomFields = _renderLocationCustomFields('edit-picture', picture);
    const locationMapField = _renderLocationMapField('edit-picture');

    // Pre-v1.3 pictures may carry a free-text exposition_time (e.g. "1h (10sec)") from
    // before the field was tightened to a plain integer number of seconds - it can't be
    // reinterpreted automatically, so the field is left blank with an explanatory notice
    // rather than silently dropping or misparsing the old value.
    const expositionRaw = picture.exposition_time;
    const isLegacyExposition = expositionRaw != null && expositionRaw !== ''
        && !(typeof expositionRaw === 'number' || /^\d+$/.test(String(expositionRaw).trim()));
    const expositionInputValue = isLegacyExposition ? '' : escapeHtml(expositionRaw ?? '');

    createModal(i18n.t('astrodex.edit_photo'), `
        <form id="edit-picture-form" class="form row g-3 align-items-end">
            ${picture.enhanced_by === 'myastroshine' ? `
                <div class="col-12">
                    <div class="small text-muted mb-0">
                        <i class="bi bi-stars text-info me-1" aria-hidden="true"></i>${i18n.t('astrodex.enhanced_with_myastroshine', { date: escapeHtml(formatDateFull(picture.enhanced_at) || '') })}
                        ${picture.enhanced_parameters && Object.keys(picture.enhanced_parameters).length ? `<a class="ms-1" data-bs-toggle="collapse" href="#enhanced-params-view">${i18n.t('astrodex.enhanced_view_settings')}</a>` : ''}
                    </div>
                    ${picture.enhanced_parameters && Object.keys(picture.enhanced_parameters).length ? `
                        <div class="collapse" id="enhanced-params-view">
                            <pre class="small bg-body-tertiary p-2 rounded mt-2 mb-0">${escapeHtml(JSON.stringify(picture.enhanced_parameters, null, 2))}</pre>
                        </div>
                    ` : ''}
                </div>
            ` : ''}
            ${_buildPictureSectionHeaderHtml(i18n.t('astrodex.section_date_location'))}
            <div class="col-md-6">
                <label for="edit-picture-date" class="form-label">${i18n.t('astrodex.observation_date')}</label>
                <input type="date" class="form-control" id="edit-picture-date" value="${escapeHtml(picture.date || '')}">
            </div>
            ${locationSelectField}
            ${locationCustomFields}
            ${locationMapField}
            ${equipmentSectionHtml}
            ${_buildPictureSectionHeaderHtml(i18n.t('astrodex.section_photo_info'))}
            ${isLegacyExposition ? `
                <div class="col-md-12">
                    <div class="alert alert-warning small mb-0">
                        ${i18n.t('astrodex.exposition_time_legacy_notice', { value: escapeHtml(String(expositionRaw)) })}
                    </div>
                </div>
            ` : ''}
            <div class="col-md-6">
                <label for="edit-picture-exposition" class="form-label">${i18n.t('astrodex.exposition_time')}</label>
                <input type="number" class="form-control" id="edit-picture-exposition" min="0" step="1" value="${expositionInputValue}">
            </div>
            <div class="col-md-6">
                <label for="edit-picture-frames" class="form-label">${i18n.t('astrodex.number_of_frames')}</label>
                <input type="number" class="form-control" id="edit-picture-frames" min="0" step="1" value="${escapeHtml(picture.frames || '')}">
            </div>
            <div class="col-md-6">
                <label for="edit-picture-integration" class="form-label">${i18n.t('astrodex.integration_minutes')}</label>
                <input type="number" class="form-control" id="edit-picture-integration" min="0" step="any" value="${escapeHtml(picture.integration_minutes ?? '')}">
            </div>
            <div class="col-md-6">
                <label for="edit-picture-iso" class="form-label">${i18n.t('astrodex.iso')}</label>
                <input type="text" class="form-control" id="edit-picture-iso" list="iso-list" autocomplete="off" value="${escapeHtml(picture.iso || '')}">
                <datalist id="iso-list">
                    ${isoOptions}
                </datalist>
            </div>
            <div class="col-md-12">
                <label class="form-label d-block">${i18n.t('astrodex.rating')}</label>
                <div id="edit-picture-rating-container"></div>
            </div>
            <div class="col-md-12">
                <label for="edit-picture-notes" class="form-label">${i18n.t('astrodex.form_notes')}</label>
                <textarea id="edit-picture-notes" class="form-control" rows="3">${escapeHtml(picture.notes || '')}</textarea>
            </div>
            <div class="form-actions text-end">
                <button type="submit" class="btn btn-primary">${i18n.t('astrodex.save_changes')}</button>
            </div>
        </form>
    `, 'lg');

    openModal('#modal_lg_close', {
        backdrop: 'static',
        // See showAddPictureModal - Leaflet must measure a laid-out container.
        onShown: () => _updatePictureLocationMap('edit-picture'),
    });

    document.getElementById('edit-picture-rating-container')?.appendChild(
        _buildRatingWidget('edit-picture', picture.rating)
    );
    _wirePictureEquipmentSection('edit-picture', picture.combination_id || null, picture.combination_used_components);
    _wireCaptureTriadInputs('edit-picture');

    document.getElementById('edit-picture-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await updatePicture(itemId, pictureId);
    });
}

async function updatePicture(itemId, pictureId) {
    try {
        const item = astrodexData.items.find(i => i.id === itemId);
        const existingPicture = item?.pictures.find(p => p.id === pictureId);

        const pictureData = {
            date: document.getElementById('edit-picture-date').value,
            exposition_time: document.getElementById('edit-picture-exposition').value,
            iso: document.getElementById('edit-picture-iso').value,
            frames: document.getElementById('edit-picture-frames').value,
            integration_minutes: document.getElementById('edit-picture-integration').value,
            rating: _getRatingWidgetValue('edit-picture'),
            notes: document.getElementById('edit-picture-notes').value,
            ..._collectPictureEquipmentFields('edit-picture', existingPicture?.combination_id),
            ..._collectPictureLocationFields('edit-picture')
        };

        await fetchJSON(`/api/astrodex/items/${itemId}/pictures/${pictureId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(pictureData)
        });

        // No alert on success
        await loadAstrodex();
        showAstrodexItemDetail(itemId);
    } catch (error) {
        console.error('Error updating picture:', error);
        showMessage('error', i18n.t('astrodex.failed_to_update_photo'));
    }
}

function showPictureSlideshow(itemId) {
    const item = astrodexData.items.find(i => i.id === itemId);
    const slideshowPictures = Array.isArray(item?.pictures) ? item.pictures : [];
    if (!item || slideshowPictures.length === 0) {
        // No pictures, do nothing
        return;
    }

    const picturesWithOwner = slideshowPictures.map(picture => ({
        ...picture,
        owner_username: picture.owner_username || item.owner_username || '',
    }));

    _mountPictureSlideshow(picturesWithOwner, {
        title: `${escapeHtml(item.name)} - ${i18n.t('astrodex.photos')}`,
        objectInfoName: item.name,
    });
}

/**
 * Open the fullscreen slideshow for an arbitrary flat list of pictures (e.g. a
 * Photo Map cluster or single pin), which may span several different Astrodex
 * items/objects. Unlike showPictureSlideshow(), there is no single celestial
 * object to inject an "Object Information" card for, so each slide instead
 * shows its own `item_name` as an info tile.
 *
 * @param {Array<Object>} pictures - Picture-like objects, each carrying at least
 *   `filename` plus the usual info fields (date, device, etc.) and `item_name`.
 * @param {{title?: string}} [options]
 */
function showPictureSlideshowFromPictures(pictures, options = {}) {
    const slideshowPictures = Array.isArray(pictures) ? pictures : [];
    if (slideshowPictures.length === 0) {
        return;
    }

    _mountPictureSlideshow(slideshowPictures, {
        title: options.title || i18n.t('astrodex.photos'),
        showItemNameTile: true,
    });
}

/**
 * Shared slideshow modal shell (image + arrows + keyboard nav + info panel) used
 * by both showPictureSlideshow() (single item, own pictures) and
 * showPictureSlideshowFromPictures() (arbitrary picture list, e.g. a map cluster).
 *
 * @param {Array<Object>} slideshowPictures - Non-empty array of picture objects.
 * @param {{title: string, objectInfoName?: string, showItemNameTile?: boolean}} opts
 */
function _mountPictureSlideshow(slideshowPictures, opts) {
    const showItemNameTile = !!opts.showItemNameTile;

    let currentIndex = 0;
    let keyHandler = null; // Store the handler reference for cleanup

    function updateModalContent() {
        const picture = slideshowPictures[currentIndex];
        const imageUrl = `/api/astrodex/images/${picture.filename}`;
        const ownerUsername = picture.owner_username || '';
        const showOwner = !!ownerUsername && picture.is_owned_by_current_user === false;

        const pictureInfo = `
        <div class="slideshow-info mt-4">
            <div class="row mb-3">
                <div class="col text-center">
                    <span class="badge fs-6 astrodex-slideshow-counter-badge">${i18n.t('astrodex.photo_x_on_y', { current: currentIndex + 1, total: slideshowPictures.length })}</span>
                </div>
            </div>
            ${showOwner ? `
                <div class="row mb-3">
                    <div class="col text-center">
                        <span class="badge bg-secondary fs-6">${i18n.t('astrodex.captured_by', { owner: escapeHtml(ownerUsername) })}</span>
                    </div>
                </div>
            ` : ''}
            <div class="row g-3">
                ${picture.date ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-calendar-event text-danger" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.observation_date')}</small>
                                <strong>${escapeHtml(formatStringToDate(picture.date))}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.exposition_time ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-stopwatch" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.exposition_time')}</small>
                                <strong>${escapeHtml(formatPictureExpositionTime(picture.exposition_time))}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.integration_minutes != null ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-hourglass-split" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.integration_minutes')}</small>
                                <strong>${escapeHtml(picture.integration_minutes)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.device && !picture.combination_id ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-binoculars" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.device_telescope')}</small>
                                <strong>${escapeHtml(picture.device)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.filters ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-palette" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.filters')}</small>
                                <strong>${escapeHtml(picture.filters)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.combination_id ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-camera2" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.equipment_combinations')}</small>
                                <strong>${escapeHtml(_findAstrodexEquipmentName('combinations', picture.combination_id) || i18n.t('astrodex.combination_unavailable'))}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.rating != null ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-star-fill text-warning" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.rating')}</small>
                                <strong>${_buildStarRatingDisplayHtml(picture.rating)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.iso ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-camera" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.iso')}</small>
                                <strong>${escapeHtml(picture.iso)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.frames ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-film" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.number_of_frames')}</small>
                                <strong>${escapeHtml(picture.frames)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.location_name ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-pin-map" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.location')}</small>
                                <strong>${escapeHtml(picture.location_name)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${showItemNameTile && picture.item_name ? `
                    <div class="col-md-6 col-lg-4">
                        <div class="d-flex align-items-center p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-stars text-danger" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.object')}</small>
                                <strong>${escapeHtml(picture.item_name)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
            </div>
            ${picture.notes ? `
                <div class="row mt-3">
                    <div class="col">
                        <div class="d-flex align-items-start p-2 rounded shadow-sm astrodex-slideshow-tile">
                            <div class="me-3 fs-4"><i class="bi bi-journal-text" aria-hidden="true"></i></div>
                            <div>
                                <small class="text-muted d-block">${i18n.t('astrodex.notes')}</small>
                                <p class="mb-0" style="white-space: pre-wrap;">${escapeHtml(picture.notes)}</p>
                            </div>
                        </div>
                    </div>
                </div>
            ` : ''}
        </div>
        `;

        const leftArrow = slideshowPictures.length > 1 && currentIndex > 0 ? `
            <button type="button"
                class="btn btn-lg slideshow-arrow astrodex-slideshow-arrow slideshow-prev position-absolute top-50 start-0 translate-middle-y ms-3
                    d-flex align-items-center justify-content-center"
                aria-label="Previous photo"
                style="z-index: 10; opacity: 0.7; border-radius: 50%; width: 50px; height: 50px;">
                <i class="bi bi-chevron-double-left" aria-hidden="true"></i>
            </button>
        ` : '';

        const rightArrow = slideshowPictures.length > 1 && currentIndex < slideshowPictures.length - 1 ? `
            <button type="button"
                class="btn btn-lg slideshow-arrow astrodex-slideshow-arrow slideshow-next position-absolute top-50 end-0 translate-middle-y me-3
                    d-flex align-items-center justify-content-center"
                aria-label="Next photo"
                style="z-index: 10; opacity: 0.7; border-radius: 50%; width: 50px; height: 50px;">
                <i class="bi bi-chevron-double-right" aria-hidden="true"></i>
            </button>
        ` : '';

        const modalContent = `
            <div class="slideshow-body">
                <div class="slideshow-container position-relative text-center mb-4">
                    <img src="${escapeHtml(imageUrl)}" alt="Photo ${escapeHtml((currentIndex + 1).toString())}" class="slideshow-image img-fluid" style="max-height: 70vh; border-radius: 8px;">
                    ${leftArrow}
                    ${rightArrow}
                </div>
                ${pictureInfo}
            </div>
        `;

        // Update only the slideshow sub-container so the info card below is preserved
        const slideshowWrapper = document.getElementById('slideshow-content-wrapper');
        if (slideshowWrapper) {
            DOMUtils.clear(slideshowWrapper);
            const fragment = document.createRange().createContextualFragment(modalContent);
            slideshowWrapper.appendChild(fragment);

            // Re-attach event listeners to navigation buttons
            attachNavigationListeners();
        }
    }

    function attachNavigationListeners() {
        if (slideshowPictures.length <= 1) return;

        const prevBtn = document.querySelector('.slideshow-prev');
        const nextBtn = document.querySelector('.slideshow-next');

        if (prevBtn) {
            prevBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (currentIndex > 0) {
                    currentIndex--;
                    updateModalContent();
                }
            });

            // Add hover effects
            prevBtn.addEventListener('mouseenter', () => {
                prevBtn.style.opacity = '1';
            });
            prevBtn.addEventListener('mouseleave', () => {
                prevBtn.style.opacity = '0.7';
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (currentIndex < slideshowPictures.length - 1) {
                    currentIndex++;
                    updateModalContent();
                }
            });

            // Add hover effects
            nextBtn.addEventListener('mouseenter', () => {
                nextBtn.style.opacity = '1';
            });
            nextBtn.addEventListener('mouseleave', () => {
                nextBtn.style.opacity = '0.7';
            });
        }
    }

    function setupKeyboardNavigation() {
        // Remove old keyboard handler if exists
        if (keyHandler) {
            document.removeEventListener('keydown', keyHandler);
        }

        // Create and add new keyboard handler
        keyHandler = (e) => {
            if (e.key === 'ArrowLeft' && currentIndex > 0) {
                e.preventDefault();
                currentIndex--;
                updateModalContent();
            } else if (e.key === 'ArrowRight' && currentIndex < slideshowPictures.length - 1) {
                e.preventDefault();
                currentIndex++;
                updateModalContent();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                closeModal('#modal_full_close');
            }
        };

        document.addEventListener('keydown', keyHandler);
    }

    // Create modal using existing Bootstrap structure - body has two stable sub-containers:
    // #slideshow-content-wrapper (replaced on navigation) and #slideshow-object-info-wrapper (persistent)
    createModal(opts.title, '', 'full');

    // Set up the two-part body structure before first render
    const modalBodyInit = document.getElementById('modal_full_close_body');
    if (modalBodyInit) {
        DOMUtils.clear(modalBodyInit);
        const slideshowDiv = document.createElement('div');
        slideshowDiv.id = 'slideshow-content-wrapper';
        const infoDiv = document.createElement('div');
        infoDiv.id = 'slideshow-object-info-wrapper';
        modalBodyInit.appendChild(slideshowDiv);
        modalBodyInit.appendChild(infoDiv);
    }

    // Initialize content and show modal
    updateModalContent();
    setupKeyboardNavigation();
    openModal('#modal_full_close', {
        backdrop: 'static',
        onHidden: () => {
            if (keyHandler) {
                document.removeEventListener('keydown', keyHandler);
                keyHandler = null;
            }
        },
    });

    // Async: inject object-info card into the stable info container (single-item flow only)
    if (typeof injectObjectInfoIntoContainer === 'function' && opts.objectInfoName) {
        const infoContainer = document.getElementById('slideshow-object-info-wrapper');
        if (infoContainer) {
            injectObjectInfoIntoContainer(opts.objectInfoName, infoContainer);
            appendVisibilityCalendarSection(opts.objectInfoName, infoContainer);
        }
    }
}

/**
 * Append a lazily-loaded "Visibility calendar" collapsible below the object-info
 * card in the Astrodex item detail modal. Renders the calendar the first time the
 * section is expanded.
 * @param {string} identifier
 * @param {HTMLElement} container
 */
function appendVisibilityCalendarSection(identifier, container) {
    if (typeof renderVisibilityCalendarInto !== 'function' || !identifier || !container) return;
    const t = (key, fb) => (typeof i18n !== 'undefined' && i18n.has(key)) ? i18n.t(key) : fb;

    const details = document.createElement('details');
    details.className = 'slideshow-info mt-3 vc-astrodex-details';
    const summary = document.createElement('summary');
    summary.className = 'fw-semibold';
    DOMUtils.append(
        summary,
        DOMUtils.createIcon('bi bi-calendar-range icon-inline'),
        ` ${t('visibility_calendar.title', 'Visibility calendar')}`
    );
    details.appendChild(summary);

    const target = document.createElement('div');
    target.className = 'mt-2';
    details.appendChild(target);
    container.appendChild(details);

    let loaded = false;
    details.addEventListener('toggle', () => {
        if (details.open && !loaded) {
            loaded = true;
            renderVisibilityCalendarInto(identifier, null, target);
        }
    });
}

// ============================================
// Utility Functions
// ============================================

async function toggleAstrodexSortOrder() {
    // Get role user
    const roleUser = await getUserRole();
    // Display Astrodex if roleUser is user or admin
    const isAllowedAstrodex = roleUser === 'user' || roleUser === 'admin';

    const button = document.getElementById('astrodex-sort-order');
    if (astrodexFilters.sortOrder === 'asc') {
        astrodexFilters.sortOrder = 'desc';
        DOMUtils.clear(button);
        DOMUtils.append(button, DOMUtils.createIcon('bi bi-sort-down-alt icon-inline'), i18n.t('astrodex.sort_order_descending'));
    } else {
        astrodexFilters.sortOrder = 'asc';
        DOMUtils.clear(button);
        DOMUtils.append(button, DOMUtils.createIcon('bi bi-sort-up-alt icon-inline'), i18n.t('astrodex.sort_order_ascending'));
    }
    renderAstrodexView(isAllowedAstrodex);
}

function createModal(title, content, size = 'lg') {
    //console.log('Creating modal with title:', title);

    //Prepare modal title
    const titleElement = document.getElementById(`modal_${size}_close_title`);
    titleElement.textContent = `${title}`;

    //Prepare modal content
    const contentElement = document.getElementById(`modal_${size}_close_body`);
    DOMUtils.clear(contentElement);
    if (content instanceof Node) {
        contentElement.appendChild(content);
        return;
    }

    const contentString = String(content || '');
    if (!contentString) {
        return;
    }

    const fragment = document.createRange().createContextualFragment(contentString);
    contentElement.appendChild(fragment);
}

// openModal() / closeModal() live in utils.js - a single Bootstrap-instance lifecycle
// shared by every feature that reuses the generic modal shells.

// ============================================
// Event Listeners Initialization
// ============================================

async function initializeAstrodexEventListeners() {
    // Get role user
    const roleUser = await getUserRole();
    // Display Astrodex if roleUser is user or admin
    const isAllowedAstrodex = roleUser === 'user' || roleUser === 'admin';
    //console.log('User role:', roleUser, ' - Access to Astrodex:', isAllowedAstrodex);

    // Use event delegation for dynamically created elements
    const astrodexTab = document.getElementById('astrodex-tab');
    if (!astrodexTab) return;

    //Buttons

    //Init buttons - wait for translations to be loaded before setting labels
    await i18n.ready;
    const buttonSort = document.getElementById('astrodex-sort-order');
    DOMUtils.clear(buttonSort);
    DOMUtils.append(buttonSort, DOMUtils.createIcon('bi bi-sort-up-alt icon-inline'), i18n.t('astrodex.sort_order_ascending'));
    const buttonAddItem = document.getElementById('add-astrodex-item');
    DOMUtils.clear(buttonAddItem);
    DOMUtils.append(buttonAddItem, DOMUtils.createIcon('bi bi-plus-circle icon-inline'), i18n.t('astrodex.add_object'));

    // ============================================
    // Event delegation on document.body for modals and dynamic content
    // ============================================

    // Handle clicks on modals and dynamic elements (anywhere in document)
    document.body.addEventListener('click', (e) => {
        const target = e.target;
        const button = target.closest('button');

        // Handle buttons with data-action
        if (button) {
            const action = button.getAttribute('data-action');
            const itemId = button.getAttribute('data-item-id');
            const pictureId = button.getAttribute('data-picture-id');
            const catalogue = button.getAttribute('data-catalogue');
            const sessionId = button.getAttribute('data-session-id');

            switch (action) {
                case 'add-picture':
                    e.preventDefault();
                    if (isAllowedAstrodex) {
                        showAddPictureModal(itemId);
                    }
                    break;
                case 'delete-item':
                    e.preventDefault();
                    if (isAllowedAstrodex) {
                        deleteAstrodexItem(itemId);
                    }
                    break;
                case 'set-main-picture':
                    e.preventDefault();
                    if (isAllowedAstrodex) {
                        setMainPicture(itemId, pictureId);
                    }
                    break;
                case 'edit-picture':
                    e.preventDefault();
                    if (isAllowedAstrodex) {
                        showEditPictureModal(itemId, pictureId);
                    }
                    break;
                case 'delete-picture':
                    e.preventDefault();
                    if (isAllowedAstrodex) {
                        deletePicture(itemId, pictureId);
                    }
                    break;
                case 'send-to-myastroshine':
                    e.preventDefault();
                    if (isAllowedAstrodex) {
                        sendPictureToMyAstroShine(itemId, pictureId);
                    }
                    break;
                case 'switch-catalogue-name':
                    e.preventDefault();
                    if (isAllowedAstrodex) {
                        switchItemCatalogueName(itemId, catalogue);
                    }
                    break;
                case 'view-observation-session':
                    // Read-only navigation, available to read-only users too (they can
                    // view the Observation Log, just not edit it).
                    e.preventDefault();
                    if (typeof openObservationSessionFromAstrodex === 'function') {
                        openObservationSessionFromAstrodex(sessionId);
                    }
                    break;
            }
        }
    });

    // ============================================
    // Event delegation on #astrodex-tab for tab-specific content
    // ============================================

    // Handle clicks on Astrodex tab
    astrodexTab.addEventListener('click', (e) => {
        const target = e.target;
        const button = target.closest('button');
        const cardImage = target.closest('.astrodex-card-image');
        const cardBody = target.closest('.astrodex-card-body');

        // Handle buttons with data-action (tab-specific)
        if (button) {
            const action = button.getAttribute('data-action');

            switch (action) {
                case 'add-astrodex-item':
                    e.preventDefault();
                    if (isAllowedAstrodex) {
                        showAddAstrodexItemModal();
                    }
                    break;
            }
        }

        // Handle card image clicks (slideshow)
        if (cardImage && !button) {
            const itemId = cardImage.getAttribute('data-item-id');
            if (itemId) {
                showPictureSlideshow(itemId);
            }
        }

        // Handle card body clicks (detail view)
        if (cardBody && !button && !cardImage) {
            const itemId = cardBody.getAttribute('data-item-id');
            if (itemId) {
                const item = astrodexData.items.find(i => i.id === itemId);
                if (!item) return;

                if (item.is_owned_by_current_user === false) {
                    showPictureSlideshow(itemId);
                    return;
                }

                if (isAllowedAstrodex) {
                    showAstrodexItemDetail(itemId);
                }
            }
        }
    });

    // Handle keyboard events on Astrodex tab
    astrodexTab.addEventListener('keydown', (e) => {
        const target = e.target;

        if (e.key === 'Enter' || e.key === ' ') {
            const cardImage = target.closest('.astrodex-card-image');
            const cardBody = target.closest('.astrodex-card-body');

            if (cardImage) {
                e.preventDefault();
                const itemId = cardImage.getAttribute('data-item-id');
                if (itemId) showPictureSlideshow(itemId);
            } else if (cardBody) {
                e.preventDefault();
                const itemId = cardBody.getAttribute('data-item-id');
                if (!itemId) return;

                const item = astrodexData.items.find(i => i.id === itemId);
                if (!item) return;

                if (item.is_owned_by_current_user === false) {
                    showPictureSlideshow(itemId);
                } else if (isAllowedAstrodex) {
                    showAstrodexItemDetail(itemId);
                }
            }
        }
    });

    // Handle change events on document.body for modal form fields
    document.body.addEventListener('change', (e) => {
        const target = e.target;
        const action = target.getAttribute('data-action');
        const itemId = target.getAttribute('data-item-id');
        const field = target.getAttribute('data-field');

        if (action === 'update-field' && itemId && field) {
            const item = astrodexData.items.find(i => i.id === itemId);
            if (item && item.is_owned_by_current_user === false) {
                return;
            }
            updateItemField(itemId, field, target.value);
        }
    });

    // Handle change events on filter/sort controls
    const searchInput = document.getElementById('astrodex-search');
    const typeFilter = document.getElementById('astrodex-type-filter');
    const photoFilter = document.getElementById('astrodex-photo-filter');
    const sortSelect = document.getElementById('astrodex-sort');
    const sortOrderBtn = document.getElementById('astrodex-sort-order');

    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            updateAstrodexFilter('search', e.target.value, isAllowedAstrodex);
        });
    }

    if (typeFilter) {
        typeFilter.addEventListener('change', (e) => {
            updateAstrodexFilter('type', e.target.value, isAllowedAstrodex);
        });
    }

    if (photoFilter) {
        photoFilter.addEventListener('change', (e) => {
            updateAstrodexFilter('hasPhotos', e.target.value, isAllowedAstrodex);
        });
    }

    if (sortSelect) {
        sortSelect.addEventListener('change', (e) => {
            updateAstrodexFilter('sortBy', e.target.value, isAllowedAstrodex);
        });
    }

    if (sortOrderBtn) {
        sortOrderBtn.addEventListener('click', () => {
            toggleAstrodexSortOrder();
        });
    }
}

// Bootstrap sets aria-hidden="true" on the modal element at the start of the
// hide transition, but the focused element (e.g. the Close button) may still
// be inside the modal at that point, triggering an accessibility warning.
// Blurring it on `hide.bs.modal` - which fires before aria-hidden is applied -
// moves focus to <body> first so the attribute change is clean.
document.addEventListener('hide.bs.modal', (e) => {
    const focused = e.target.querySelector(':focus');
    if (focused) focused.blur();
});

// Initialize event listeners when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeAstrodexEventListeners);
} else {
    initializeAstrodexEventListeners();
}
