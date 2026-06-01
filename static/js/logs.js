// Log Management Functions

// ======================
// Application Logs
// ======================

function _applyLogFilter() {
    const filter = (document.getElementById('log-filter')?.value || '').toLowerCase();
    const logsContainer = document.getElementById('logs-display');
    const lineCountEl   = document.getElementById('logs-line-count');
    if (!logsContainer) return;

    const entries = logsContainer.querySelectorAll('.log-entry');
    let visible = 0;
    entries.forEach(el => {
        const match = !filter || el.textContent.toLowerCase().includes(filter);
        el.classList.toggle('d-none', !match);
        if (match) visible++;
    });

    if (lineCountEl && lineCountEl.dataset.total) {
        const total    = lineCountEl.dataset.total;
        const showing  = lineCountEl.dataset.showing;
        lineCountEl.textContent = filter
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

            // Display logs in chronological order (newest last)
            data.logs.forEach(log => {
                const logEntry = document.createElement('div');
                logEntry.className = 'log-entry';

                if (log.includes('ERROR') || log.includes('CRITICAL')) {
                    logEntry.classList.add('log-error');
                } else if (log.includes('WARNING')) {
                    logEntry.classList.add('log-warning');
                } else if (log.includes('INFO')) {
                    logEntry.classList.add('log-info');
                } else if (log.includes('DEBUG')) {
                    logEntry.classList.add('log-debug');
                }

                logEntry.textContent = log;
                logsContainer.appendChild(logEntry);
            });

            _applyLogFilter();

            // Auto-scroll to bottom to show latest logs
            logsContainer.scrollTop = logsContainer.scrollHeight;
        } else {
            if (lineCountEl) lineCountEl.style.display = 'none';
            DOMUtils.clear(logsContainer);
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

// Wire up the filter input once the DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const filterInput = document.getElementById('log-filter');
    if (filterInput) {
        filterInput.addEventListener('input', _applyLogFilter);
    }
});

async function clearLogsDisplay() {
    await fetchJSON('/api/logs/clear', {
        method: 'POST'
    });

    showMessage("success", "Logs cleared");

    const logsDisplay = document.getElementById('logs-display');
    if (logsDisplay) {
        DOMUtils.clear(logsDisplay);
        const empty = document.createElement('div');
        empty.className = 'log-empty';
        empty.textContent = 'Logs cleared (refresh to reload)';
        logsDisplay.appendChild(empty);
    }
}
