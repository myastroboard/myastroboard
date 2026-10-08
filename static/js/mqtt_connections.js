// ======================
// MQTT connections - Parameters -> Configuration
// ======================
//
// The brokers shared by the MQTT connectors (backend: utils/mqtt_connections.py,
// routes: blueprints/mqtt_connections.py). A connector picks one of them on its card
// (Parameters -> Connectors); a connection still picked by a connector cannot be deleted.
// The password never reaches the browser: the list only says whether one is stored.

let _mqttConnections = [];

/** fetch() that also hands back the JSON body of an error answer (400 / 409 reasons). */
async function _mqttConnectionRequest(endpoint, method = 'GET', body = undefined) {
    const options = { method, headers: {} };
    if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }
    try {
        const response = await fetch(resolveEndpoint(endpoint), options);
        const data = await response.json().catch(() => ({}));
        return { ok: response.ok, status: response.status, data };
    } catch (error) {
        console.error(`Error calling ${endpoint}:`, error);
        return { ok: false, status: 0, data: {} };
    }
}

/** Display names of the connectors listed in a connection's `used_by`. */
function _mqttConnectionUsers(names) {
    return (names || []).map(name => i18n.t(`connectors.${name}_label`)).join(', ');
}

async function loadMqttConnections() {
    const list = document.getElementById('mqtt-connections-list');
    if (!list) return;

    const result = await _mqttConnectionRequest(appUrl('/api/mqtt-connections'));
    DOMUtils.clear(list);
    if (!result.ok || !Array.isArray(result.data)) {
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger mb-0';
        alert.textContent = i18n.t('mqtt_connections.load_error');
        list.appendChild(alert);
        return;
    }

    _mqttConnections = result.data;
    if (_mqttConnections.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'text-muted mb-0';
        empty.textContent = i18n.t('mqtt_connections.empty');
        list.appendChild(empty);
        return;
    }
    _mqttConnections.forEach(connection => list.appendChild(_mqttConnectionRow(connection)));
    // Same "is the broker alive" check as the connector card's test button, run once per
    // connection on display so a dead broker shows up without a click.
    _mqttConnections.forEach(connection => _probeSavedMqttConnection(connection));
}

function _mqttConnectionRow(connection) {
    // The same light panel as the settings blocks of this page; .bg-features forces
    // display:block, so the flex layout lives on an inner div.
    const panel = document.createElement('div');
    panel.className = 'bg-features rounded';
    panel.id = `mqtt-connection-row-${connection.id}`;
    const row = document.createElement('div');
    row.className = 'mqtt-connection-row d-flex flex-wrap align-items-center gap-2';
    panel.appendChild(row);

    const info = document.createElement('div');
    info.className = 'mqtt-connection-info flex-grow-1';

    const name = document.createElement('div');
    name.className = 'fw-semibold';
    name.appendChild(DOMUtils.createIcon('bi bi-broadcast me-1 text-info'));
    name.appendChild(document.createTextNode(connection.name));
    info.appendChild(name);

    const url = document.createElement('div');
    url.className = 'small font-monospace text-break';
    url.textContent = connection.url;
    info.appendChild(url);

    const details = document.createElement('div');
    details.className = 'small text-muted';
    const parts = [connection.username
        ? `${i18n.t('connectors.mqtt_username_field')}: ${connection.username}`
        : i18n.t('mqtt_connections.anonymous')];
    if (connection.username && connection.has_password) parts.push(i18n.t('mqtt_connections.has_password'));
    if (connection.tls_insecure) parts.push(i18n.t('mqtt_connections.tls_insecure_short'));
    parts.push((connection.used_by || []).length
        ? i18n.t('mqtt_connections.used_by', { connectors: _mqttConnectionUsers(connection.used_by) })
        : i18n.t('mqtt_connections.unused'));
    details.textContent = parts.join(' - ');
    info.appendChild(details);

    const status = document.createElement('div');
    status.className = 'small mqtt-connection-status';
    status.id = `mqtt-connection-status-${connection.id}`;
    info.appendChild(status);

    const actions = document.createElement('div');
    actions.className = 'btn-group btn-group-sm';
    actions.appendChild(_mqttConnectionButton('bi bi-wifi', 'mqtt_connections.test', 'btn-outline-secondary',
        () => _probeSavedMqttConnection(connection)));
    actions.appendChild(_mqttConnectionButton('bi bi-pencil', 'mqtt_connections.edit', 'btn-outline-primary',
        () => _openMqttConnectionForm(connection)));
    actions.appendChild(_mqttConnectionButton('bi bi-trash', 'mqtt_connections.delete', 'btn-outline-danger',
        () => _deleteMqttConnection(connection)));

    row.appendChild(info);
    row.appendChild(actions);
    return panel;
}

