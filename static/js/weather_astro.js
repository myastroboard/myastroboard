// ======================
// Astrophotography Weather
// ======================

// Global variables for astro weather
let astroWeatherData = null;
let astroWeatherUpdateInterval = null;
let astroWeatherRequestInFlight = null;


function updateAstroWeatherLoadingMessage(message) {
    const loadingDiv = document.getElementById('astro-weather-loading');
    if (!loadingDiv) return;

    const textNode = loadingDiv.querySelector('.card-text');
    if (textNode) {
        textNode.textContent = message;
    } else {
        loadingDiv.textContent = message;
    }
}


function destroyAstroWeatherCharts() {
    if (window.astroSeeingChart) {
        window.astroSeeingChart.destroy();
        window.astroSeeingChart = null;
    }
    if (window.astroCloudsChart) {
        window.astroCloudsChart.destroy();
        window.astroCloudsChart = null;
    }
    if (window.astroConditionsChart) {
        window.astroConditionsChart.destroy();
        window.astroConditionsChart = null;
    }
}

function createAstroChartShell(title, canvasId, legendItems = [], footerText = '') {
    const col = document.createElement('div');
    col.className = 'col mb-3';

    const card = document.createElement('div');
    card.className = 'card h-100';

    const header = document.createElement('div');
    header.className = 'card-header';
    const h5 = document.createElement('h5');
    h5.className = 'mb-0';
    h5.innerHTML = title;
    header.appendChild(h5);

    const body = document.createElement('div');
    body.className = 'card-body';
    const canvas = document.createElement('canvas');
    canvas.id = canvasId;
    canvas.style.width = '100%';
    canvas.style.height = '300px';
    body.appendChild(canvas);

    const footer = document.createElement('div');
    footer.className = 'card-footer text-muted small';
    const row = document.createElement('div');
    row.className = 'row';

    legendItems.forEach((item) => {
        const colAuto = document.createElement('div');
        colAuto.className = 'col-auto';
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.backgroundColor = item.color;
        badge.textContent = item.label;
        colAuto.appendChild(badge);
        row.appendChild(colAuto);
    });

    if (footerText) {
        const colAuto = document.createElement('div');
        colAuto.className = 'col-auto';
        const span = document.createElement('span');
        span.className = 'text-muted';
        span.textContent = footerText;
        colAuto.appendChild(span);
        row.appendChild(colAuto);
    }

    footer.appendChild(row);
    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);
    col.appendChild(card);
    return col;
}

function createAstroConditionCard({ title, value, valueClass = '', badgeClass, badgeText, note, qualityClass = '' }) {
    const col = document.createElement('div');
    col.className = 'col mb-3';

    const card = document.createElement('div');
    card.className = `card h-100 astro-condition-card${qualityClass ? ' ' + qualityClass : ''}`;

    // Build stacked header: icon above, label below
    const cardTitle = document.createElement('div');
    cardTitle.className = 'card-body astro-card-header';
    const titleTemp = document.createElement('div');
    titleTemp.innerHTML = title;
    const iconEl = titleTemp.querySelector('i');
    const labelText = titleTemp.textContent.trim();
    if (iconEl) {
        iconEl.classList.remove('icon-inline');
        iconEl.classList.add('astro-card-icon');
        cardTitle.appendChild(iconEl);
    }
    const labelEl = document.createElement('div');
    labelEl.className = 'astro-card-label';
    labelEl.textContent = labelText;
    cardTitle.appendChild(labelEl);

    const body = document.createElement('div');
    body.className = 'card-body text-center';

    const main = document.createElement('div');
    main.className = `astro-main-value ${valueClass}`;
    main.textContent = value;

    const badge = document.createElement('div');
    badge.className = badgeClass;
    badge.textContent = badgeText;

    const noteNode = document.createElement('div');
    noteNode.className = 'fw-light fst-italic';
    noteNode.textContent = note;

    body.appendChild(main);
    body.appendChild(badge);
    body.appendChild(noteNode);

    card.appendChild(cardTitle);
    card.appendChild(body);
    col.appendChild(card);
    return col;
}

/**
 * Load comprehensive astrophotography weather analysis
 */
