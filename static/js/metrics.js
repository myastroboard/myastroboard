// System Metrics Functions

const METRICS_REFRESH_INTERVAL_MS = 5000;
// Generous margin for the one-time cold-start cost: disk usage is served from
// a background-refreshed cache (see metrics_collector.py) so steady-state
// calls are fast, but the very first call after a restart has no cached
// value yet and must scan synchronously once - slow on some Docker/Windows
// bind-mount setups.
const METRICS_FETCH_TIMEOUT_MS = 20000;
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
    best_window_strict:       'Best Window (strict)',
    best_window_practical:    'Best Window (practical)',
    best_window_illumination: 'Best Window (illumination)',
    solar_eclipse:        'Solar Eclipse',
    lunar_eclipse:        'Lunar Eclipse',
    horizon_graph:        'Horizon Graph',
    aurora:               'Aurora',
    iss_passes:           'ISS Passes',
    css_passes:           'CSS Passes',
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

// Job rows the admin has expanded to see the per-location breakdown - kept
// across the 5s auto-refresh so re-rendering doesn't collapse them.
const _expandedCacheJobRows = new Set();

function _formatCacheDt(iso) {
    if (!iso) return '-';
    try { return new Date(iso).toLocaleString(); } catch (_) { return iso; }
}

function _formatCacheSecs(secs) {
    if (secs == null || !Number.isFinite(Number(secs))) return '-';
    const s = Number(secs);
    return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${(s % 60).toFixed(0)}s`;
}

function _cacheStatusBadge(isValid) {
    const b = document.createElement('span');
    if (isValid === null || isValid === undefined) {
        b.className = 'badge bg-secondary';
        b.textContent = i18n.t('metrics.cache_status_unknown') || '-';
    } else if (isValid) {
        b.className = 'badge bg-success';
        b.textContent = i18n.t('metrics.cache_status_valid') || 'Valid';
    } else {
        b.className = 'badge bg-warning text-dark';
        b.textContent = i18n.t('metrics.cache_status_stale') || 'Stale';
    }
    return b;
}

function _cacheDurationCell(exec) {
    const td = document.createElement('td');
    td.className = 'font-monospace small';
    if (exec.last_success === false) {
        const errBadge = document.createElement('span');
        errBadge.className = 'badge bg-danger me-1';
        errBadge.textContent = i18n.t('metrics.cache_status_failed') || 'Failed';
        td.appendChild(errBadge);
    }
    td.appendChild(document.createTextNode(_formatCacheSecs(exec.last_duration_s)));
    return td;
}

// A job is "location-scoped" when at least one scheduler location reports a
// validity flag for it in details.locations (global jobs like spaceflight/IERS/
// AllSky never appear there and keep the old single-row rendering).
function _cacheJobLocationIds(jobKey, locationsBlock) {
    return Object.keys(locationsBlock).filter((locId) => (
        Object.prototype.hasOwnProperty.call(locationsBlock[locId] || {}, jobKey)
    ));
}

// best_window_strict/practical/illumination are 3 separate cache slots (each
// with its own staleness) but share ONE execution: a single Astropy night-scan
// computes all 3 modes together, recorded under the unified 'best_window' job
// name. Execution lookups for any of the 3 modes must use that shared name.
function _cacheExecFamilyKey(jobKey) {
    return jobKey.startsWith('best_window_') ? 'best_window' : jobKey;
}

// Match execution_metrics entries to this job, across every location label
// variant ("<job>" for the install default, "<job>@<slug>" for the rest).
function _cacheJobExecEntries(jobKey, execMeta, installDefaultId) {
    const execKey = _cacheExecFamilyKey(jobKey);
    const entries = [];
    for (const [key, exec] of Object.entries(execMeta)) {
        if (key !== execKey && !key.startsWith(`${execKey}@`)) continue;
        const locationId = exec.location_id ?? (key === execKey ? installDefaultId : null);
        entries.push({ locationId, exec });
    }
    return entries;
}

async function updateCacheJobsMetrics() {
    const tbody = document.getElementById('cache-jobs-table-body');
    if (!tbody) return;

    try {
        const data = await fetchJSON('/api/cache');
        if (!data) return;

        const details          = data.details ?? {};
        const ttls             = details.ttls ?? {};
        const execMeta          = details.execution_metrics ?? {};
        const locationsBlock    = details.locations ?? {};
        const locationNames     = data.location_names ?? {};
        const installDefaultId  = data.install_default_location_id ?? null;

        // Build job order: keys from ttls (canonical list), fallback to execMeta keys
        const jobKeys = Object.keys(ttls).length
            ? Object.keys(ttls)
            : Object.keys(CACHE_JOB_LABELS);

        DOMUtils.clear(tbody);

        for (const jobKey of jobKeys) {
            const ttl   = ttls[jobKey];
            const label = getCacheJobLabel(jobKey);
            const locationIds = _cacheJobLocationIds(jobKey, locationsBlock);
            const execEntries = _cacheJobExecEntries(jobKey, execMeta, installDefaultId);

            const tr = document.createElement('tr');

            // Job name (+ expand toggle for multi-location jobs)
            const tdName = document.createElement('td');
            if (locationIds.length > 1) {
                const isExpanded = _expandedCacheJobRows.has(jobKey);
                const toggle = document.createElement('button');
                toggle.type = 'button';
                toggle.className = 'btn btn-sm btn-link p-0 me-1 text-decoration-none';
                toggle.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
                toggle.setAttribute('aria-label', i18n.t('metrics.cache_job_toggle_locations') || 'Toggle per-location detail');
                toggle.appendChild(DOMUtils.createIcon(`bi ${isExpanded ? 'bi-chevron-down' : 'bi-chevron-right'}`));
                toggle.addEventListener('click', () => {
                    if (_expandedCacheJobRows.has(jobKey)) {
                        _expandedCacheJobRows.delete(jobKey);
                    } else {
                        _expandedCacheJobRows.add(jobKey);
                    }
                    updateCacheJobsMetrics();
                });
                tdName.appendChild(toggle);
            }
            tdName.appendChild(document.createTextNode(label));
            if (locationIds.length > 1) {
                const countBadge = document.createElement('span');
                countBadge.className = 'badge bg-secondary-subtle text-secondary-emphasis ms-2';
                countBadge.textContent = `×${locationIds.length}`;
                tdName.appendChild(countBadge);
            }
            tr.appendChild(tdName);

            // TTL
            const tdTTL = document.createElement('td');
            const ttlBadge = document.createElement('span');
            ttlBadge.className = 'badge bg-secondary font-monospace';
            ttlBadge.textContent = formatTTL(ttl);
            tdTTL.appendChild(ttlBadge);
            tr.appendChild(tdTTL);

            // Valid / stale badge - aggregated across every scheduler location
            const tdStatus = document.createElement('td');
            if (locationIds.length > 1) {
                const validCount = locationIds.filter((id) => locationsBlock[id]?.[jobKey]).length;
                // Any location stale (even just one of many) means the row needs
                // attention - "Stale", not an ambiguous "-" unknown badge. The
                // (n/total) text below still shows how many locations are affected.
                tdStatus.appendChild(_cacheStatusBadge(validCount === locationIds.length));
                if (validCount !== locationIds.length) {
                    const countText = document.createElement('span');
                    countText.className = 'text-muted small ms-1';
                    countText.textContent = `(${validCount}/${locationIds.length})`;
                    tdStatus.appendChild(countText);
                }
            } else {
                tdStatus.appendChild(_cacheStatusBadge(details[jobKey] ?? null));
            }
            tr.appendChild(tdStatus);

            // Last run / duration - most recent execution across all locations
            const latestExec = execEntries
                .map((e) => e.exec)
                .sort((a, b) => new Date(b.last_run_at || 0) - new Date(a.last_run_at || 0))[0] ?? {};

            const tdLastRun = document.createElement('td');
            tdLastRun.className = 'font-monospace small';
            tdLastRun.textContent = _formatCacheDt(latestExec.last_run_at);
            tr.appendChild(tdLastRun);

            tr.appendChild(_cacheDurationCell(latestExec));

            tbody.appendChild(tr);

            // Per-location sub-rows (only when expanded)
            if (locationIds.length > 1 && _expandedCacheJobRows.has(jobKey)) {
                for (const locId of locationIds) {
                    const locExec = execEntries.find((e) => e.locationId === locId)?.exec ?? {};
                    const locName = locationNames[locId] || locId;

                    const subTr = document.createElement('tr');
                    subTr.className = 'table-secondary bg-opacity-10';

                    const tdLocName = document.createElement('td');
                    tdLocName.className = 'ps-4 small';
                    tdLocName.appendChild(DOMUtils.createIcon('bi bi-geo-alt', 'icon-inline'));
                    tdLocName.appendChild(document.createTextNode(' '));
                    tdLocName.appendChild(document.createTextNode(locName));
                    if (locId === installDefaultId) {
                        const defBadge = document.createElement('span');
                        defBadge.className = 'badge bg-info-subtle text-info-emphasis ms-2';
                        defBadge.textContent = i18n.t('settings.location_default_badge') || 'Default';
                        tdLocName.appendChild(defBadge);
                    }
                    subTr.appendChild(tdLocName);

                    subTr.appendChild(document.createElement('td')); // TTL - same as parent, left blank

                    const tdLocStatus = document.createElement('td');
                    tdLocStatus.appendChild(_cacheStatusBadge(locationsBlock[locId]?.[jobKey] ?? null));
                    subTr.appendChild(tdLocStatus);

                    const tdLocLastRun = document.createElement('td');
                    tdLocLastRun.className = 'font-monospace small';
                    tdLocLastRun.textContent = _formatCacheDt(locExec.last_run_at);
                    subTr.appendChild(tdLocLastRun);

                    subTr.appendChild(_cacheDurationCell(locExec));

                    tbody.appendChild(subTr);
                }
            }
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

    DOMUtils.clear(tableBody);

    if (!rows.length) {
        const emptyRow = document.createElement('tr');
        const emptyCell = document.createElement('td');
        emptyCell.setAttribute('colspan', '5');
        emptyCell.className = 'text-muted';
        emptyCell.textContent = i18n.t('metrics.no_process_data');
        emptyRow.appendChild(emptyCell);
        tableBody.appendChild(emptyRow);
        return;
    }

    rows.forEach((proc) => {
        const cpuPercent = Number(proc.cpu_percent || 0);
        const cpuBar = Math.max(0, Math.min(100, cpuPercent));
        const statusClass = getStatusBadgeClass(proc.status || 'unknown');
        const isContainerProc = Boolean(proc.is_container_related);

        const tr = document.createElement('tr');
        if (isContainerProc) tr.className = 'process-row-container';

        const tdName = document.createElement('td');
        const nameCell = document.createElement('div');
        nameCell.className = 'process-name-cell';
        nameCell.appendChild(DOMUtils.createIcon(`bi ${isContainerProc ? 'bi-boxes text-info' : 'bi-terminal text-muted'}`));
        const nameDiv = document.createElement('div');
        const mainName = document.createElement('div');
        mainName.className = 'process-main-name';
        mainName.textContent = proc.name || 'unknown';
        if (isContainerProc) {
            const chip = document.createElement('span');
            chip.className = 'process-container-chip';
            chip.textContent = i18n.t('metrics.container');
            mainName.append(' ', chip);
        }
        const subDiv = document.createElement('div');
        subDiv.className = 'process-sub';
        subDiv.textContent = `${i18n.t('metrics.pid')}${Number(proc.pid || 0)}`;
        nameDiv.appendChild(mainName);
        nameDiv.appendChild(subDiv);
        nameCell.appendChild(nameDiv);
        tdName.appendChild(nameCell);

        const tdStatus = document.createElement('td');
        const statusBadge = document.createElement('span');
        statusBadge.className = `badge ${statusClass}`;
        statusBadge.textContent = proc.status || 'unknown';
        tdStatus.appendChild(statusBadge);

        const tdCpu = document.createElement('td');
        const cpuCell = document.createElement('div');
        cpuCell.className = 'process-cpu-cell';
        const cpuBarBg = document.createElement('div');
        cpuBarBg.className = 'process-cpu-bar-bg';
        const cpuBarEl = document.createElement('div');
        cpuBarEl.className = 'process-cpu-bar';
        cpuBarEl.style.width = `${cpuBar}%`;
        cpuBarBg.appendChild(cpuBarEl);
        const cpuText = document.createElement('span');
        cpuText.textContent = `${cpuPercent.toFixed(1)}${i18n.t('units.percent')}`;
        cpuCell.appendChild(cpuBarBg);
        cpuCell.appendChild(cpuText);
        tdCpu.appendChild(cpuCell);

        const tdMem = document.createElement('td');
        const memSpan = document.createElement('span');
        memSpan.className = 'process-num';
        memSpan.textContent = formatBytes(proc.memory_rss || 0);
        tdMem.appendChild(memSpan);

        const tdUptime = document.createElement('td');
        const uptimeSpan = document.createElement('span');
        uptimeSpan.className = 'process-num';
        uptimeSpan.textContent = formatUptime(proc.uptime_seconds || 0);
        tdUptime.appendChild(uptimeSpan);

        tr.appendChild(tdName);
        tr.appendChild(tdStatus);
        tr.appendChild(tdCpu);
        tr.appendChild(tdMem);
        tr.appendChild(tdUptime);
        tableBody.appendChild(tr);
    });
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
