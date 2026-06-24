/**
 * object_info.js
 * Fetch and display deep-sky object metadata (SIMBAD + SkyView + Wikipedia)
 * via GET /api/object/<identifier>?lang=<code>
 */

// In-session cache: identifier (lowercased) → Promise<data>
const _objectInfoCache = new Map();

/**
 * Fetch object info from the backend, with session-level memoization.
 * @param {string} identifier - Object identifier (e.g. "NGC 2632", "M44")
 * @returns {Promise<object|null>}
 */
async function fetchObjectInfo(identifier) {
    const lang = (typeof i18n !== 'undefined' && i18n.getCurrentLanguage) ? i18n.getCurrentLanguage() : 'en';
    const key = `${lang}:${identifier.trim().toLowerCase()}`;
    if (_objectInfoCache.has(key)) {
        return _objectInfoCache.get(key);
    }
    const url = `/api/object/${encodeURIComponent(identifier.trim())}?lang=${encodeURIComponent(lang)}`;
    const promise = fetch(url, { credentials: 'same-origin' })
        .then(resp => {
            if (resp.status >= 500) throw new Error(`HTTP ${resp.status}`);
            return resp.json();
        })
        .catch(err => {
            console.warn(`[object_info] fetch failed for "${identifier}":`, err);
            _objectInfoCache.delete(key); // allow retry on next call
            return null;
        });
    _objectInfoCache.set(key, promise);
    return promise;
}

/**
 * Build and return a DOM element for an object-info section.
 * Uses the same card pattern as the slideshow picture-info tiles.
 *
 * @param {object} data  - Response from /api/object/<id>
 * @param {object} opts  - { compact: bool, vertical: bool, noImage: bool, noError: bool }
 * @returns {HTMLElement|null} DOM element, or null when suppressed by noError
 */
