// ============================================================
// Sky Status Widget
// Persistent compact widget in the navbar showing current sky
// period (day / twilight / night) and tonight's observation score.
// Expands on hover (desktop) or tap (mobile) to show period details.
// ============================================================

const SkyWidget = (() => {
    const REFRESH_MS = 5 * 60 * 1000; // 5 minutes
    let _refreshTimer = null;

    const PERIOD_ICONS = {
        day:                    'bi-sun-fill',
        civil_twilight:         'bi-sunset-fill',
        nautical_twilight:      'bi-moon',
        astronomical_twilight:  'bi-moon-fill',
        astronomical_night:     'bi-moon-stars-fill',
        astronomical_dawn:      'bi-sunrise-fill',
        unknown:                'bi-circle',
    };

    function _scoreClass(score) {
        if (score >= 8) return 'score-good';
        if (score >= 6) return 'score-fair';
        if (score >= 4) return 'score-poor';
        return 'score-bad';
    }

    function _formatSeconds(seconds) {
        if (!seconds || seconds <= 0) return '0m';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        if (h > 0 && m > 0) return `${h}h ${m}m`;
        if (h > 0) return `${h}h`;
        return `${m}m`;
    }

    function _periodLabel(key) {
        if (!key) return '';
        const i18nKey = `sky_widget.period_${key}`;
        return i18n.t(i18nKey);
    }

    function _render(data) {
        const widget = document.getElementById('sky-status-widget');
        if (!widget) return;

        // Swap period class
        const periodClasses = [
            'period-day', 'period-civil_twilight', 'period-nautical_twilight',
            'period-astronomical_twilight', 'period-astronomical_night', 'period-unknown',
        ];
        periodClasses.forEach(c => widget.classList.remove(c));
        widget.classList.add(`period-${data.period || 'unknown'}`);

        // Header icon (large)
        const iconEl = document.getElementById('sky-widget-icon');
        if (iconEl) {
            iconEl.className = `bi ${PERIOD_ICONS[data.period] || PERIOD_ICONS.unknown} sky-widget-period-icon`;
        }

        // Location
        const locationEl = document.getElementById('sky-widget-location');
        if (locationEl) locationEl.textContent = data.location || '';

        // Score badge
        const scoreEl = document.getElementById('sky-widget-score');
        if (scoreEl) {
            if (data.observation_score !== null && data.observation_score !== undefined && data.observation_score > 0) {
                scoreEl.textContent = data.observation_score;
                scoreEl.className = `sky-widget-score ms-1 ${_scoreClass(data.observation_score)}`;
                scoreEl.title = i18n.t('sky_widget.score_title');
                scoreEl.style.display = '';
            } else {
                scoreEl.style.display = 'none';
            }
        }

        // Panel icon
        const panelIconEl = document.getElementById('sky-widget-panel-icon');
        if (panelIconEl) {
            panelIconEl.className = `bi ${PERIOD_ICONS[data.period] || PERIOD_ICONS.unknown} sky-widget-panel-period-icon`;
        }

        // Period label
        const periodLabelEl = document.getElementById('sky-widget-period-label');
        if (periodLabelEl) periodLabelEl.textContent = _periodLabel(data.period);

        // Next period
        const nextLabelEl = document.getElementById('sky-widget-next-label');
        const nextDivEl = document.getElementById('sky-widget-panel-next');
        if (nextLabelEl) {
            if (data.next_period && data.time_until_next_seconds !== null) {
                nextLabelEl.textContent = i18n.t('sky_widget.next_in', {
                    period: _periodLabel(data.next_period),
                    time: _formatSeconds(data.time_until_next_seconds),
                });
                if (nextDivEl) nextDivEl.style.display = '';
            } else {
                nextLabelEl.textContent = '';
                if (nextDivEl) nextDivEl.style.display = 'none';
            }
        }
    }

    function _renderLoading() {
        const locationEl = document.getElementById('sky-widget-location');
        if (locationEl) locationEl.textContent = i18n.t('sky_widget.loading');
        const scoreEl = document.getElementById('sky-widget-score');
        if (scoreEl) scoreEl.style.display = 'none';
    }

    async function refresh() {
        try {
            const data = await fetchJSON('/api/sky-widget');
            if (data && !data.error) {
                _render(data);
            }
        } catch (_) {
            // Widget is non-critical; fail silently
        }
    }

    function _setupInteraction() {
        const widget = document.getElementById('sky-status-widget');
        if (!widget) return;

        // Touch: toggle expanded state
        widget.addEventListener('touchstart', (e) => {
            // Allow touch to toggle — stop propagation only on the widget itself
            e.stopPropagation();
            widget.classList.toggle('sky-widget--open');
        }, { passive: true });

        // Collapse when tapping outside
        document.addEventListener('touchstart', (e) => {
            if (!widget.contains(e.target)) {
                widget.classList.remove('sky-widget--open');
            }
        }, { passive: true });

        // Keyboard: Enter/Space toggles
        widget.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                widget.classList.toggle('sky-widget--open');
            } else if (e.key === 'Escape') {
                widget.classList.remove('sky-widget--open');
            }
        });
    }

    async function init() {
        _setupInteraction();
        _renderLoading();
        await refresh();
        _refreshTimer = setInterval(refresh, REFRESH_MS);
    }

    function destroy() {
        if (_refreshTimer) {
            clearInterval(_refreshTimer);
            _refreshTimer = null;
        }
    }

    // Re-render text when the language changes
    window.addEventListener('i18nLanguageChanged', () => {
        refresh();
    });

    return { init, refresh, destroy };
})();

window.SkyWidget = SkyWidget;