async function loadAstroWeather() {
    if (astroWeatherRequestInFlight) {
        return astroWeatherRequestInFlight;
    }

    astroWeatherRequestInFlight = (async () => {
    const container = document.getElementById('astro-weather-display');
    const loadingDiv = document.getElementById('astro-weather-loading');
    const errorDiv = document.getElementById('astro-weather-error');
    
    if (loadingDiv) loadingDiv.style.display = 'block';
    if (errorDiv) errorDiv.style.display = 'none';
    if (container) container.style.display = 'none';
    
    try {
        const currentLang = (typeof i18n !== 'undefined' && typeof i18n.getCurrentLanguage === 'function')
            ? i18n.getCurrentLanguage()
            : 'en';
        const data = await fetchJSONWithRetry(`/api/weather/astro-analysis?hours=24&lang=${encodeURIComponent(currentLang)}`, {}, {
            maxAttempts: 8,
            baseDelayMs: 1000,
            maxDelayMs: 15000,
            timeoutMs: 20000,
            shouldRetryData: (payload) => payload && payload.status === 'pending',
            onRetry: ({ reason, attempt, maxAttempts, waitMs }) => {
                if (!loadingDiv) return;
                const seconds = Math.max(1, Math.round(waitMs / 1000));
                const message = i18n.t('astro_weather.loading_details');
                updateAstroWeatherLoadingMessage(`${message} ${i18n.t('common.retrying_in', { seconds, attempt, maxAttempts })}`);
            }
        });

        if (data.status === 'pending') {
            throw new Error(i18n.t('weather.loading_astro_failed'));
        }
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        astroWeatherData = data;
        
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (container) container.style.display = 'block';
        
        // Render different sections
        renderCurrentAstroConditions(data.current_conditions);
        renderNightTimeline(data.hourly_data, data.location?.timezone);
        renderBestObservationPeriods(data.best_observation_periods);
        renderAstroWeatherCharts(data.hourly_data, data.location?.timezone);
        renderWeatherAlerts(data.weather_alerts, data.location?.timezone);
        
        // Load horizon graph separately (has its own API call)
        loadHorizonGraph();        

        const footerContainer = document.getElementById('astro-advanced-weather-main');
        const existingFooter = footerContainer ? footerContainer.querySelector('.sf-data-source') : null;
        if (existingFooter && existingFooter.parentNode) {
            existingFooter.parentNode.removeChild(existingFooter);
        }
        appendDataSourceFooter(footerContainer, {
            text: i18n.t('astro_weather.footer_source'),
            links: [
                { href: 'https://open-meteo.com/', label: 'Open-Meteo' }
            ]
        });
        
        //console.log('Astro weather data loaded:', data);
        
    } catch (error) {
        console.error('Error loading astro weather:', error);
        
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (errorDiv) {
            errorDiv.style.display = 'block';
            DOMUtils.clear(errorDiv);
            const col = document.createElement('div');
            col.className = 'col';
            const card = document.createElement('div');
            card.className = 'card h-100 bg-danger-subtle';
            const body = document.createElement('div');
            body.className = 'card-body';
            const title = document.createElement('h5');
            title.className = 'card-title';
            title.replaceChildren(DOMUtils.createIcon('bi bi-clouds', 'icon-inline'), document.createTextNode(` ${i18n.t('common.error')}`));
            const text = document.createElement('p');
            text.className = 'card-text';
            text.textContent = `${i18n.t('common.failed_to_load_element')}${error.message}`;
            body.appendChild(title);
            body.appendChild(text);
            card.appendChild(body);
            col.appendChild(card);
            errorDiv.appendChild(col);
        }
    } finally {
        astroWeatherRequestInFlight = null;
    }
    })();

    return astroWeatherRequestInFlight;
}

/**
 * Render current astrophotography conditions summary
 */
