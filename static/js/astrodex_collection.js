// ======================
// Astrodex - Catalogue Collection sub-tab
// ======================
//
// A read-only "Pokedex" view: pick a catalogue and browse every one of its objects as a
// small card. Captured objects show your own Astrodex cover photo; the rest show the
// DSS2/SkyView preview, greyed out. Cards carry no actions - this view only reflects
// state owned by the Astrodex and SkyTonight catalogue.
//
// Filtering, sorting and paging are all done server-side (see
// backend/observation/catalogue_collection.py): the biggest catalogues run to 13k
// objects, far past what is sensible to hold in the page.

const COLLECTION_PAGE_SIZE = 60;

// Catalogue ids come from the SkyTonight dataset and are internal keys ("OpenNGC",
// "AbellPNe"). Anything without an entry here falls back to its raw id, which is already
// the display name for Messier, Caldwell, Arp, LBN, Sharpless, Barnard and vdB.
const COLLECTION_CATALOGUE_LABEL_KEYS = {
    Bodies: 'astrodex.collection_cat_bodies',
    CommonName: 'astrodex.collection_cat_commonname',
    OpenNGC: 'astrodex.collection_cat_openngc',
    OpenIC: 'astrodex.collection_cat_openic',
    Herschel400: 'astrodex.collection_cat_herschel400',
    Pensack500: 'astrodex.collection_cat_pensack500',
    GaryImm: 'astrodex.collection_cat_garyimm',
    AbellPNe: 'astrodex.collection_cat_abellpne',
    AbellClusters: 'astrodex.collection_cat_abellclusters',
};

const collectionState = {
    catalogue: '',
    page: 0,
    sort: 'catalogue_id',
    order: 'asc',
    search: '',
    caught: 'all',
    type: '',
    constellation: '',
    difficulty: '',
    listenersBound: false,
    // Incremented on every request so a slow page that resolves after the user has
    // already moved on cannot overwrite the grid.
    requestToken: 0,
};

let collectionImageObserver = null;
let collectionSearchDebounce = null;

/**
 * Entry point, called by app.js when the Catalogue Collection sub-tab is activated.
 */
async function loadCatalogueCollection() {
    bindCollectionListeners();
    await loadCollectionCatalogues();
    if (!collectionState.catalogue) {
        // The picker could not be built (dataset missing, or the request failed), so
        // there is no catalogue to page through - say so instead of leaving a blank grid.
        showCollectionError();
        return;
    }
    await renderCollectionPage();
}

function showCollectionError() {
    const grid = document.getElementById('collection-grid');
    if (!grid) return;
    DOMUtils.clear(grid);
    const col = document.createElement('div');
    col.className = 'col-12';
    const alert = document.createElement('div');
    alert.className = 'alert alert-danger mb-0';
    alert.textContent = i18n.t('astrodex.collection_error');
    col.appendChild(alert);
    grid.appendChild(col);
    DOMUtils.clear('collection-pagination');
}

function collectionCatalogueLabel(catalogueId) {
    const key = COLLECTION_CATALOGUE_LABEL_KEYS[catalogueId];
    return key && i18n.has(key) ? i18n.t(key) : catalogueId;
}

function collectionTypeLabel(objectType) {
    if (!objectType) return '';
    const key = `skytonight.type_${strToTranslateKey(objectType)}`;
    return i18n.has(key) ? i18n.t(key) : objectType;
}

/**
 * Display name for a card. Deep-sky names are proper nouns and stay as the catalogue
 * spells them, but solar-system bodies have real translations ("Moon" -> "Lune"), so
 * those go through the shared `planets` dictionary.
 */
function collectionObjectName(item) {
    const bodySlug = (item.target_id || '').startsWith('body-') ? item.target_id.slice('body-'.length) : '';
    if (bodySlug) {
        const key = `planets.${bodySlug}`;
        if (i18n.has(key)) return i18n.t(key);
    }
    return item.preferred_name || '';
}

