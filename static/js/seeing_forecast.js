// ======================
// Seeing Forecast (7Timer)
// ======================

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

function renderSeeingForecastRows(forecast, timezone) {
    const table = document.createElement('table');
    table.className = 'table table-striped table-hover mb-0 seeing-forecast-table';

    const thead = document.createElement('thead');
    const trh = document.createElement('tr');
    ['common.time_label', 'seeing_forecast.current_seeing', 'seeing_forecast.quality_table'].forEach((key) => {
        const th = document.createElement('th');
        th.textContent = i18n.t(key);
        trh.appendChild(th);
    });
    thead.appendChild(trh);

    const tbody = document.createElement('tbody');
    const now = Date.now();
    (forecast || []).filter(point => new Date(point.time).getTime() >= now).forEach((point) => {
        const tr = document.createElement('tr');
        const night = isLikelyNight(point.time, timezone);
        tr.classList.add(night ? 'seeing-row-night' : 'seeing-row-day');

        const tdTime = document.createElement('td');
        const timeCellWrap = document.createElement('div');
        timeCellWrap.className = 'seeing-time-cell';

        const period = document.createElement('span');
        const periodLabel = night
            ? i18n.t('common.night', 'Night')
            : i18n.t('common.day', 'Day');
        period.className = `seeing-daynight-indicator ${night ? 'is-night' : 'is-day'}`;
        period.setAttribute('title', periodLabel);
        period.setAttribute('aria-label', periodLabel);
        period.appendChild(DOMUtils.createIcon(`bi ${night ? 'bi-moon-stars-fill' : 'bi-sun-fill'}`));
        timeCellWrap.appendChild(period);

        const tlabel = document.createElement('span');
        tlabel.className = 'seeing-time-label';
        tlabel.textContent = formatTimeThenDateInTimezone(point.time, timezone);
        timeCellWrap.appendChild(tlabel);
        tdTime.appendChild(timeCellWrap);

        const tdSeeing = document.createElement('td');
        const badgeClass = getSeeingBadgeClass(point.seeing);
        const _pill = document.createElement('span');
        _pill.className = `seeing-score-pill fw-bold ${badgeClass}`;
        _pill.textContent = point.seeing;
        tdSeeing.appendChild(_pill);

        const tdDesc = document.createElement('td');
        const qualityText = document.createElement('div');
        qualityText.textContent = getLocalizedSeeingQuality(point.seeing, point.description);
        tdDesc.appendChild(qualityText);

        const detailText = getLocalizedSeeingDetails(point.seeing, point.conditions);
        if (detailText) {
            const detailNode = document.createElement('small');
            detailNode.className = 'text-muted d-block';
            detailNode.textContent = detailText;
            tdDesc.appendChild(detailNode);
        }

        tr.appendChild(tdTime);
        tr.appendChild(tdSeeing);
        tr.appendChild(tdDesc);
        tbody.appendChild(tr);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    return table;
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
    topRow.className = 'row row-cols-1 row-cols-lg-2 g-3 mb-3';

    const currentCol = document.createElement('div');
    currentCol.className = 'col';
    const currentCard = document.createElement('div');
    currentCard.className = 'card h-100';
    const _curHeader = document.createElement('div');
    _curHeader.className = 'card-header fw-bold';
    DOMUtils.append(_curHeader, DOMUtils.createIcon('bi bi-eye icon-inline'), i18n.t('seeing_forecast.current_seeing'));
    const _curBody = document.createElement('div');
    _curBody.className = 'card-body';
    const _scoreDiv = document.createElement('div');
    _scoreDiv.className = `fs-3 fw-bold ${getSeeingBadgeClass(seeingData.now)}`;
    _scoreDiv.textContent = seeingData.now ?? '-';
    const _qualDiv = document.createElement('div');
    _qualDiv.className = 'text-muted';
    _qualDiv.textContent = getLocalizedSeeingQuality(seeingData.now, seeingData.now_description);
    const _detailSmall = document.createElement('small');
    _detailSmall.className = 'text-muted d-block mt-1';
    _detailSmall.textContent = getLocalizedSeeingDetails(seeingData.now, '');
    const _srcSmall = document.createElement('small');
    _srcSmall.className = 'text-muted';
    _srcSmall.textContent = i18n.t('seeing_forecast.data_source');
    _curBody.appendChild(_scoreDiv);
    _curBody.appendChild(_qualDiv);
    _curBody.appendChild(_detailSmall);
    _curBody.appendChild(_srcSmall);
    currentCard.appendChild(_curHeader);
    currentCard.appendChild(_curBody);
    currentCol.appendChild(currentCard);

    const bestCol = document.createElement('div');
    bestCol.className = 'col';
    const bestCard = document.createElement('div');
    bestCard.className = 'card h-100';
    const bw = seeingData.best_window;
    const _bwHeader = document.createElement('div');
    _bwHeader.className = 'card-header fw-bold';
    DOMUtils.append(_bwHeader, DOMUtils.createIcon('bi bi-clock-history icon-inline'), i18n.t('seeing_forecast.best_window'));
    bestCard.appendChild(_bwHeader);
    if (bw) {
        const _bwBody = document.createElement('div');
        _bwBody.className = 'card-body';
        const _timeDiv = document.createElement('div');
        const _tStrong = document.createElement('strong');
        _tStrong.textContent = `${i18n.t('common.time_label')}:`;
        _timeDiv.appendChild(_tStrong);
        _timeDiv.append(` ${formatTimeThenDateInTimezone(bw.start, configuredTimezone)}`);
        const _durDiv = document.createElement('div');
        const _dStrong = document.createElement('strong');
        _dStrong.textContent = i18n.t('common.duration');
        _durDiv.appendChild(_dStrong);
        _durDiv.append(` ${bw.duration_hours}h`);
        const _qualDiv = document.createElement('div');
        const _qStrong = document.createElement('strong');
        _qStrong.textContent = i18n.t('common.quality');
        _qualDiv.appendChild(_qStrong);
        _qualDiv.append(' ');
        const _qualSpan = document.createElement('span');
        _qualSpan.className = getSeeingBadgeClass(bw.seeing);
        _qualSpan.textContent = getLocalizedSeeingQuality(bw.seeing, bw.description);
        _qualDiv.appendChild(_qualSpan);
        const _detDiv = document.createElement('div');
        _detDiv.className = 'small text-muted mt-1';
        _detDiv.textContent = getLocalizedSeeingDetails(bw.seeing, bw.conditions || '');
        _bwBody.appendChild(_timeDiv);
        _bwBody.appendChild(_durDiv);
        _bwBody.appendChild(_qualDiv);
        _bwBody.appendChild(_detDiv);
        bestCard.appendChild(_bwBody);
    } else {
        const _bwBody = document.createElement('div');
        _bwBody.className = 'card-body text-muted';
        _bwBody.textContent = i18n.t('seeing_forecast.no_data');
        bestCard.appendChild(_bwBody);
    }
    bestCol.appendChild(bestCard);

    topRow.appendChild(currentCol);
    topRow.appendChild(bestCol);
    container.appendChild(topRow);

    const forecastCard = document.createElement('div');
    forecastCard.className = 'card h-100';
    const header = document.createElement('div');
    header.className = 'card-header fw-bold';
    DOMUtils.append(header, DOMUtils.createIcon('bi bi-calendar-event text-danger icon-inline'), i18n.t('seeing_forecast.forecast'));
    const body = document.createElement('div');
    body.className = 'table-responsive';
    body.appendChild(renderSeeingForecastRows(seeingData.forecast, configuredTimezone));

    forecastCard.appendChild(header);
    forecastCard.appendChild(body);
    container.appendChild(forecastCard);

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