function _mqttConnectionButton(icon, labelKey, variant, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `btn ${variant}`;
    btn.title = i18n.t(labelKey);
    btn.setAttribute('aria-label', i18n.t(labelKey));
    btn.appendChild(DOMUtils.createIcon(icon));
    btn.addEventListener('click', onClick);
    return btn;
}

/** Paint a probe outcome (or the in-progress spinner when `result` is null) into `target`. */
function _renderMqttProbe(target, result) {
    if (!target) return;
    DOMUtils.clear(target);
    const span = document.createElement('span');
    if (result === null) {
        span.className = 'text-muted';
        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm me-1';
        span.appendChild(spinner);
        span.appendChild(document.createTextNode(i18n.t('connectors.testing')));
    } else if (result.reachable) {
        span.className = 'text-success';
        span.appendChild(DOMUtils.createIcon('bi bi-check-circle me-1'));
        span.appendChild(document.createTextNode(i18n.t('connectors.reachable')));
    } else {
        span.className = 'text-danger';
        span.appendChild(DOMUtils.createIcon('bi bi-x-circle me-1'));
        span.appendChild(document.createTextNode(i18n.t('connectors.mqtt_test_offline_hint')));
        if (result.error) {
            // The backend's own one-line reason (refused, timeout, TLS...), never a credential.
            const detail = document.createElement('span');
            detail.className = 'text-muted ms-1';
            detail.textContent = `(${result.error})`;
            span.appendChild(detail);
        }
    }
    target.appendChild(span);
}

async function _probeMqttBroker(target, payload) {
    _renderMqttProbe(target, null);
    const result = await _mqttConnectionRequest(appUrl('/api/mqtt-connections/health'), 'POST', payload);
    if (!result.ok && result.status !== 400) {
        _renderMqttProbe(target, { reachable: false, error: i18n.t('connectors.health_error') });
        return;
    }
    _renderMqttProbe(target, result.data || { reachable: false });
}

function _probeSavedMqttConnection(connection) {
    // A blank password with the saved id and URL means "use the stored one".
    return _probeMqttBroker(document.getElementById(`mqtt-connection-status-${connection.id}`), {
        id: connection.id,
        url: connection.url,
        username: connection.username,
        tls_insecure: connection.tls_insecure,
    });
}

function _mqttFormFields() {
    return {
        form: document.getElementById('mqtt-connection-form'),
        wrap: document.getElementById('mqtt-connection-form-wrap'),
        title: document.getElementById('mqtt-connection-form-title'),
        id: document.getElementById('mqtt-connection-id'),
        name: document.getElementById('mqtt-connection-name'),
        url: document.getElementById('mqtt-connection-url'),
        username: document.getElementById('mqtt-connection-username'),
        password: document.getElementById('mqtt-connection-password'),
        tlsInsecure: document.getElementById('mqtt-connection-tls-insecure'),
        testResult: document.getElementById('mqtt-connection-test-result'),
    };
}

function _openMqttConnectionForm(connection = null) {
    const f = _mqttFormFields();
    if (!f.form || !f.wrap) return;
    f.title.textContent = i18n.t(connection ? 'mqtt_connections.form_title_edit' : 'mqtt_connections.form_title_add');
    f.id.value = connection ? connection.id : '';
    f.name.value = connection ? connection.name : '';
    f.url.value = connection ? connection.url : '';
    f.username.value = connection ? connection.username : '';
    // The stored password is never sent: show its masked form as a placeholder, and leave the
    // input blank so saving it unchanged keeps the stored value.
    f.password.value = '';
    f.password.placeholder = connection && connection.has_password ? connection.password : '';
    f.tlsInsecure.checked = Boolean(connection && connection.tls_insecure);
    DOMUtils.clear(f.testResult);
    f.wrap.style.display = '';
    f.name.focus();
}

