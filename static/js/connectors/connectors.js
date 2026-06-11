// ======================
// Connectors Store — Parameters → Connectors sub-tab
// ======================

async function loadConnectorsStore() {
    const container = document.getElementById('connectors-store');
    if (!container) return;

    DOMUtils.clear(container);
    const loading = document.createElement('div');
    loading.className = 'text-muted text-center py-3';
    const spinner = document.createElement('div');
    spinner.className = 'spinner-border spinner-border-sm';
    loading.appendChild(spinner);
    container.appendChild(loading);

    const connectors = await fetchJSONOnce('/api/connectors').catch(() => null);
    if (!connectors) {
        DOMUtils.clear(container);
        const col = document.createElement('div');
        col.className = 'col-12';
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger';
        alert.textContent = i18n.t('connectors.load_error');
        col.appendChild(alert);
        container.appendChild(col);
        return;
    }

    DOMUtils.clear(container);
    connectors.forEach(c => container.appendChild(_connectorCard(c)));
    container.appendChild(_suggestCard());
    connectors.forEach(c => _bindConnectorEvents(c));
}

function _connectorCard(c) {
    const col = document.createElement('div');
    col.className = 'col-12 col-md-6 col-xl-4';

    const card = document.createElement('div');
    card.className = 'card h-100';
    card.id = `connector-card-${c.name}`;

    // Header
    const header = document.createElement('div');
    header.className = 'card-header d-flex justify-content-between align-items-center';

    const headerLeft = document.createElement('span');
    headerLeft.appendChild(DOMUtils.createIcon('bi bi-camera-video me-2 text-info'));
    headerLeft.appendChild(document.createTextNode(i18n.t(`connectors.${c.name}_label`)));
    if (c.homepage) {
        const link = document.createElement('a');
        link.href = c.homepage;
        link.target = '_blank';
        link.rel = 'noopener';
        link.className = 'ms-2 text-muted';
        link.title = c.homepage;
        link.appendChild(DOMUtils.createIcon('bi bi-github'));
        headerLeft.appendChild(link);
    }

    const badge = document.createElement('span');
    if (c.enabled) {
        badge.className = 'badge bg-success';
        badge.textContent = i18n.t('connectors.enabled');
    } else if (c.installed) {
        badge.className = 'badge bg-secondary';
        badge.textContent = i18n.t('connectors.installed');
    } else {
        badge.className = 'badge bg-light text-dark border';
        badge.textContent = i18n.t('connectors.not_installed');
    }
    header.appendChild(headerLeft);
    header.appendChild(badge);

    // Body
    const body = document.createElement('div');
    body.className = 'card-body';

    const desc = document.createElement('p');
    desc.className = 'text-muted small mb-2';
    desc.textContent = i18n.t(`connectors.${c.name}_desc`);
    body.appendChild(desc);

    if (c.min_version) {
        const ver = document.createElement('p');
        ver.className = 'text-muted small mb-2';
        ver.appendChild(DOMUtils.createIcon('bi bi-tag me-1'));
        ver.appendChild(document.createTextNode(`${i18n.t('connectors.requires')} ${c.min_version}`));
        body.appendChild(ver);
    }

    const configBtn = document.createElement('button');
    configBtn.className = 'btn btn-sm btn-outline-primary w-100 connector-configure-btn';
    configBtn.dataset.connector = c.name;
    configBtn.appendChild(DOMUtils.createIcon('bi bi-gear me-1'));
    configBtn.appendChild(document.createTextNode(i18n.t('connectors.configure')));
    body.appendChild(configBtn);

    // Config panel
    const panel = document.createElement('div');
    panel.className = 'connector-config-panel card-body border-top pt-3';
    panel.id = `connector-panel-${c.name}`;
    panel.style.display = 'none';
    panel.appendChild(_connectorConfigForm(c));

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(panel);
    col.appendChild(card);
    return col;
}

