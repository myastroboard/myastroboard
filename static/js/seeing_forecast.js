// ======================
// Seeing Forecast (7Timer)
// ======================

function getQualityScoreColorClass(score) {
    const v = Number(score);
    if (!Number.isFinite(v)) return 'text-secondary';
    if (v >= 6) return 'text-success';
    if (v >= 4) return 'text-warning';
    return 'text-danger';
}

function getQualityScoreCssClass(score) {
    const v = Number(score);
    if (!Number.isFinite(v)) return 'quality-bad';
    if (v >= 8) return 'quality-excellent';
    if (v >= 6) return 'quality-good';
    if (v >= 4) return 'quality-fair';
    if (v >= 2) return 'quality-poor';
    return 'quality-bad';
}

function getLocalizedQualityScoreLabel(score) {
    const v = Number(score);
    if (!Number.isFinite(v)) return i18n.t('common.quality_scale.unknown');
    if (v >= 8) return i18n.t('common.quality_scale.excellent');
    if (v >= 6) return i18n.t('common.quality_scale.good');
    if (v >= 4) return i18n.t('common.quality_scale.fair');
    if (v >= 2) return i18n.t('common.quality_scale.poor');
    return i18n.t('common.quality_scale.bad');
}

// Generic 1..N 7Timer scale -> quality color class, used for the per-metric icons.
// Matches the backend's _quality_component: most scales are 1=best/N=worst, but
// transparency is inverted (1=worst/N=best per 7Timer's own docs).
function getScaleColorClass(value, scaleSize, higherRawIsBetter = false) {
    const v = Number(value);
    if (!Number.isFinite(v) || !scaleSize || scaleSize <= 1 || v < 1 || v > scaleSize) return 'text-secondary';
    const quality = higherRawIsBetter ? (v - 1) / (scaleSize - 1) : (scaleSize - v) / (scaleSize - 1); // 1 = best, 0 = worst
    const clamped = Math.max(0, Math.min(1, quality));
    if (clamped >= 0.66) return 'text-success';
    if (clamped >= 0.33) return 'text-warning';
    return 'text-danger';
}

function getSeeingBadgeClass(seeingValue) {
    const v = Number(seeingValue);
    if (!Number.isFinite(v)) return 'text-secondary';
    if (v <= 1) return 'text-success';
    if (v <= 2) return 'text-primary';
    if (v <= 3) return 'text-warning';
    return 'text-danger';
}

function getLocalizedSeeingQuality(seeingValue, rawDescription) {
    const normalizeSeeingLevel = (value) => {
        const v = Number(value);
        if (!Number.isFinite(v)) return null;
        if (v <= 1) return 1;
        if (v <= 2) return 2;
        if (v <= 3) return 3;
        if (v <= 4) return 4;
        return 5;
    };

    const seeingNumber = Number(seeingValue);
    const normalizedLevel = normalizeSeeingLevel(seeingNumber);
    const keyByValue = {
        1: 'common.quality_scale.excellent',
        2: 'common.quality_scale.good',
        3: 'common.quality_scale.moderate',
        4: 'common.quality_scale.poor',
        5: 'common.quality_scale.bad'
    };

    if (normalizedLevel && keyByValue[normalizedLevel]) {
        return i18n.t(keyByValue[normalizedLevel]);
    }

    const normalized = String(rawDescription || '').trim().toLowerCase();
    const keyByDescription = {
        'excellent': 'common.quality_scale.excellent',
        'very good': 'common.quality_scale.high',
        'good': 'common.quality_scale.good',
        'moderate': 'common.quality_scale.moderate',
        'fair': 'common.quality_scale.fair',
        'poor': 'common.quality_scale.poor',
        'very poor': 'common.quality_scale.bad',
        'bad': 'common.quality_scale.bad',
        'unavailable': 'common.quality_scale.unknown',
        'unknown': 'common.quality_scale.unknown'
    };

    if (normalized && keyByDescription[normalized]) {
        return i18n.t(keyByDescription[normalized]);
    }

    return rawDescription || i18n.t('common.quality_scale.unknown');
}