function renderCurrentAstroConditions(conditions) {
    const container = document.getElementById('astro-current-conditions');
    if (!container || !conditions) return;
    
    // Quality indicators
    const seeingQuality = getSeeingQualityText(conditions.seeing_pickering);
    const transparencyQuality = getTransparencyQualityText(conditions.transparency_score);
    const dewRiskColor = getDewRiskColor(conditions.dew_risk_level);
    const trackingQuality = getTrackingQualityText(conditions.tracking_stability_score);
    const cloudQuality = getCloudQualityText(conditions.cloud_discrimination);

    DOMUtils.clear(container);
    const cards = [
        createAstroConditionCard({
            title: `<i class="bi bi-eye icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.seeing')}`,
            value: `${conditions.seeing_pickering}/10`,
            badgeClass: `astro-quality-text quality-box ${seeingQuality.class}`,
            badgeText: seeingQuality.text,
            note: i18n.t('astro_weather.pickering_scale'),
            qualityClass: seeingQuality.class
        }),
        createAstroConditionCard({
            title: `<i class="bi bi-stars text-warning icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.transparency')}`,
            value: `${conditions.limiting_magnitude}m`,
            badgeClass: `astro-quality-text quality-box ${transparencyQuality.class}`,
            badgeText: transparencyQuality.text,
            note: i18n.t('astro_weather.limiting_magnitude'),
            qualityClass: transparencyQuality.class
        }),
        createAstroConditionCard({
            title: `<i class="bi bi-clouds icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.cloud_layers')}`,
            value: `${Math.round(conditions.cloud_discrimination)}%`,
            badgeClass: `astro-quality-text quality-box ${cloudQuality.class}`,
            badgeText: cloudQuality.text,
            note: i18n.t('astro_weather.discrimination_score'),
            qualityClass: cloudQuality.class
        }),
        createAstroConditionCard({
            title: `<i class="bi bi-droplet text-primary icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.dew_risk')}`,
            value: `${Math.round(conditions.dew_point_spread * 10) / 10}${i18n.t('units.temperature_celsius')}`,
            badgeClass: `astro-quality-text dew-box ${dewRiskColor.class}`,
            badgeText: `${dewRiskColor.text}`,
            note: i18n.t('astro_weather.temperature_spread'),
            qualityClass: dewRiskColor.class
        }),
        createAstroConditionCard({
            title: `<i class="bi bi-crosshair2 icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.tracking')}`,
            value: `${conditions.tracking_stability_score}%`,
            badgeClass: `astro-quality-text quality-box ${trackingQuality.class}`,
            badgeText: trackingQuality.text,
            note: i18n.t('astro_weather.wind_stability'),
            qualityClass: trackingQuality.class
        })
    ];
    cards.forEach(card => container.appendChild(card));
}

/**
 * Render the hourly night score timeline (sunset → sunrise)
 */