function _closeMqttConnectionForm() {
    const f = _mqttFormFields();
    if (f.wrap) f.wrap.style.display = 'none';
}

function _mqttFormPayload() {
    const f = _mqttFormFields();
    return {
        name: f.name.value.trim(),
        url: f.url.value.trim().replace(/\/+$/, ''),
        username: f.username.value.trim(),
        password: f.password.value,
        tls_insecure: f.tlsInsecure.checked,
    };
}

/** A translated message for a refused save; the backend's reasons are fixed English strings. */
function _mqttConnectionErrorMessage(error) {
    const known = {
        'name required': 'mqtt_connections.error_name_required',
        'a connection with this name already exists': 'mqtt_connections.error_name_taken',
        'url required': 'connectors.url_required',
    };
    if (known[error]) return i18n.t(known[error]);
    if (typeof error === 'string' && error.startsWith('url')) return i18n.t('mqtt_connections.error_invalid_url');
    return i18n.t('mqtt_connections.save_error');
}

async function _saveMqttConnection(event) {
    event.preventDefault();
    const f = _mqttFormFields();
    const id = f.id.value;
    const saveBtn = document.getElementById('mqtt-connection-save');
    if (saveBtn) saveBtn.disabled = true;
    const result = id
        ? await _mqttConnectionRequest(appUrl(`/api/mqtt-connections/${encodeURIComponent(id)}`), 'PUT', _mqttFormPayload())
        : await _mqttConnectionRequest(appUrl('/api/mqtt-connections'), 'POST', _mqttFormPayload());
    if (saveBtn) saveBtn.disabled = false;

    if (!result.ok) {
        showMessage('error', _mqttConnectionErrorMessage(result.data && result.data.error));
        return;
    }
    showMessage('success', i18n.t('mqtt_connections.saved'));
    _closeMqttConnectionForm();
    loadMqttConnections();
}

function _testMqttConnectionForm() {
    const f = _mqttFormFields();
    const payload = _mqttFormPayload();
    if (!payload.url) {
        DOMUtils.clear(f.testResult);
        const span = document.createElement('span');
        span.className = 'text-danger';
        span.textContent = i18n.t('connectors.url_required');
        f.testResult.appendChild(span);
        return;
    }
    // While editing, a blank password lets the backend use the stored one - only if the URL
    // is still the saved one.
    if (f.id.value) payload.id = f.id.value;
    _probeMqttBroker(f.testResult, payload);
}

async function _deleteMqttConnection(connection) {
    if ((connection.used_by || []).length) {
        showMessage('error', i18n.t('mqtt_connections.in_use', { connectors: _mqttConnectionUsers(connection.used_by) }));
        return;
    }
    if (!window.confirm(i18n.t('mqtt_connections.delete_confirm', { name: connection.name }))) return;

    const result = await _mqttConnectionRequest(appUrl(`/api/mqtt-connections/${encodeURIComponent(connection.id)}`), 'DELETE');
    if (result.status === 409) {
        // Picked by a connector since the list was loaded
        showMessage('error', i18n.t('mqtt_connections.in_use', { connectors: _mqttConnectionUsers(result.data.used_by) }));
        loadMqttConnections();
        return;
    }
    if (!result.ok) {
        showMessage('error', i18n.t('mqtt_connections.delete_error'));
        return;
    }
    showMessage('success', i18n.t('mqtt_connections.deleted'));
    if (document.getElementById('mqtt-connection-id')?.value === connection.id) _closeMqttConnectionForm();
    loadMqttConnections();
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('mqtt-connection-add')?.addEventListener('click', () => _openMqttConnectionForm());
    document.getElementById('mqtt-connection-cancel')?.addEventListener('click', _closeMqttConnectionForm);
    document.getElementById('mqtt-connection-test')?.addEventListener('click', _testMqttConnectionForm);
    document.getElementById('mqtt-connection-form')?.addEventListener('submit', _saveMqttConnection);
});

window.addEventListener('i18nLanguageChanged', () => {
    if (document.getElementById('configuration-subtab')?.classList.contains('active')) loadMqttConnections();
});