function getLocalizedSeeingDetails(seeingValue, fallbackDetails = '') {
    const seeingNumber = Number(seeingValue);
    let normalizedLevel = null;
    if (Number.isFinite(seeingNumber)) {
        if (seeingNumber <= 1) normalizedLevel = 1;
        else if (seeingNumber <= 2) normalizedLevel = 2;
        else if (seeingNumber <= 3) normalizedLevel = 3;
        else if (seeingNumber <= 4) normalizedLevel = 4;
        else normalizedLevel = 5;
    }

    const key = `seeing_forecast.seeing_descriptions.${normalizedLevel}`;
    if (normalizedLevel && i18n.has(key)) {
        return i18n.t(key);
    }
    return fallbackDetails || '';
}

// Localized label for one of the new 7Timer scales (transparency/cloudcover/wind), falling
// back to the backend-provided English label if the language pack has no entry yet.
function getLocalizedScaleLabel(namespace, value, fallbackLabel) {
    if (value === null || value === undefined) return i18n.t('common.quality_scale.unknown');
    const key = `seeing_forecast.${namespace}.${value}`;
    return i18n.t(key, fallbackLabel || i18n.t('common.quality_scale.unknown'));
}

function formatTimeThenDateInTimezone(isoString, timezone, locale = navigator.language) {
    if (!isoString) return 'N/A';
    const date = new Date(isoString);

    try {
        const timeFormatter = new Intl.DateTimeFormat(locale, {
            hour: '2-digit',
            minute: '2-digit',
            hour12: getHour12Option(),
            timeZone: timezone || 'UTC'
        });

        const dateFormatter = new Intl.DateTimeFormat(locale, {
            month: 'numeric',
            day: 'numeric',
            timeZone: timezone || 'UTC'
        });

        return `${timeFormatter.format(date)} (${dateFormatter.format(date)})`;
    } catch {
        // Fallback for invalid/unsupported timezone values.
        return formatTimeThenDate(isoString, locale);
    }
}

function getHourInTimezone(isoString, timezone) {
    if (!isoString) return null;
    try {
        const date = new Date(isoString);
        const parts = new Intl.DateTimeFormat('en-GB', {
            hour: '2-digit',
            hour12: false,
            timeZone: timezone || 'UTC'
        }).formatToParts(date);
        const hourPart = parts.find(p => p.type === 'hour');
        const hour = Number(hourPart?.value);
        return Number.isFinite(hour) ? hour : null;
    } catch {
        return null;
    }
}

function isLikelyNight(isoString, timezone) {
    const hour = getHourInTimezone(isoString, timezone);
    if (hour === null) return false;
    // Visual heuristic for night period in local time.
    return hour >= 19 || hour < 6;
}

function createSeeingMetricIcon(iconClass, colorClass, tooltip) {
    const ico = DOMUtils.createIcon(iconClass);
    ico.className += ` ${colorClass}`;
    ico.title = tooltip;
    ico.setAttribute('aria-hidden', 'false');
    ico.setAttribute('aria-label', tooltip);
    return ico;
}

/**
 * Build the icon row summarizing every raw 7Timer metric for one forecast point,
 * so the tab surfaces seeing + transparency + clouds + wind + humidity + precipitation
 * instead of seeing alone.
 */
