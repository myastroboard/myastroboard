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

// Per-connector presentation. Everything else about a connector comes from
// GET /api/connectors; this covers only what the card cannot infer: which icon to use,
// which i18n key labels its URL field, and the config inputs beyond the common
// label / URL / enabled / modules. Each field's `key` is the config key the backend
// accepts in POST /api/connectors/<name>/config (its CONFIG_FIELDS), so adding a field
// is one entry here and one entry there.
const _CONNECTOR_UI = {
    allsky: {
        icon: 'bi bi-camera-video me-2 text-info',
        urlLabelKey: 'url_field',
        advanced: [
            { key: 'image_path',       labelKey: 'allsky_image_path',       placeholder: 'current/tmp' },
            { key: 'image_filename',   labelKey: 'allsky_image_filename',   placeholder: 'image.jpg' },
            { key: 'export_json_path', labelKey: 'allsky_export_json_path', placeholder: 'allskydata.json' },
        ],
    },
    myastroshine: {
        icon: 'bi bi-stars me-2 text-info',
        urlLabelKey: 'myastroshine_url_field',
        urlPlaceholder: 'http://192.168.x.x:8002',
        unreachableHintKey: 'myastroshine_test_offline_hint',
        fields: [
            { key: 'token',          labelKey: 'myastroshine_token_field',  type: 'password', secret: true },
            { key: 'signing_secret', labelKey: 'myastroshine_secret_field', type: 'password', secret: true },
        ],
        fieldsHelpKey: 'myastroshine_token_help',
        checkboxes: [
            { key: 'copy_rating', labelKey: 'myastroshine_copy_rating_field' },
        ],
        advanced: [
            { key: 'callback_url_override', labelKey: 'myastroshine_callback_override_field',
              type: 'url', helpKey: 'myastroshine_callback_override_hint' },
        ],
    },
    mqtt: {
        icon: 'bi bi-broadcast me-2 text-info',
        urlLabelKey: 'mqtt_url_field',
        urlPlaceholder: 'mqtt://192.168.x.x:1883',
        urlHelpKey: 'mqtt_url_help',
        unreachableHintKey: 'mqtt_test_offline_hint',
        fields: [
            { key: 'username', labelKey: 'mqtt_username_field' },
            { key: 'password', labelKey: 'mqtt_password_field', type: 'password', secret: true },
        ],
        fieldsHelpKey: 'mqtt_credentials_help',
        checkboxes: [
            { key: 'discovery_enabled', labelKey: 'mqtt_discovery_field' },
        ],
        advanced: [
            { key: 'base_topic',               labelKey: 'mqtt_base_topic_field',       placeholder: 'myastroboard' },
            { key: 'discovery_prefix',         labelKey: 'mqtt_discovery_prefix_field', placeholder: 'homeassistant' },
            { key: 'publish_interval_seconds', labelKey: 'mqtt_interval_field',         type: 'number', min: 15, step: 5, placeholder: '60' },
            { key: 'client_id',                labelKey: 'mqtt_client_id_field',        helpKey: 'mqtt_client_id_hint' },
            { key: 'tls_insecure',             labelKey: 'mqtt_tls_insecure_field',     checkbox: true },
        ],
        statusEndpoint: '/api/connectors/mqtt/status',
        statusRenderer: _mqttStatusLine,
        actions: [
            { key: 'publish', labelKey: 'mqtt_publish_now',    icon: 'bi bi-send',  endpoint: '/api/connectors/mqtt/publish',
              successKey: 'mqtt_publish_requested' },
            { key: 'remove',  labelKey: 'mqtt_remove_from_ha', icon: 'bi bi-trash', endpoint: '/api/connectors/mqtt/remove',
              confirmKey: 'mqtt_remove_confirm', successKey: 'mqtt_remove_requested', danger: true },
        ],
    },
};

/**
 * Status line of the MQTT card, from GET /api/connectors/mqtt/status (written by the
 * publisher thread): connection, last publish, published devices, last error.
 */