function renderNightTimeline(hourlyData, timezone) {
    const container = document.getElementById('night-timeline-display');
    const mainEl = document.getElementById('night-timeline-main');
    if (!container || !mainEl || !hourlyData || hourlyData.length === 0) return;

    const nowMs = Date.now();
    const cutoff = nowMs - 30 * 60 * 1000;

    // Sort all hourly data chronologically
    const allSorted = [...hourlyData].sort((a, b) => new Date(a.datetime) - new Date(b.datetime));

    // Find the first continuous night block (is_day === 0) at or after cutoff,
    // avoiding mixing tonight's tail with tomorrow's night.
    let nightStartIdx = -1, nightEndIdx = -1;
    for (let i = 0; i < allSorted.length; i++) {
        const h = allSorted[i];
        if (h.is_day !== 0 || new Date(h.datetime).getTime() < cutoff) continue;
        nightStartIdx = i;
        nightEndIdx = i;
        for (let j = i + 1; j < allSorted.length; j++) {
            if (allSorted[j].is_day !== 0) break;
            const gapMs = new Date(allSorted[j].datetime) - new Date(allSorted[j - 1].datetime);
            if (gapMs > 2 * 60 * 60 * 1000) break;
            nightEndIdx = j;
        }
        break;
    }

    mainEl.style.display = 'block';
    DOMUtils.clear(container);

    if (nightStartIdx === -1) {
        const msg = document.createElement('p');
        msg.className = 'text-muted fst-italic mb-0';
        msg.textContent = i18n.t('astro_weather.night_score_no_night');
        container.appendChild(msg);
        return;
    }

    // Extend 2 hours before and after the night block to show twilight context
    const extStart = Math.max(0, nightStartIdx - 2);
    const extEnd = Math.min(allSorted.length - 1, nightEndIdx + 2);
    const nightHours = allSorted.slice(extStart, extEnd + 1);

    const timeline = document.createElement('div');
    timeline.className = 'night-score-timeline';

    nightHours.forEach(h => {
        const hMs = new Date(h.datetime).getTime();
        const isNow = Math.abs(hMs - nowMs) < 60 * 60 * 1000;

        // Composite score 0–10 (same formula as best_observation_periods backend)
        const rawScore = (
            (h.seeing_pickering || 0) * 10 +
            (h.transparency_score || 0) +
            (h.cloud_discrimination || 0) +
            (h.tracking_stability_score || 0)
        ) / 4;
        const score = rawScore / 10;

        const qualityClass = score >= 8 ? 'quality-excellent'
            : score >= 6 ? 'quality-good'
            : score >= 4 ? 'quality-fair'
            : score >= 2 ? 'quality-poor'
            : 'quality-bad';

        const qualityLabel = score >= 8 ? i18n.t('common.quality_scale.excellent')
            : score >= 6 ? i18n.t('common.quality_scale.good')
            : score >= 4 ? i18n.t('common.quality_scale.fair')
            : i18n.t('common.quality_scale.poor');

        const scoreColorClass = score >= 6 ? 'text-success' : score >= 4 ? 'text-warning' : 'text-danger';

        const card = document.createElement('div');
        card.className = `card h-100 night-score-card${isNow ? ' night-score-card-now' : ''}`;

        const body = document.createElement('div');
        body.className = 'card-body p-1 text-center';

        const hourRow = document.createElement('div');
        hourRow.className = 'night-score-hour-row';

        const phaseIco = DOMUtils.createIcon(h.is_day === 1 ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill');
        phaseIco.className += h.is_day === 1 ? ' text-warning' : ' text-info';
        hourRow.appendChild(phaseIco);

        const hourEl = document.createElement('span');
        hourEl.className = 'fw-semibold night-score-hour';
        hourEl.textContent = formatTimeOnlyInTimezone(h.datetime, timezone || 'UTC');
        hourRow.appendChild(hourEl);

        body.appendChild(hourRow);

        const scoreEl = document.createElement('div');
        scoreEl.className = `night-score-value ${scoreColorClass}`;
        scoreEl.textContent = score.toFixed(1);
        body.appendChild(scoreEl);

        const qualBadge = document.createElement('div');
        qualBadge.className = `astro-quality-text quality-box ${qualityClass}`;
        qualBadge.textContent = qualityLabel;
        body.appendChild(qualBadge);

        const metricColor = (val) => val >= 80 ? 'text-success' : val >= 60 ? 'text-warning' : 'text-danger';
        const dewColor = (s) => s >= 70 ? 'text-success' : s >= 50 ? 'text-warning' : 'text-danger';

        const iconRow = document.createElement('div');
        iconRow.className = 'night-score-icons';
        [
            ['bi bi-eye', metricColor((h.seeing_pickering || 0) * 10), i18n.t('astro_weather.seeing')],
            ['bi bi-stars', metricColor(h.transparency_score || 0), i18n.t('astro_weather.transparency')],
            ['bi bi-clouds', metricColor(h.cloud_discrimination || 0), i18n.t('astro_weather.cloud_layers')],
            ['bi bi-droplet', dewColor(h.dew_risk_score || 0), i18n.t('astro_weather.dew_risk')],
            ['bi bi-crosshair2', metricColor(h.tracking_stability_score || 0), i18n.t('astro_weather.tracking')],
        ].forEach(([cls, color, title]) => {
            const ico = DOMUtils.createIcon(cls);
            ico.className += ` ${color}`;
            ico.title = title;
            iconRow.appendChild(ico);
        });

        body.appendChild(iconRow);
        card.appendChild(body);
        timeline.appendChild(card);
    });

    container.appendChild(timeline);
}

/**
 * Render best observation periods
 */
function renderBestObservationPeriods(periods, timezone) {
    const container = document.getElementById('astro-best-periods');
    if (!container) return;

    const mainContainer = document.getElementById('best-observation-periods-main');
    if (mainContainer) mainContainer.style.display = 'block';

    // Fake periods for testing
    /*
    periods = [
        {
            start: new Date(Date.now() + 1 * 60 * 60 * 1000).toISOString(),
            end: new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString(),
            duration_hours: 2,
            average_quality: 85.5
        },
        {
            start: new Date(Date.now() + 5 * 60 * 60 * 1000).toISOString(),
            end: new Date(Date.now() + 7 * 60 * 60 * 1000).toISOString(),
            duration_hours: 2,
            average_quality: 78.2
        }
    ];
    //*/
    
    if (!periods || periods.length === 0) {
        DOMUtils.clear(container);
        const row = document.createElement('div');
        row.className = 'row row-cols-1';
        const col = document.createElement('div');
        col.className = 'col';
        const card = document.createElement('div');
        card.className = 'card h-100';
        const header = document.createElement('div');
        header.className = 'card-header';
        const headerTitle = document.createElement('h5');
        headerTitle.className = 'mb-0';
        headerTitle.textContent = i18n.t('astro_weather.best_periods_description');
        header.appendChild(headerTitle);
        const contentBody = document.createElement('div');
        contentBody.className = 'card-body text-center';
        const icon = document.createElement('h1');
        icon.replaceChildren(DOMUtils.createIcon('bi bi-emoji-frown'));
        icon.className = 'astro-icon text-center best-period-empty-icon text-warning';
        const text = document.createElement('div');
        text.className = 'text-center best-period-empty-text fw-light fst-italic';
        text.textContent = i18n.t('astro_weather.no_observation_periods');
        contentBody.appendChild(icon);
        contentBody.appendChild(text);
        card.appendChild(header);
        card.appendChild(contentBody);
        col.appendChild(card);
        row.appendChild(col);
        container.appendChild(row);
        return;
    }

    DOMUtils.clear(container);
    const row = document.createElement('div');
    row.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-3 row-cols-xl-4 g-3';

    periods.forEach((period) => {
        const startTime = new Date(period.start);
        const endTime = new Date(period.end);

        const col = document.createElement('div');
        col.className = 'col';
        const card = document.createElement('div');
        card.className = 'card h-100 best-period-card';
        const header = document.createElement('div');
        header.className = 'card-header fw-bold';
        const h5 = document.createElement('h5');
        h5.className = 'card-title mb-0';
        h5.textContent = `${formatTimeOnlyInTimezone(period.start, timezone || 'UTC')} - ${formatTimeOnlyInTimezone(period.end, timezone || 'UTC')}`;
        const h6 = document.createElement('h6');
        h6.className = 'card-subtitle mt-1 mb-0 text-muted';
        const startDate = startTime.toLocaleDateString(navigator.language, {month: 'short', day: 'numeric', timeZone: timezone || 'UTC'});
        const endDate = endTime.toLocaleDateString(navigator.language, {month: 'short', day: 'numeric', timeZone: timezone || 'UTC'});
        const startDateKey = startTime.toLocaleDateString('en-CA', {timeZone: timezone || 'UTC'});
        const endDateKey = endTime.toLocaleDateString('en-CA', {timeZone: timezone || 'UTC'});
        h6.textContent = startDateKey !== endDateKey ? `${startDate} - ${endDate}` : startDate;
        header.appendChild(h5);
        header.appendChild(h6);

        const list = document.createElement('ul');
        list.className = 'list-group list-group-flush';

        const durationItem = document.createElement('li');
        durationItem.className = 'list-group-item d-flex justify-content-between align-items-center';
        const durationLabel = document.createElement('span');
        durationLabel.innerHTML = `<i class="bi bi-clock-history icon-inline" aria-hidden="true"></i>${i18n.t('common.duration')}`;
        durationItem.appendChild(durationLabel);
        const durationBadge = document.createElement('span');
        durationBadge.className = 'fw-bold';
        durationBadge.textContent = `${period.duration_hours.toFixed(1)}h`;
        durationItem.appendChild(durationBadge);

        const qualityItem = document.createElement('li');
        qualityItem.className = 'list-group-item d-flex justify-content-between align-items-center';
        const qualityLabel = document.createElement('span');
        qualityLabel.innerHTML = `<i class="bi bi-stars icon-inline" aria-hidden="true"></i>${i18n.t('common.quality')}`;
        qualityItem.appendChild(qualityLabel);
        const qualityBadge = document.createElement('span');
        qualityBadge.className = 'fw-bold';
        qualityBadge.textContent = `${period.average_quality.toFixed(1)}%`;
        qualityItem.appendChild(qualityBadge);

        list.appendChild(durationItem);
        list.appendChild(qualityItem);
        card.appendChild(header);
        card.appendChild(list);
        col.appendChild(card);
        row.appendChild(col);
    });

    container.appendChild(row);
}

/**
 * Render astrophotography weather charts
 */
function renderAstroWeatherCharts(hourlyData, timezone) {
    if (!hourlyData || hourlyData.length === 0) return;
    
    const labels = hourlyData.map(item => formatTimeOnlyInTimezone(item.datetime, timezone || 'UTC'));
    
    // Seeing and Transparency Chart
    renderSeeingTransparencyChart(labels, hourlyData);
    
    // Cloud Layers Chart  
    renderCloudLayersChart(labels, hourlyData);
    
    // Dew Point and Tracking Chart
    renderDewTrackingChart(labels, hourlyData);
}

/**
 * Render seeing and transparency chart
 */
function renderSeeingTransparencyChart(labels, data) {
    const container = document.getElementById('astro-seeing-chart-container');
    if (!container) return;
    
    // Destroy existing chart
    destroyAstroWeatherCharts();
    
    const seeingData = data.map(item => item.seeing_pickering * 10); // Convert to percentage scale
    const transparencyData = data.map(item => item.transparency_score);
    
    DOMUtils.clear(container);
    container.appendChild(createAstroChartShell(`<i class="bi bi-eye icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.chart_seeing_title')}` , 'astro-seeing-chart', [
        { label: i18n.t('astro_weather.seeing_label'), color: '#3b82f6' },
        { label: i18n.t('astro_weather.transparency_label'), color: '#a855f7' }
    ], i18n.t('astro_weather.quality_score_label')));
    
    // Render chart
    const ctx = document.getElementById('astro-seeing-chart');
    if (!ctx || typeof ctx.getContext !== 'function') return;
    const ctx2d = ctx.getContext('2d');
    if (!ctx2d) return;

    window.astroSeeingChart = new Chart(ctx2d, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: i18n.t('astro_weather.seeing_label_x10'),
                    data: seeingData,
                    borderColor: 'rgb(59, 130, 246)',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 3,
                    tension: 0.4,
                    yAxisID: 'y'
                },
                {
                    label: i18n.t('astro_weather.transparency_label'),
                    data: transparencyData,
                    borderColor: 'rgb(168, 85, 247)',
                    backgroundColor: 'rgba(168, 85, 247, 0.1)',
                    borderWidth: 3,
                    tension: 0.4,
                    yAxisID: 'y'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    display: true,
                    title: {
                        display: true,
                        text: i18n.t('common.time_label')
                    }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: {
                        display: true,
                        text: i18n.t('astro_weather.quality_score_label')
                    },
                    min: 0,
                    max: 105,
                    ticks: {
                        stepSize: 20,
                        callback: function(value) {
                            if (value === 105) {
                                return '';
                            }
                            return value + '%';
                        }
                    },
                    afterBuildTicks: function(axis) {
                        axis.ticks = [0, 20, 40, 60, 80, 100, 105].map(value => ({ value }));
                    }
                }
            }
        }
    });
}