/**
 * Fill the catalogue picker with every browsable catalogue and its captured count.
 * Re-run on each activation so counts follow newly added Astrodex objects.
 */
async function loadCollectionCatalogues() {
    const select = document.getElementById('collection-catalogue');
    if (!select) return;

    try {
        const data = await fetchJSON('/api/astrodex/collection/catalogues');
        const catalogues = data.catalogues || [];
        if (catalogues.length === 0) return;

        const previous = collectionState.catalogue;
        DOMUtils.clear(select);
        catalogues.forEach((catalogue) => {
            const option = document.createElement('option');
            option.value = catalogue.id;
            option.textContent =
                `${collectionCatalogueLabel(catalogue.id)} (${catalogue.caught}/${catalogue.total})`;
            select.appendChild(option);
        });

        const stillExists = catalogues.some((catalogue) => catalogue.id === previous);
        collectionState.catalogue = stillExists ? previous : catalogues[0].id;
        select.value = collectionState.catalogue;
    } catch (err) {
        console.error('Error loading collection catalogues:', err);
    }
}

function bindCollectionListeners() {
    if (collectionState.listenersBound) return;

    const search = document.getElementById('collection-search');
    if (search) {
        search.addEventListener('input', (e) => {
            // Every keystroke is a round trip, so wait for a pause in typing.
            clearTimeout(collectionSearchDebounce);
            const value = e.target.value;
            collectionSearchDebounce = setTimeout(() => {
                collectionState.search = value;
                collectionState.page = 0;
                renderCollectionPage();
            }, 300);
        });
    }

    const simpleFilters = [
        ['collection-catalogue', 'catalogue'],
        ['collection-caught-filter', 'caught'],
        ['collection-difficulty-filter', 'difficulty'],
        ['collection-type-filter', 'type'],
        ['collection-constellation-filter', 'constellation'],
        ['collection-sort', 'sort'],
    ];
    simpleFilters.forEach(([elementId, stateKey]) => {
        const element = document.getElementById(elementId);
        if (!element) return;
        element.addEventListener('change', (e) => {
            collectionState[stateKey] = e.target.value;
            collectionState.page = 0;
            if (stateKey === 'catalogue') {
                // Type/constellation options belong to the previous catalogue.
                collectionState.type = '';
                collectionState.constellation = '';
            }
            renderCollectionPage();
        });
    });

    const sortOrder = document.getElementById('collection-sort-order');
    if (sortOrder) {
        sortOrder.addEventListener('click', () => {
            collectionState.order = collectionState.order === 'asc' ? 'desc' : 'asc';
            collectionState.page = 0;
            updateCollectionSortOrderButton();
            renderCollectionPage();
        });
        updateCollectionSortOrderButton();
    }

    collectionState.listenersBound = true;
}

function updateCollectionSortOrderButton() {
    const button = document.getElementById('collection-sort-order');
    if (!button) return;
    const ascending = collectionState.order === 'asc';
    const label = i18n.t(ascending ? 'astrodex.sort_order_ascending' : 'astrodex.sort_order_descending');
    DOMUtils.clear(button);
    button.appendChild(DOMUtils.createIcon(ascending ? 'bi bi-sort-up-alt' : 'bi bi-sort-down-alt'));
    button.title = label;
    button.setAttribute('aria-label', label);
}

/**
 * Fetch and render the current page of cards, plus the progress bar, filter options
 * and pagination bar around it.
 */