function _mqttStatusLine(status) {
    const frag = document.createDocumentFragment();
    const badge = document.createElement('span');
    if (!status.enabled) {
        badge.className = 'badge bg-light text-dark border me-2';
        badge.textContent = i18n.t('connectors.mqtt_status_disabled');
    } else if (status.connected) {
        badge.className = 'badge bg-success me-2';
        badge.textContent = i18n.t('connectors.mqtt_status_connected');
    } else {
        badge.className = 'badge bg-warning text-dark me-2';
        badge.textContent = i18n.t('connectors.mqtt_status_disconnected');
    }
    frag.appendChild(badge);

    const parts = [];
    if (status.last_publish_at) {
        parts.push(`${i18n.t('connectors.mqtt_status_last_publish')} ${formatDateTime(status.last_publish_at)}`);
    } else if (status.enabled) {
        parts.push(i18n.t('connectors.mqtt_status_never_published'));
    }
    if (Array.isArray(status.devices) && status.devices.length) {
        const entities = status.devices.reduce((sum, d) => sum + (d.entities || 0), 0);
        parts.push(i18n.t('connectors.mqtt_status_devices', { devices: status.devices.length, entities }));
    }
    const text = document.createElement('span');
    text.className = 'text-muted';
    text.textContent = parts.join(' - ');
    frag.appendChild(text);

    if (status.last_error) {
        const err = document.createElement('div');
        err.className = 'text-danger small mt-1';
        err.appendChild(DOMUtils.createIcon('bi bi-exclamation-circle me-1'));
        err.appendChild(document.createTextNode(status.last_error));
        frag.appendChild(err);
    }

    // User devices only exist for users who opted in themselves (Customize): say so rather
    // than leaving an admin wondering why the user modules publish nothing.
    const hasUserDevice = Array.isArray(status.devices) && status.devices.some(d => d.kind === 'user');
    if (status.enabled && status.user_modules_enabled && !hasUserDevice) {
        const hint = document.createElement('div');
        hint.className = 'text-muted small mt-1';
        hint.appendChild(DOMUtils.createIcon('bi bi-info-circle me-1'));
        hint.appendChild(document.createTextNode(i18n.t('connectors.mqtt_status_no_user_opted_in')));
        frag.appendChild(hint);
    }
    return frag;
}

function _connectorUI(name) {
    return _CONNECTOR_UI[name] || {};
}

/**
 * Every declared input for a connector, main and advanced, so the save path can collect
 * them without knowing which connector it is looking at.
 */
function _connectorFieldSpecs(name) {
    const ui = _connectorUI(name);
    return [...(ui.fields || []), ...(ui.checkboxes || []), ...(ui.advanced || [])];
}

function _fieldInputId(name, key) {
    return `connector-field-${name}-${key}`;
}

/** Render one labelled text/password/url input from a field spec. */
function _connectorFieldInput(c, spec) {
    const cfg = c.config || {};
    const frag = document.createDocumentFragment();
    const id = _fieldInputId(c.name, spec.key);

    const lbl = document.createElement('label');
    lbl.className = 'form-label fw-semibold small';
    lbl.setAttribute('for', id);
    lbl.textContent = i18n.t(`connectors.${spec.labelKey}`);
    frag.appendChild(lbl);

    const input = document.createElement('input');
    input.type = spec.type || 'text';
    input.className = 'form-control form-control-sm mb-2 connector-field-input';
    input.id = id;
    input.dataset.connector = c.name;
    input.dataset.field = spec.key;
    if (spec.type === 'number') {
        if (spec.min !== undefined) input.min = String(spec.min);
        if (spec.max !== undefined) input.max = String(spec.max);
        if (spec.step !== undefined) input.step = String(spec.step);
    }
    if (spec.secret) {
        // The value is never sent to the browser: show the masked form as a placeholder,
        // and leave the input blank so submitting it unchanged keeps the stored secret.
        input.value = '';
        input.placeholder = cfg[spec.key] || i18n.t('connectors.secret_unchanged');
        input.dataset.secret = 'true';
    } else {
        input.value = cfg[spec.key] ?? spec.placeholder ?? '';
        input.placeholder = spec.placeholder || '';
    }
    frag.appendChild(input);

    if (spec.helpKey) {
        const help = document.createElement('div');
        help.className = 'form-text small mb-2';
        help.textContent = i18n.t(`connectors.${spec.helpKey}`);
        frag.appendChild(help);
    }
    return frag;
}

