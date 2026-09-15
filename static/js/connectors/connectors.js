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

    // MyAstroShine is not a BaseConnector (bidirectional, lives in the AstroDex
    // tab) so it is not in /api/connectors - render its card here, next to the
    // BaseConnector cards, backed by its own /api/astrodex/integration/* routes.
    const masCard = await _myAstroShineCard();
    if (masCard) container.appendChild(masCard);

    container.appendChild(_suggestCard());
    connectors.forEach(c => _bindConnectorEvents(c));
    if (masCard) _bindMyAstroShineEvents();
}

// A connector does not necessarily feed the Observatory: AllSky does, MyAstroShine feeds
// the AstroDex, and a connector can feed nothing at all (self-contained). `target_modules`
// carries the app areas each connector surfaces in; these are navbar tabs, so their labels
// are reused from the navbar namespace rather than duplicated per connector.
const _TARGET_MODULE_I18N_KEYS = {
    observatory:      'navbar.observatory',
    astrodex:         'navbar.astrodex',
    astrophotography: 'navbar.astrophotography',
    weather:          'navbar.weather',
    skytonight:       'navbar.skytonight',
    equipment:        'navbar.equipment',
    plan_my_night:    'navbar.plan_my_night',
    observation_log:  'navbar.observation_log',
    calendar:         'navbar.calendar',
};

/**
 * "Appears in: [Observatory]" row for a connector card.
 * An empty/missing target_modules list renders a single "Standalone" badge — that is a
 * deliberate state (a self-contained connector), not missing data.
 */
function _targetModulesRow(targetModules) {
    const row = document.createElement('p');
    row.className = 'small mb-2 d-flex flex-wrap align-items-center gap-1';

    const label = document.createElement('span');
    label.className = 'text-muted';
    label.textContent = i18n.t('connectors.target_modules_title');
    row.appendChild(label);

    const slugs = Array.isArray(targetModules) ? targetModules : [];
    if (slugs.length === 0) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-light text-dark border';
        badge.title = i18n.t('connectors.target_modules_standalone_hint');
        badge.textContent = i18n.t('connectors.target_modules_standalone');
        row.appendChild(badge);
        return row;
    }

    slugs.forEach(slug => {
        const badge = document.createElement('span');
        badge.className = 'badge bg-primary-subtle text-primary-emphasis border border-primary-subtle';
        const key = _TARGET_MODULE_I18N_KEYS[slug];
        badge.textContent = key ? i18n.t(key) : slug;
        row.appendChild(badge);
    });
    return row;
}

/**
 * "Requires <version>" line, or null when the connector declares no minimum version.
 */