async function renderCollectionPage() {
    const grid = document.getElementById('collection-grid');
    if (!grid || !collectionState.catalogue) return;

    const token = ++collectionState.requestToken;
    resetCollectionImageObserver();
    DOMUtils.clear(grid);
    const loading = document.createElement('div');
    loading.className = 'col-12';
    loading.appendChild(DOMUtils.createSpinnerWrapper(i18n.t('common.loading')));
    grid.appendChild(loading);

    const params = new URLSearchParams({
        catalogue: collectionState.catalogue,
        page: String(collectionState.page),
        page_size: String(COLLECTION_PAGE_SIZE),
        sort: collectionState.sort,
        order: collectionState.order,
        q: collectionState.search,
        type: collectionState.type,
        constellation: collectionState.constellation,
        caught: collectionState.caught,
        difficulty: collectionState.difficulty,
    });

    try {
        const data = await fetchJSON(`/api/astrodex/collection?${params.toString()}`);
        if (token !== collectionState.requestToken) return; // a newer request already won
        if (data.error) throw new Error(data.error);

        renderCollectionProgress(data);
        syncCollectionFilterOptions(data);
        renderCollectionCards(data.items || []);
        renderCollectionPagination(data);
    } catch (err) {
        if (token !== collectionState.requestToken) return;
        console.error('Error loading catalogue collection:', err);
        showCollectionError();
    }
}

function renderCollectionProgress(data) {
    const container = document.getElementById('collection-progress');
    if (!container) return;
    DOMUtils.clear(container);

    const total = data.total || 0;
    const caught = data.caught || 0;
    const percent = total > 0 ? Math.round((caught / total) * 100) : 0;

    const label = document.createElement('div');
    label.className = 'collection-progress-label';
    const left = document.createElement('span');
    const count = document.createElement('span');
    count.className = 'collection-progress-count';
    count.textContent = `${caught} / ${total}`;
    DOMUtils.append(left, count, ' ', i18n.t('astrodex.collection_captured'));
    const right = document.createElement('span');
    right.textContent = `${percent}%`;
    label.appendChild(left);
    label.appendChild(right);

    const progress = document.createElement('div');
    progress.className = 'progress';
    progress.setAttribute('role', 'progressbar');
    progress.setAttribute('aria-valuenow', String(percent));
    progress.setAttribute('aria-valuemin', '0');
    progress.setAttribute('aria-valuemax', '100');
    progress.setAttribute('aria-label', i18n.t('astrodex.collection_captured'));
    const bar = document.createElement('div');
    bar.className = 'progress-bar bg-success';
    // Bootstrap drives the fill from an inline width; there is no utility class for an
    // arbitrary percentage, so this one property stays inline.
    bar.style.width = `${percent}%`;
    progress.appendChild(bar);

    container.appendChild(label);
    container.appendChild(progress);
}

/**
 * Refill the type and constellation dropdowns from the catalogue currently shown.
 * The backend computes both over the whole catalogue, so the option lists stay stable
 * while paging or filtering.
 */
function syncCollectionFilterOptions(data) {
    const definitions = [
        {
            elementId: 'collection-type-filter',
            values: data.types || [],
            selected: collectionState.type,
            allLabelKey: 'astrodex.filter_type_all',
            labelFor: collectionTypeLabel,
        },
        {
            elementId: 'collection-constellation-filter',
            values: data.constellations || [],
            selected: collectionState.constellation,
            allLabelKey: 'astrodex.collection_filter_constellation_all',
            labelFor: (value) =>
                (typeof getConstellationDisplayName === 'function' ? getConstellationDisplayName(value) : value),
        },
    ];

    definitions.forEach(({ elementId, values, selected, allLabelKey, labelFor }) => {
        const select = document.getElementById(elementId);
        if (!select) return;
        DOMUtils.clear(select);

        const allOption = document.createElement('option');
        allOption.value = '';
        allOption.textContent = i18n.t(allLabelKey);
        select.appendChild(allOption);

        // The backend sorts on the raw English values; re-sort on the translated labels
        // so the dropdown reads alphabetically in the user's own language.
        values
            .map((value) => ({ value, label: labelFor(value) || value }))
            .sort((a, b) => a.label.localeCompare(b.label, i18n.getCurrentLanguage()))
            .forEach(({ value, label }) => {
                const option = document.createElement('option');
                option.value = value;
                option.textContent = label;
                select.appendChild(option);
            });

        select.value = values.includes(selected) ? selected : '';
    });
}