/**
 * Render cloud layers discrimination chart
 */
function renderCloudLayersChart(labels, data) {
    const container = document.getElementById('astro-clouds-chart-container');
    if (!container) return;
    
    // Destroy existing chart
    if (window.astroCloudsChart) {
        window.astroCloudsChart.destroy();
        window.astroCloudsChart = null;
    }
    
    const highCloudImpact = data.map(item => item.high_cloud_impact);
    const midCloudImpact = data.map(item => item.mid_cloud_impact);
    const lowCloudImpact = data.map(item => item.low_cloud_impact);
    
    DOMUtils.clear(container);
    container.appendChild(createAstroChartShell(`<i class="bi bi-clouds icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.chart_cloud_title')}`, 'astro-clouds-chart', [
        { label: i18n.t('astro_weather.high_cloud_impact'), color: '#22c55e' },
        { label: i18n.t('astro_weather.mid_cloud_impact'), color: '#fbbf24' },
        { label: i18n.t('astro_weather.low_cloud_impact'), color: '#ef4444' }
    ]));
    
    // Render chart
    const ctx = document.getElementById('astro-clouds-chart');
    if (!ctx || typeof ctx.getContext !== 'function') return;
    const ctx2d = ctx.getContext('2d');
    if (!ctx2d) return;

    window.astroCloudsChart = new Chart(ctx2d, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: i18n.t('astro_weather.high_cloud_impact'),
                    data: highCloudImpact,
                    borderColor: 'rgb(34, 197, 94)',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderWidth: 2,
                    tension: 0.4
                },
                {
                    label: i18n.t('astro_weather.mid_cloud_impact'),
                    data: midCloudImpact,
                    borderColor: 'rgb(251, 191, 36)',
                    backgroundColor: 'rgba(251, 191, 36, 0.1)',
                    borderWidth: 2,
                    tension: 0.4
                },
                {
                    label: i18n.t('astro_weather.low_cloud_impact'),
                    data: lowCloudImpact,
                    borderColor: 'rgb(239, 68, 68)',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    borderWidth: 2,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    display: true,
                    title: {
                        display: true,
                        text: i18n.t('common.time_label')
                    }
                },
                y: {
                    display: true,
                    title: {
                        display: true,
                        text: i18n.t('astro_weather.chart_cloud_impact')
                    },
                    min: 0,
                    max: 105,
                    ticks: {
                        stepSize: 20,
                        callback: function(value) {
                            if (value === 105) {
                                return '';
                            }
                            return value + '%';
                        }
                    },
                    afterBuildTicks: function(axis) {
                        axis.ticks = [0, 20, 40, 60, 80, 100, 105].map(value => ({ value }));
                    }
                }
            }
        }
    });
}