function buildForecastPointIconRow(point) {
    const iconRow = document.createElement('div');
    iconRow.className = 'night-score-icons';

    iconRow.appendChild(createSeeingMetricIcon(
        'bi bi-eye',
        getSeeingBadgeClass(point.seeing),
        `${i18n.t('astro_weather.seeing')}: ${getLocalizedSeeingQuality(point.seeing, point.description)}`
    ));

    iconRow.appendChild(createSeeingMetricIcon(
        'bi bi-stars',
        getScaleColorClass(point.transparency, 8, true),
        `${i18n.t('astro_weather.transparency')}: ${getLocalizedScaleLabel('transparency_scale', point.transparency, point.transparency_label)}`
    ));

    iconRow.appendChild(createSeeingMetricIcon(
        'bi bi-clouds',
        getScaleColorClass(point.cloudcover, 9),
        `${i18n.t('weather.cloud_cover')}: ${getLocalizedScaleLabel('cloudcover_scale', point.cloudcover, point.cloudcover_label)}`
    ));

    const windLabel = getLocalizedScaleLabel('wind_scale', point.wind_speed_class, point.wind_label);
    const windDirection = point.wind_direction ? ` (${point.wind_direction})` : '';
    iconRow.appendChild(createSeeingMetricIcon(
        'bi bi-wind',
        getScaleColorClass(point.wind_speed_class, 8),
        `${i18n.t('weather.wind')}: ${windLabel}${windDirection}`
    ));

    if (point.humidity_percent !== null && point.humidity_percent !== undefined) {
        const humidityColor = point.humidity_percent <= 50 ? 'text-success' : point.humidity_percent <= 75 ? 'text-warning' : 'text-danger';
        iconRow.appendChild(createSeeingMetricIcon(
            'bi bi-droplet-half',
            humidityColor,
            `${i18n.t('weather.humidity')}: ~${Math.round(point.humidity_percent)}${i18n.t('units.percent')}`
        ));
    }

    const precType = point.prec_type || 'none';
    const hasPrecipitation = precType !== 'none';
    iconRow.appendChild(createSeeingMetricIcon(
        'bi bi-cloud-rain',
        hasPrecipitation ? 'text-danger' : 'text-secondary',
        `${i18n.t('weather.precipitation')}: ${i18n.t(`seeing_forecast.prec_type.${precType}`, precType)}`
    ));

    return iconRow;
}

/**
 * Render the 7Timer forecast as an hourly quality timeline, in the same visual language as
 * the Trend sub-tab's "Tonight's Score" (night-score-timeline): one card per timeslot with a
 * combined quality_score, a quality badge, and an icon row for every underlying metric.
 */
function renderSeeingQualityTimeline(forecast, timezone) {
    const timeline = document.createElement('div');
    timeline.className = 'night-score-timeline';

    const now = Date.now();
    const futurePoints = (forecast || []).filter(point => new Date(point.time).getTime() >= now);

    if (futurePoints.length === 0) {
        const msg = document.createElement('p');
        msg.className = 'text-muted fst-italic mb-0';
        msg.textContent = i18n.t('seeing_forecast.no_data');
        return msg;
    }

    // Only the single closest future point is flagged "now" (half of the 3h step margin),
    // matching the "now" highlight convention used by night-score-timeline.
    const rangeMargin = 90 * 60 * 1000;
    let nowIdx = -1;
    let nowBestDiff = Infinity;
    futurePoints.forEach((point, i) => {
        const diff = Math.abs(new Date(point.time).getTime() - now);
        if (diff <= rangeMargin && diff < nowBestDiff) {
            nowBestDiff = diff;
            nowIdx = i;
        }
    });

    futurePoints.forEach((point, i) => {
        const isNow = i === nowIdx;
        const night = isLikelyNight(point.time, timezone);

        const card = document.createElement('div');
        card.className = `card h-100 night-score-card${isNow ? ' night-score-card-now' : ''}`;

        const body = document.createElement('div');
        body.className = 'card-body p-1 text-center';

        const hourRow = document.createElement('div');
        hourRow.className = 'night-score-hour-row';

        const phaseIco = DOMUtils.createIcon(night ? 'bi bi-moon-stars-fill' : 'bi bi-sun-fill');
        phaseIco.className += night ? ' text-info' : ' text-warning';
        hourRow.appendChild(phaseIco);

        const hourEl = document.createElement('span');
        hourEl.className = 'fw-semibold night-score-hour';
        hourEl.textContent = formatTimeThenDateInTimezone(point.time, timezone);
        hourRow.appendChild(hourEl);

        body.appendChild(hourRow);

        const scoreEl = document.createElement('div');
        scoreEl.className = `night-score-value ${getQualityScoreColorClass(point.quality_score)}`;
        scoreEl.textContent = point.quality_score ?? '-';
        body.appendChild(scoreEl);

        const qualBadge = document.createElement('div');
        qualBadge.className = `astro-quality-text quality-box ${getQualityScoreCssClass(point.quality_score)}`;
        qualBadge.textContent = getLocalizedQualityScoreLabel(point.quality_score);
        body.appendChild(qualBadge);

        body.appendChild(buildForecastPointIconRow(point));

        card.appendChild(body);
        timeline.appendChild(card);
    });

    return timeline;
}

