// Astrodex functionality
// Pokédex-style collection system for astrophotography objects

let astrodexData = {
    items: [],
    stats: {},
    privateMode: true,
    currentUserId: null
};

let currentAstrodexItem = null;
let astrodexFilters = {
    search: '',
    type: 'all',
    hasPhotos: 'all',
    sortBy: 'name',
    sortOrder: 'asc'
};

function getObjectTypeOptionsHtml(selectedType = '') {
    const objectTypes = [
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
        ['Other', 'type_other'],
    ];

    return objectTypes
        .map(([value, key]) => `<option value="${value}" ${selectedType === value ? 'selected' : ''}>${tSkyTonightCompat(key)}</option>`)
        .join('');
}

// ============================================
// Equipment Integration
// ============================================

let astrodexEquipmentCache = {
    combinations: [],
    sharedCombinations: [],
    filters: [],
    sharedFilters: []
};

async function loadEquipmentForAstrodex() {
    try {
        // Load combinations (own + shared)
        const combosRes = await fetchJSON('/api/equipment/combinations');
        astrodexEquipmentCache.combinations = combosRes.data || [];
        astrodexEquipmentCache.sharedCombinations = combosRes.shared_from_others || [];

        // Load filters (own + shared)
        const filtersRes = await fetchJSON('/api/equipment/filters');
        astrodexEquipmentCache.filters = filtersRes.data || [];
        astrodexEquipmentCache.sharedFilters = filtersRes.shared_from_others || [];
    } catch (error) {
        console.error('Error loading equipment for Astrodex:', error);
    }
}

function buildEquipmentCombinationOptions() {
    const own = astrodexEquipmentCache.combinations
        .map(combo => `<option value="${escapeHtml(combo.name)}" data-combo-id="${combo.id}">${escapeHtml(combo.name)}</option>`)
        .join('');
    const shared = astrodexEquipmentCache.sharedCombinations
        .map(combo => {
            const label = combo.owner_username
                ? `${escapeHtml(combo.name)} ${i18n.t('equipment.shared_fov_suffix', { username: escapeHtml(combo.owner_username) })}`
                : escapeHtml(combo.name);
            return `<option value="${escapeHtml(combo.name)}" data-combo-id="${combo.id}">${label}</option>`;
        })
        .join('');
    return own + shared;
}

function buildEquipmentFilterOptions() {
    const own = astrodexEquipmentCache.filters
        .map(filter => `<option value="${escapeHtml(filter.name)}" data-filter-id="${filter.id}">${escapeHtml(filter.name)}</option>`)
        .join('');
    const shared = astrodexEquipmentCache.sharedFilters
        .map(filter => {
            const label = filter.owner_username
                ? `${escapeHtml(filter.name)} ${i18n.t('equipment.shared_fov_suffix', { username: escapeHtml(filter.owner_username) })}`
                : escapeHtml(filter.name);
            return `<option value="${escapeHtml(filter.name)}" data-filter-id="${filter.id}">${label}</option>`;
        })
        .join('');
    return own + shared;
}

function updateDeviceField() {
    const select = document.getElementById('picture-device-select');
    const textField = document.getElementById('picture-device');
    if (select && textField && select.value) {
        textField.value = select.value;
    }
}

function updateFilterField() {
    const select = document.getElementById('picture-filters-select');
    const textField = document.getElementById('picture-filters');
    if (select && textField && select.value) {
        textField.value = select.value;
    }
}

function updateEditDeviceField() {
    const select = document.getElementById('edit-picture-device-select');
    const textField = document.getElementById('edit-picture-device');
    if (select && textField && select.value) {
        textField.value = select.value;
    }
}

function updateEditFilterField() {
    const select = document.getElementById('edit-picture-filters-select');
    const textField = document.getElementById('edit-picture-filters');
    if (select && textField && select.value) {
        textField.value = select.value;
    }
}

// ============================================
// Astrodex Data Loading
// ============================================