/**
 * Render dew point and tracking stability chart
 */
function renderDewTrackingChart(labels, data) {
    const container = document.getElementById('astro-conditions-chart-container');
    if (!container) return;

    const mainContainer = document.getElementById('astro-advanced-weather-main');
    if (mainContainer) mainContainer.style.display = 'block';
    
    // Destroy existing chart
    if (window.astroConditionsChart) {
        window.astroConditionsChart.destroy();
        window.astroConditionsChart = null;
    }
    
    const dewRiskScore = data.map(item => item.dew_risk_score);
    const trackingScore = data.map(item => item.tracking_stability_score);
    
    DOMUtils.clear(container);
    container.appendChild(createAstroChartShell(`<i class="bi bi-droplet icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.chart_dew_tracking_title')}`, 'astro-conditions-chart', [
        { label: i18n.t('astro_weather.dew_label'), color: '#06b6d4' },
        { label: i18n.t('astro_weather.tracking_stability_label'), color: '#f56565' }
    ], i18n.t('astro_weather.score_100_label')));
    
    // Render chart
    const ctx = document.getElementById('astro-conditions-chart');
    if (!ctx || typeof ctx.getContext !== 'function') return;
    const ctx2d = ctx.getContext('2d');
    if (!ctx2d) return;

    window.astroConditionsChart = new Chart(ctx2d, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: i18n.t('astro_weather.dew_label'),
                    data: dewRiskScore,
                    borderColor: 'rgb(6, 182, 212)',
                    backgroundColor: 'rgba(6, 182, 212, 0.1)',
                    borderWidth: 3,
                    tension: 0.4
                },
                {
                    label: i18n.t('astro_weather.tracking_stability_label'),
                    data: trackingScore,
                    borderColor: 'rgb(245, 101, 101)',
                    backgroundColor: 'rgba(245, 101, 101, 0.1)',
                    borderWidth: 3,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    display: true,
                    title: {
                        display: true,
                        text: i18n.t('common.time_label')
                    }
                },
                y: {
                    display: true,
                    title: {
                        display: true,
                        text: i18n.t('astro_weather.score_100_label')
                    },
                    min: 0,
                    max: 105,
                    ticks: {
                        stepSize: 20,
                        callback: function(value) {
                            if (value === 105) {
                                return '';
                            }
                            return value + '%';
                        }
                    },
                    afterBuildTicks: function(axis) {
                        axis.ticks = [0, 20, 40, 60, 80, 100, 105].map(value => ({ value }));
                    }
                }
            }
        }
    });
}