function _minVersionRow(minVersion) {
    if (!minVersion) return null;
    const ver = document.createElement('p');
    ver.className = 'text-muted small mb-2';
    ver.appendChild(DOMUtils.createIcon('bi bi-tag me-1'));
    ver.appendChild(document.createTextNode(`${i18n.t('connectors.requires')} ${minVersion}`));
    return ver;
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

    body.appendChild(_targetModulesRow(c.target_modules));

    const verRow = _minVersionRow(c.min_version);
    if (verRow) body.appendChild(verRow);

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
    urlInput.placeholder = 'http://192.168.x.x';
    const testBtn = document.createElement('button');
    testBtn.className = 'btn btn-outline-secondary connector-test-btn';
    testBtn.dataset.connector = c.name;
    testBtn.appendChild(DOMUtils.createIcon('bi bi-wifi'));
    inputGroup.appendChild(urlInput);
    inputGroup.appendChild(testBtn);
    urlDiv.appendChild(inputGroup);

    const localWarn = document.createElement('div');
    localWarn.className = 'form-text text-warning connector-local-warn d-none';
    localWarn.appendChild(DOMUtils.createIcon('bi bi-exclamation-triangle me-1'));
    localWarn.appendChild(document.createTextNode(i18n.t('connectors.local_hostname_warning')));
    urlDiv.appendChild(localWarn);

    const _updateLocalWarn = () => {
        const v = urlInput.value.trim();
        localWarn.classList.toggle('d-none', !/\.local(\/|$)/i.test(v));
    };
    urlInput.addEventListener('input', _updateLocalWarn);
    _updateLocalWarn();

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

// ── MyAstroShine integration card ─────────────────────────────────────────────

function _masField(labelText, inputId, type, value, placeholder) {
    const wrap = document.createElement('div');
    wrap.className = 'mb-3';
    const lbl = document.createElement('label');
    lbl.className = 'form-label fw-semibold small';
    lbl.setAttribute('for', inputId);
    lbl.textContent = labelText;
    const input = document.createElement('input');
    input.type = type;
    input.className = 'form-control form-control-sm';
    input.id = inputId;
    if (value) input.value = value;
    if (placeholder) input.placeholder = placeholder;
    if (type === 'password') input.autocomplete = 'new-password';
    wrap.appendChild(lbl);
    wrap.appendChild(input);
    return wrap;
}

async function _myAstroShineCard() {
    const cfg = await fetchJSONOnce('/api/astrodex/integration/config').catch(() => null);
    if (!cfg) return null;

    const col = document.createElement('div');
    col.className = 'col-12 col-md-6 col-xl-4';

    const card = document.createElement('div');
    card.className = 'card h-100';
    card.id = 'connector-card-myastroshine';

    // Header
    const header = document.createElement('div');
    header.className = 'card-header d-flex justify-content-between align-items-center';
    const headerLeft = document.createElement('span');
    headerLeft.appendChild(DOMUtils.createIcon('bi bi-stars me-2 text-info'));
    headerLeft.appendChild(document.createTextNode(cfg.label || i18n.t('connectors.myastroshine_label')));
    if (cfg.homepage) {
        const repoLink = document.createElement('a');
        repoLink.href = cfg.homepage;
        repoLink.target = '_blank';
        repoLink.rel = 'noopener';
        repoLink.className = 'ms-2 text-muted';
        repoLink.title = cfg.homepage;
        repoLink.appendChild(DOMUtils.createIcon('bi bi-github'));
        headerLeft.appendChild(repoLink);
    }

    const badge = document.createElement('span');
    if (cfg.effective_enabled) {
        badge.className = 'badge bg-success';
        badge.textContent = i18n.t('connectors.enabled');
    } else if (cfg.url) {
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
    desc.textContent = i18n.t('connectors.myastroshine_desc');
    body.appendChild(desc);

    body.appendChild(_targetModulesRow(cfg.target_modules));

    const masVerRow = _minVersionRow(cfg.min_version);
    if (masVerRow) body.appendChild(masVerRow);

    const configBtn = document.createElement('button');
    configBtn.className = 'btn btn-sm btn-outline-primary w-100';
    configBtn.id = 'connector-configure-myastroshine';
    configBtn.appendChild(DOMUtils.createIcon('bi bi-gear me-1'));
    configBtn.appendChild(document.createTextNode(i18n.t('connectors.configure')));
    body.appendChild(configBtn);

    // Config panel
    const panel = document.createElement('div');
    panel.className = 'connector-config-panel card-body border-top pt-3';
    panel.id = 'connector-panel-myastroshine';
    panel.style.display = 'none';
    panel.appendChild(_myAstroShineConfigForm(cfg));

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(panel);
    col.appendChild(card);
    return col;
}

function _myAstroShineConfigForm(cfg) {
    const frag = document.createDocumentFragment();
    const unchanged = i18n.t('connectors.myastroshine_secret_unchanged');

    frag.appendChild(_masField(
        i18n.t('connectors.label_field'), 'mas-label', 'text', cfg.label || '', i18n.t('connectors.myastroshine_label')));

    // URL + server-side reachability test button
    const urlDiv = document.createElement('div');
    urlDiv.className = 'mb-3';
    const urlLbl = document.createElement('label');
    urlLbl.className = 'form-label fw-semibold small';
    urlLbl.setAttribute('for', 'mas-url');
    urlLbl.textContent = i18n.t('connectors.myastroshine_url_field');
    urlDiv.appendChild(urlLbl);
    const inputGroup = document.createElement('div');
    inputGroup.className = 'input-group input-group-sm';
    const urlInput = document.createElement('input');
    urlInput.type = 'url';
    urlInput.className = 'form-control';
    urlInput.id = 'mas-url';
    urlInput.value = cfg.url || '';
    urlInput.placeholder = 'http://192.168.1.42:8002';
    const testBtn = document.createElement('button');
    testBtn.className = 'btn btn-outline-secondary';
    testBtn.type = 'button';
    testBtn.id = 'mas-test-btn';
    testBtn.appendChild(DOMUtils.createIcon('bi bi-wifi'));
    inputGroup.appendChild(urlInput);
    inputGroup.appendChild(testBtn);
    urlDiv.appendChild(inputGroup);
    const testResult = document.createElement('div');
    testResult.className = 'form-text connector-test-result';
    testResult.id = 'mas-test-result';
    urlDiv.appendChild(testResult);
    frag.appendChild(urlDiv);

    // Token + signing secret (secrets: blank means "keep current")
    frag.appendChild(_masField(
        i18n.t('connectors.myastroshine_token_field'), 'mas-token', 'password', '',
        cfg.has_token ? unchanged : 'mas_...'));
    frag.appendChild(_masField(
        i18n.t('connectors.myastroshine_secret_field'), 'mas-signing-secret', 'password', '',
        cfg.has_signing_secret ? unchanged : ''));
    const tokenHelp = document.createElement('p');
    tokenHelp.className = 'form-text text-muted small mt-0 mb-3';
    tokenHelp.textContent = i18n.t('connectors.myastroshine_token_help');
    frag.appendChild(tokenHelp);

    // Advanced (collapse) - callback URL override
    const advDiv = document.createElement('div');
    advDiv.className = 'mb-3 collapse';
    advDiv.id = 'connector-advanced-myastroshine';
    advDiv.appendChild(_masField(
        i18n.t('connectors.myastroshine_callback_override_field'), 'mas-callback-override', 'url',
        cfg.callback_url_override || '', 'http://192.168.1.42:5000'));
    const cbHint = document.createElement('p');
    cbHint.className = 'form-text text-muted small mt-0';
    cbHint.textContent = i18n.t('connectors.myastroshine_callback_override_hint');
    advDiv.appendChild(cbHint);
    frag.appendChild(advDiv);

    const advLink = document.createElement('a');
    advLink.className = 'small text-muted d-block mb-3';
    advLink.dataset.bsToggle = 'collapse';
    advLink.href = '#connector-advanced-myastroshine';
    advLink.appendChild(DOMUtils.createIcon('bi bi-chevron-down me-1'));
    advLink.appendChild(document.createTextNode(i18n.t('connectors.advanced_settings')));
    frag.appendChild(advLink);

    // copy_rating switch
    const copyRatingWrap = document.createElement('div');
    copyRatingWrap.className = 'form-check form-switch mb-3';
    const copyRatingChk = document.createElement('input');
    copyRatingChk.type = 'checkbox';
    copyRatingChk.className = 'form-check-input';
    copyRatingChk.id = 'mas-copy-rating';
    copyRatingChk.checked = !!cfg.copy_rating;
    const copyRatingLbl = document.createElement('label');
    copyRatingLbl.className = 'form-check-label small';
    copyRatingLbl.setAttribute('for', 'mas-copy-rating');
    copyRatingLbl.textContent = i18n.t('connectors.myastroshine_copy_rating_field');
    copyRatingWrap.appendChild(copyRatingChk);
    copyRatingWrap.appendChild(copyRatingLbl);
    frag.appendChild(copyRatingWrap);

    // Actions: enable switch + save
    const actions = document.createElement('div');
    actions.className = 'd-flex gap-2';
    const switchRow = document.createElement('div');
    switchRow.className = 'form-check form-switch me-auto align-self-center';
    const enabledChk = document.createElement('input');
    enabledChk.type = 'checkbox';
    enabledChk.className = 'form-check-input';
    enabledChk.id = 'mas-enabled';
    enabledChk.checked = !!cfg.enabled;
    const enabledLbl = document.createElement('label');
    enabledLbl.className = 'form-check-label small';
    enabledLbl.setAttribute('for', 'mas-enabled');
    enabledLbl.textContent = i18n.t('connectors.enabled_label');
    switchRow.appendChild(enabledChk);
    switchRow.appendChild(enabledLbl);

    const saveBtn = document.createElement('button');
    saveBtn.className = 'btn btn-sm btn-primary';
    saveBtn.type = 'button';
    saveBtn.id = 'mas-save-btn';
    saveBtn.appendChild(DOMUtils.createIcon('bi bi-floppy me-1'));
    saveBtn.appendChild(document.createTextNode(i18n.t('common.save')));

    actions.appendChild(switchRow);
    actions.appendChild(saveBtn);
    frag.appendChild(actions);

    return frag;
}

function _bindMyAstroShineEvents() {
    const configureBtn = document.getElementById('connector-configure-myastroshine');
    const panel = document.getElementById('connector-panel-myastroshine');
    if (configureBtn && panel) {
        configureBtn.addEventListener('click', () => {
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        });
    }
    const testBtn = document.getElementById('mas-test-btn');
    if (testBtn) testBtn.addEventListener('click', _testMyAstroShine);
    const saveBtn = document.getElementById('mas-save-btn');
    if (saveBtn) saveBtn.addEventListener('click', _saveMyAstroShine);
}

async function _testMyAstroShine() {
    const urlInput = document.getElementById('mas-url');
    const resultDiv = document.getElementById('mas-test-result');
    if (!urlInput || !resultDiv) return;

    const url = urlInput.value.trim().replace(/\/+$/, '');
    if (!url) {
        _setResultMessage(resultDiv, i18n.t('connectors.url_required'), 'text-danger');
        return;
    }
    _setResultSpinner(resultDiv, i18n.t('connectors.testing'));

    const result = await fetchJSONOnce('/api/astrodex/integration/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
    }).catch(() => null);

    if (result && result.reachable) {
        _setResultMessage(resultDiv, i18n.t('connectors.reachable'), 'text-success', 'bi bi-check-circle');
    } else {
        _setResultMessage(
            resultDiv, i18n.t('connectors.myastroshine_test_offline_hint'), 'text-warning', 'bi bi-exclamation-triangle');
    }
}

async function _saveMyAstroShine() {
    const saveBtn = document.getElementById('mas-save-btn');
    const payload = {
        label: (document.getElementById('mas-label')?.value || '').trim(),
        url: (document.getElementById('mas-url')?.value || '').trim().replace(/\/+$/, ''),
        callback_url_override: (document.getElementById('mas-callback-override')?.value || '').trim().replace(/\/+$/, ''),
        copy_rating: !!document.getElementById('mas-copy-rating')?.checked,
        enabled: !!document.getElementById('mas-enabled')?.checked,
    };
    // Only send secrets when the user actually typed something (blank = keep current).
    const token = (document.getElementById('mas-token')?.value || '').trim();
    const secret = (document.getElementById('mas-signing-secret')?.value || '').trim();
    if (token) payload.token = token;
    if (secret) payload.signing_secret = secret;

    if (saveBtn) {
        saveBtn.disabled = true;
        DOMUtils.clear(saveBtn);
        const spinner = document.createElement('div');
        spinner.className = 'spinner-border spinner-border-sm';
        saveBtn.appendChild(spinner);
    }

    const result = await fetchJSONOnce('/api/astrodex/integration/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).catch(() => null);

    if (saveBtn) {
        saveBtn.disabled = false;
        DOMUtils.clear(saveBtn);
        saveBtn.appendChild(DOMUtils.createIcon('bi bi-floppy me-1'));
        saveBtn.appendChild(document.createTextNode(i18n.t('common.save')));
    }

    if (result?.status === 'success') {
        showMessage('success', i18n.t('connectors.myastroshine_saved'));
        loadConnectorsStore();
    } else {
        showMessage('error', i18n.t('connectors.myastroshine_save_error'));
    }
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

    const url = urlInput.value.trim().replace(/\/+$/, '');
    if (!url) {
        _setResultMessage(resultDiv, i18n.t('connectors.url_required'), 'text-danger');
        return;
    }

    _setResultSpinner(resultDiv, i18n.t('connectors.testing'));

    const result = await fetchJSONOnce(`/api/connectors/${name}/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
    }).catch(() => null);

    if (!result) {
        _setResultMessage(resultDiv, i18n.t('connectors.health_error'), 'text-danger');
    } else if (result.reachable) {
        _setResultMessage(resultDiv, i18n.t('connectors.reachable'), 'text-success', 'bi bi-check-circle');
    } else {
        _setResultMessage(resultDiv, i18n.t('connectors.unreachable'), 'text-danger', 'bi bi-x-circle');
    }
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
        const titleParts = [result.detail || ''];
        if (result.url) titleParts.push(result.url);
        badge.title = titleParts.join('\n');
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
        url:     urlInput.value.trim().replace(/\/+$/, ''),
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
