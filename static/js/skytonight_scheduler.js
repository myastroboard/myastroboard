/* =====================
    skytonightScheduler
    (SkyTonight execution)
   ===================== */

const SkyTonightScheduler = (() => {

    const state = {
        isExecuting: false,
        pollInterval: null,
        mode: 'idle', // idle | manual | scheduled
    };

    // Guard against transient is_executing=false flicker during thread start.
    // We only call finish() after two consecutive false responses.
    let _notExecutingCount = 0;

    let last_catalogue_executed = null;

    const els = {
        banner: () => document.getElementById('global-scheduler-banner'),
        progress: () => document.getElementById('global-scheduler-progress'),
        detail: () => document.getElementById('global-scheduler-detail'),
        button: () => document.getElementById('run-now'),
    };

    async function fetchStatus() {
        const retryOptions = {
            maxAttempts: 3,
            baseDelayMs: 1000,
            maxDelayMs: 5000,
            timeoutMs: 8000
        };

        try {
            return await fetchJSONWithRetry('/api/skytonight/scheduler/status', {
                cache: 'no-store'
            }, retryOptions);
        } catch (error) {
            // If the primary endpoint briefly returns 5xx (e.g. reverse proxy
            // restart), try the legacy alias before surfacing the failure.
            if (error && Number.isFinite(Number(error.status)) && Number(error.status) >= 500) {
                return fetchJSONWithRetry('/api/scheduler/status', {
                    cache: 'no-store'
                }, {
                    ...retryOptions,
                    maxAttempts: 2
                });
            }
            throw error;
        }
    }

    async function trigger() {
        try {
            blockButton();
            state.mode = 'manual';

            const data = await fetchJSONWithRetry('/api/skytonight/scheduler/trigger', {
                method: 'POST'
            }, {
                maxAttempts: 1,
                timeoutMs: 10000
            });

            if (data.status !== 'triggered') {
                throw new Error('Trigger failed');
            }

            // Show immediate feedback while worker picks up the manual trigger.
            showBanner();
            els.progress().textContent = i18n.t('scheduler.status_running');
            els.detail().textContent = i18n.t('scheduler.processing_catalogues');

            // Poll right away, then continue on a faster cadence for manual runs.
            await poll();
            startPolling(2000, true);
        } catch (e) {
            console.error(e);
            resetUI();
            showMessage('error', 'Failed to trigger scheduler');
        }
    }

    function render(status) {
        
        if (status.is_executing) {
            _notExecutingCount = 0;
            state.isExecuting = true;
            showBanner();
            blockButton();

            const p = status.progress;
            const duration = p?.execution_duration_seconds
                ? ` (${formatDuration(p.execution_duration_seconds)})`
                : '';

            if (p?.phase && p.phase !== '') {
                // Phase-based progress from skytonight_calculator
                const phaseLabel = i18n.t(`scheduler.phase_${p.phase}`, {}, p.phase);
                if (p.phase_total > 0) {
                    els.progress().textContent =
                        `${phaseLabel} - ${p.phase_processed}/${p.phase_total}${duration}`;
                } else {
                    els.progress().textContent = `${phaseLabel}${duration}`;
                }
                els.detail().textContent = '';
            } else if (p?.current_catalogue && p.total_catalogues > 0) {
                // Legacy per-catalogue progress
                els.progress().textContent =
                    `${i18n.t('scheduler.processing')} ${p.current_index}/${p.total_catalogues}${duration}`;
                els.detail().textContent =
                    `${i18n.t('scheduler.current')} ${p.current_catalogue}`;
                last_catalogue_executed = p.current_catalogue;
            } else {
                els.progress().textContent =
                    i18n.t('scheduler.processing_catalogues') + duration;
                els.detail().textContent = '';
            }
        } else if (state.isExecuting) {
            _notExecutingCount++;
            if (_notExecutingCount >= 2) {
                // Two consecutive false responses - execution genuinely finished.
                loadSkyTonightResultsTabs();
                last_catalogue_executed = null;
                state.isExecuting = false;
                _notExecutingCount = 0;
                finish();
            }
            // else: keep banner up, wait for confirmation next poll
        }
    }

    function finish() {
        stopPolling();

        const _prog = els.progress();
        DOMUtils.clear(_prog);
        DOMUtils.append(_prog, DOMUtils.createIcon('bi bi-check-circle-fill text-success icon-inline'), i18n.t('scheduler.complete'));
        els.detail().textContent =
            i18n.t('scheduler.success');

        showMessage(
            'success',
            state.mode === 'manual'
                ? i18n.t('scheduler.manual_complete')
                : i18n.t('scheduler.scheduled_complete')
        );

        setTimeout(resetUI, state.mode === 'manual' ? 3000 : 5000);
        state.mode = 'idle';
    }

    async function poll() {
        try {
            const status = await fetchStatus();
            render(status);
        } catch (e) {
            // Keep polling - a transient error (server restart, brief network
            // hiccup) must not permanently kill the interval and leave the
            // banner stuck hidden for the rest of the page session.
            console.warn('SkyTonight scheduler poll failed (will retry):', e);
        }
    }

    function startPolling(interval, forceRestart = false) {
        if (state.pollInterval) {
            if (!forceRestart) {
                return;
            }
            stopPolling();
        }
        state.pollInterval = setInterval(poll, interval);
    }

    function stopPolling() {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
    }

    function showBanner() {
        els.banner().style.display = 'block';
    }

    function hideBanner() {
        els.banner().style.display = 'none';
    }

    function blockButton() {
        const btn = els.button();
        if (!btn) return;
        btn.disabled = true;
        DOMUtils.clear(btn);
        DOMUtils.append(btn, DOMUtils.createIcon('bi bi-hourglass-split icon-inline'), i18n.t('scheduler.status_running'));
    }

    function resetButton() {
        const btn = els.button();
        if (!btn) return;
        btn.disabled = false;
        DOMUtils.clear(btn);
        DOMUtils.append(btn, DOMUtils.createIcon('bi bi-play-fill icon-inline'), i18n.t('scheduler.run_now'));
    }

    function resetUI() {
        hideBanner();
        resetButton();
    }

    function init() {
        // Poll immediately so the banner appears at once if a scheduled run
        // is already executing when the page loads, without waiting 3 seconds
        // for the first interval tick.
        poll();
        startPolling(3000); // Detect scheduled runs
    }

    return {
        init,
        trigger,
    };
})();