/** Render one labelled checkbox from a field spec. */
function _connectorFieldCheckbox(c, spec) {
    const cfg = c.config || {};
    const wrap = document.createElement('div');
    wrap.className = 'form-check form-switch mb-3';
    const chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.className = 'form-check-input connector-field-input';
    chk.id = _fieldInputId(c.name, spec.key);
    chk.dataset.connector = c.name;
    chk.dataset.field = spec.key;
    chk.dataset.checkbox = 'true';
    chk.checked = Boolean(cfg[spec.key]);
    const lbl = document.createElement('label');
    lbl.className = 'form-check-label small';
    lbl.setAttribute('for', chk.id);
    lbl.textContent = i18n.t(`connectors.${spec.labelKey}`);
    wrap.appendChild(chk);
    wrap.appendChild(lbl);
    return wrap;
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
    headerLeft.appendChild(DOMUtils.createIcon(_connectorUI(c.name).icon || 'bi bi-plug me-2 text-info'));
    // The connector's own name, not config.label: that one is the user's display name for
    // the Observatory panel, and it ships with a default ("My AllSky Camera") that would
    // otherwise replace the connector's name on every install.
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
    urlLbl.textContent = i18n.t(`connectors.${_connectorUI(c.name).urlLabelKey || 'url_field'}`);
    urlDiv.appendChild(urlLbl);

    const inputGroup = document.createElement('div');
    inputGroup.className = 'input-group input-group-sm';
    const urlInput = document.createElement('input');
    urlInput.type = 'url';
    urlInput.className = 'form-control connector-url-input';
    urlInput.id = `connector-url-${c.name}`;
    urlInput.dataset.connector = c.name;
    urlInput.value = cfg.url || '';
    urlInput.placeholder = _connectorUI(c.name).urlPlaceholder || 'http://192.168.x.x';
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

    if (_connectorUI(c.name).urlHelpKey) {
        const urlHelp = document.createElement('div');
        urlHelp.className = 'form-text small';
        urlHelp.textContent = i18n.t(`connectors.${_connectorUI(c.name).urlHelpKey}`);
        urlDiv.appendChild(urlHelp);
    }

    const testResult = document.createElement('div');
    testResult.className = 'form-text connector-test-result';
    testResult.id = `test-result-${c.name}`;
    urlDiv.appendChild(testResult);
    frag.appendChild(urlDiv);

    // Connector-specific fields (credentials, options)
    const ui = _connectorUI(c.name);
    (ui.fields || []).forEach(spec => frag.appendChild(_connectorFieldInput(c, spec)));
    if (ui.fieldsHelpKey) {
        const help = document.createElement('div');
        help.className = 'form-text small mb-3';
        help.textContent = i18n.t(`connectors.${ui.fieldsHelpKey}`);
        frag.appendChild(help);
    }
    (ui.checkboxes || []).forEach(spec => frag.appendChild(_connectorFieldCheckbox(c, spec)));

    // Advanced (collapse)
    const advDiv = document.createElement('div');
    advDiv.className = 'mb-3 collapse';
    advDiv.id = `connector-advanced-${c.name}`;
    (ui.advanced || []).forEach(spec => {
        advDiv.appendChild(spec.checkbox ? _connectorFieldCheckbox(c, spec) : _connectorFieldInput(c, spec));
    });
    frag.appendChild(advDiv);

    const advLink = document.createElement('a');
    advLink.className = 'small text-muted d-block mb-3';
    advLink.dataset.bsToggle = 'collapse';
    advLink.href = `#connector-advanced-${c.name}`;
    advLink.appendChild(DOMUtils.createIcon('bi bi-chevron-down me-1'));
    advLink.appendChild(document.createTextNode(i18n.t('connectors.advanced_settings')));
    frag.appendChild(advLink);

    // Modules — omitted entirely by a connector that exposes none.
    const modsDiv = document.createElement('div');
    modsDiv.className = 'mb-3';
    if ((c.modules || []).length) {
        const modsTitle = document.createElement('p');
        modsTitle.className = 'fw-semibold small mb-2';
        modsTitle.textContent = i18n.t('connectors.modules_title');
        modsDiv.appendChild(modsTitle);
    }

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

    // Live status + connector-specific actions (a connector that runs something in the
    // background, like the MQTT publisher, reports what it is doing here).
    if (ui.statusEndpoint) {
        const statusDiv = document.createElement('div');
        statusDiv.className = 'connector-status-line small mt-3';
        statusDiv.id = `connector-status-${c.name}`;
        frag.appendChild(statusDiv);
    }
    if ((ui.actions || []).length) {
        const actionRow = document.createElement('div');
        actionRow.className = 'd-flex flex-wrap gap-2 mt-2';
        ui.actions.forEach(spec => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `btn btn-sm ${spec.danger ? 'btn-outline-danger' : 'btn-outline-primary'} connector-action-btn`;
            btn.dataset.connector = c.name;
            btn.dataset.action = spec.key;
            btn.appendChild(DOMUtils.createIcon(`${spec.icon} me-1`));
            btn.appendChild(document.createTextNode(i18n.t(`connectors.${spec.labelKey}`)));
            actionRow.appendChild(btn);
        });
        frag.appendChild(actionRow);
    }

    return frag;
}