function _connectorConfigForm(c) {
    const cfg     = c.config || {};
    const modules = cfg.modules || {};
    const frag    = document.createDocumentFragment();

    // Label
    const labelDiv = document.createElement('div');
    labelDiv.className = 'mb-3';
    const labelLbl = document.createElement('label');
    labelLbl.className = 'form-label fw-semibold small';
    labelLbl.setAttribute('for', `connector-label-${c.name}`);
    labelLbl.textContent = i18n.t('connectors.label_field');
    const labelInput = document.createElement('input');
    labelInput.type = 'text';
    labelInput.className = 'form-control form-control-sm connector-label-input';
    labelInput.id = `connector-label-${c.name}`;
    labelInput.dataset.connector = c.name;
    labelInput.value = cfg.label || '';
    labelInput.placeholder = c.label;
    labelDiv.appendChild(labelLbl);
    labelDiv.appendChild(labelInput);
    frag.appendChild(labelDiv);

    // URL
    const urlDiv = document.createElement('div');
    urlDiv.className = 'mb-3';
    const urlLbl = document.createElement('label');
    urlLbl.className = 'form-label fw-semibold small';
    urlLbl.setAttribute('for', `connector-url-${c.name}`);
    urlLbl.textContent = i18n.t('connectors.url_field');
    urlDiv.appendChild(urlLbl);

    const inputGroup = document.createElement('div');
    inputGroup.className = 'input-group input-group-sm';
    const urlInput = document.createElement('input');
    urlInput.type = 'url';
    urlInput.className = 'form-control connector-url-input';
    urlInput.id = `connector-url-${c.name}`;
    urlInput.dataset.connector = c.name;
    urlInput.value = cfg.url || '';
    urlInput.placeholder = 'http://allsky.local';
    const testBtn = document.createElement('button');
    testBtn.className = 'btn btn-outline-secondary connector-test-btn';
    testBtn.dataset.connector = c.name;
    testBtn.appendChild(DOMUtils.createIcon('bi bi-wifi'));
    inputGroup.appendChild(urlInput);
    inputGroup.appendChild(testBtn);
    urlDiv.appendChild(inputGroup);

    const testResult = document.createElement('div');
    testResult.className = 'form-text connector-test-result';
    testResult.id = `test-result-${c.name}`;
    urlDiv.appendChild(testResult);
    frag.appendChild(urlDiv);

    // Advanced (collapse)
    const advDiv = document.createElement('div');
    advDiv.className = 'mb-3 collapse';
    advDiv.id = `connector-advanced-${c.name}`;
    if (c.name === 'allsky') advDiv.appendChild(_allskyAdvancedFields(cfg));
    frag.appendChild(advDiv);

    const advLink = document.createElement('a');
    advLink.className = 'small text-muted d-block mb-3';
    advLink.dataset.bsToggle = 'collapse';
    advLink.href = `#connector-advanced-${c.name}`;
    advLink.appendChild(DOMUtils.createIcon('bi bi-chevron-down me-1'));
    advLink.appendChild(document.createTextNode(i18n.t('connectors.advanced_settings')));
    frag.appendChild(advLink);

    // Modules
    const modsDiv = document.createElement('div');
    modsDiv.className = 'mb-3';
    const modsTitle = document.createElement('p');
    modsTitle.className = 'fw-semibold small mb-2';
    modsTitle.textContent = i18n.t('connectors.modules_title');
    modsDiv.appendChild(modsTitle);

    (c.modules || []).forEach(m => {
        const enabled = modules[m.slug]?.enabled ?? m.default_enabled;
        const row = document.createElement('div');
        row.className = 'd-flex align-items-start gap-2 mb-2';
        row.id = `connector-module-row-${c.name}-${m.slug}`;

        const switchWrap = document.createElement('div');
        switchWrap.className = 'form-check form-switch mt-1';
        const chk = document.createElement('input');
        chk.type = 'checkbox';
        chk.className = 'form-check-input connector-module-toggle';
        chk.id = `module-${c.name}-${m.slug}`;
        chk.dataset.connector = c.name;
        chk.dataset.module = m.slug;
        chk.checked = enabled;
        switchWrap.appendChild(chk);

        const info = document.createElement('div');
        info.className = 'flex-grow-1';
        const modLbl = document.createElement('label');
        modLbl.className = 'form-check-label fw-semibold small';
        modLbl.setAttribute('for', `module-${c.name}-${m.slug}`);
        modLbl.textContent = i18n.t(`connectors.module_${m.slug}_label`);
        const modDesc = document.createElement('p');
        modDesc.className = 'text-muted small mb-0';
        modDesc.textContent = i18n.t(`connectors.module_${m.slug}_desc`);
        info.appendChild(modLbl);
        info.appendChild(modDesc);

        const healthBadge = document.createElement('span');
        healthBadge.className = 'connector-module-health badge bg-secondary small align-self-center';
        healthBadge.id = `health-${c.name}-${m.slug}`;
        healthBadge.textContent = '–';

        row.appendChild(switchWrap);
        row.appendChild(info);
        row.appendChild(healthBadge);
        modsDiv.appendChild(row);
    });
    frag.appendChild(modsDiv);

    // Actions
    const actions = document.createElement('div');
    actions.className = 'd-flex gap-2';

    const switchRow = document.createElement('div');
    switchRow.className = 'form-check form-switch me-auto align-self-center';
    const enabledChk = document.createElement('input');
    enabledChk.type = 'checkbox';
    enabledChk.className = 'form-check-input connector-enabled-toggle';
    enabledChk.id = `connector-enabled-${c.name}`;
    enabledChk.dataset.connector = c.name;
    enabledChk.checked = c.enabled;
    const enabledLbl = document.createElement('label');
    enabledLbl.className = 'form-check-label small';
    enabledLbl.setAttribute('for', `connector-enabled-${c.name}`);
    enabledLbl.textContent = i18n.t('connectors.enabled_label');
    switchRow.appendChild(enabledChk);
    switchRow.appendChild(enabledLbl);

    const saveBtn = document.createElement('button');
    saveBtn.className = 'btn btn-sm btn-primary connector-save-btn';
    saveBtn.dataset.connector = c.name;
    saveBtn.appendChild(DOMUtils.createIcon('bi bi-floppy me-1'));
    saveBtn.appendChild(document.createTextNode(i18n.t('common.save')));

    const healthBtn = document.createElement('button');
    healthBtn.className = 'btn btn-sm btn-outline-secondary connector-health-btn';
    healthBtn.dataset.connector = c.name;
    healthBtn.appendChild(DOMUtils.createIcon('bi bi-heart-pulse'));

    actions.appendChild(switchRow);
    actions.appendChild(saveBtn);
    actions.appendChild(healthBtn);
    frag.appendChild(actions);

    return frag;
}