function renderCollectionCards(items) {
    const grid = document.getElementById('collection-grid');
    if (!grid) return;

    resetCollectionImageObserver();
    DOMUtils.clear(grid);

    if (items.length === 0) {
        const col = document.createElement('div');
        col.className = 'col-12';
        const empty = document.createElement('div');
        empty.className = 'alert alert-info mb-0';
        empty.textContent = i18n.t('astrodex.collection_empty');
        col.appendChild(empty);
        grid.appendChild(col);
        return;
    }

    items.forEach((item) => grid.appendChild(buildCollectionCard(item)));
}

function buildCollectionCard(item) {
    const col = document.createElement('div');
    col.className = 'col';

    const card = document.createElement('div');
    card.className = `card collection-card${item.caught ? '' : ' collection-card-uncaught'}`;

    const typeLabel = collectionTypeLabel(item.object_type);
    const constellationLabel = item.constellation && typeof getConstellationDisplayName === 'function'
        ? getConstellationDisplayName(item.constellation)
        : item.constellation;
    const objectName = collectionObjectName(item);
    const displayName = objectName && objectName !== item.catalogue_id ? objectName : '';
    const difficultyLabel = item.difficulty ? i18n.t(`difficulty.${item.difficulty}`) : '';
    card.title = [item.catalogue_id, displayName, typeLabel, constellationLabel, difficultyLabel]
        .filter(Boolean)
        .join(' - ');

    // ── Thumbnail ────────────────────────────────────────────────────────────
    const imageWrap = document.createElement('div');
    imageWrap.className = 'collection-card-image';

    if (item.image_url) {
        const img = document.createElement('img');
        img.alt = item.catalogue_id;
        img.loading = 'lazy';
        img.decoding = 'async';
        // The DSS2 tile behind this URL may still need fetching from CDS server-side, so
        // the request is deferred until the card is near the viewport.
        img.dataset.src = item.image_url;
        img.addEventListener('load', () => img.classList.add('is-loaded'));
        img.addEventListener('error', () => {
            img.remove();
            imageWrap.appendChild(collectionPlaceholderIcon());
        });
        imageWrap.appendChild(img);
        observeCollectionImage(img);
    } else {
        imageWrap.appendChild(collectionPlaceholderIcon());
    }

    if (item.caught) {
        const badge = document.createElement('span');
        badge.className = 'collection-card-badge';
        badge.title = i18n.t('astrodex.collection_captured');
        badge.appendChild(DOMUtils.createIcon('bi bi-check-circle-fill'));
        if (item.picture_count > 0) {
            badge.appendChild(document.createTextNode(String(item.picture_count)));
        }
        imageWrap.appendChild(badge);
    }
    card.appendChild(imageWrap);

    // ── Identity and metadata ────────────────────────────────────────────────
    const body = document.createElement('div');
    body.className = 'card-body collection-card-body';

    const id = document.createElement('div');
    id.className = 'collection-card-id';
    id.textContent = item.catalogue_id;
    body.appendChild(id);

    if (displayName) {
        const name = document.createElement('div');
        name.className = 'collection-card-name';
        name.textContent = displayName;
        body.appendChild(name);
    }

    const meta = [typeLabel, constellationLabel].filter(Boolean).join(' · ');
    if (meta) {
        const metaLine = document.createElement('div');
        metaLine.className = 'collection-card-meta';
        metaLine.textContent = meta;
        body.appendChild(metaLine);
    }

    // Same beginner/intermediate/advanced badge SkyTonight and the Astrodex grid use.
    // Solar-system bodies carry no rating, so they simply get no badge.
    if (item.difficulty && typeof createDifficultyBadgeNode === 'function') {
        const difficultyRow = document.createElement('div');
        difficultyRow.className = 'collection-card-difficulty';
        difficultyRow.appendChild(createDifficultyBadgeNode(item.difficulty));
        body.appendChild(difficultyRow);
    }

    if (item.magnitude !== null && item.magnitude !== undefined) {
        const magnitude = document.createElement('div');
        magnitude.className = 'collection-card-meta';
        magnitude.textContent = `${i18n.t('astrodex.collection_magnitude')} ${Number(item.magnitude).toFixed(1)}`;
        body.appendChild(magnitude);
    }

    card.appendChild(body);
    col.appendChild(card);
    return col;
}