function buildObjectInfoCardHtml(data, opts = {}) {
    const t = (key, fb) => (typeof i18n !== 'undefined' && i18n.has(key)) ? i18n.t(key) : fb;
    const compact = !!opts.compact;
    const noImage = !!opts.noImage;
    const noError = !!opts.noError;
    const colClass = opts.vertical ? 'col-12' : 'col-md-6 col-lg-4';

    const mkTile = (iconClass, labelText, ...valueNodes) => {
        const col = document.createElement('div');
        col.className = colClass;
        const tile = document.createElement('div');
        tile.className = 'd-flex align-items-center p-2 rounded shadow-sm object-info-tile h-100';
        const iconWrap = document.createElement('div');
        iconWrap.className = 'me-3 fs-4';
        iconWrap.appendChild(DOMUtils.createIcon(iconClass));
        const textWrap = document.createElement('div');
        const label = document.createElement('small');
        label.className = 'text-muted d-block';
        label.textContent = labelText;
        textWrap.appendChild(label);
        valueNodes.forEach(n => textWrap.appendChild(n));
        tile.appendChild(iconWrap);
        tile.appendChild(textWrap);
        col.appendChild(tile);
        return col;
    };

    if (!data || data.error === 'not_found') {
        if (noError) return null;
        const wrap = document.createElement('div');
        wrap.className = 'slideshow-info mt-4';
        const p = document.createElement('p');
        p.className = 'text-muted small';
        DOMUtils.append(p, DOMUtils.createIcon('bi bi-question-circle icon-inline'), t('object_info.not_found', 'Object not found in SIMBAD'));
        wrap.appendChild(p);
        return wrap;
    }
    if (data.error === 'invalid_identifier') {
        if (noError) return null;
        const wrap = document.createElement('div');
        wrap.className = 'slideshow-info mt-4';
        const p = document.createElement('p');
        p.className = 'text-muted small';
        DOMUtils.append(p, DOMUtils.createIcon('bi bi-exclamation-circle icon-inline'), t('object_info.invalid_identifier', 'Invalid identifier'));
        wrap.appendChild(p);
        return wrap;
    }

    const container = document.createElement('div');
    container.className = 'slideshow-info mt-4';

    // ── Section heading ───────────────────────────────────
    const headRow = document.createElement('div');
    headRow.className = 'row mb-3';
    const headCol = document.createElement('div');
    headCol.className = 'col';
    const h5 = document.createElement('h5');
    h5.className = 'mb-0';
    DOMUtils.append(h5, DOMUtils.createIcon('bi bi-telescope icon-inline'), t('object_info.title', 'Object Information'));
    headCol.appendChild(h5);
    headRow.appendChild(headCol);
    container.appendChild(headRow);

    // ── Image ────────────────────────────────────────────
    if (!noImage && data.image && data.image.url) {
        const imgRow = document.createElement('div');
        imgRow.className = 'row mb-3';
        const imgCol = document.createElement('div');
        imgCol.className = 'col text-center';
        const img = document.createElement('img');
        img.src = data.image.url;
        img.alt = data.name || '';
        img.className = 'img-fluid rounded shadow-sm';
        img.loading = 'lazy';
        img.style.maxHeight = compact ? '160px' : '300px';
        img.style.objectFit = 'cover';
        img.addEventListener('error', () => { imgRow.style.display = 'none'; });
        const credit = document.createElement('small');
        credit.className = 'text-muted d-block mt-1';
        DOMUtils.append(credit, DOMUtils.createIcon('bi bi-camera icon-inline'), data.image.credit || '');
        imgCol.appendChild(img);
        imgCol.appendChild(credit);
        imgRow.appendChild(imgCol);
        container.appendChild(imgRow);
    }

    // ── Data tiles ───────────────────────────────────────
    const tilesRow = document.createElement('div');
    tilesRow.className = 'row g-3';

    if (data.type) {
        const strong = document.createElement('strong');
        strong.textContent = data.type;
        tilesRow.appendChild(mkTile('bi bi-tag text-primary', t('object_info.type_label', 'Type'), strong));
    }

    if (data.coordinates) {
        const ra  = data.coordinates.ra  != null ? Number(data.coordinates.ra).toFixed(4)  : '-';
        const dec = data.coordinates.dec != null ? Number(data.coordinates.dec).toFixed(4) : '-';
        const strong = document.createElement('strong');
        strong.textContent = `RA ${ra}°  Dec ${dec}°`;
        tilesRow.appendChild(mkTile('bi bi-geo-alt text-success', t('object_info.coordinates_label', 'Coordinates'), strong));
    }

    if (data.aliases && data.aliases.length > 0) {
        const shown = compact ? data.aliases.slice(0, 4) : data.aliases;
        const aliasesDiv = document.createElement('div');
        aliasesDiv.className = 'mt-1';
        shown.forEach(a => {
            const badge = document.createElement('span');
            badge.className = 'badge bg-secondary me-1 mb-1';
            badge.textContent = a;
            aliasesDiv.appendChild(badge);
        });
        const aliasTile = document.createElement('div');
        aliasTile.className = colClass;
        const tileInner = document.createElement('div');
        tileInner.className = 'd-flex align-items-start p-2 rounded shadow-sm object-info-tile h-100';
        const iconWrap = document.createElement('div');
        iconWrap.className = 'me-3 fs-4';
        iconWrap.appendChild(DOMUtils.createIcon('bi bi-bookmarks text-warning'));
        const textWrap = document.createElement('div');
        const lbl = document.createElement('small');
        lbl.className = 'text-muted d-block';
        lbl.textContent = t('object_info.aliases_label', 'Also known as');
        textWrap.appendChild(lbl);
        textWrap.appendChild(aliasesDiv);
        tileInner.appendChild(iconWrap);
        tileInner.appendChild(textWrap);
        aliasTile.appendChild(tileInner);
        tilesRow.appendChild(aliasTile);
    }

    container.appendChild(tilesRow);

    // ── Description ──────────────────────────────────────
    if (data.description) {
        const maxLen = compact ? 500 : 1200;
        const text = data.description.length > maxLen
            ? data.description.slice(0, maxLen) + '…'
            : data.description;
        const descRow = document.createElement('div');
        descRow.className = 'row mt-3';
        const descCol = document.createElement('div');
        descCol.className = 'col';
        const descTile = document.createElement('div');
        descTile.className = 'd-flex align-items-start p-2 rounded shadow-sm object-info-tile';
        const iconWrap = document.createElement('div');
        iconWrap.className = 'me-3 fs-4';
        iconWrap.appendChild(DOMUtils.createIcon('bi bi-journal-text'));
        const textWrap = document.createElement('div');
        const lbl = document.createElement('small');
        lbl.className = 'text-muted d-block';
        lbl.textContent = t('object_info.description_label', 'Description');
        const p = document.createElement('p');
        p.className = 'mb-0 small mt-1';
        p.style.whiteSpace = 'pre-wrap';
        p.textContent = text;
        textWrap.appendChild(lbl);
        textWrap.appendChild(p);
        descTile.appendChild(iconWrap);
        descTile.appendChild(textWrap);
        descCol.appendChild(descTile);
        descRow.appendChild(descCol);
        container.appendChild(descRow);
    }

    // ── Sources ──────────────────────────────────────────
    const srcList = [t('object_info.source_simbad', 'Source: SIMBAD (CDS, Strasbourg)')];
    if (!noImage && data.image) srcList.push(t('object_info.source_skyview',   'Image: DSS2 / SkyView (NASA GSFC)'));
    if (data.description)       srcList.push(t('object_info.source_wikipedia', 'Description: Wikipedia'));
    const srcRow = document.createElement('div');
    srcRow.className = 'row mt-3';
    const srcCol = document.createElement('div');
    srcCol.className = 'col';
    const srcSmall = document.createElement('small');
    srcSmall.className = 'text-muted';
    srcSmall.appendChild(DOMUtils.createIcon('bi bi-c-circle icon-inline'));
    srcList.forEach((s, i) => {
        if (i > 0) srcSmall.appendChild(document.createTextNode('  ·  '));
        srcSmall.appendChild(document.createTextNode(s));
    });
    srcCol.appendChild(srcSmall);
    srcRow.appendChild(srcCol);
    container.appendChild(srcRow);

    return container;
}

