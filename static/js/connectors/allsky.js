// ======================
// AllSky Connector — Observatory tab
// ======================

let _allskySensorInterval = null;
let _allskyImageInterval  = null;
let _allskyImageRetryTimeout = null;

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
        container.innerHTML = `
            <div class="alert alert-secondary text-center mt-4">
                <i class="bi bi-camera-video-off fs-2 d-block mb-2"></i>
                <span>${i18n.t('observatory.not_configured')}</span>
            </div>`;
        return;
    }

    const modules = allskyCfg.config.modules || {};
    container.innerHTML = _buildAllSkyLayout(allskyCfg, modules, urls || {});

    _startAllSkyPolling(modules, urls || {});
}

// ── HTML builder ─────────────────────────────────────────────────────────────

function _buildAllSkyLayout(cfg, modules, urls) {
    const label = cfg.config.label || 'AllSky';
    let html = `<h5 class="mb-3"><i class="bi bi-camera-video me-2"></i>${label}</h5><div class="row g-3">`;

    // Determine live image column width: full row if no sensor panel, 2/3 if sensor is next to it
    const hasSensor = modules.sensor_data?.enabled;
    const liveCol = hasSensor ? 'col-12 col-lg-8' : 'col-12';

    if (modules.live_image?.enabled && urls.live_image) {
        html += `
        <div class="${liveCol}">
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span>${i18n.t('observatory.live_image')}</span>
                    <span id="allsky-day-night-badge" class="badge bg-secondary ms-2"></span>
                </div>
                <div class="card-body p-1 text-center" id="allsky-live-body">
                    <img id="allsky-live-img" src="${urls.live_image}" alt="AllSky live"
                         class="img-fluid rounded" style="max-height:480px;object-fit:contain;">
                </div>
            </div>
        </div>`;
    }

    if (hasSensor) {
        html += `
        <div class="col-12 col-lg-4">
            <div class="card h-100">
                <div class="card-header">${i18n.t('observatory.sensor_data')}</div>
                <div class="card-body p-2" id="allsky-sensor-body">
                    <div class="text-muted text-center py-3"><div class="spinner-border spinner-border-sm"></div></div>
                </div>
            </div>
        </div>`;
    }

    if (modules.mini_timelapse?.enabled && urls.mini_timelapse_thumb) {
        html += `
        <div class="col-12 col-md-6 col-lg-3">
            <div class="card h-100">
                <div class="card-header">${i18n.t('observatory.mini_timelapse')}</div>
                <div class="card-body p-1 text-center" id="allsky-mini-body">
                    <a href="${urls.mini_timelapse_video || '#'}" target="_blank" rel="noopener">
                        <img id="allsky-mini-img" src="${urls.mini_timelapse_thumb}" alt="mini-timelapse"
                             class="img-fluid rounded" style="max-height:200px;object-fit:contain;">
                        <div class="mt-1 small text-muted"><i class="bi bi-play-circle me-1"></i>${i18n.t('observatory.watch_video')}</div>
                    </a>
                </div>
            </div>
        </div>`;
    }

    if (modules.keogram?.enabled && urls.keogram) {
        // Keogram is a wide timeline strip — give it as much horizontal space as possible
        const hasNeighbour = modules.startrails?.enabled || modules.mini_timelapse?.enabled;
        const keogramCol = hasNeighbour ? 'col-12 col-lg-9' : 'col-12';
        html += `
        <div class="${keogramCol}">
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span>${i18n.t('observatory.keogram')}</span>
                    <span id="allsky-keogram-date" class="badge bg-dark text-muted small"></span>
                </div>
                <div class="card-body p-1 text-center" id="allsky-keogram-body">
                    <img id="allsky-keogram-img" src="${urls.keogram}" alt="keogram" class="img-fluid rounded">
                </div>
            </div>
        </div>`;
    }

    if (modules.startrails?.enabled && urls.startrails) {
        html += `
        <div class="col-12 col-md-6 col-lg-3">
            <div class="card h-100">
                <div class="card-header">${i18n.t('observatory.startrails')}</div>
                <div class="card-body p-1 text-center" id="allsky-startrails-body">
                    <img id="allsky-startrails-img" src="${urls.startrails}" alt="startrails" class="img-fluid rounded">
                </div>
            </div>
        </div>`;
    }

    if (modules.daily_timelapse?.enabled && urls.daily_timelapse) {
        html += `
        <div class="col-12 col-md-6">
            <div class="card h-100">
                <div class="card-header">${i18n.t('observatory.daily_timelapse')}</div>
                <div class="card-body p-1 text-center" id="allsky-timelapse-body">
                    <video id="allsky-timelapse-video" controls class="img-fluid rounded" style="max-height:240px;">
                        <source src="${urls.daily_timelapse}" type="video/mp4">
                    </video>
                </div>
            </div>
        </div>`;
    }

    html += '</div>';
    return html;
}