/** Re-fetch and repaint a connector's status line, if it declares one. */
async function _refreshConnectorStatus(name) {
    const ui = _connectorUI(name);
    const statusDiv = document.getElementById(`connector-status-${name}`);
    if (!ui.statusEndpoint || !statusDiv) return;
    const status = await fetchJSONOnce(ui.statusEndpoint).catch(() => null);
    DOMUtils.clear(statusDiv);
    if (!status) {
        _setResultMessage(statusDiv, i18n.t('connectors.status_error'), 'text-danger', 'bi bi-x-circle');
        return;
    }
    if (typeof ui.statusRenderer === 'function') statusDiv.appendChild(ui.statusRenderer(status));
}

/** Run one of a connector's declared actions (POST), with an optional confirmation first. */
async function _runConnectorAction(name, actionKey) {
    const spec = (_connectorUI(name).actions || []).find(a => a.key === actionKey);
    if (!spec) return;
    if (spec.confirmKey && !window.confirm(i18n.t(`connectors.${spec.confirmKey}`))) return;

    const btn = document.querySelector(`.connector-action-btn[data-connector="${name}"][data-action="${actionKey}"]`);
    if (btn) btn.disabled = true;
    const result = await fetchJSONOnce(spec.endpoint, { method: spec.method || 'POST' }).catch(() => null);
    if (btn) btn.disabled = false;

    if (!result) {
        showMessage('error', i18n.t('connectors.action_error'));
        return;
    }
    showMessage('success', i18n.t(`connectors.${spec.successKey || 'action_done'}`));
    if (result.enabled === false) {
        const enabledChk = document.getElementById(`connector-enabled-${name}`);
        if (enabledChk) enabledChk.checked = false;
        _updateStatusBadge(name, { enabled: false, installed: true });
    }
    // The publisher reacts on its next tick - repaint now and again once it has had time to.
    _refreshConnectorStatus(name);
    setTimeout(() => _refreshConnectorStatus(name), 6000);
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

    document.querySelectorAll(`.connector-action-btn[data-connector="${c.name}"]`).forEach(btn => {
        btn.addEventListener('click', () => _runConnectorAction(c.name, btn.dataset.action));
    });
    _refreshConnectorStatus(c.name);
}

function _setResultMessage(resultDiv, text, cssClass, iconClass) {
    DOMUtils.clear(resultDiv);
    const span = document.createElement('span');
    span.className = cssClass;
    if (iconClass) span.appendChild(DOMUtils.createIcon(`${iconClass} me-1`));
    span.appendChild(document.createTextNode(text));
    resultDiv.appendChild(span);
}

/**
 * "Unreachable", or the connector's own explanation of what that means for it.
 */
