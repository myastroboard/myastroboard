// ======================
// Connectors Store — Parameters → Connectors sub-tab
// ======================

async function loadConnectorsStore() {
    const container = document.getElementById('connectors-store');
    if (!container) return;

    container.innerHTML = `<div class="text-muted text-center py-3"><div class="spinner-border spinner-border-sm"></div></div>`;

    const connectors = await fetchJSONOnce('/api/connectors').catch(() => null);
    if (!connectors) {
        container.innerHTML = `<div class="col-12"><div class="alert alert-danger">${i18n.t('connectors.load_error')}</div></div>`;
        return;
    }

    container.innerHTML = connectors.map(c => _connectorCard(c)).join('') +
        _suggestCard();

    // Wire up events
    connectors.forEach(c => _bindConnectorEvents(c));
}

function _connectorCard(c) {
    const installed = c.installed;
    const enabled   = c.enabled;
    const statusBadge = enabled
        ? `<span class="badge bg-success">${i18n.t('connectors.enabled')}</span>`
        : installed
            ? `<span class="badge bg-secondary">${i18n.t('connectors.installed')}</span>`
            : `<span class="badge bg-light text-dark border">${i18n.t('connectors.not_installed')}</span>`;

    return `
    <div class="col-12 col-md-6 col-xl-4">
        <div class="card h-100" id="connector-card-${c.name}">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-camera-video me-2 text-info"></i>${i18n.t(`connectors.${c.name}_label`)}</span>
                ${statusBadge}
            </div>
            <div class="card-body">
                <p class="text-muted small mb-2">${i18n.t(`connectors.${c.name}_desc`)}</p>
                ${c.min_version ? `<p class="text-muted small mb-2"><i class="bi bi-tag me-1"></i>${i18n.t('connectors.requires')} ${c.min_version}</p>` : ''}
                <button class="btn btn-sm btn-outline-primary w-100 connector-configure-btn" data-connector="${c.name}">
                    <i class="bi bi-gear me-1"></i>${i18n.t('connectors.configure')}
                </button>
            </div>
            <div class="connector-config-panel card-body border-top pt-3" id="connector-panel-${c.name}" style="display:none;">
                ${_connectorConfigForm(c)}
            </div>
        </div>
    </div>`;
}

function _connectorConfigForm(c) {
    const cfg = c.config || {};
    const modules = cfg.modules || {};

    const moduleRows = (c.modules || []).map(m => {
        const enabled = modules[m.slug]?.enabled ?? m.default_enabled;
        return `
        <div class="d-flex align-items-start gap-2 mb-2" id="connector-module-row-${c.name}-${m.slug}">
            <div class="form-check form-switch mt-1">
                <input class="form-check-input connector-module-toggle"
                       type="checkbox" id="module-${c.name}-${m.slug}"
                       data-connector="${c.name}" data-module="${m.slug}"
                       ${enabled ? 'checked' : ''}>
            </div>
            <div class="flex-grow-1">
                <label class="form-check-label fw-semibold small" for="module-${c.name}-${m.slug}">${i18n.t(`connectors.module_${m.slug}_label`)}</label>
                <p class="text-muted small mb-0">${i18n.t(`connectors.module_${m.slug}_desc`)}</p>
            </div>
            <span class="connector-module-health badge bg-secondary small align-self-center" id="health-${c.name}-${m.slug}">–</span>
        </div>`;
    }).join('');

    return `
    <div class="mb-3">
        <label class="form-label fw-semibold small" data-i18n="connectors.label_field">${i18n.t('connectors.label_field')}</label>
        <input type="text" class="form-control form-control-sm connector-label-input"
               id="connector-label-${c.name}" data-connector="${c.name}"
               value="${cfg.label || ''}" placeholder="${c.label}">
    </div>
    <div class="mb-3">
        <label class="form-label fw-semibold small" data-i18n="connectors.url_field">${i18n.t('connectors.url_field')}</label>
        <div class="input-group input-group-sm">
            <input type="url" class="form-control connector-url-input"
                   id="connector-url-${c.name}" data-connector="${c.name}"
                   value="${cfg.url || ''}" placeholder="http://allsky.local">
            <button class="btn btn-outline-secondary connector-test-btn" data-connector="${c.name}">
                <i class="bi bi-wifi"></i>
            </button>
        </div>
        <div class="form-text connector-test-result" id="test-result-${c.name}"></div>
    </div>
    <div class="mb-3 collapse" id="connector-advanced-${c.name}">
        ${c.name === 'allsky' ? _allskyAdvancedFields(cfg) : ''}
    </div>
    <a class="small text-muted d-block mb-3" data-bs-toggle="collapse" href="#connector-advanced-${c.name}">
        <i class="bi bi-chevron-down me-1"></i>${i18n.t('connectors.advanced_settings')}
    </a>
    <div class="mb-3">
        <p class="fw-semibold small mb-2" data-i18n="connectors.modules_title">${i18n.t('connectors.modules_title')}</p>
        ${moduleRows}
    </div>
    <div class="d-flex gap-2">
        <div class="form-check form-switch me-auto align-self-center">
            <input class="form-check-input connector-enabled-toggle" type="checkbox"
                   id="connector-enabled-${c.name}" data-connector="${c.name}"
                   ${c.enabled ? 'checked' : ''}>
            <label class="form-check-label small" for="connector-enabled-${c.name}" data-i18n="connectors.enabled_label">${i18n.t('connectors.enabled_label')}</label>
        </div>
        <button class="btn btn-sm btn-primary connector-save-btn" data-connector="${c.name}">
            <i class="bi bi-floppy me-1"></i>${i18n.t('common.save')}
        </button>
        <button class="btn btn-sm btn-outline-secondary connector-health-btn" data-connector="${c.name}">
            <i class="bi bi-heart-pulse"></i>
        </button>
    </div>`;
}