/**
 * Render weather alerts for astrophotography
 */
function renderWeatherAlerts(alerts, timezone) {
    const container = document.getElementById('astro-weather-alerts');
    if (!container) return;

    const mainContainer = document.getElementById('astro-weather-alerts-main');
    if (mainContainer) mainContainer.style.display = 'block';
    
    if (!alerts || alerts.length === 0) {
        DOMUtils.clear(container);
        const alert = document.createElement('div');
        alert.className = 'alert alert-success';
        alert.setAttribute('role', 'alert');
        const title = document.createElement('div');
        title.className = 'fw-bold';
        title.replaceChildren(DOMUtils.createIcon('bi bi-check-circle-fill text-success', 'icon-inline'), document.createTextNode(` ${i18n.t('weather_alerts.no_astro_alerts')}`));
        alert.appendChild(title);
        container.appendChild(alert);
        return;
    }

    DOMUtils.clear(container);
    const intro = document.createElement('div');
    intro.className = 'mb-2';
    intro.textContent = i18n.t('weather_alerts.conditions_next_6_hours');
    container.appendChild(intro);

    const list = document.createElement('div');
    list.className = 'astro-alerts-list';

    alerts.forEach((alertData) => {
        const alert = document.createElement('div');
        alert.className = `alert alert-${alertData.severity === 'HIGH' ? 'danger' : 'warning'}`;
        alert.setAttribute('role', 'alert');

        const title = document.createElement('div');
        title.className = 'fw-bold';
        title.replaceChildren(DOMUtils.createIcon(getSeverityIcon(alertData.severity), 'icon-inline'), document.createTextNode(` ${getWeatherAlertTypeLabel(alertData.type)} ${formatTimeOnlyInTimezone(alertData.time, timezone || 'UTC')}`));

        const message = document.createElement('div');
        message.textContent = alertData.message;

        alert.appendChild(title);
        alert.appendChild(message);
        list.appendChild(alert);
    });

    container.appendChild(list);
}

