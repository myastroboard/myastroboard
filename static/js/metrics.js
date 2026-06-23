// System Metrics Functions

const METRICS_REFRESH_INTERVAL_MS = 5000;
const METRICS_FETCH_TIMEOUT_MS = 10000;
let metricsUpdateInterval = null;
let metricsLoading = false;
let processSortState = { key: 'cpu_percent', direction: 'desc' };
let processShowAll = false;

// ======================
// System Metrics
// ======================

async function loadSystemMetrics() {
    if (metricsLoading) return;
    metricsLoading = true;
    try {
        const data = await fetchJSONOnce('/api/metrics', { timeoutMs: METRICS_FETCH_TIMEOUT_MS });
        
        if (!data) {
            console.warn('No metrics data received');
            return;
        }
        
        console.debug('Metrics data received:', data);
        
        // Update CPU metrics
        const cpuPercent = Number(data?.cpu?.percent);
        const hasCpuPercent = Number.isFinite(cpuPercent);
        updateProgressBar('cpu-usage-bar', hasCpuPercent ? cpuPercent : 0);
        document.getElementById('cpu-usage-text').textContent = hasCpuPercent
            ? `${cpuPercent}${i18n.t('units.percent')}`
            : i18n.t('units.na');
        document.getElementById('cpu-logical').textContent = data?.cpu?.count_logical ?? i18n.t('units.na');
        document.getElementById('cpu-physical').textContent = data?.cpu?.count_physical ?? i18n.t('units.na');
        
        if (data?.cpu?.frequency?.current) {
            document.getElementById('cpu-frequency').textContent = 
                `${(data.cpu.frequency.current / 1000).toFixed(2)} ${i18n.t('units.ghz')}`;
        } else {
            document.getElementById('cpu-frequency').textContent = i18n.t('units.na');
        }
        
        // Update Memory metrics
        updateProgressBar('memory-usage-bar', data.memory.percent);
        document.getElementById('memory-used').textContent = formatBytes(data.memory.used);
        document.getElementById('memory-total').textContent = formatBytes(data.memory.total);
        
        // Update Swap metrics
        updateProgressBar('swap-usage-bar', data.swap.percent);
        document.getElementById('swap-used').textContent = formatBytes(data.swap.used);
        document.getElementById('swap-total').textContent = formatBytes(data.swap.total);
        
        // Update Disk metrics (from root filesystem)
        if (data.disk && data.disk.root) {
            updateProgressBar('disk-usage-bar', data.disk.root.percent);
            document.getElementById('disk-used').textContent = formatBytes(data.disk.root.used);
            document.getElementById('disk-total').textContent = formatBytes(data.disk.root.total);
            document.getElementById('disk-free').textContent = formatBytes(data.disk.root.free);
        }
        
        // Update folder disk usage (from disk.details, not disk.root.details)
        if (data.disk && data.disk.details && data.disk.details.folders) {
            updateFolderMetrics(data.disk.details.folders, data?.disk?.root?.total);
        }
        
        // Update System info
        document.getElementById('platform-system').textContent = 
            `${data.platform.system} ${data.platform.release}`;
        document.getElementById('platform-release').textContent = data.platform.version;
        document.getElementById('platform-machine').textContent = data.platform.machine;
        document.getElementById('platform-python').textContent = data.platform.python_version;
        
        // Update status
        document.getElementById('system-uptime').textContent = formatUptime(data.uptime.seconds);
        document.getElementById('process-count').textContent = (data.process.system_count !== undefined && data.process.system_count !== null) ? data.process.system_count : '-';
        document.getElementById('network-sent').textContent = formatBytes(data.network.bytes_sent);
        document.getElementById('network-recv').textContent = formatBytes(data.network.bytes_recv);
        
        console.debug('Process data:', data.process);
        
        // Update Container/VM detection
        if (data.environment) {
            updateEnvironmentMetrics(data.environment);
        }
        
        // Update Process details
        if (data.process && Array.isArray(data.process.processes)) {
            updateProcessesTable(data.process);
        } else {
            console.warn('No process list data available');
            updateProcessesTable({ processes: [] });
        }
        
    } catch (error) {
        console.error('Error loading system metrics:', error);
    } finally {
        metricsLoading = false;
    }

    // Scheduler status is fetched from a separate endpoint
    updateSchedulerMetrics();
    // Cache jobs metrics from /api/cache
    updateCacheJobsMetrics();
}

