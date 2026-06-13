// ======================
// AllSky Connector — Observatory tab
// ======================

let _allskySensorInterval = null;
let _allskyImageInterval  = null;
let _allskyImageRetryTimeout = null;
let _allskyModalRefreshInterval = null;

const _ALLSKY_IMAGE_REFRESH_MS = 30000;  // 30s normal refresh
const _ALLSKY_IMAGE_RETRY_MS   = 300000; // 5 min retry after failure

async function loadAllSkyObservatory() {
    const container = document.getElementById('allsky-observatory');
    if (!container) return;

    const [connectors, urls] = await Promise.all([
        fetchJSONOnce('/api/connectors').catch(() => []),
        fetchJSONOnce('/api/connectors/allsky/urls').catch(() => null),
    ]);

    const allskyCfg = (connectors || []).find(c => c.name === 'allsky');
    if (!allskyCfg || !allskyCfg.enabled) {
        DOMUtils.clear(container);
        const alert = document.createElement('div');
        alert.className = 'alert alert-secondary text-center mt-4';
        alert.appendChild(DOMUtils.createIcon('bi bi-camera-video-off fs-2 d-block mb-2'));
        const text = document.createElement('span');
        text.textContent = i18n.t('observatory.not_configured');
        alert.appendChild(text);
        container.appendChild(alert);
        return;
    }

    const modules = allskyCfg.config.modules || {};
    DOMUtils.clear(container);
    container.appendChild(_buildAllSkyLayout(allskyCfg, modules, urls || {}));
    _startAllSkyPolling(modules, urls || {});
}

// ── HTML builder ─────────────────────────────────────────────────────────────