/**
 * Helper functions for quality assessments
 */

function getSeeingQualityText(seeingValue) {
    if (seeingValue >= 8) return { text: i18n.t('common.quality_scale.excellent'), class: 'quality-excellent' };
    if (seeingValue >= 6) return { text: i18n.t('common.quality_scale.good'), class: 'quality-good' };
    if (seeingValue >= 4) return { text: i18n.t('common.quality_scale.fair'), class: 'quality-fair' };
    return { text: i18n.t('common.quality_scale.poor'), class: 'quality-poor' };
}

function getTransparencyQualityText(transparencyValue) {
    if (transparencyValue >= 80) return { text: i18n.t('common.quality_scale.excellent'), class: 'quality-excellent' };
    if (transparencyValue >= 60) return { text: i18n.t('common.quality_scale.good'), class: 'quality-good' };
    if (transparencyValue >= 40) return { text: i18n.t('common.quality_scale.fair'), class: 'quality-fair' };
    return { text: i18n.t('common.quality_scale.poor'), class: 'quality-poor' };
}

function getCloudQualityText(cloudValue) {
    if (cloudValue >= 80) return { text: i18n.t('common.quality_scale.excellent'), class: 'quality-excellent' };
    if (cloudValue >= 60) return { text: i18n.t('common.quality_scale.good'), class: 'quality-good' };
    if (cloudValue >= 40) return { text: i18n.t('common.quality_scale.fair'), class: 'quality-fair' };
    return { text: i18n.t('common.quality_scale.poor'), class: 'quality-poor' };
}

function getTrackingQualityText(trackingValue) {
    if (trackingValue >= 80) return { text: i18n.t('common.quality_scale.excellent'), class: 'quality-excellent' };
    if (trackingValue >= 60) return { text: i18n.t('common.quality_scale.good'), class: 'quality-good' };
    if (trackingValue >= 40) return { text: i18n.t('common.quality_scale.fair'), class: 'quality-fair' };
    return { text: i18n.t('common.quality_scale.poor'), class: 'quality-poor' };
}

function getDewRiskColor(riskLevel) {
    switch (riskLevel) {
        case 'MINIMAL': return { text: i18n.t('common.quality_scale.minimal'), class: 'dew-minimal' };
        case 'LOW': return { text: i18n.t('common.quality_scale.low'), class: 'dew-low' };
        case 'MODERATE': return { text: i18n.t('common.quality_scale.moderate'), class: 'dew-moderate' };
        case 'HIGH': return { text: i18n.t('common.quality_scale.high'), class: 'dew-high' };
        case 'CRITICAL': return { text: i18n.t('common.quality_scale.critical'), class: 'dew-critical' };
        default: return { text: i18n.t('common.quality_scale.unknown'), class: 'dew-unknown' };
    }
}

function getSeverityIcon(severity) {
    switch (severity) {
        case 'HIGH': return 'bi bi-circle-fill text-danger';
        case 'MEDIUM': return 'bi bi-circle-fill text-warning';
        case 'LOW': return 'bi bi-circle-fill text-success';
        default: return 'bi bi-info-circle';
    }
}

function getWeatherAlertTypeLabel(type) {
    const keyMap = {
        DEW_WARNING: 'weather_alerts.alert_dew_warning',
        WIND_WARNING: 'weather_alerts.alert_wind_warning',
        SEEING_WARNING: 'weather_alerts.alert_seeing_warning',
        TRANSPARENCY_WARNING: 'weather_alerts.alert_transparency_warning',
    };
    const key = keyMap[type];
    if (key) {
        return i18n.t(key);
    }
    return String(type || '').replaceAll('_', ' ');
}

/**
 * Auto-refresh functionality for astro weather
 */
function startAstroWeatherAutoRefresh() {
    // Refresh every 10 minutes
    astroWeatherUpdateInterval = setInterval(loadAstroWeather, 600000);
}

/**
 * Initialize astrophotography weather module
 */
function initAstroWeather() {
    // Load initial data
    loadAstroWeather();
    
    // Start auto-refresh
    startAstroWeatherAutoRefresh();
    
    //console.log('Astrophotography weather module initialized');
}

// Export functions for global use
window.loadAstroWeather = loadAstroWeather;
window.initAstroWeather = initAstroWeather;