async function updateSchedulerMetrics() {
    const setText = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text ?? '-';
    };
    const setBadge = (id, text, colorClass) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className = `badge ${colorClass}`;
    };
    const formatDt = (iso) => {
        if (!iso) return '-';
        try {
            return new Date(iso).toLocaleString();
        } catch (_) { return iso; }
    };
    const formatSecs = (secs) => {
        if (secs == null || !Number.isFinite(Number(secs))) return '-';
        const s = Number(secs);
        if (s < 60) return `${s.toFixed(1)}s`;
        const m = Math.floor(s / 60);
        const rem = (s % 60).toFixed(0).padStart(2, '0');
        return `${m}m ${rem}s`;
    };
    try {
        const data = await fetchJSON('/api/skytonight/scheduler/status');
        if (!data) return;

        // Status badges
        setBadge('sched-enabled',   data.enabled   ? i18n.t('metrics.yes') : i18n.t('metrics.no'),   data.enabled   ? 'badge bg-success' : 'badge bg-secondary');
        setBadge('sched-running',   data.running    ? i18n.t('metrics.yes') : i18n.t('metrics.no'),   data.running    ? 'badge bg-success' : 'badge bg-secondary');
        setBadge('sched-executing', data.is_executing ? i18n.t('metrics.yes') : i18n.t('metrics.no'), data.is_executing ? 'badge bg-warning text-dark' : 'badge bg-secondary');
        setBadge('sched-mode',      data.mode ?? '-', 'badge bg-info');

        setText('sched-timezone',      data.timezone ?? '-');
        setText('sched-last-run',      formatDt(data.last_run));
        setText('sched-next-run',      formatDt(data.next_run));
        setText('sched-reason',        data.reason ?? '-');
        setText('sched-last-duration', formatSecs(data.progress?.last_execution_duration_seconds));
        setText('sched-last-error',    data.last_error ?? '-');

        const lr = data.last_result;
        if (lr) {
            setText('sched-night-start',  formatDt(lr.calculation?.night_start));
            setText('sched-night-end',    formatDt(lr.calculation?.night_end));
            setText('sched-dso-count',    lr.counts?.deep_sky     ?? '-');
            setText('sched-bodies-count', lr.counts?.bodies        ?? '-');
            setText('sched-comets-count', lr.counts?.comets        ?? '-');
        } else {
            ['sched-night-start','sched-night-end','sched-dso-count','sched-bodies-count','sched-comets-count']
                .forEach(id => setText(id, '-'));
        }
    } catch (error) {
        console.warn('Error loading scheduler metrics:', error);
    }
}

// Human-readable TTL label
function formatTTL(seconds) {
    if (!seconds) return '-';
    const s = Number(seconds);
    if (s >= 86400) return `${Math.round(s / 86400)}d`;
    if (s >= 3600)  return `${Math.round(s / 3600)}h`;
    if (s >= 60)    return `${Math.round(s / 60)}m`;
    return `${s}s`;
}

// Map job names to human-friendly labels
// Fallback labels used when the i18n key is missing
const CACHE_JOB_LABELS = {
    moon_report:          'Moon Report',
    dark_window:          'Dark Window',
    moon_planner:         'Moon Planner',
    sun_report:           'Sun Report',
    best_window:          'Best Window',
    solar_eclipse:        'Solar Eclipse',
    lunar_eclipse:        'Lunar Eclipse',
    horizon_graph:        'Horizon Graph',
    aurora:               'Aurora',
    iss_passes:           'ISS Passes',
    planetary_events:     'Planetary Events',
    special_phenomena:    'Special Phenomena',
    solar_system_events:  'Solar System Events',
    sidereal_time:        'Sidereal Time',
    seeing_forecast:      'Seeing Forecast',
    weather_forecast:     'Weather Forecast',
    allsky_sensor:        'AllSky Sensor Data',
    allsky_health:        'AllSky Health Check',
};

function getCacheJobLabel(jobKey) {
    const key = `cache.step_${jobKey}`;
    const translated = i18n.t(key);
    // i18n.t returns the key itself when missing - fall back to the static map
    return (translated && translated !== key)
        ? translated
        : (CACHE_JOB_LABELS[jobKey] ?? jobKey);
}