function createSeeingSummaryCard({ iconClass, titleKey, score, scoreLabel, subLines }) {
    const col = document.createElement('div');
    col.className = 'col';
    const card = document.createElement('div');
    card.className = 'card h-100';

    const header = document.createElement('div');
    header.className = 'card-header fw-bold';
    DOMUtils.append(header, DOMUtils.createIcon(`${iconClass} icon-inline`), i18n.t(titleKey));
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'card-body';

    if (score === null || score === undefined) {
        body.className += ' text-muted';
        body.textContent = i18n.t('seeing_forecast.no_data');
    } else {
        const scoreDiv = document.createElement('div');
        scoreDiv.className = `fs-3 fw-bold ${getQualityScoreColorClass(score)}`;
        scoreDiv.textContent = score;
        body.appendChild(scoreDiv);

        const qualDiv = document.createElement('div');
        qualDiv.className = 'text-muted';
        qualDiv.textContent = scoreLabel;
        body.appendChild(qualDiv);

        (subLines || []).forEach((line) => {
            const small = document.createElement('small');
            small.className = 'text-muted d-block mt-1';
            small.textContent = line;
            body.appendChild(small);
        });
    }

    card.appendChild(body);
    col.appendChild(card);
    return col;
}

async function loadSeeingForecast() {
    const container = document.getElementById('seeing-forecast-display');
    const data = await fetchJSONWithUI('/api/seeing-forecast', container, i18n.t('seeing_forecast.loading_forecast'));
    if (!data) return;

    DOMUtils.clear(container);

    const seeingData = data.seeing_forecast;
    const configuredTimezone = data?.location?.timezone || seeingData?.location?.timezone || 'UTC';
    if (!seeingData) {
        const warning = document.createElement('div');
        warning.className = 'alert alert-warning';
        warning.setAttribute('role', 'alert');
        warning.textContent = data.message_key ? i18n.t(data.message_key) : (data.message || i18n.t('seeing_forecast.no_data'));
        container.appendChild(warning);
        return;
    }

    if (seeingData.message_key || seeingData.message) {
        const notice = document.createElement('div');
        notice.className = 'alert alert-warning';
        notice.setAttribute('role', 'alert');
        notice.textContent = seeingData.message_key ? i18n.t(seeingData.message_key) : seeingData.message;
        container.appendChild(notice);
    }

    const infoAlert = document.createElement('div');
    infoAlert.className = 'alert alert-info';
    infoAlert.setAttribute('role', 'alert');
    DOMUtils.append(infoAlert, DOMUtils.createIcon('bi bi-bullseye icon-inline'), i18n.t('seeing_forecast.planetary_imaging'));
    container.appendChild(infoAlert);

    const topRow = document.createElement('div');
    topRow.className = 'row row-cols-1 row-cols-lg-3 g-3 mb-3';

    topRow.appendChild(createSeeingSummaryCard({
        iconClass: 'bi bi-speedometer2',
        titleKey: 'seeing_forecast.current_conditions',
        score: seeingData.now_quality_score,
        scoreLabel: getLocalizedQualityScoreLabel(seeingData.now_quality_score),
        subLines: [
            `${i18n.t('astro_weather.seeing')}: ${getLocalizedSeeingQuality(seeingData.now, seeingData.now_description)}`,
            i18n.t('seeing_forecast.data_source')
        ]
    }));

    const bw = seeingData.best_window;
    topRow.appendChild(createSeeingSummaryCard({
        iconClass: 'bi bi-clock-history',
        titleKey: 'seeing_forecast.best_window',
        score: bw ? bw.quality_score : null,
        scoreLabel: bw ? getLocalizedQualityScoreLabel(bw.quality_score) : null,
        subLines: bw ? [
            `${i18n.t('common.time_label')}: ${formatTimeThenDateInTimezone(bw.start, configuredTimezone)}`,
            `${i18n.t('common.duration')} ${bw.duration_hours}h`
        ] : null
    }));

    const bsw = seeingData.best_seeing_window;
    topRow.appendChild(createSeeingSummaryCard({
        iconClass: 'bi bi-eye',
        titleKey: 'seeing_forecast.best_seeing_window',
        score: bsw ? bsw.seeing : null,
        scoreLabel: bsw ? getLocalizedSeeingQuality(bsw.seeing, bsw.description) : null,
        subLines: bsw ? [
            `${i18n.t('common.time_label')}: ${formatTimeThenDateInTimezone(bsw.start, configuredTimezone)}`,
            `${i18n.t('common.duration')} ${bsw.duration_hours}h`
        ] : null
    }));

    container.appendChild(topRow);

    const timelineCard = document.createElement('div');
    timelineCard.className = 'card h-100';
    const header = document.createElement('div');
    header.className = 'card-header fw-bold';
    DOMUtils.append(header, DOMUtils.createIcon('bi bi-calendar-event text-danger icon-inline'), i18n.t('seeing_forecast.forecast'));
    const body = document.createElement('div');
    body.className = 'night-score-timeline-scroll';
    body.appendChild(renderSeeingQualityTimeline(seeingData.forecast, configuredTimezone));

    timelineCard.appendChild(header);
    timelineCard.appendChild(body);
    container.appendChild(timelineCard);

    const normalizationInfo = document.createElement('div');
    normalizationInfo.className = 'alert alert-secondary mt-3 mb-0';
    normalizationInfo.setAttribute('role', 'note');
    normalizationInfo.appendChild(DOMUtils.createIcon('bi bi-info-circle icon-inline'));
    normalizationInfo.append(' ');
    const _normStrong = document.createElement('strong');
    _normStrong.textContent = i18n.t('seeing_forecast.scale_mapping_title');
    normalizationInfo.appendChild(_normStrong);
    const _normInfo = document.createElement('div');
    _normInfo.className = 'small mt-1';
    _normInfo.textContent = i18n.t('seeing_forecast.scale_mapping_info');
    normalizationInfo.appendChild(_normInfo);
    container.appendChild(normalizationInfo);

    const tips = [];
    for (let idx = 1; idx <= 10; idx += 1) {
        const tipKey = `seeing_forecast.tips.${idx}`;
        if (i18n.has(tipKey)) {
            tips.push(i18n.t(tipKey));
        }
    }

    if (tips.length > 0) {
        const tipsCard = document.createElement('div');
        tipsCard.className = 'card mt-3';

        const tipsHeader = document.createElement('div');
        tipsHeader.className = 'card-header fw-bold';
        DOMUtils.append(tipsHeader, DOMUtils.createIcon('bi bi-lightbulb icon-inline'), i18n.t('common.info'));

        const tipsBody = document.createElement('div');
        tipsBody.className = 'card-body py-2';
        const tipsList = document.createElement('ul');
        tipsList.className = 'mb-0';

        tips.forEach((tip) => {
            const item = document.createElement('li');
            item.textContent = tip;
            tipsList.appendChild(item);
        });

        tipsBody.appendChild(tipsList);
        tipsCard.appendChild(tipsHeader);
        tipsCard.appendChild(tipsBody);
        container.appendChild(tipsCard);
    }

    appendDataSourceFooter(container, {
        text: i18n.t('seeing_forecast.footer_source'),
        links: [
            { href: 'http://www.7timer.info/', label: '7Timer' }
        ]
    });
}