// ── Error placeholder ─────────────────────────────────────────────────────────

function _notYetGeneratedHTML() {
    return `<p class="text-muted small p-2 mb-0"><i class="bi bi-hourglass-split me-1"></i>${i18n.t('observatory.not_yet_generated')}</p>`;
}

function _imageUnavailableHTML() {
    return `<p class="text-muted small p-2 mb-0"><i class="bi bi-wifi-off me-1"></i>${i18n.t('observatory.image_unavailable')}</p>`;
}

// ── Error handlers (set after DOM is ready, never inline) ─────────────────────

function _attachImageErrorHandlers(modules, urls) {
    // Live image — on error: show placeholder, stop interval, schedule retry
    const liveImg = document.getElementById('allsky-live-img');
    if (liveImg) {
        liveImg.onerror = () => {
            liveImg.onerror = null; // prevent any further onerror firing
            const body = document.getElementById('allsky-live-body');
            if (body) body.innerHTML = _imageUnavailableHTML();
            _stopLiveImageRefresh();
            // Retry after 5 min — just reload the whole Observatory widget
            _allskyImageRetryTimeout = setTimeout(loadAllSkyObservatory, _ALLSKY_IMAGE_RETRY_MS);
        };
    }

    // Mini-timelapse — static snapshot, no retry needed
    const miniImg = document.getElementById('allsky-mini-img');
    if (miniImg) {
        miniImg.onerror = () => {
            miniImg.onerror = null;
            const body = document.getElementById('allsky-mini-body');
            if (body) body.innerHTML = _notYetGeneratedHTML();
        };
    }

    // Keogram — generated end-of-night, show "not yet" message
    const keogramImg = document.getElementById('allsky-keogram-img');
    if (keogramImg) {
        keogramImg.onerror = () => {
            keogramImg.onerror = null;
            const body = document.getElementById('allsky-keogram-body');
            if (body) body.innerHTML = _notYetGeneratedHTML();
        };
    }

    // Startrails — same as keogram
    const startrailsImg = document.getElementById('allsky-startrails-img');
    if (startrailsImg) {
        startrailsImg.onerror = () => {
            startrailsImg.onerror = null;
            const body = document.getElementById('allsky-startrails-body');
            if (body) body.innerHTML = _notYetGeneratedHTML();
        };
    }

    // Daily timelapse video — <video> error fires on the element itself
    const video = document.getElementById('allsky-timelapse-video');
    if (video) {
        video.onerror = () => {
            video.onerror = null;
            const body = document.getElementById('allsky-timelapse-body');
            if (body) body.innerHTML = _notYetGeneratedHTML();
        };
    }
}

// ── Polling ───────────────────────────────────────────────────────────────────