function _allskyAdvancedFields(cfg) {
    const frag = document.createDocumentFragment();
    const fields = [
        { id: 'connector-allsky-image-path',      key: 'allsky_image_path',       value: cfg.image_path       || 'current/tmp',     placeholder: 'current/tmp' },
        { id: 'connector-allsky-image-filename',   key: 'allsky_image_filename',    value: cfg.image_filename   || 'image.jpg',       placeholder: 'image.jpg' },
        { id: 'connector-allsky-export-json-path', key: 'allsky_export_json_path',  value: cfg.export_json_path || 'allskydata.json', placeholder: 'allskydata.json' },
    ];
    fields.forEach(({ id, key, value, placeholder }) => {
        const lbl = document.createElement('label');
        lbl.className = 'form-label fw-semibold small';
        lbl.setAttribute('for', id);
        lbl.textContent = i18n.t(`connectors.${key}`);
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm mb-2';
        input.id = id;
        input.value = value;
        input.placeholder = placeholder;
        frag.appendChild(lbl);
        frag.appendChild(input);
    });
    return frag;
}

function _suggestCard() {
    const url = 'https://github.com/myastroboard/myastroboard/discussions/new?category=ideas&labels=enhancement,connector';

    const col = document.createElement('div');
    col.className = 'col-12 col-md-6 col-xl-4';

    const card = document.createElement('div');
    card.className = 'card h-100 text-center py-4 px-3 connector-suggest-card';

    const body = document.createElement('div');
    body.className = 'card-body d-flex flex-column align-items-center justify-content-center';

    body.appendChild(DOMUtils.createIcon('bi bi-plug fs-2 text-primary mb-3 d-block'));

    const title = document.createElement('h6');
    title.className = 'fw-semibold mb-2';
    title.textContent = i18n.t('connectors.suggest_title');
    body.appendChild(title);

    const desc = document.createElement('p');
    desc.className = 'text-muted small mb-3';
    desc.textContent = i18n.t('connectors.suggest_desc');
    body.appendChild(desc);

    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.className = 'btn btn-sm btn-outline-primary';
    link.appendChild(DOMUtils.createIcon('bi bi-lightbulb me-1'));
    link.appendChild(document.createTextNode(i18n.t('connectors.suggest_btn')));
    body.appendChild(link);

    const examples = document.createElement('p');
    examples.className = 'text-muted mt-3 mb-0 small';
    examples.textContent = i18n.t('connectors.suggest_examples');
    body.appendChild(examples);

    card.appendChild(body);
    col.appendChild(card);
    return col;
}