async function loadAstrodex() {
    try {
           
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
        if(isAllowedAstrodex) {
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
        title.innerHTML = `<i class="bi bi-galaxy text-warning icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.my_collection')}`;
        if (subtitle) {
            subtitle.textContent = i18n.t('astrodex.your_collection');
        }
    } else {
        title.innerHTML = `<i class="bi bi-galaxy text-warning icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.common_collection')}`;
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
            title.innerHTML = `<i class="bi bi-journal-bookmark icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.astrodex_empty')}`;
            body.appendChild(title);
            body.appendChild(document.createElement('br'));
            body.append(i18n.t('astrodex.start_adding'));

            const footer = document.createElement('div');
            footer.className = 'card-footer text-center';
            const button = document.createElement('button');
            button.className = 'btn btn-outline-primary';
            button.setAttribute('data-action', 'add-astrodex-item');
            button.innerHTML = `<i class="bi bi-plus-circle icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.add_object')}`;
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
            title.innerHTML = '<i class="bi bi-journal-bookmark icon-inline" aria-hidden="true"></i>Astrodex is empty';
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
            badge.innerHTML = `${photoCount} <i class="bi bi-camera" aria-hidden="true"></i>`;
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

        if (item.constellation) {
            const constellationLabel = getConstellationDisplayName(item.constellation);

            const constellation = document.createElement('div');
            constellation.className = 'astrodex-card-constellation';
            constellation.innerHTML = `<i class="bi bi-geo-alt text-danger icon-inline" aria-hidden="true"></i>${constellationLabel}`;
            body.appendChild(constellation);
        }

        if (!isOwnedByCurrentUser) {
            const owner = document.createElement('div');
            owner.className = 'astrodex-card-constellation';
            owner.innerHTML = `<i class="bi bi-person text-primary icon-inline" aria-hidden="true"></i>${item.owner_username || 'Shared'}`;
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
    
    // Apply sorting
    items.sort((a, b) => {
        let compareA, compareB;
        
        switch (astrodexFilters.sortBy) {
            case 'name':
                compareA = a.name.toLowerCase();
                compareB = b.name.toLowerCase();
                break;
            case 'type':
                compareA = (a.type || '').toLowerCase();
                compareB = (b.type || '').toLowerCase();
                break;
            case 'date':
                compareA = new Date(a.created_at || 0);
                compareB = new Date(b.created_at || 0);
                break;
            case 'photos':
                compareA = a.pictures ? a.pictures.length : 0;
                compareB = b.pictures ? b.pictures.length : 0;
                break;
            default:
                return 0;
        }
        
        if (compareA < compareB) return astrodexFilters.sortOrder === 'asc' ? -1 : 1;
        if (compareA > compareB) return astrodexFilters.sortOrder === 'asc' ? 1 : -1;
        return 0;
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

async function addToAstrodex(itemData) {
    try {
        const response = await fetchJSON('/api/astrodex/items', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(itemData)
        });
        
        if (response.status === 'success') {
            // No alert on success - just redirect to item
            await loadAstrodex();
            
            // Update catalogue badges if the function exists (from app.js)
            if (typeof updateCatalogueCapturedBadge === 'function') {
                updateCatalogueCapturedBadge(response.item || itemData, true);
            }
            
            return true;
        } else {
            showMessage('error', response.error || i18n.t('astrodex.failed_to_add_item'));
            return false;
        }
    } catch (error) {
        console.error('Error adding to astrodex:', error);
        if (error.message && error.message.includes('already exists')) {
            showMessage('warning', i18n.t('astrodex.item_already_exists'));
        } else {
            showMessage('error', i18n.t('astrodex.failed_to_add_astrodex_item'));
        }
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

    closeModal(); // Close any existing modal to avoid stacking

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
                <input type="text" id="item-name" class="form-control" required autocomplete="off">
                <input type="hidden" id="item-catalogue" value="">
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
                <textarea id="item-notes" class="form-control" rows="3"placeholder="${i18n.t('astrodex.form_notes_placeholder')}"></textarea>
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

    function _mapCatalogueType(rawType) {
        if (!rawType) return '';
        const t = rawType.toLowerCase();
        if (t.includes('open cluster')) return 'Open Cluster';
        if (t.includes('globular')) return 'Globular Cluster';
        if (t.includes('galaxy')) return 'Galaxy';
        if (t.includes('planetary nebula')) return 'Planetary Nebula';
        if (t.includes('nebula') || t.includes('supernova') || t.includes('remnant')) return 'Nebula';
        if (t.includes('star cluster') || t.includes('cluster')) return 'Star Cluster';
        if (t.includes('planet')) return 'Planet';
        if (t.includes('moon')) return 'Moon';
        if (t.includes('comet')) return 'Comet';
        return 'Other';
    }

    async function _triggerCatalogueSearch() {
        const val = (searchInput?.value || '').trim();
        if (!val) return;

        if (searchBtn) {
            searchBtn.disabled = true;
            searchBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
        }
        if (feedbackEl) feedbackEl.classList.add('d-none');

        try {
            const res = await fetchJSON(`/api/astrodex/catalogue-lookup?name=${encodeURIComponent(val)}`);

            if (!res || !res.found) {
                if (feedbackEl) {
                    feedbackEl.innerHTML = `<span class="badge bg-warning text-dark"><i class="bi bi-exclamation-circle me-1"></i>${i18n.t('astrodex.catalogue_not_found')}</span>`;
                    feedbackEl.classList.remove('d-none');
                }
                return;
            }

            const nameInput = document.getElementById('item-name');
            const typeSelect = document.getElementById('item-type');
            const constSelect = document.getElementById('item-constellation');
            const catInput = document.getElementById('item-catalogue');

            if (nameInput) nameInput.value = res.preferred_name || val;

            // Resolve catalogue key matching the preferred_name
            let matchedCat = '';
            for (const [cat, catName] of Object.entries(res.catalogue_names || {})) {
                if (catName === res.preferred_name) { matchedCat = cat; break; }
            }
            if (catInput) catInput.value = matchedCat;

            if (typeSelect) {
                const mappedType = _mapCatalogueType(res.object_type);
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
                feedbackEl.innerHTML = `<span class="badge bg-success"><i class="bi bi-check-circle me-1"></i>${i18n.t('astrodex.catalogue_found')}</span>`;
                feedbackEl.classList.remove('d-none');
            }
        } catch (_) { /* silent — lookup is best-effort */ }
        finally {
            if (searchBtn) {
                searchBtn.disabled = false;
                searchBtn.innerHTML = '<i class="bi bi-search"></i>';
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
    
    document.getElementById('add-astrodex-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const itemData = {
            name: document.getElementById('item-name').value,
            type: document.getElementById('item-type').value,
            catalogue: document.getElementById('item-catalogue')?.value || '',
            constellation: document.getElementById('item-constellation').value,
            notes: document.getElementById('item-notes').value
        };
        
        const success = await addToAstrodex(itemData);
        if (success) {
            closeModal();
        }
    });

    // Show the modal
    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static', 
        focus: true,
        keyboard: true
    }); 
    bs_modal.show();

    // Event listener when modal is closed
    document.getElementById('modal_lg_close').addEventListener('hidden.bs.modal', () => {
        // Remove previous event listeners to prevent duplicates
        const form = document.getElementById('add-astrodex-form');
        if (form) {
            form.removeEventListener('submit', async (e) => {
                e.preventDefault();
            });
        }

        //Remove self listener to prevent duplicates if modal is opened again
        document.getElementById('modal_lg_close').removeEventListener('hidden.bs.modal', () => {});
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

    // Get list of constellations for select options
    const constellations = await getConstellationsList();
    
    const mainPicture = getMainPicture(item);
    const imageUrl = mainPicture 
        ? `/api/astrodex/images/${escapeHtml(mainPicture.filename)}`
        : '/static/img/default_astro_object.svg';
    
    // Escape values for safe HTML insertion
    const escapedName = escapeHtml(item.name);
    const escapedImageUrl = escapeHtml(imageUrl);
    
    // Escape for JavaScript context
    const jsEscapedName = escapeForJs(item.name);
    const jsEscapedImageUrl = escapeForJs(imageUrl);
    const catalogueAliasesSection = renderCatalogueAliasesSection(item);
    const ownPicturesCount = Array.isArray(item.own_pictures)
        ? item.own_pictures.length
        : (item.pictures ? item.pictures.length : 0);
    const totalPicturesCount = Number(item.total_pictures ?? ownPicturesCount);
    const picturesTitle = totalPicturesCount > ownPicturesCount
        ? i18n.t('astrodex.my_photos', { ownPicturesCount, totalPicturesCount })
        : i18n.t('astrodex.all_photos', { ownPicturesCount });
    
    const modal = createModal(item.name, `                    
        <h3>${i18n.t('astrodex.object_info')}</h3>
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

    const modalEl = document.getElementById('modal_xl_close');
    if (modalEl && modalEl.classList.contains('show')) {
        return;
    }

    // Show the modal
    const bs_modal = new bootstrap.Modal('#modal_xl_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();

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
        // Escape values for safe HTML insertion
        const escapedName = escapeHtml(item.name);
        const imageUrl = `/api/astrodex/images/${picture.filename}`;
        const escapedImageUrl = escapeHtml(imageUrl);
        
        // Escape for JavaScript context
        const jsEscapedName = escapeForJs(item.name);
        const jsEscapedImageUrl = escapeForJs(imageUrl);
        
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
                            ${picture.exposition_time ? `<div><i class="bi bi-stopwatch icon-inline" aria-hidden="true"></i>${escapeHtml(picture.exposition_time)}</div>` : ''}
                            ${picture.device ? `<div><i class="bi bi-binoculars icon-inline" aria-hidden="true"></i>${escapeHtml(picture.device)}</div>` : ''}
                        </p>
                    </div>
                    <div class="card-footer text-center">
                        ${!picture.is_main ? `<button class="btn btn-outline-secondary" data-action="set-main-picture" data-item-id="${escapeForJs(item.id)}" data-picture-id="${escapeForJs(picture.id)}" title="${i18n.t('astrodex.set_as_main')}"><i class="bi bi-star text-warning" aria-hidden="true"></i></button>` : '<span class="btn-icon-placeholder"></span>'}
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

function showAddPictureModal(itemId) {
    closeModal(); // Close current modal to avoid stacking

    // Get current date in YYYY-MM-DD format
    const today = new Date().toISOString().split('T')[0];
    
    // Get autocomplete suggestions from user's previous photos
    const allPictures = [];
    astrodexData.items.forEach(item => {
        if (item.pictures) {
            allPictures.push(...item.pictures);
        }
    });
    
    // Extract unique values for autocomplete
    const devices = [...new Set(allPictures.map(p => p.device).filter(d => d))];
    const filters = [...new Set(allPictures.map(p => p.filters).filter(f => f))];
    const isos = [...new Set(allPictures.map(p => p.iso).filter(i => i))];
    
    // Create datalist options
    const deviceOptions = devices.map(d => `<option value="${escapeHtml(d)}">`).join('');
    const filterOptions = filters.map(f => `<option value="${escapeHtml(f)}">`).join('');
    const isoOptions = isos.map(i => `<option value="${escapeHtml(i)}">`).join('');
    
    // Equipment combination and filter options
    const equipmentComboOptions = buildEquipmentCombinationOptions();
    const equipmentFilterOptions = buildEquipmentFilterOptions();
    
    createModal(`${i18n.t('astrodex.add_picture')}`, `
        <form id="add-picture-form" class="form row g-3">
            <div class="col-md-12">
                <label for="picture-file" class="form-label">${i18n.t('astrodex.image_file')} *</label>
                <input type="file" class="form-control" id="picture-file" accept="image/*" required>
            </div>
            <div class="col-md-6">
                <label for="picture-date" class="form-label">${i18n.t('astrodex.observation_date')}</label>
                <input type="date" class="form-control" id="picture-date" value="${escapeHtml(today)}">
            </div>
            <div class="col-md-6">
                <label for="picture-exposition" class="form-label">${i18n.t('astrodex.exposition_time')}</label>
                <input type="text" class="form-control" id="picture-exposition" placeholder="${i18n.t('astrodex.exposition_time_placeholder')}">
            </div>
            <div class="col-md-6">
                <label for="picture-device" class="form-label">${i18n.t('astrodex.equipment_combinations')}</label>
                <select class="form-select" id="picture-device-select" onchange="updateDeviceField()">
                    <option value="">${i18n.t('astrodex.free_text')}</option>
                    ${equipmentComboOptions}
                </select>
            </div>            
            <div class="col-md-6">
                <label for="picture-device" class="form-label">${i18n.t('astrodex.custom_equipment')}</label>
                <input type="text" class="form-control" id="picture-device" list="device-list" autocomplete="off">
                <datalist id="device-list">
                    ${deviceOptions}
                </datalist>
            </div>
            <div class="col-md-6">
                <label for="picture-filters" class="form-label">${i18n.t('astrodex.filters')}</label>
                <select class="form-select" id="picture-filters-select" onchange="updateFilterField()">
                    <option value="">${i18n.t('astrodex.free_text')}</option>
                    ${equipmentFilterOptions}
                </select>
            </div>
            <div class="col-md-6">
                <label for="picture-filters" class="form-label">${i18n.t('astrodex.custom_filters')}</label>
                <input type="text" class="form-control" id="picture-filters" placeholder="${i18n.t('astrodex.filters_placeholder')}" list="filters-list" autocomplete="off">
                <datalist id="filters-list">
                    ${filterOptions}
                </datalist>
            </div>
            <div class="col-md-6">
                <label for="picture-iso" class="form-label">${i18n.t('astrodex.iso')}</label>
                <input type="text" class="form-control" id="picture-iso" list="iso-list" autocomplete="off">
                <datalist id="iso-list">
                    ${isoOptions}
                </datalist>
            </div>
            <div class="col-md-6">
                <label for="picture-frames" class="form-label">${i18n.t('astrodex.number_of_frames')}</label>
                <input type="text" class="form-control" id="picture-frames">
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

    // Open the modal
    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();
    
    document.getElementById('add-picture-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await uploadPicture(itemId);
    });    

    // Event listener when modal is closed
    document.getElementById('modal_lg_close').addEventListener('hidden.bs.modal', () => {
        //Remove event listener
        const pictureForm = document.getElementById('add-picture-form');
        if (pictureForm) {
            pictureForm.removeEventListener('submit', async (e) => {
                e.preventDefault();
            });
        }

        //Remove self listener to prevent duplicates if modal is opened again
        document.getElementById('modal_lg_close').removeEventListener('hidden.bs.modal', () => {});
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
            device: document.getElementById('picture-device').value,
            filters: document.getElementById('picture-filters').value,
            iso: document.getElementById('picture-iso').value,
            frames: document.getElementById('picture-frames').value,
            notes: document.getElementById('picture-notes').value
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
            closeModal();
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

function showEditPictureModal(itemId, pictureId) {
    closeModal(); // Close current modal to avoid stacking

    const item = astrodexData.items.find(i => i.id === itemId);
    if (!item) return;
    
    const picture = item.pictures.find(p => p.id === pictureId);
    if (!picture) return;
    
    createModal(i18n.t('astrodex.edit_photo'), `
        <form id="edit-picture-form" class="form row g-3">            
            <div class="col-md-6">
                <label for="edit-picture-date" class="form-label">${i18n.t('astrodex.observation_date')}</label>
                <input type="date" class="form-control" id="edit-picture-date" value="${escapeHtml(picture.date || '')}">
            </div>
            <div class="col-md-6">
                <label for="edit-picture-exposition" class="form-label">${i18n.t('astrodex.exposition_time')}</label>
                <input type="text" class="form-control" id="edit-picture-exposition" placeholder="e.g., 120x30s" value="${escapeHtml(picture.exposition_time || '')}">
            </div>
            <div class="col-md-6">
                <label for="edit-picture-device" class="form-label">${i18n.t('astrodex.equipment_combinations')}</label>                
                <select class="form-select" id="edit-picture-device-select" onchange="updateEditDeviceField()">
                    <option value="">${i18n.t('astrodex.free_text')}</option>
                    ${buildEquipmentCombinationOptions()}
                </select>
            </div>
            <div class="col-md-6">
                <label for="edit-picture-device" class="form-label">${i18n.t('astrodex.custom_equipment')}</label>
                <input type="text" class="form-control" id="edit-picture-device" list="device-list" autocomplete="off" value="${escapeHtml(picture.device || '')}">
            </div>
            <div class="col-md-6">
                <label for="edit-picture-filters" class="form-label">${i18n.t('astrodex.filters')}</label>
                <select class="form-select" id="edit-picture-filters-select" onchange="updateEditFilterField()">
                    <option value="">${i18n.t('astrodex.free_text')}</option>
                    ${buildEquipmentFilterOptions()}
                </select>
            </div>
            <div class="col-md-6">
                <label for="edit-picture-filters" class="form-label">${i18n.t('astrodex.custom_filters')}</label>
                <input type="text" class="form-control" id="edit-picture-filters" placeholder="${i18n.t('astrodex.custom_filters_placeholder')}" list="filters-list" autocomplete="off" value="${escapeHtml(picture.filters || '')}">
            </div>
            <div class="col-md-6">
                <label for="edit-picture-iso" class="form-label">${i18n.t('astrodex.iso')}</label>
                <input type="text" class="form-control" id="edit-picture-iso" list="iso-list" autocomplete="off" value="${escapeHtml(picture.iso || '')}">
            </div>
            <div class="col-md-6">
                <label for="edit-picture-frames" class="form-label">${i18n.t('astrodex.number_of_frames')}</label>
                <input type="text" class="form-control" id="edit-picture-frames" value="${escapeHtml(picture.frames || '')}">
            </div>
            <div class="col-md-12">
                <label for="edit-picture-notes" class="form-label">${i18n.t('astrodex.form_notes')}</label>
                <textarea id="edit-picture-notes" class="form-control" rows="3">${escapeHtml(picture.notes || '')}</textarea>
            </div>
            </div>
            <div class="form-actions text-end">
                <button type="submit" class="btn btn-primary">${i18n.t('astrodex.save_changes')}</button>
            </div>
        </form>
    `, 'lg');
    
    // Open the modal
    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();

    document.getElementById('edit-picture-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await updatePicture(itemId, pictureId);
    });
       

    // Event listener when modal is closed
    document.getElementById('modal_lg_close').addEventListener('hidden.bs.modal', () => {
        //Remove event listener
        const pictureForm = document.getElementById('edit-picture-form');
        if (pictureForm) {
            pictureForm.removeEventListener('submit', async (e) => {
                e.preventDefault();
            });
        }

        //Remove self listener to prevent duplicates if modal is opened again
        document.getElementById('modal_lg_close').removeEventListener('hidden.bs.modal', () => {});
    });
}

async function updatePicture(itemId, pictureId) {
    try {
        const pictureData = {
            date: document.getElementById('edit-picture-date').value,
            exposition_time: document.getElementById('edit-picture-exposition').value,
            device: document.getElementById('edit-picture-device').value,
            filters: document.getElementById('edit-picture-filters').value,
            iso: document.getElementById('edit-picture-iso').value,
            frames: document.getElementById('edit-picture-frames').value,
            notes: document.getElementById('edit-picture-notes').value
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
        closeModal();
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
    
    let currentIndex = 0;
    let keyHandler = null; // Store the handler reference for cleanup
    let bs_modal = null; // Store bootstrap modal reference
    
    function updateModalContent() {
        const picture = slideshowPictures[currentIndex];
        const imageUrl = `/api/astrodex/images/${picture.filename}`;
        const ownerUsername = picture.owner_username || item.owner_username || '';
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
                                <strong>${escapeHtml(picture.exposition_time)}</strong>
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${picture.device ? `
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
                if (bs_modal) {
                    bs_modal.hide();
                }
            }
        };
        
        document.addEventListener('keydown', keyHandler);
    }
    
    // Create modal using existing Bootstrap structure — body has two stable sub-containers:
    // #slideshow-content-wrapper (replaced on navigation) and #slideshow-object-info-wrapper (persistent)
    createModal(`${escapeHtml(item.name)} - ${i18n.t('astrodex.photos')}`, '', 'full');

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

    // Show the modal
    bs_modal = new bootstrap.Modal('#modal_full_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    
    // Setup cleanup when modal is hidden
    document.getElementById('modal_full_close').addEventListener('hidden.bs.modal', function cleanup() {
        // Remove keyboard handler
        if (keyHandler) {
            document.removeEventListener('keydown', keyHandler);
            keyHandler = null;
        }
        
        // Remove this event listener to prevent duplicates
        document.getElementById('modal_full_close').removeEventListener('hidden.bs.modal', cleanup);
    });
    
    // Initialize content and show modal
    updateModalContent();
    setupKeyboardNavigation();
    bs_modal.show();

    // Async: inject object-info card into the stable info container
    if (typeof injectObjectInfoIntoContainer === 'function' && item.name) {
        const infoContainer = document.getElementById('slideshow-object-info-wrapper');
        if (infoContainer) {
            injectObjectInfoIntoContainer(item.name, infoContainer);
        }
    }
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
        button.innerHTML = `<i class="bi bi-sort-down-alt icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.sort_order_descending')}`;
    } else {
        astrodexFilters.sortOrder = 'asc';
        button.innerHTML = `<i class="bi bi-sort-up-alt icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.sort_order_ascending')}`;
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

function closeModal() {
    //Close all bs modals to prevent stacking
    const modals = document.querySelectorAll('.modal.show');
    modals.forEach(modal => {
        const bs_modal = bootstrap.Modal.getInstance(modal);
        if (bs_modal) {
            bs_modal.hide();
        }
    });

    // Remove any lingering backdrops to avoid stacked blur layers
    const backdrops = document.querySelectorAll('.modal-backdrop');
    backdrops.forEach(backdrop => backdrop.remove());

    //Remove any existing close modal event listeners to prevent duplicates
    const closeButtons = document.querySelectorAll('[data-action="close-modal"], [data-action="cleanup-close-modal"]');
    closeButtons.forEach(button => {
        button.removeEventListener('click', handleModalClick);
    });
}

function handleModalClick(event) {

    if (event.target.classList.contains('modal-overlay')) {
        closeModal();
    }
}

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

    //Init buttons — wait for translations to be loaded before setting labels
    await i18n.ready;
    const buttonSort = document.getElementById('astrodex-sort-order');
    buttonSort.innerHTML = `<i class="bi bi-sort-up-alt icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.sort_order_ascending')}`;
    const buttonAddItem = document.getElementById('add-astrodex-item');
    buttonAddItem.innerHTML = `<i class="bi bi-plus-circle icon-inline" aria-hidden="true"></i>${i18n.t('astrodex.add_object')}`;
    
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
            
            switch(action) {
                case 'close-modal':
                    e.preventDefault();
                    closeModal();
                    break;
                case 'cleanup-close-modal':
                    e.preventDefault();
                    cleanupAndCloseModal();
                    break;
                case 'add-picture':
                    e.preventDefault();
                    if(isAllowedAstrodex) {
                        showAddPictureModal(itemId);
                    }
                    break;
                case 'delete-item':
                    e.preventDefault();
                    if(isAllowedAstrodex) {
                        deleteAstrodexItem(itemId);
                    }
                    break;
                case 'set-main-picture':
                    e.preventDefault();
                    if(isAllowedAstrodex) {
                        setMainPicture(itemId, pictureId);
                    }
                    break;
                case 'edit-picture':
                    e.preventDefault();
                    if(isAllowedAstrodex) {
                        showEditPictureModal(itemId, pictureId);
                    }
                    break;
                case 'delete-picture':
                    e.preventDefault();
                    if(isAllowedAstrodex) {
                        deletePicture(itemId, pictureId);
                    }
                    break;
                case 'switch-catalogue-name':
                    e.preventDefault();
                    if(isAllowedAstrodex) {
                        switchItemCatalogueName(itemId, catalogue);
                    }
                    break;
            }
        }
        
        // Handle modal overlay clicks
        if (target.classList.contains('modal-overlay')) {
            handleModalClick(e);
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
            const itemId = button.getAttribute('data-item-id');
            
            switch(action) {
                case 'add-astrodex-item':
                    e.preventDefault();
                    if(isAllowedAstrodex) {
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
            const pictureImg = target.closest('[data-picture-url]');
            
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
// Blurring it on `hide.bs.modal` — which fires before aria-hidden is applied —
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