async function updateCacheJobsMetrics() {
    const tbody = document.getElementById('cache-jobs-table-body');
    if (!tbody) return;

    const formatDt = (iso) => {
        if (!iso) return '-';
        try { return new Date(iso).toLocaleString(); } catch (_) { return iso; }
    };
    const formatSecs = (secs) => {
        if (secs == null || !Number.isFinite(Number(secs))) return '-';
        const s = Number(secs);
        return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${(s % 60).toFixed(0)}s`;
    };

    try {
        const data = await fetchJSON('/api/cache');
        if (!data) return;

        const details   = data.details ?? {};
        const ttls      = details.ttls ?? {};
        const execMeta  = details.execution_metrics ?? {};

        // Build job order: keys from ttls (canonical list), fallback to execMeta keys
        const jobKeys = Object.keys(ttls).length
            ? Object.keys(ttls)
            : Object.keys(CACHE_JOB_LABELS);

        DOMUtils.clear(tbody);

        for (const jobKey of jobKeys) {
            const ttl       = ttls[jobKey];
            const exec      = execMeta[jobKey] ?? {};
            // best_window validity uses best_window_strict in details
            const validKey  = jobKey === 'best_window' ? 'best_window_strict' : jobKey;
            const isValid   = details[validKey] ?? null;
            const label     = getCacheJobLabel(jobKey);

            const tr = document.createElement('tr');

            // Job name
            const tdName = document.createElement('td');
            tdName.textContent = label;
            tr.appendChild(tdName);

            // TTL
            const tdTTL = document.createElement('td');
            const ttlBadge = document.createElement('span');
            ttlBadge.className = 'badge bg-secondary font-monospace';
            ttlBadge.textContent = formatTTL(ttl);
            tdTTL.appendChild(ttlBadge);
            tr.appendChild(tdTTL);

            // Valid / stale badge
            const tdStatus = document.createElement('td');
            if (isValid === null) {
                const b = document.createElement('span');
                b.className = 'badge bg-secondary';
                b.textContent = i18n.t('metrics.cache_status_unknown') || '-';
                tdStatus.appendChild(b);
            } else if (isValid) {
                const b = document.createElement('span');
                b.className = 'badge bg-success';
                b.textContent = i18n.t('metrics.cache_status_valid') || 'Valid';
                tdStatus.appendChild(b);
            } else {
                const b = document.createElement('span');
                b.className = 'badge bg-warning text-dark';
                b.textContent = i18n.t('metrics.cache_status_stale') || 'Stale';
                tdStatus.appendChild(b);
            }
            tr.appendChild(tdStatus);

            // Last run
            const tdLastRun = document.createElement('td');
            tdLastRun.className = 'font-monospace small';
            tdLastRun.textContent = formatDt(exec.last_run_at);
            tr.appendChild(tdLastRun);

            // Duration
            const tdDur = document.createElement('td');
            tdDur.className = 'font-monospace small';
            if (exec.last_success === false) {
                const errBadge = document.createElement('span');
                errBadge.className = 'badge bg-danger me-1';
                errBadge.textContent = i18n.t('metrics.cache_status_failed') || 'Failed';
                tdDur.appendChild(errBadge);
            }
            tdDur.appendChild(document.createTextNode(formatSecs(exec.last_duration_s)));
            tr.appendChild(tdDur);

            tbody.appendChild(tr);
        }
    } catch (error) {
        console.warn('Error loading cache jobs metrics:', error);
    }
}

function updateFolderMetrics(folders, rootTotalBytes = null) {
    const folderMap = {
        'data': 'data',
        'data/astrodex': 'astrodex',
        'data/cache': 'cache',
        'data/equipments': 'equipments',
        'data/projects': 'projects',
        'data/skytonight': 'skytonight',
        'data/skytonight/calculations': 'skytonight-calculations',
        'data/skytonight/catalogues': 'skytonight-catalogues',
        'data/skytonight/logs': 'skytonight-logs',
        'data/skytonight/outputs': 'skytonight-outputs',
        'data/skytonight/runtime': 'skytonight-runtime',
    };
    
    for (const [folderPath, folderKey] of Object.entries(folderMap)) {
        const folderData = folders[folderPath];
        if (folderData) {
            const barId = `folder-${folderKey}-bar`;
            const sizeId = `folder-${folderKey}-size`;
            const totalId = `folder-${folderKey}-total`;
            const percentId = `folder-${folderKey}-percent`;
            
            const bar = document.getElementById(barId);
            const sizeElement = document.getElementById(sizeId);
            const totalElement = document.getElementById(totalId);
            const percentElement = document.getElementById(percentId);
            
            if (bar && sizeElement && totalElement && percentElement) {
                const percent = folderData.percent_of_root || 0;
                updateCompactProgressBar(barId, percent);
                sizeElement.textContent = formatBytes(folderData.bytes || 0);
                percentElement.textContent = `${Math.round(percent)}${i18n.t('units.percent')}`;
                totalElement.textContent = rootTotalBytes ? formatBytes(rootTotalBytes) : '-';
            }
        }
    }
}

function updateCompactProgressBar(elementId, percent) {
    const bar = document.getElementById(elementId);
    if (!bar) return;

    const safePercent = Number.isFinite(percent) ? Math.max(0, Math.min(percent, 100)) : 0;
    const roundedPercent = Math.round(safePercent * 10) / 10;
    bar.style.width = `${roundedPercent}${i18n.t('units.percent')}`;
    bar.setAttribute('aria-valuenow', roundedPercent);
    bar.textContent = '';

    bar.className = 'progress-bar';
    if (safePercent >= 90) {
        bar.classList.add('bg-danger');
    } else if (safePercent >= 75) {
        bar.classList.add('bg-warning');
    } else {
        bar.classList.add('bg-success');
    }
}

function updateEnvironmentMetrics(environment) {
    const statusElement = document.getElementById('container-status');
    const badgeElement = document.getElementById('container-badge');
    const typeElement = document.getElementById('container-type');
    
    if (environment.is_container) {
        statusElement.textContent = i18n.t('metrics.yes');
        badgeElement.style.display = 'inline-block';
        badgeElement.className = 'badge bg-info';
        badgeElement.textContent = environment.container_type || i18n.t('metrics.unknown');
        typeElement.textContent = environment.container_type || i18n.t('metrics.unknown_container');
    } else {
        statusElement.textContent = i18n.t('metrics.no');
        badgeElement.style.display = 'none';
        typeElement.textContent = i18n.t('metrics.no_running_in_container');
    }
}

function updateProcessesTable(processData) {
    const tableBody = document.getElementById('processes-table-body');
    const countBadge = document.getElementById('process-count-badge');
    const dindBadge = document.getElementById('dind-badge');
    if (!tableBody || !countBadge || !dindBadge) return;

    const processes = Array.isArray(processData.processes) ? [...processData.processes] : [];
    const visibleCount = processData.visible_count ?? processes.length;
    countBadge.textContent = String(visibleCount);

    if (processData?.docker_in_docker?.enabled) {
        dindBadge.style.display = 'inline-flex';
    } else {
        dindBadge.style.display = 'none';
    }

    const showLimit = processShowAll ? Number.POSITIVE_INFINITY : 10;
    const sorted = sortProcesses(processes, processSortState);
    const rows = sorted.slice(0, showLimit);

    if (!rows.length) {
        tableBody.innerHTML = `<tr><td colspan="5" class="text-muted">${escapeHtml(i18n.t('metrics.no_process_data'))}</td></tr>`;
        return;
    }

    tableBody.innerHTML = rows.map((proc) => {
        const cpuPercent = Number(proc.cpu_percent || 0);
        const cpuBar = Math.max(0, Math.min(100, cpuPercent));
        const statusClass = getStatusBadgeClass(proc.status || 'unknown');
        const isContainerProc = Boolean(proc.is_container_related);
        const rowClass = isContainerProc ? 'process-row-container' : '';
        const processName = escapeHtml(proc.name || 'unknown');
        const status = escapeHtml(proc.status || 'unknown');
        const pid = Number(proc.pid || 0);
        const pidLabel = escapeHtml(i18n.t('metrics.pid'));
        const containerLabel = escapeHtml(i18n.t('metrics.container'));
        const memory = formatBytes(proc.memory_rss || 0);
        const uptime = formatUptime(proc.uptime_seconds || 0);

        return `
            <tr class="${rowClass}">
                <td>
                    <div class="process-name-cell">
                        <i class="bi ${isContainerProc ? 'bi-boxes text-info' : 'bi-terminal text-muted'}" aria-hidden="true"></i>
                        <div>
                            <div class="process-main-name">${processName}${isContainerProc ? ` <span class="process-container-chip">${containerLabel}</span>` : ''}</div>
                            <div class="process-sub">${pidLabel}${pid}</div>
                        </div>
                    </div>
                </td>
                <td><span class="badge ${statusClass}">${status}</span></td>
                <td>
                    <div class="process-cpu-cell">
                        <div class="process-cpu-bar-bg"><div class="process-cpu-bar" style="width:${cpuBar}%;"></div></div>
                        <span>${cpuPercent.toFixed(1)}${i18n.t('units.percent')}</span>
                    </div>
                </td>
                <td><span class="process-num">${memory}</span></td>
                <td><span class="process-num">${uptime}</span></td>
            </tr>
        `;
    }).join('');
}

function sortProcesses(processes, sortState) {
    const { key, direction } = sortState;
    const multiplier = direction === 'asc' ? 1 : -1;

    return processes.sort((a, b) => {
        const av = a?.[key];
        const bv = b?.[key];

        if (typeof av === 'number' && typeof bv === 'number') {
            return (av - bv) * multiplier;
        }

        const as = String(av ?? '').toLowerCase();
        const bs = String(bv ?? '').toLowerCase();
        if (as < bs) return -1 * multiplier;
        if (as > bs) return 1 * multiplier;
        return 0;
    });
}

function getStatusBadgeClass(status) {
    const value = String(status || '').toLowerCase();
    if (value === 'running') return 'bg-success-subtle text-success-emphasis';
    if (value === 'sleeping' || value === 'idle') return 'bg-warning-subtle text-warning-emphasis';
    if (value === 'zombie' || value === 'dead' || value === 'stopped') return 'bg-danger-subtle text-danger-emphasis';
    return 'bg-secondary-subtle text-secondary-emphasis';
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function updateProgressBar(elementId, percent) {
    const bar = document.getElementById(elementId);
    if (!bar) return;
    if (!Number.isFinite(percent)) return;

    const roundedPercent = Math.round(percent * 10) / 10;
    bar.style.width = `${roundedPercent}${i18n.t('units.percent')}`;
    bar.setAttribute('aria-valuenow', roundedPercent);
    bar.textContent = `${roundedPercent}${i18n.t('units.percent')}`;
    
    // Color coding
    bar.className = 'progress-bar';
    if (percent >= 90) {
        bar.classList.add('bg-danger');
    } else if (percent >= 75) {
        bar.classList.add('bg-warning');
    } else {
        bar.classList.add('bg-success');
    }
}

function formatBytes(bytes) {
    if (bytes === null || bytes === undefined) return '-';
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
}

function formatUptime(seconds) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    
    const parts = [];
    if (days > 0) parts.push(`${days}${i18n.t('units.day')}`);
    if (hours > 0) parts.push(`${hours}${i18n.t('units.hour')}`);
    if (minutes > 0) parts.push(`${minutes}${i18n.t('units.minute')}`);
    
    return parts.length > 0 ? parts.join(' ') : `< 1${i18n.t('units.minute')}`;
}

function startMetricsAutoRefresh() {
    initializeProcessTableControls();

    if (metricsUpdateInterval) {
        clearTimeout(metricsUpdateInterval);
        metricsUpdateInterval = null;
    }

    async function runAndReschedule() {
        await loadSystemMetrics();
        metricsUpdateInterval = setTimeout(runAndReschedule, METRICS_REFRESH_INTERVAL_MS);
    }

    runAndReschedule();
}

function stopMetricsAutoRefresh() {
    if (metricsUpdateInterval) {
        clearTimeout(metricsUpdateInterval);
        metricsUpdateInterval = null;
    }
}

function initializeProcessTableControls() {
    const showAllToggle = document.getElementById('process-show-all');
    if (showAllToggle && !showAllToggle.dataset.bound) {
        showAllToggle.dataset.bound = '1';
        showAllToggle.addEventListener('change', () => {
            processShowAll = Boolean(showAllToggle.checked);
            loadSystemMetrics();
        });
    }

    const table = document.getElementById('processes-table');
    if (table && !table.dataset.bound) {
        table.dataset.bound = '1';
        table.querySelectorAll('th.sortable').forEach((th) => {
            th.addEventListener('click', () => {
                const key = th.dataset.sortKey;
                if (!key) return;

                if (processSortState.key === key) {
                    processSortState.direction = processSortState.direction === 'asc' ? 'desc' : 'asc';
                } else {
                    processSortState = { key, direction: 'desc' };
                }

                loadSystemMetrics();
            });
        });
    }
}
