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
 * Build and return the HTML for an object-info section.
 * Uses the same card pattern as the slideshow picture-info tiles
 * (d-flex align-items-center p-2 rounded shadow-sm bg-light).
 *
 * @param {object} data  - Response from /api/object/<id>
 * @param {object} opts  - { compact: bool }  compact = fewer aliases / shorter description
 * @returns {string} HTML string
 */
function buildObjectInfoCardHtml(data, opts = {}) {
    const t = (key, fb) => (typeof i18n !== 'undefined' && i18n.has(key)) ? i18n.t(key) : fb;
    const compact = !!opts.compact;
    const noImage = !!opts.noImage;
    const noError = !!opts.noError;
    const colClass = opts.vertical ? 'col-12' : 'col-md-6 col-lg-4';

    if (!data || data.error === 'not_found') {
        if (noError) return '';
        return `<div class="slideshow-info mt-4">
            <p class="text-muted small">
                <i class="bi bi-question-circle icon-inline" aria-hidden="true"></i>
                ${escapeHtml(t('object_info.not_found', 'Object not found in SIMBAD'))}
            </p>
        </div>`;
    }
    if (data.error === 'invalid_identifier') {
        if (noError) return '';
        return `<div class="slideshow-info mt-4">
            <p class="text-muted small">
                <i class="bi bi-exclamation-circle icon-inline" aria-hidden="true"></i>
                ${escapeHtml(t('object_info.invalid_identifier', 'Invalid identifier'))}
            </p>
        </div>`;
    }

    let html = `<div class="slideshow-info mt-4">`;

    // ── Section heading ───────────────────────────────────
    html += `<div class="row mb-3">
        <div class="col">
            <h5 class="mb-0">
                <i class="bi bi-telescope icon-inline" aria-hidden="true"></i>
                ${escapeHtml(t('object_info.title', 'Object Information'))}
            </h5>
        </div>
    </div>`;

    // ── Image ────────────────────────────────────────────
    if (!noImage && data.image && data.image.url) {
        html += `<div class="row mb-3">
            <div class="col text-center">
                <img src="${escapeHtml(data.image.url)}"
                     alt="${escapeHtml(data.name)}"
                     class="img-fluid rounded shadow-sm"
                     loading="lazy"
                     style="max-height:${compact ? '160px' : '300px'}; object-fit:cover;"
                     onerror="this.closest('.row').style.display='none'">
                <small class="text-muted d-block mt-1">
                    <i class="bi bi-camera icon-inline" aria-hidden="true"></i>
                    ${escapeHtml(data.image.credit)}
                </small>
            </div>
        </div>`;
    }

    // ── Data tiles ───────────────────────────────────────
    html += `<div class="row g-3">`;

    if (data.type) {
        html += `<div class="${colClass}">
            <div class="d-flex align-items-center p-2 rounded shadow-sm object-info-tile h-100">
                <div class="me-3 fs-4"><i class="bi bi-tag text-primary" aria-hidden="true"></i></div>
                <div>
                    <small class="text-muted d-block">${escapeHtml(t('object_info.type_label', 'Type'))}</small>
                    <strong>${escapeHtml(data.type)}</strong>
                </div>
            </div>
        </div>`;
    }

    if (data.coordinates) {
        const ra  = data.coordinates.ra  != null ? Number(data.coordinates.ra).toFixed(4)  : '-';
        const dec = data.coordinates.dec != null ? Number(data.coordinates.dec).toFixed(4) : '-';
        html += `<div class="${colClass}">
            <div class="d-flex align-items-center p-2 rounded shadow-sm object-info-tile h-100">
                <div class="me-3 fs-4"><i class="bi bi-geo-alt text-success" aria-hidden="true"></i></div>
                <div>
                    <small class="text-muted d-block">${escapeHtml(t('object_info.coordinates_label', 'Coordinates'))}</small>
                    <strong>RA ${escapeHtml(ra)}° &nbsp; Dec ${escapeHtml(dec)}°</strong>
                </div>
            </div>
        </div>`;
    }

    if (data.aliases && data.aliases.length > 0) {
        const shown = compact ? data.aliases.slice(0, 4) : data.aliases;
        html += `<div class="${colClass}">
            <div class="d-flex align-items-start p-2 rounded shadow-sm object-info-tile h-100">
                <div class="me-3 fs-4"><i class="bi bi-bookmarks text-warning" aria-hidden="true"></i></div>
                <div>
                    <small class="text-muted d-block">${escapeHtml(t('object_info.aliases_label', 'Also known as'))}</small>
                    <div class="mt-1">${shown.map(a => `<span class="badge bg-secondary me-1 mb-1">${escapeHtml(a)}</span>`).join('')}</div>
                </div>
            </div>
        </div>`;
    }

    html += `</div>`; // row g-3

    // ── Description ──────────────────────────────────────
    if (data.description) {
        const maxLen = compact ? 500 : 1200;
        const text = data.description.length > maxLen
            ? data.description.slice(0, maxLen) + '…'
            : data.description;
        html += `<div class="row mt-3">
            <div class="col">
                <div class="d-flex align-items-start p-2 rounded shadow-sm object-info-tile">
                    <div class="me-3 fs-4"><i class="bi bi-journal-text" aria-hidden="true"></i></div>
                    <div>
                        <small class="text-muted d-block">${escapeHtml(t('object_info.description_label', 'Description'))}</small>
                        <p class="mb-0 small mt-1" style="white-space:pre-wrap;">${escapeHtml(text)}</p>
                    </div>
                </div>
            </div>
        </div>`;
    }

    // ── Sources ──────────────────────────────────────────
    let sources = [t('object_info.source_simbad', 'Source: SIMBAD (CDS, Strasbourg)')];
    if (!noImage && data.image) sources.push(t('object_info.source_skyview',   'Image: DSS2 / SkyView (NASA GSFC)'));
    if (data.description)       sources.push(t('object_info.source_wikipedia', 'Description: Wikipedia'));
    html += `<div class="row mt-3">
        <div class="col">
            <small class="text-muted">
                <i class="bi bi-c-circle icon-inline" aria-hidden="true"></i>
                ${sources.map(s => escapeHtml(s)).join(' &nbsp;·&nbsp; ')}
            </small>
        </div>
    </div>`;

    html += `</div>`; // .slideshow-info
    return html;
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
    bodyEl.innerHTML = `<div class="text-center py-4">
        <div class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></div>
        ${escapeHtml(t('object_info.loading', 'Loading object data…'))}
    </div>`;

    const _modalEl = document.getElementById('modal_lg_close');
    let bs_modal = bootstrap.Modal.getInstance(_modalEl);
    if (!bs_modal) {
        bs_modal = new bootstrap.Modal(_modalEl, { backdrop: true, focus: true, keyboard: true });
    }
    bs_modal.show();

    const data = await fetchObjectInfo(identifier);

    DOMUtils.clear(bodyEl);
    bodyEl.innerHTML = buildObjectInfoCardHtml(data, { compact: false, vertical: true });
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
    placeholder.innerHTML = `<div class="text-muted small py-2"><div class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></div>${escapeHtml(t('object_info.loading', 'Loading…'))}</div>`;
    container.appendChild(placeholder);

    const data = await fetchObjectInfo(identifier);

    const html = buildObjectInfoCardHtml(data, { compact: true, noImage: true, noError: true });
    if (!html) {
        placeholder.remove();
        return;
    }
    placeholder.outerHTML = html;
}