function _allskyAdvancedFields(cfg) {
    return `
    <label class="form-label fw-semibold small" data-i18n="connectors.allsky_image_path">${i18n.t('connectors.allsky_image_path')}</label>
    <input type="text" class="form-control form-control-sm mb-2"
           id="connector-allsky-image-path" value="${cfg.image_path || 'current/tmp'}" placeholder="current/tmp">
    <label class="form-label fw-semibold small" data-i18n="connectors.allsky_image_filename">${i18n.t('connectors.allsky_image_filename')}</label>
    <input type="text" class="form-control form-control-sm mb-2"
           id="connector-allsky-image-filename" value="${cfg.image_filename || 'image.jpg'}" placeholder="image.jpg">
    <label class="form-label fw-semibold small" data-i18n="connectors.allsky_export_json_path">${i18n.t('connectors.allsky_export_json_path')}</label>
    <input type="text" class="form-control form-control-sm"
           id="connector-allsky-export-json-path" value="${cfg.export_json_path || 'allskydata.json'}" placeholder="allskydata.json">`;
}

function _suggestCard() {
    const url = 'https://github.com/myastroboard/myastroboard/discussions/new?category=ideas&labels=enhancement,connector';

    return `
    <div class="col-12 col-md-6 col-xl-4">
        <div class="card h-100 text-center py-4 px-3" style="border: 2px dashed var(--bs-border-color);">
            <div class="card-body d-flex flex-column align-items-center justify-content-center">
                <i class="bi bi-plug fs-2 text-primary mb-3 d-block"></i>
                <h6 class="fw-semibold mb-2">${i18n.t('connectors.suggest_title')}</h6>
                <p class="text-muted small mb-3">${i18n.t('connectors.suggest_desc')}</p>
                <a href="${url}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary">
                    <i class="bi bi-lightbulb me-1"></i>${i18n.t('connectors.suggest_btn')}
                </a>
                <p class="text-muted mt-3 mb-0" style="font-size:0.75rem;">${i18n.t('connectors.suggest_examples')}</p>
            </div>
        </div>
    </div>`;
}

function _bindConnectorEvents(c) {
    // Toggle configure panel
    const configureBtn = document.querySelector(`.connector-configure-btn[data-connector="${c.name}"]`);
    const panel = document.getElementById(`connector-panel-${c.name}`);
    if (configureBtn && panel) {
        configureBtn.addEventListener('click', () => {
            const visible = panel.style.display !== 'none';
            panel.style.display = visible ? 'none' : 'block';
        });
    }

    // Test connection button
    const testBtn = document.querySelector(`.connector-test-btn[data-connector="${c.name}"]`);
    if (testBtn) {
        testBtn.addEventListener('click', () => _testConnector(c.name));
    }

    // Health check button
    const healthBtn = document.querySelector(`.connector-health-btn[data-connector="${c.name}"]`);
    if (healthBtn) {
        healthBtn.addEventListener('click', () => _runHealthCheck(c.name));
    }

    // Save button
    const saveBtn = document.querySelector(`.connector-save-btn[data-connector="${c.name}"]`);
    if (saveBtn) {
        saveBtn.addEventListener('click', () => _saveConnector(c.name));
    }
}