function _setUnreachable(name, resultDiv, detail) {
    const hintKey = _connectorUI(name).unreachableHintKey;
    if (hintKey) {
        _setResultMessage(resultDiv, i18n.t(`connectors.${hintKey}`), 'text-warning', 'bi bi-exclamation-triangle');
    } else {
        _setResultMessage(resultDiv, i18n.t('connectors.unreachable'), 'text-danger', 'bi bi-x-circle');
    }
    if (detail) {
        // The backend's own one-line reason (refused, timeout, TLS...), never a credential.
        const span = document.createElement('span');
        span.className = 'text-muted ms-1';
        span.textContent = `(${detail})`;
        resultDiv.appendChild(span);
    }
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

    // The URL plus the connector's fields as typed, so a probe can use the credentials in the
    // form. A blank secret means "use the stored one" - the backend only does so for the
    // saved URL.
    const payload = { url };
    document.querySelectorAll(`.connector-field-input[data-connector="${name}"]`).forEach(input => {
        payload[input.dataset.field] = input.dataset.checkbox ? input.checked : input.value.trim();
    });

    const result = await fetchJSONOnce(`/api/connectors/${name}/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).catch(() => null);

    if (!result) {
        _setResultMessage(resultDiv, i18n.t('connectors.health_error'), 'text-danger');
    } else if (result.reachable) {
        _setResultMessage(resultDiv, i18n.t('connectors.reachable'), 'text-success', 'bi bi-check-circle');
    } else {
        _setUnreachable(name, resultDiv, result.error);
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
        if (resultDiv) _setUnreachable(name, resultDiv, health.error);
    } else {
        if (resultDiv) _setResultMessage(resultDiv, i18n.t('connectors.reachable'), 'text-success', 'bi bi-check-circle');
    }
    _refreshConnectorStatus(name);

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

    const modules = {};
    document.querySelectorAll(`.connector-module-toggle[data-connector="${name}"]`).forEach(chk => {
        modules[chk.dataset.module] = { enabled: chk.checked };
    });

    const payload = {
        url:     urlInput.value.trim().replace(/\/+$/, ''),
        enabled: enabledChk ? enabledChk.checked : undefined,
        modules,
    };
    if (labelInput) payload.label = labelInput.value.trim();

    // Only fields the connector declared, collected by their config key. A blank secret is
    // sent as an empty string and the backend reads that as "keep the stored value".
    document.querySelectorAll(`.connector-field-input[data-connector="${name}"]`).forEach(input => {
        payload[input.dataset.field] = input.dataset.checkbox ? input.checked : input.value.trim();
    });

    if (saveBtn) {
        saveBtn.disabled = true;
        DOMUtils.clear(saveBtn);
        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm';
        saveBtn.appendChild(spinner);
    }

    const result = await fetchJSONOnce(`/api/connectors/${name}/config`, {
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

    if (!result) {
        showMessage('error', i18n.t('connectors.save_error'));
        return;
    }

    showMessage('success', i18n.t('connectors.saved'));
    _updateStatusBadge(name, result);
    if (typeof updateObservatoryNavVisibility === 'function') updateObservatoryNavVisibility();
    if (typeof updateMqttPublishOptionVisibility === 'function') updateMqttPublishOptionVisibility();
    _runHealthCheck(name);
}

/** Repaint a card's Enabled / Installed / Not installed badge after a save. */
function _updateStatusBadge(name, state) {
    const badge = document.querySelector(`#connector-card-${name} .card-header .badge`);
    if (!badge) return;
    if (state.enabled) {
        badge.className = 'badge bg-success';
        badge.textContent = i18n.t('connectors.enabled');
    } else if (state.installed) {
        badge.className = 'badge bg-secondary';
        badge.textContent = i18n.t('connectors.installed');
    } else {
        badge.className = 'badge bg-light text-dark border';
        badge.textContent = i18n.t('connectors.not_installed');
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

/** Enabled connectors whose data lands in the Observatory tab (declared via target_modules). */
function _feedsObservatory(c) {
    return Boolean(c && c.enabled && Array.isArray(c.target_modules) && c.target_modules.includes('observatory'));
}

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
    // Only connectors that declare the Observatory as a target have a panel here: an enabled
    // MyAstroShine (AstroDex) or MQTT (standalone) connector must not get an empty sub-tab.
    const enabled = (connectors || []).filter(_feedsObservatory);

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
        const hasEnabled = (connectors || []).some(_feedsObservatory);
        const navItem = document.getElementById('observatory-nav-item');
        if (navItem) navItem.style.display = hasEnabled ? '' : 'none';
    }).catch(() => {});
}