/**
 * Open the lg modal and show an object-info card for *identifier*.
 * Used from the SkyTonight table info icon.
 *
 * @param {string} identifier
 */
async function showObjectInfoModal(identifier) {
    const titleEl = document.getElementById('modal_lg_close_title');
    const bodyEl  = document.getElementById('modal_lg_close_body');
    if (!titleEl || !bodyEl) return;

    const t = (key, fb) => (typeof i18n !== 'undefined' && i18n.has(key)) ? i18n.t(key) : fb;

    titleEl.textContent = `${escapeHtml(identifier)} - ${t('object_info.title', 'Object Information')}`;

    // Loading state
    DOMUtils.clear(bodyEl);
    const _loadDiv = document.createElement('div');
    _loadDiv.className = 'text-center py-4';
    const _loadSpinner = document.createElement('div');
    _loadSpinner.className = 'spinner-border spinner-border-sm me-2';
    _loadSpinner.setAttribute('role', 'status');
    _loadSpinner.setAttribute('aria-hidden', 'true');
    _loadDiv.appendChild(_loadSpinner);
    _loadDiv.appendChild(document.createTextNode(t('object_info.loading', 'Loading object data…')));
    bodyEl.appendChild(_loadDiv);

    const _modalEl = document.getElementById('modal_lg_close');
    let bs_modal = bootstrap.Modal.getInstance(_modalEl);
    if (!bs_modal) {
        bs_modal = new bootstrap.Modal(_modalEl, { backdrop: true, focus: true, keyboard: true });
    }
    bs_modal.show();

    const data = await fetchObjectInfo(identifier);

    DOMUtils.clear(bodyEl);
    const _cardEl = buildObjectInfoCardHtml(data, { compact: false, vertical: true });
    if (_cardEl) bodyEl.appendChild(_cardEl);
}

/**
 * Inject an async object-info section into an already-open astrodex detail modal.
 * Appended above the photos heading.
 *
 * @param {string} identifier - item.name or best alias
 * @param {HTMLElement} container - element to append the card into
 */
async function injectObjectInfoIntoContainer(identifier, container) {
    if (!container) return;
    const t = (key, fb) => (typeof i18n !== 'undefined' && i18n.has(key)) ? i18n.t(key) : fb;

    // Placeholder while loading
    const placeholder = document.createElement('div');
    placeholder.className = 'slideshow-info mt-4';
    const _phInner = document.createElement('div');
    _phInner.className = 'text-muted small py-2';
    const _phSpinner = document.createElement('div');
    _phSpinner.className = 'spinner-border spinner-border-sm me-2';
    _phSpinner.setAttribute('role', 'status');
    _phSpinner.setAttribute('aria-hidden', 'true');
    _phInner.appendChild(_phSpinner);
    _phInner.appendChild(document.createTextNode(t('object_info.loading', 'Loading…')));
    placeholder.appendChild(_phInner);
    container.appendChild(placeholder);

    const data = await fetchObjectInfo(identifier);

    const _infoEl = buildObjectInfoCardHtml(data, { compact: true, noImage: true, noError: true });
    if (!_infoEl) {
        placeholder.remove();
        return;
    }
    placeholder.replaceWith(_infoEl);
}