async function _testConnector(name) {
    const urlInput = document.getElementById(`connector-url-${name}`);
    const resultDiv = document.getElementById(`test-result-${name}`);
    if (!urlInput || !resultDiv) return;

    const url = urlInput.value.trim();
    if (!url) {
        resultDiv.innerHTML = `<span class="text-danger">${i18n.t('connectors.url_required')}</span>`;
        return;
    }

    resultDiv.innerHTML = `<span class="text-muted"><div class="spinner-border spinner-border-sm me-1"></div>${i18n.t('connectors.testing')}</span>`;

    const data = await fetchJSONOnce(`/api/connectors/${name}/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
    }).catch(() => null);

    // Trigger fresh health check by saving URL first, then checking
    // Simpler: just try to fetch the URL from the client side (CORS may block, so use backend)
    // We'll do a GET on the health endpoint after saving the URL
    resultDiv.innerHTML = `<span class="text-info">${i18n.t('connectors.save_to_test')}</span>`;
}

async function _runHealthCheck(name) {
    const resultDiv = document.getElementById(`test-result-${name}`);
    if (resultDiv) resultDiv.innerHTML = `<span class="text-muted"><div class="spinner-border spinner-border-sm me-1"></div>${i18n.t('connectors.checking_health')}</span>`;

    // Force fresh check by invalidating cache via a query param
    const health = await fetchJSONOnce(`/api/connectors/${name}/health?fresh=1`).catch(() => null);
    if (!health) {
        if (resultDiv) resultDiv.innerHTML = `<span class="text-danger">${i18n.t('connectors.health_error')}</span>`;
        return;
    }

    if (!health.reachable) {
        if (resultDiv) resultDiv.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle me-1"></i>${i18n.t('connectors.unreachable')}</span>`;
    } else {
        if (resultDiv) resultDiv.innerHTML = `<span class="text-success"><i class="bi bi-check-circle me-1"></i>${i18n.t('connectors.reachable')}</span>`;
    }

    // Update per-module health badges
    for (const [slug, result] of Object.entries(health.modules || {})) {
        const badge = document.getElementById(`health-${name}-${slug}`);
        if (!badge) continue;
        badge.textContent = result.ok ? '✓' : '✗';
        badge.className = `connector-module-health badge small align-self-center ${result.ok ? 'bg-success' : 'bg-danger'}`;
        badge.title = result.detail || '';
    }
}

async function _saveConnector(name) {
    const urlInput    = document.getElementById(`connector-url-${name}`);
    const labelInput  = document.getElementById(`connector-label-${name}`);
    const enabledChk  = document.getElementById(`connector-enabled-${name}`);
    const saveBtn     = document.querySelector(`.connector-save-btn[data-connector="${name}"]`);

    if (!urlInput) return;

    const config = await fetchJSONOnce('/api/config').catch(() => null);
    if (!config) return;

    const connectorsCfg = config.connectors || {};
    const existing = connectorsCfg[name] || {};

    const modules = {};
    document.querySelectorAll(`.connector-module-toggle[data-connector="${name}"]`).forEach(chk => {
        modules[chk.dataset.module] = { enabled: chk.checked };
    });

    const updated = {
        ...existing,
        url:     urlInput.value.trim(),
        label:   labelInput ? labelInput.value.trim() : existing.label,
        enabled: enabledChk ? enabledChk.checked : existing.enabled,
        modules: { ...(existing.modules || {}), ...modules },
    };

    // AllSky advanced fields
    if (name === 'allsky') {
        const imgPath   = document.getElementById('connector-allsky-image-path');
        const imgFile   = document.getElementById('connector-allsky-image-filename');
        const jsonPath  = document.getElementById('connector-allsky-export-json-path');
        if (imgPath)  updated.image_path       = imgPath.value.trim() || 'current/tmp';
        if (imgFile)  updated.image_filename   = imgFile.value.trim() || 'image.jpg';
        if (jsonPath) updated.export_json_path = jsonPath.value.trim() || 'allskydata.json';
    }

    config.connectors = { ...connectorsCfg, [name]: updated };

    if (saveBtn) { saveBtn.disabled = true; saveBtn.innerHTML = `<div class="spinner-border spinner-border-sm"></div>`; }

    const result = await fetchJSONOnce('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
    }).catch(() => null);

    if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = `<i class="bi bi-floppy me-1"></i>${i18n.t('common.save')}`; }

    if (result?.status === 'success') {
        updateObservatoryNavVisibility();
        _runHealthCheck(name);
    }
}

function updateObservatoryNavVisibility() {
    fetchJSONOnce('/api/connectors').then(connectors => {
        const hasEnabled = (connectors || []).some(c => c.enabled);
        const navItem = document.getElementById('observatory-nav-item');
        if (navItem) navItem.style.display = hasEnabled ? '' : 'none';
    }).catch(() => {});
}
