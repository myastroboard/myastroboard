// ============================================================
// Sky Status Widget
// Persistent compact widget in the navbar showing current sky
// period (day / twilight / night) and tonight's observation score.
// Expands on click/tap (desktop and mobile alike) to show period details
// and, for multi-location users, a switcher - hover-to-open was removed
// because it made the location list unreachable (closes before the pointer
// crosses the gap to the panel).
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

    // Every time shown anywhere in the app (sun/moon times, forecasts, passes...)
    // is the ACTIVE LOCATION's own local time, not the viewer's browser time -
    // astronomy events are tied to the observer's site, not the viewer's device.
    // When those differ, surface it here so a foreign-timezone location doesn't
    // read as silently wrong everywhere else in the UI.
    function _browserTimezone() {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
        } catch (_) {
            return null;
        }
    }

    function _formatUtcOffset(tzName) {
        try {
            const parts = new Intl.DateTimeFormat('en', { timeZone: tzName, timeZoneName: 'shortOffset' })
                .formatToParts(new Date());
            const tzPart = parts.find(p => p.type === 'timeZoneName');
            // Normalize "GMT" (offset 0) to the more familiar "UTC"
            return tzPart ? tzPart.value.replace('GMT', 'UTC') : null;
        } catch (_) {
            return null;
        }
    }

    function _renderTimezoneNotice(locationTimezone) {
        const badge = document.getElementById('sky-widget-tz-badge');
        const panelTz = document.getElementById('sky-widget-panel-tz');
        const panelTzLabel = document.getElementById('sky-widget-tz-label');
        if (!badge || !panelTz || !panelTzLabel) return;

        const browserTz = _browserTimezone();
        if (!locationTimezone || !browserTz || locationTimezone === browserTz) {
            badge.style.display = 'none';
            panelTz.style.display = 'none';
            return;
        }

        const locationOffset = _formatUtcOffset(locationTimezone);
        const browserOffset = _formatUtcOffset(browserTz);
        if (!locationOffset || !browserOffset) {
            badge.style.display = 'none';
            panelTz.style.display = 'none';
            return;
        }

        badge.textContent = locationOffset;
        badge.title = i18n.t('sky_widget.tz_badge_title', { offset: locationOffset });
        badge.style.display = '';

        panelTzLabel.textContent = i18n.t('sky_widget.tz_notice', {
            tz: locationTimezone,
            offset: locationOffset,
            your_tz: browserTz,
            your_offset: browserOffset,
        });
        panelTz.style.display = '';
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

        _renderTimezoneNotice(data.timezone);

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

    // ------------------------------------------------------------
    // Location switcher (v1.2): panel list of the user's attributed
    // locations. Invisible for single-location users (the majority).
    // ------------------------------------------------------------

    async function _renderLocationList() {
        const block = document.getElementById('sky-widget-locations');
        const list = document.getElementById('sky-widget-locations-list');
        const widget = document.getElementById('sky-status-widget');
        if (!block || !list || typeof fetchMyLocations !== 'function') return;

        let data;
        try {
            // Force a fresh fetch each poll: the payload now carries a per-location
            // observation score, which the widget's cheap file-read endpoint keeps
            // current - the client-side cache is only meant to dedupe rapid calls,
            // not to survive across a 5-minute refresh cycle.
            data = await fetchMyLocations(true);
        } catch (_) {
            return; // list is optional - widget stays fully functional without it
        }
        const locations = (data && data.locations) || [];

        if (locations.length <= 1) {
            block.style.display = 'none';
            if (widget) widget.classList.remove('sky-widget--multi');
            return;
        }

        if (widget) widget.classList.add('sky-widget--multi');
        block.style.display = '';
        DOMUtils.clear(list);

        locations.forEach(loc => {
            const isActive = loc.id === data.active_location_id;
            const li = document.createElement('li');
            li.className = `sky-widget-location-row${isActive ? ' active' : ''}`;
            li.setAttribute('role', 'option');
            li.setAttribute('aria-selected', isActive ? 'true' : 'false');
            li.tabIndex = 0;

            if (isActive) {
                const check = document.createElement('i');
                check.className = 'bi bi-check-lg icon-inline';
                check.setAttribute('aria-hidden', 'true');
                li.appendChild(check);
            }

            const name = document.createElement('span');
            name.className = 'sky-widget-location-name';
            name.textContent = loc.name || '?';
            li.appendChild(name);

            if (loc.score !== null && loc.score !== undefined) {
                const score = document.createElement('span');
                score.className = `sky-widget-score sky-widget-location-score ${_scoreClass(loc.score)}`;
                score.textContent = loc.score;
                score.title = i18n.t('sky_widget.score_title');
                li.appendChild(score);
            }

            const bortle = document.createElement('span');
            bortle.className = 'sky-widget-location-bortle';
            bortle.textContent = loc.bortle != null ? `B${loc.bortle}` : '';
            li.appendChild(bortle);

            const activate = async () => {
                if (isActive) return;
                try {
                    await setActiveLocation(loc.id);
                    // A location switch re-drives every calculation on the page:
                    // a full reload is the simplest correct "all tabs re-fetch".
                    window.location.reload();
                } catch (err) {
                    console.error('Error switching location:', err);
                }
            };
            li.addEventListener('click', activate);
            li.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    e.stopPropagation();
                    activate();
                }
            });

            list.appendChild(li);
        });
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
        _renderLocationList();
    }

    function _setupInteraction() {
        const widget = document.getElementById('sky-status-widget');
        const compact = widget?.querySelector('.sky-widget-compact');
        if (!widget || !compact) return;

        // Click/tap the compact pill to toggle the panel - no hover-to-open, so the
        // multi-location list can be reached without the panel closing on the way
        // (a 'click' handler also correctly fires from touch without the ghost-click
        // double-toggle that a 'touchstart' + implicit click would cause).
        compact.addEventListener('click', (e) => {
            e.stopPropagation();
            widget.classList.toggle('sky-widget--open');
        });

        // Collapse when clicking/tapping outside
        document.addEventListener('click', (e) => {
            if (!widget.contains(e.target)) {
                widget.classList.remove('sky-widget--open');
            }
        });

        // Keyboard: Enter/Space toggles, Escape closes
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