function _buildAllSkyLayout(cfg, modules, urls) {
    const row = document.createElement('div');
    row.className = 'row g-3';

    const hasSensor = modules.sensor_data?.enabled;
    const liveCol = hasSensor ? 'col-12 col-lg-8' : 'col-12';

    if (modules.live_image?.enabled && urls.live_image) {
        const col = document.createElement('div');
        col.className = liveCol;

        const card = document.createElement('div');
        card.className = 'card h-100';

        const header = document.createElement('div');
        header.className = 'card-header d-flex justify-content-between align-items-center';
        const headerText = document.createElement('span');
        headerText.textContent = i18n.t('observatory.live_image');
        const dayNightBadge = document.createElement('span');
        dayNightBadge.id = 'allsky-day-night-badge';
        dayNightBadge.className = 'badge bg-secondary ms-2';
        header.appendChild(headerText);
        header.appendChild(dayNightBadge);

        const body = document.createElement('div');
        body.className = 'card-body p-1 text-center';
        body.id = 'allsky-live-body';
        const img = document.createElement('img');
        img.id = 'allsky-live-img';
        img.src = urls.live_image;
        img.alt = 'AllSky live';
        img.className = 'img-fluid rounded allsky-media-fit allsky-zoomable';
        img.addEventListener('click', () => _openAllSkyZoomModal(urls));
        img.addEventListener('load', _updateLiveTimestamp, { once: true });
        body.appendChild(img);

        const ts = document.createElement('p');
        ts.id = 'allsky-live-ts';
        ts.className = 'text-muted small mb-0 mt-1';
        body.appendChild(ts);

        card.appendChild(header);
        card.appendChild(body);
        col.appendChild(card);
        row.appendChild(col);
    }

    if (hasSensor) {
        const col = document.createElement('div');
        col.className = 'col-12 col-lg-4';

        const card = document.createElement('div');
        card.className = 'card h-100';

        const header = document.createElement('div');
        header.className = 'card-header';
        header.textContent = i18n.t('observatory.sensor_data');

        const body = document.createElement('div');
        body.className = 'card-body p-2';
        body.id = 'allsky-sensor-body';
        const sensorSpinner = document.createElement('div');
        sensorSpinner.className = 'text-muted text-center py-3';
        const sensorSpinnerIcon = document.createElement('div');
        sensorSpinnerIcon.className = 'spinner-border spinner-border-sm';
        sensorSpinner.appendChild(sensorSpinnerIcon);
        body.appendChild(sensorSpinner);

        card.appendChild(header);
        card.appendChild(body);
        col.appendChild(card);
        row.appendChild(col);
    }

    if (modules.mini_timelapse?.enabled && urls.mini_timelapse_thumb) {
        const col = document.createElement('div');
        col.className = 'col-12 col-md-6 col-lg-3';

        const card = document.createElement('div');
        card.className = 'card h-100';

        const header = document.createElement('div');
        header.className = 'card-header';
        header.textContent = i18n.t('observatory.mini_timelapse');

        const body = document.createElement('div');
        body.className = 'card-body p-1 text-center';
        body.id = 'allsky-mini-body';

        const link = document.createElement('a');
        link.href = urls.mini_timelapse_video || '#';
        link.target = '_blank';
        link.rel = 'noopener';

        const img = document.createElement('img');
        img.id = 'allsky-mini-img';
        img.src = urls.mini_timelapse_thumb;
        img.alt = 'mini-timelapse';
        img.className = 'img-fluid rounded allsky-media-thumb';

        const caption = document.createElement('div');
        caption.className = 'mt-1 small text-muted';
        caption.appendChild(DOMUtils.createIcon('bi bi-play-circle me-1'));
        caption.appendChild(document.createTextNode(i18n.t('observatory.watch_video')));

        link.appendChild(img);
        link.appendChild(caption);
        body.appendChild(link);
        card.appendChild(header);
        card.appendChild(body);
        col.appendChild(card);
        row.appendChild(col);
    }

    if (modules.keogram?.enabled && urls.keogram) {
        const hasNeighbour = modules.startrails?.enabled || modules.mini_timelapse?.enabled;
        const keogramCol = hasNeighbour ? 'col-12 col-lg-9' : 'col-12';

        const col = document.createElement('div');
        col.className = keogramCol;

        const card = document.createElement('div');
        card.className = 'card h-100';

        const header = document.createElement('div');
        header.className = 'card-header d-flex justify-content-between align-items-center';
        const headerText = document.createElement('span');
        headerText.textContent = i18n.t('observatory.keogram');
        const dateBadge = document.createElement('span');
        dateBadge.id = 'allsky-keogram-date';
        dateBadge.className = 'badge bg-dark text-muted small';
        header.appendChild(headerText);
        header.appendChild(dateBadge);

        const body = document.createElement('div');
        body.className = 'card-body p-1 text-center';
        body.id = 'allsky-keogram-body';
        const img = document.createElement('img');
        img.id = 'allsky-keogram-img';
        img.src = urls.keogram;
        img.alt = 'keogram';
        img.className = 'img-fluid rounded allsky-zoomable';
        img.addEventListener('click', () => _openAllSkyStaticModal(i18n.t('observatory.keogram'), urls.keogram));
        body.appendChild(img);

        card.appendChild(header);
        card.appendChild(body);
        col.appendChild(card);
        row.appendChild(col);
    }

    if (modules.startrails?.enabled && urls.startrails) {
        const col = document.createElement('div');
        col.className = 'col-12 col-md-6 col-lg-3';

        const card = document.createElement('div');
        card.className = 'card h-100';

        const header = document.createElement('div');
        header.className = 'card-header';
        header.textContent = i18n.t('observatory.startrails');

        const body = document.createElement('div');
        body.className = 'card-body p-1 text-center';
        body.id = 'allsky-startrails-body';
        const img = document.createElement('img');
        img.id = 'allsky-startrails-img';
        img.src = urls.startrails;
        img.alt = 'startrails';
        img.className = 'img-fluid rounded allsky-zoomable';
        img.addEventListener('click', () => _openAllSkyStaticModal(i18n.t('observatory.startrails'), urls.startrails));
        body.appendChild(img);

        card.appendChild(header);
        card.appendChild(body);
        col.appendChild(card);
        row.appendChild(col);
    }

    if (modules.daily_timelapse?.enabled && urls.daily_timelapse) {
        const col = document.createElement('div');
        col.className = 'col-12 col-md-6';

        const card = document.createElement('div');
        card.className = 'card h-100';

        const header = document.createElement('div');
        header.className = 'card-header';
        header.textContent = i18n.t('observatory.daily_timelapse');

        const body = document.createElement('div');
        body.className = 'card-body p-1 text-center';
        body.id = 'allsky-timelapse-body';

        const video = document.createElement('video');
        video.id = 'allsky-timelapse-video';
        video.controls = true;
        video.className = 'img-fluid rounded allsky-media-video';
        video.src = urls.daily_timelapse;
        body.appendChild(video);

        card.appendChild(header);
        card.appendChild(body);
        col.appendChild(card);
        row.appendChild(col);
    }

    return row;
}

// ── Error placeholder nodes ────────────────────────────────────────────────────

function _notYetGeneratedNode() {
    const p = document.createElement('p');
    p.className = 'text-muted small p-2 mb-0';
    p.appendChild(DOMUtils.createIcon('bi bi-hourglass-split me-1'));
    p.appendChild(document.createTextNode(i18n.t('observatory.not_yet_generated')));
    return p;
}

function _imageUnavailableNode() {
    const p = document.createElement('p');
    p.className = 'text-muted small p-2 mb-0';
    p.appendChild(DOMUtils.createIcon('bi bi-wifi-off me-1'));
    p.appendChild(document.createTextNode(i18n.t('observatory.image_unavailable')));
    return p;
}

// ── Error handlers (set after DOM is ready, never inline) ─────────────────────