function collectionPlaceholderIcon() {
    return DOMUtils.createIcon('bi bi-question-circle', 'collection-card-placeholder');
}

/**
 * Load thumbnails only as their card approaches the viewport. A single page can hold
 * 60 objects whose DSS2 tiles are not yet in the server-side cache; loading them all
 * upfront would fire that many cold fetches to CDS at once.
 */
function observeCollectionImage(img) {
    if (!('IntersectionObserver' in window)) {
        img.src = img.dataset.src;
        return;
    }
    if (!collectionImageObserver) {
        collectionImageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                const target = entry.target;
                observer.unobserve(target);
                if (target.dataset.src) target.src = target.dataset.src;
            });
        }, { rootMargin: '200px' });
    }
    collectionImageObserver.observe(img);
}

function resetCollectionImageObserver() {
    if (collectionImageObserver) {
        collectionImageObserver.disconnect();
        collectionImageObserver = null;
    }
}

function renderCollectionPagination(data) {
    const container = document.getElementById('collection-pagination');
    if (!container) return;
    DOMUtils.clear(container);

    const totalPages = data.total_pages || 1;
    const filteredTotal = data.filtered_total || 0;
    if (filteredTotal === 0) return;

    const bar = document.createElement('div');
    bar.className = 'collection-pagination-bar mt-3 pt-2 border-top';

    const page = data.page || 0;
    const start = page * (data.page_size || COLLECTION_PAGE_SIZE) + 1;
    const end = Math.min(start + (data.items || []).length - 1, filteredTotal);
    const count = document.createElement('span');
    count.className = 'text-muted small';
    count.textContent = `${start}–${end} / ${filteredTotal}`;
    bar.appendChild(count);

    if (totalPages > 1) {
        const nav = document.createElement('nav');
        nav.setAttribute('aria-label', i18n.t('astrodex.collection_pagination'));
        const list = document.createElement('ul');
        list.className = 'pagination pagination-sm mb-0 gap-1';

        const addButton = (iconClass, targetPage, disabled, ariaLabel) => {
            const listItem = document.createElement('li');
            listItem.className = `page-item${disabled ? ' disabled' : ''}`;
            const link = document.createElement('button');
            link.type = 'button';
            link.className = 'page-link';
            link.disabled = disabled;
            link.setAttribute('aria-label', ariaLabel);
            link.appendChild(DOMUtils.createIcon(iconClass));
            link.addEventListener('click', () => {
                collectionState.page = targetPage;
                renderCollectionPage();
            });
            listItem.appendChild(link);
            list.appendChild(listItem);
        };

        addButton('bi bi-chevron-double-left', 0, page === 0, i18n.t('astrodex.collection_page_first'));
        addButton('bi bi-chevron-left', page - 1, page === 0, i18n.t('astrodex.collection_page_previous'));

        const current = document.createElement('li');
        current.className = 'page-item disabled';
        const currentLabel = document.createElement('span');
        currentLabel.className = 'page-link';
        currentLabel.textContent = `${page + 1} / ${totalPages}`;
        current.appendChild(currentLabel);
        list.appendChild(current);

        addButton('bi bi-chevron-right', page + 1, page >= totalPages - 1, i18n.t('astrodex.collection_page_next'));
        addButton(
            'bi bi-chevron-double-right',
            totalPages - 1,
            page >= totalPages - 1,
            i18n.t('astrodex.collection_page_last')
        );

        nav.appendChild(list);
        bar.appendChild(nav);
    }

    container.appendChild(bar);
}