function _bindConnectorEvents(c) {
    const configureBtn = document.querySelector(`.connector-configure-btn[data-connector="${c.name}"]`);
    const panel = document.getElementById(`connector-panel-${c.name}`);
    if (configureBtn && panel) {
        configureBtn.addEventListener('click', () => {
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        });
    }

    const testBtn = document.querySelector(`.connector-test-btn[data-connector="${c.name}"]`);
    if (testBtn) testBtn.addEventListener('click', () => _testConnector(c.name));

    const healthBtn = document.querySelector(`.connector-health-btn[data-connector="${c.name}"]`);
    if (healthBtn) healthBtn.addEventListener('click', () => _runHealthCheck(c.name));

    const saveBtn = document.querySelector(`.connector-save-btn[data-connector="${c.name}"]`);
    if (saveBtn) saveBtn.addEventListener('click', () => _saveConnector(c.name));
}

function _setResultMessage(resultDiv, text, cssClass, iconClass) {
    DOMUtils.clear(resultDiv);
    const span = document.createElement('span');
    span.className = cssClass;
    if (iconClass) span.appendChild(DOMUtils.createIcon(`${iconClass} me-1`));
    span.appendChild(document.createTextNode(text));
    resultDiv.appendChild(span);
}

function _setResultSpinner(resultDiv, text) {
    DOMUtils.clear(resultDiv);
    const span = document.createElement('span');
    span.className = 'text-muted';
    const spinner = document.createElement('div');
    spinner.className = 'spinner-border spinner-border-sm me-1';
    span.appendChild(spinner);
    span.appendChild(document.createTextNode(text));
    resultDiv.appendChild(span);
}