function _startAllSkyPolling(modules, urls) {
    stopAllSkyPolling();

    // Attach error handlers before starting the interval
    _attachImageErrorHandlers(modules, urls);

    // Refresh live image every 30s only while the img element is present
    if (modules.live_image?.enabled && urls.live_image) {
        _allskyImageInterval = setInterval(() => {
            const img = document.getElementById('allsky-live-img');
            if (!img) {
                // Element was replaced by error handler — stop the interval
                _stopLiveImageRefresh();
                return;
            }
            img.src = `${urls.live_image}&_ts=${Date.now()}`;
        }, _ALLSKY_IMAGE_REFRESH_MS);
    }

    // Poll sensor data every 60s
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
    if (_allskySensorInterval)    { clearInterval(_allskySensorInterval);      _allskySensorInterval = null; }
    if (_allskyImageRetryTimeout) { clearTimeout(_allskyImageRetryTimeout);    _allskyImageRetryTimeout = null; }
}

// ── Sensor data ───────────────────────────────────────────────────────────────

async function _pollAllSkySensor() {
    const body = document.getElementById('allsky-sensor-body');
    if (!body) return;

    const data = await fetchJSONOnce('/api/connectors/allsky/status').catch(() => null);
    if (!data) {
        body.innerHTML = `<p class="text-danger small p-2">${i18n.t('observatory.sensor_unavailable')}</p>`;
        return;
    }

    // Update day/night badge on live image card (only if present)
    const badge = document.getElementById('allsky-day-night-badge');
    if (badge) {
        const dn = (data.DAY_OR_NIGHT || '').toLowerCase();
        badge.textContent = dn === 'night' ? i18n.t('observatory.night') : i18n.t('observatory.day');
        badge.className = `badge ms-2 ${dn === 'night' ? 'bg-primary' : 'bg-warning text-dark'}`;
    }

    // Humidity: prefer dew controller reading, fall back to direct sensor
    const humidityKey = data['AS_DEWCONTROLHUMIDITY'] != null ? 'AS_DEWCONTROLHUMIDITY' : 'AS_HUMIDITY';
    // Exposure: prefer human-readable string, fall back to raw µs
    const exposureKey = data['AS_sEXPOSURE'] != null ? 'AS_sEXPOSURE' : 'AS_EXPOSURE_US';
    const exposureUnit = exposureKey === 'AS_EXPOSURE_US' ? 'µs' : '';

    const rows = [
        { key: 'AS_TEMPERATURE_C',      label: i18n.t('observatory.temperature'),    unit: '°C', icon: 'bi-thermometer-half' },
        { key: humidityKey,             label: i18n.t('observatory.humidity'),        unit: '%',  icon: 'bi-droplet-half' },
        { key: 'AS_DEWCONTROLDEW',      label: i18n.t('observatory.dew_point'),       unit: '°C', icon: 'bi-water' },
        { key: 'AS_DEWCONTROLHEATER',   label: i18n.t('observatory.dew_heater'),      unit: '',   icon: 'bi-lightning-charge' },
        { key: 'AS_GAIN',               label: i18n.t('observatory.gain'),            unit: '',   icon: 'bi-sliders' },
        { key: exposureKey,             label: i18n.t('observatory.exposure'),        unit: exposureUnit, icon: 'bi-clock' },
        { key: 'AS_MEAN',               label: i18n.t('observatory.mean_brightness'), unit: '',   icon: 'bi-brightness-high' },
        { key: 'ALLSKY_VERSION',        label: i18n.t('observatory.version'),         unit: '',   icon: 'bi-info-circle' },
    ];

    let html = '<table class="table table-sm table-borderless mb-0 small">';
    for (const { key, label, unit, icon } of rows) {
        if (data[key] == null) continue;
        html += `<tr>
            <td class="text-muted pe-2"><i class="${icon} me-1"></i>${label}</td>
            <td class="fw-semibold">${data[key]}${unit ? ' ' + unit : ''}</td>
        </tr>`;
    }
    html += '</table>';

    if (!html.includes('<tr>')) {
        html = `<p class="text-muted small p-2">${i18n.t('observatory.sensor_no_data')}</p>`;
    }

    body.innerHTML = html;
}