function _attachImageErrorHandlers(modules, urls) {
    const liveImg = document.getElementById('allsky-live-img');
    if (liveImg) {
        liveImg.onerror = () => {
            liveImg.onerror = null;
            const body = document.getElementById('allsky-live-body');
            if (body) { DOMUtils.clear(body); body.appendChild(_imageUnavailableNode()); }
            _stopLiveImageRefresh();
            _allskyImageRetryTimeout = setTimeout(loadAllSkyObservatory, _ALLSKY_IMAGE_RETRY_MS);
        };
    }

    const miniImg = document.getElementById('allsky-mini-img');
    if (miniImg) {
        miniImg.onerror = () => {
            miniImg.onerror = null;
            const body = document.getElementById('allsky-mini-body');
            if (body) { DOMUtils.clear(body); body.appendChild(_notYetGeneratedNode()); }
        };
    }

    const keogramImg = document.getElementById('allsky-keogram-img');
    if (keogramImg) {
        keogramImg.onerror = () => {
            keogramImg.onerror = null;
            const body = document.getElementById('allsky-keogram-body');
            if (body) { DOMUtils.clear(body); body.appendChild(_notYetGeneratedNode()); }
        };
    }

    const startrailsImg = document.getElementById('allsky-startrails-img');
    if (startrailsImg) {
        startrailsImg.onerror = () => {
            startrailsImg.onerror = null;
            const body = document.getElementById('allsky-startrails-body');
            if (body) { DOMUtils.clear(body); body.appendChild(_notYetGeneratedNode()); }
        };
    }

    const video = document.getElementById('allsky-timelapse-video');
    if (video) {
        video.onerror = () => {
            video.onerror = null;
            const body = document.getElementById('allsky-timelapse-body');
            if (body) { DOMUtils.clear(body); body.appendChild(_notYetGeneratedNode()); }
        };
    }
}

// ── Polling ───────────────────────────────────────────────────────────────────

function _startAllSkyPolling(modules, urls) {
    stopAllSkyPolling();
    _attachImageErrorHandlers(modules, urls);

    if (modules.live_image?.enabled && urls.live_image) {
        _allskyImageInterval = setInterval(() => {
            const img = document.getElementById('allsky-live-img');
            if (!img) { _stopLiveImageRefresh(); return; }
            img.src = `${urls.live_image}&_ts=${Date.now()}`;
            _updateLiveTimestamp();
        }, _ALLSKY_IMAGE_REFRESH_MS);
    }

    if (modules.sensor_data?.enabled) {
        _pollAllSkySensor();
        _allskySensorInterval = setInterval(_pollAllSkySensor, 60000);
    }
}

function _stopLiveImageRefresh() {
    if (_allskyImageInterval) { clearInterval(_allskyImageInterval); _allskyImageInterval = null; }
}

function stopAllSkyPolling() {
    _stopLiveImageRefresh();
    if (_allskySensorInterval)       { clearInterval(_allskySensorInterval);       _allskySensorInterval = null; }
    if (_allskyImageRetryTimeout)    { clearTimeout(_allskyImageRetryTimeout);     _allskyImageRetryTimeout = null; }
    if (_allskyModalRefreshInterval) { clearInterval(_allskyModalRefreshInterval); _allskyModalRefreshInterval = null; }
}

// ── Live image timestamp ──────────────────────────────────────────────────────

function _updateLiveTimestamp() {
    const ts = document.getElementById('allsky-live-ts');
    if (!ts) return;
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    DOMUtils.clear(ts);
    ts.appendChild(DOMUtils.createIcon('bi bi-arrow-clockwise me-1'));
    ts.appendChild(document.createTextNode(`${i18n.t('observatory.updated_at')} ${time}`));
}

// ── Zoom modals ───────────────────────────────────────────────────────────────

function _openAllSkyStaticModal(title, url) {
    const titleEl = document.getElementById('modal_full_close_title');
    const bodyEl  = document.getElementById('modal_full_close_body');
    if (!titleEl || !bodyEl) return;

    titleEl.textContent = title;
    DOMUtils.clear(bodyEl);

    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex align-items-center justify-content-center h-100';

    const img = document.createElement('img');
    img.src       = url;
    img.alt       = title;
    img.className = 'img-fluid allsky-modal-img';

    wrapper.appendChild(img);
    bodyEl.appendChild(wrapper);

    new bootstrap.Modal(document.getElementById('modal_full_close'), { backdrop: true, keyboard: true }).show();
}