async function _testConnector(name) {
    const urlInput  = document.getElementById(`connector-url-${name}`);
    const resultDiv = document.getElementById(`test-result-${name}`);
    if (!urlInput || !resultDiv) return;

    const url = urlInput.value.trim();
    if (!url) {
        _setResultMessage(resultDiv, i18n.t('connectors.url_required'), 'text-danger');
        return;
    }

    _setResultSpinner(resultDiv, i18n.t('connectors.testing'));

    await fetchJSONOnce(`/api/connectors/${name}/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
    }).catch(() => null);

    _setResultMessage(resultDiv, i18n.t('connectors.save_to_test'), 'text-info');
}

async function _runHealthCheck(name) {
    const resultDiv = document.getElementById(`test-result-${name}`);
    if (resultDiv) _setResultSpinner(resultDiv, i18n.t('connectors.checking_health'));

    const health = await fetchJSONOnce(`/api/connectors/${name}/health?fresh=1`).catch(() => null);
    if (!health) {
        if (resultDiv) _setResultMessage(resultDiv, i18n.t('connectors.health_error'), 'text-danger');
        return;
    }

    if (!health.reachable) {
        if (resultDiv) _setResultMessage(resultDiv, i18n.t('connectors.unreachable'), 'text-danger', 'bi bi-x-circle');
    } else {
        if (resultDiv) _setResultMessage(resultDiv, i18n.t('connectors.reachable'), 'text-success', 'bi bi-check-circle');
    }

    for (const [slug, result] of Object.entries(health.modules || {})) {
        const badge = document.getElementById(`health-${name}-${slug}`);
        if (!badge) continue;
        badge.textContent = result.ok ? '✓' : '✗';
        badge.className = `connector-module-health badge small align-self-center ${result.ok ? 'bg-success' : 'bg-danger'}`;
        badge.title = result.detail || '';
    }
}

async function _saveConnector(name) {
    const urlInput   = document.getElementById(`connector-url-${name}`);
    const labelInput = document.getElementById(`connector-label-${name}`);
    const enabledChk = document.getElementById(`connector-enabled-${name}`);
    const saveBtn    = document.querySelector(`.connector-save-btn[data-connector="${name}"]`);

    if (!urlInput) return;

    const config = await fetchJSONOnce('/api/config').catch(() => null);
    if (!config) return;

    const connectorsCfg = config.connectors || {};
    const existing      = connectorsCfg[name] || {};

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

    if (name === 'allsky') {
        const imgPath  = document.getElementById('connector-allsky-image-path');
        const imgFile  = document.getElementById('connector-allsky-image-filename');
        const jsonPath = document.getElementById('connector-allsky-export-json-path');
        if (imgPath)  updated.image_path       = imgPath.value.trim()  || 'current/tmp';
        if (imgFile)  updated.image_filename   = imgFile.value.trim()  || 'image.jpg';
        if (jsonPath) updated.export_json_path = jsonPath.value.trim() || 'allskydata.json';
    }

    config.connectors = { ...connectorsCfg, [name]: updated };

    if (saveBtn) {
        saveBtn.disabled = true;
        DOMUtils.clear(saveBtn);
        const spinner = document.createElement('div');
        spinner.className = 'spinner-border spinner-border-sm';
        saveBtn.appendChild(spinner);
    }

    const result = await fetchJSONOnce('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
    }).catch(() => null);

    if (saveBtn) {
        saveBtn.disabled = false;
        DOMUtils.clear(saveBtn);
        saveBtn.appendChild(DOMUtils.createIcon('bi bi-floppy me-1'));
        saveBtn.appendChild(document.createTextNode(i18n.t('common.save')));
    }

    if (result?.status === 'success') {
        updateObservatoryNavVisibility();
        _runHealthCheck(name);
    }
}

// ── Observatory dispatcher ────────────────────────────────────────────────────

const _CONNECTOR_SCRIPTS = {
    allsky: '/static/js/connectors/allsky.js',
};

const _CONNECTOR_LOADERS = {
    allsky: 'loadAllSkyObservatory',
};

const _CONNECTOR_CONTAINERS = {
    allsky: 'allsky-observatory',
};

const _CONNECTOR_ICONS = {
    allsky: 'bi-camera-video',
};

function _ensureScript(src) {
    const version = document.querySelector('meta[name="app-version"]')?.content || '';
    const fullSrc = `${src}?v=${version}`;
    return new Promise((resolve, reject) => {
        if (document.querySelector(`script[src="${fullSrc}"]`)) { resolve(); return; }
        const s = document.createElement('script');
        s.src = fullSrc;
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
    });
}

function _createConnectorContainer(parent, connector) {
    const id    = _CONNECTOR_CONTAINERS[connector.name] || `${connector.name}-observatory`;
    const label = connector.config?.label || connector.label;
    const icon  = _CONNECTOR_ICONS[connector.name] || 'bi-plug';

    DOMUtils.clear(parent);

    const wrapper = document.createElement('div');
    wrapper.className = 'shadow p-2 mb-3 rounded bg-sub-container sub-tab-content active';

    const h2 = document.createElement('h2');
    h2.appendChild(DOMUtils.createIcon(`bi ${icon} icon-inline text-info`));
    h2.appendChild(document.createTextNode(` ${label}`));
    wrapper.appendChild(h2);

    const inner = document.createElement('div');
    inner.id = id;
    const spinner = document.createElement('div');
    spinner.className = 'text-muted text-center py-4';
    const spinnerIcon = document.createElement('div');
    spinnerIcon.className = 'spinner-border spinner-border-sm';
    spinner.appendChild(spinnerIcon);
    inner.appendChild(spinner);
    wrapper.appendChild(inner);

    parent.appendChild(wrapper);
}

async function _loadConnectorScript(connector) {
    const src    = _CONNECTOR_SCRIPTS[connector.name];
    const loader = _CONNECTOR_LOADERS[connector.name];
    if (!src || !loader) return;
    await _ensureScript(src);
    if (typeof window[loader] === 'function') window[loader]();
}

async function _switchConnectorPanel(connector) {
    if (typeof stopAllSkyPolling === 'function') stopAllSkyPolling();
    const panel = document.getElementById('observatory-connector-panel');
    if (panel) _createConnectorContainer(panel, connector);
    await _loadConnectorScript(connector);
}

async function loadObservatory() {
    const container = document.getElementById('observatory-content');
    if (!container) return;

    const connectors = await fetchJSONOnce('/api/connectors').catch(() => []);
    const enabled = (connectors || []).filter(c => c.enabled);

    if (enabled.length === 0) {
        DOMUtils.clear(container);
        const wrapper = document.createElement('div');
        wrapper.className = 'shadow p-2 mb-3 rounded bg-sub-container';
        const inner = document.createElement('div');
        inner.className = 'text-center py-4';
        inner.appendChild(DOMUtils.createIcon('bi bi-plug fs-2 d-block mb-2 opacity-50'));
        const msg = document.createElement('span');
        msg.className = 'text-muted';
        msg.textContent = i18n.t('observatory.not_configured');
        inner.appendChild(msg);
        wrapper.appendChild(inner);
        container.appendChild(wrapper);
        return;
    }

    if (enabled.length === 1) {
        _createConnectorContainer(container, enabled[0]);
        await _loadConnectorScript(enabled[0]);
        return;
    }

    // Multiple connectors — populate sub-tabs nav + render first connector
    const subtabsContainer = document.getElementById('observatory-subtabs-container');
    const subtabsEl        = document.getElementById('observatory-subtabs');
    if (subtabsContainer) subtabsContainer.style.display = '';
    if (subtabsEl) {
        DOMUtils.clear(subtabsEl);
        enabled.forEach((c, i) => {
            const li = document.createElement('li');
            li.className = 'nav-item';
            const link = document.createElement('a');
            link.className = `nav-link sub-tab-btn${i === 0 ? ' active' : ''}`;
            link.href = '#';
            link.dataset.observatoryConnector = c.name;
            link.appendChild(DOMUtils.createIcon(`bi ${_CONNECTOR_ICONS[c.name] || 'bi-plug'} icon-inline text-info`));
            link.appendChild(document.createTextNode(` ${i18n.t(`connectors.${c.name}_label`)}`));
            li.appendChild(link);
            subtabsEl.appendChild(li);
        });

        subtabsEl.querySelectorAll('[data-observatory-connector]').forEach(link => {
            link.addEventListener('click', async (e) => {
                e.preventDefault();
                subtabsEl.querySelectorAll('[data-observatory-connector]').forEach(l => l.classList.remove('active'));
                link.classList.add('active');
                const c = enabled.find(x => x.name === link.dataset.observatoryConnector);
                if (c) await _switchConnectorPanel(c);
            });
        });
    }

    DOMUtils.clear(container);
    const panel = document.createElement('div');
    panel.id = 'observatory-connector-panel';
    container.appendChild(panel);
    await _switchConnectorPanel(enabled[0]);
}

function updateObservatoryNavVisibility() {
    fetchJSONOnce('/api/connectors').then(connectors => {
        const hasEnabled = (connectors || []).some(c => c.enabled);
        const navItem = document.getElementById('observatory-nav-item');
        if (navItem) navItem.style.display = hasEnabled ? '' : 'none';
    }).catch(() => {});
}
