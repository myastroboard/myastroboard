// Log Management Functions

// ======================
// Application Logs
// ======================

const _LOG_PATTERN = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}(?:\s[+-]\d{4})?)\s+-\s+([\w.]+)\s+-\s+(\w+)\s+-\s+\[([^\]]+)\]\s+-\s+(.*)$/;

function _buildLogEntry(rawLine) {
    const logEntry = document.createElement('div');
    logEntry.className = 'log-entry';

    const match = _LOG_PATTERN.exec(rawLine);
    if (!match) {
        logEntry.classList.add('log-continuation');
        const span = document.createElement('span');
        span.className = 'log-col-message';
        span.textContent = rawLine;
        logEntry.appendChild(span);
        return logEntry;
    }

    const [, timestamp, module, level, location, message] = match;
    logEntry.dataset.module = module;

    const levelLower = level.toLowerCase();
    if (level === 'ERROR' || level === 'CRITICAL') logEntry.classList.add('log-error');
    else if (level === 'WARNING') logEntry.classList.add('log-warning');
    else if (level === 'DEBUG') logEntry.classList.add('log-debug');

    const timeEl = document.createElement('span');
    timeEl.className = 'log-col-time';
    timeEl.textContent = timestamp.substring(11, 19);
    timeEl.title = timestamp;
    logEntry.appendChild(timeEl);

    const levelEl = document.createElement('span');
    levelEl.className = `log-col-level log-badge-${levelLower}`;
    levelEl.textContent = level;
    logEntry.appendChild(levelEl);

    const moduleEl = document.createElement('span');
    moduleEl.className = 'log-col-module';
    moduleEl.textContent = module;
    moduleEl.title = module;
    logEntry.appendChild(moduleEl);

    const locEl = document.createElement('span');
    locEl.className = 'log-col-location';
    locEl.textContent = location;
    locEl.title = location;
    logEntry.appendChild(locEl);

    const msgEl = document.createElement('span');
    msgEl.className = 'log-col-message';
    msgEl.textContent = message;
    logEntry.appendChild(msgEl);

    return logEntry;
}

function _populateModuleFilter(moduleSet) {
    const select = document.getElementById('log-module-filter');
    if (!select) return;
    const current = select.value;
    while (select.options.length > 1) select.remove(1);
    [...moduleSet].sort().forEach(mod => {
        const opt = document.createElement('option');
        opt.value = mod;
        opt.textContent = mod;
        select.appendChild(opt);
    });
    if (current && moduleSet.has(current)) select.value = current;
}

function _applyLogFilter() {
    const filter       = (document.getElementById('log-filter')?.value || '').toLowerCase();
    const moduleFilter = document.getElementById('log-module-filter')?.value || '';
    const logsContainer = document.getElementById('logs-display');
    const lineCountEl   = document.getElementById('logs-line-count');
    if (!logsContainer) return;

    const entries = logsContainer.querySelectorAll('.log-entry');
    let visible = 0;
    entries.forEach(el => {
        const moduleMatch = !moduleFilter || el.dataset.module === moduleFilter;
        const textMatch   = !filter || el.textContent.toLowerCase().includes(filter);
        const show = moduleMatch && textMatch;
        el.classList.toggle('d-none', !show);
        if (show) visible++;
    });

    if (lineCountEl && lineCountEl.dataset.total) {
        const total   = lineCountEl.dataset.total;
        const showing = lineCountEl.dataset.showing;
        lineCountEl.textContent = (filter || moduleFilter)
            ? `${visible} matching / ${showing} loaded / ${total} total`
            : `${showing} / ${total}`;
    }
}

async function loadLogs() {
    try {
        const logLevelElement = document.getElementById('log-level');
        const logLimitElement = document.getElementById('log-limit');

        if (!logLevelElement || !logLimitElement) {
            console.error('Log filter elements not found');
            return;
        }

        const level = logLevelElement.value;
        const limit = logLimitElement.value;
        const data = await fetchJSON(`/api/logs?level=${level}&limit=${limit}`);

        const logsContainer = document.getElementById('logs-display');
        if (!logsContainer) {
            console.error('Logs display container not found');
            return;
        }

        DOMUtils.clear(logsContainer);

        const lineCountEl = document.getElementById('logs-line-count');

        if (data.logs && data.logs.length > 0) {
            if (lineCountEl) {
                lineCountEl.dataset.showing = data.showing;
                lineCountEl.dataset.total   = data.total;
                lineCountEl.style.display   = '';
            }

            const modules = new Set();
            const fragment = document.createDocumentFragment();
            data.logs.forEach(log => {
                const entry = _buildLogEntry(log);
                if (entry.dataset.module) modules.add(entry.dataset.module);
                fragment.appendChild(entry);
            });
            logsContainer.appendChild(fragment);

            _populateModuleFilter(modules);
            _applyLogFilter();
            logsContainer.scrollTop = logsContainer.scrollHeight;
        } else {
            if (lineCountEl) lineCountEl.style.display = 'none';
            const empty = document.createElement('div');
            empty.className = 'log-empty';
            empty.textContent = 'No logs available yet';
            logsContainer.appendChild(empty);
        }
    } catch (error) {
        console.error('Error loading logs:', error);
        const logsDisplay = document.getElementById('logs-display');
        if (logsDisplay) {
            DOMUtils.clear(logsDisplay);
            const errorEl = document.createElement('div');
            errorEl.className = 'log-error';
            errorEl.textContent = 'Error loading logs';
            logsDisplay.appendChild(errorEl);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const filterInput    = document.getElementById('log-filter');
    const moduleSelect   = document.getElementById('log-module-filter');
    if (filterInput)  filterInput.addEventListener('input', _applyLogFilter);
    if (moduleSelect) moduleSelect.addEventListener('change', _applyLogFilter);
});

async function clearLogsDisplay() {
    if (!window.confirm(i18n.t('settings.clear_logs_confirm'))) return;

    await fetchJSON('/api/logs/clear', { method: 'POST' });
    showMessage('success', i18n.t('settings.logs_cleared'));

    const logsDisplay = document.getElementById('logs-display');
    if (logsDisplay) {
        DOMUtils.clear(logsDisplay);
        const empty = document.createElement('div');
        empty.className = 'log-empty';
        empty.textContent = i18n.t('settings.logs_cleared_hint');
        logsDisplay.appendChild(empty);
    }

    const moduleSelect = document.getElementById('log-module-filter');
    if (moduleSelect) {
        while (moduleSelect.options.length > 1) moduleSelect.remove(1);
        moduleSelect.value = '';
    }
}