function _openAllSkyZoomModal(urls) {
    const titleEl = document.getElementById('modal_full_close_title');
    const bodyEl  = document.getElementById('modal_full_close_body');
    if (!titleEl || !bodyEl) return;

    titleEl.textContent = i18n.t('observatory.live_image');
    DOMUtils.clear(bodyEl);

    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex align-items-center justify-content-center h-100';

    const modalImg = document.createElement('img');
    modalImg.id        = 'allsky-modal-img';
    modalImg.src       = `${urls.live_image}&_ts=${Date.now()}`;
    modalImg.alt       = 'AllSky live';
    modalImg.className = 'img-fluid allsky-modal-img';

    wrapper.appendChild(modalImg);
    bodyEl.appendChild(wrapper);

    const modalEl = document.getElementById('modal_full_close');
    const bsModal = new bootstrap.Modal(modalEl, { backdrop: true, keyboard: true });

    _allskyModalRefreshInterval = setInterval(() => {
        const img = document.getElementById('allsky-modal-img');
        if (img) img.src = `${urls.live_image}&_ts=${Date.now()}`;
    }, _ALLSKY_IMAGE_REFRESH_MS);

    modalEl.addEventListener('hidden.bs.modal', function cleanup() {
        if (_allskyModalRefreshInterval) {
            clearInterval(_allskyModalRefreshInterval);
            _allskyModalRefreshInterval = null;
        }
        modalEl.removeEventListener('hidden.bs.modal', cleanup);
    });

    bsModal.show();
}

// ── Sensor data ───────────────────────────────────────────────────────────────

async function _pollAllSkySensor() {
    const body = document.getElementById('allsky-sensor-body');
    if (!body) return;

    const data = await fetchJSONOnce('/api/connectors/allsky/status').catch(() => null);
    if (!data) {
        DOMUtils.clear(body);
        const errMsg = document.createElement('p');
        errMsg.className = 'text-danger small p-2';
        errMsg.textContent = i18n.t('observatory.sensor_unavailable');
        body.appendChild(errMsg);
        return;
    }

    const badge = document.getElementById('allsky-day-night-badge');
    if (badge) {
        const dn = (data.DAY_OR_NIGHT || '').toLowerCase();
        badge.textContent = dn === 'night' ? i18n.t('observatory.night') : i18n.t('observatory.day');
        badge.className = `badge ms-2 ${dn === 'night' ? 'bg-primary' : 'bg-warning text-dark'}`;
    }

    const humidityKey  = data['AS_DEWCONTROLHUMIDITY'] != null ? 'AS_DEWCONTROLHUMIDITY' : 'AS_HUMIDITY';
    const exposureKey  = data['AS_sEXPOSURE'] != null ? 'AS_sEXPOSURE' : 'AS_EXPOSURE_US';
    const exposureUnit = exposureKey === 'AS_EXPOSURE_US' ? 'µs' : '';

    const rows = [
        { key: 'AS_TEMPERATURE_C',    label: i18n.t('observatory.temperature'),     unit: '°C', icon: 'bi-thermometer-half' },
        { key: humidityKey,           label: i18n.t('observatory.humidity'),         unit: '%',  icon: 'bi-droplet-half' },
        { key: 'AS_DEWCONTROLDEW',    label: i18n.t('observatory.dew_point'),        unit: '°C', icon: 'bi-water' },
        { key: 'AS_DEWCONTROLHEATER', label: i18n.t('observatory.dew_heater'),       unit: '',   icon: 'bi-lightning-charge' },
        { key: 'AS_GAIN',             label: i18n.t('observatory.gain'),             unit: '',   icon: 'bi-sliders' },
        { key: exposureKey,           label: i18n.t('observatory.exposure'),         unit: exposureUnit, icon: 'bi-clock' },
        { key: 'AS_MEAN',             label: i18n.t('observatory.mean_brightness'),  unit: '',   icon: 'bi-brightness-high' },
        { key: 'ALLSKY_VERSION',      label: i18n.t('observatory.version'),          unit: '',   icon: 'bi-info-circle' },
    ];

    const table = document.createElement('table');
    table.className = 'table table-sm table-borderless mb-0 small';
    let hasRows = false;

    for (const { key, label, unit, icon } of rows) {
        if (data[key] == null) continue;
        hasRows = true;
        const tr = document.createElement('tr');
        const td1 = document.createElement('td');
        td1.className = 'text-muted pe-2';
        td1.appendChild(DOMUtils.createIcon(`${icon} me-1`));
        td1.appendChild(document.createTextNode(label));
        const td2 = document.createElement('td');
        td2.className = 'fw-semibold';
        td2.textContent = `${data[key]}${unit ? ' ' + unit : ''}`;
        tr.appendChild(td1);
        tr.appendChild(td2);
        table.appendChild(tr);
    }

    DOMUtils.clear(body);
    if (!hasRows) {
        const msg = document.createElement('p');
        msg.className = 'text-muted small p-2';
        msg.textContent = i18n.t('observatory.sensor_no_data');
        body.appendChild(msg);
    } else {
        body.appendChild(table);
    }
}
