// ======================
// Weather
// ======================


function createChartShell(title, canvasId, legendItems = [], footerText = '') {
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
        const col = document.createElement('div');
        col.className = 'col-auto';
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.backgroundColor = item.color;
        badge.textContent = item.label;
        col.appendChild(badge);
        row.appendChild(col);
    });

    if (footerText) {
        const col = document.createElement('div');
        col.className = 'col-auto';
        const text = document.createElement('span');
        text.className = 'text-muted';
        text.textContent = footerText;
        col.appendChild(text);
        row.appendChild(col);
    }

    footer.appendChild(row);

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);
    return card;
}

//Load Weather forecast
async function loadWeather() {
    const container = document.getElementById('weather-display');
    const containerLocation = document.getElementById('weather-location');
    
    const data = await fetchJSONWithUI('/api/weather/forecast', container, i18n.t('weather.loading_text'), {
        wrapInCard: true,
        cardTitle: i18n.t('weather.loading_title'),
        cardIcon: 'bi-cloud-sun'
    });
    if (!data) return;
    
    //console.log('Weather forecast data:', data);
    
    // Clear containers
    clearContainer(containerLocation);
    clearContainer(container);

    // If data location is available
    if (data.location) {
        const nameCol = document.createElement('div');
        nameCol.className = 'col mb-3';
        const nameCard = document.createElement('div');
        nameCard.className = 'card h-100';
        const nameBody = document.createElement('div');
        nameBody.className = 'card-body';
        const nameP = document.createElement('p');
        nameP.className = 'card-text';
        const nameStrong = document.createElement('strong');
        nameStrong.textContent = data.location.name;
        nameP.appendChild(nameStrong);
        nameBody.appendChild(nameP);
        nameCard.appendChild(nameBody);
        nameCol.appendChild(nameCard);

        const coordCol = document.createElement('div');
        coordCol.className = 'col mb-3';
        const coordCard = document.createElement('div');
        coordCard.className = 'card h-100';
        const coordBody = document.createElement('div');
        coordBody.className = 'card-body';
        const coordP = document.createElement('p');
        coordP.className = 'card-text';
        coordP.textContent = `${i18n.t('weather.latitude')}${data.location.latitude.toFixed(2)}${i18n.t('units.degrees')}\n${i18n.t('weather.longitude')}${data.location.longitude.toFixed(2)}${i18n.t('units.degrees')}\n${i18n.t('weather.elevation')}${data.location.elevation} ${i18n.t('units.meters')}`;
        coordP.style.whiteSpace = 'pre-line';
        coordBody.appendChild(coordP);
        coordCard.appendChild(coordBody);
        coordCol.appendChild(coordCard);

        const tzCol = document.createElement('div');
        tzCol.className = 'col mb-3';
        const tzCard = document.createElement('div');
        tzCard.className = 'card h-100';
        const tzBody = document.createElement('div');
        tzBody.className = 'card-body';
        const tzP = document.createElement('p');
        tzP.className = 'card-text';
        tzP.textContent = `${i18n.t('weather.timezone')}${data.location.timezone}`;
        tzBody.appendChild(tzP);
        tzCard.appendChild(tzBody);
        tzCol.appendChild(tzCard);

        containerLocation.appendChild(nameCol);
        containerLocation.appendChild(coordCol);
        containerLocation.appendChild(tzCol);

        // Append Bortle/SQM to the timezone card if configured (non-blocking)
        fetchJSON('/api/skyquality').then(sq => {
            if (sq && sq.bortle != null) {
                const sqP = document.createElement('p');
                sqP.className = 'card-text mt-2';
                const bortleLabel = i18n.t(`settings.sky_quality_bortle_${sq.bortle}`);
                let sqText = `${i18n.t('weather.bortle')}${bortleLabel}`;
                if (sq.sqm != null) {
                    sqText += `\n${i18n.t('weather.sqm')}${sq.sqm} mag/arcsec²`;
                }
                sqP.textContent = sqText;
                sqP.style.whiteSpace = 'pre-line';
                tzBody.appendChild(sqP);
            }
        }).catch(() => {});
    }

    // if forecast list is available
    if (data.hourly && data.hourly.length > 0) {
        const now = Date.now();
        const configuredTimezone = data?.location?.timezone || 'UTC';
        // We receive up to 12 hours of data; skip entries that are already in the past
        data.hourly.filter(forecast => new Date(forecast.date).getTime() >= now).forEach(forecast => {
            const cloudCover = Math.round(forecast.cloud_cover);
            const cloudCoverL = Math.round(forecast.cloud_cover_low);
            const cloudCoverM = Math.round(forecast.cloud_cover_mid);
            const cloudCoverH = Math.round(forecast.cloud_cover_high);
            const humidity = Math.round(forecast.relative_humidity_2m);
            const temp = forecast.temperature_2m.toFixed(1);
            const pressure = Math.round(forecast.surface_pressure);
            const windSpeed = Math.round(forecast.wind_speed_10m);
            const dewPoint = forecast.dew_point_2m.toFixed(1);
            const condition = forecast.condition.toFixed(1);

            // Determine observation quality based on condition
            let quality = '';
            let qualityClass = '';
            if (condition >= 90) {
                quality = i18n.t('common.quality_scale.excellent');
                qualityClass = 'quality-excellent';
            } else if (condition >= 70) {
                quality = i18n.t('common.quality_scale.good');
                qualityClass = 'quality-good';
            } else if (condition >= 50) {
                quality = i18n.t('common.quality_scale.fair');
                qualityClass = 'quality-fair';
            } else if (condition > 30) {
                quality = i18n.t('common.quality_scale.poor');
                qualityClass = 'quality-poor';
            } else {
                quality = i18n.t('common.quality_scale.bad');
                qualityClass = 'quality-bad';
            }

            const item = document.createElement('div');
            item.className = 'col mb-3';
            const card = document.createElement('div');
            card.className = 'card h-100';

            // Header: time on the left, quality label on the right
            const cardHeader = document.createElement('div');
            cardHeader.className = `card-header d-flex justify-content-between align-items-center quality-box ${qualityClass}`;
            const timeEl = document.createElement('span');
            timeEl.className = 'fw-semibold';
            timeEl.textContent = formatTimeOnlyInTimezone(forecast.date, configuredTimezone);
            const qualityEl = document.createElement('span');
            qualityEl.className = 'weather-quality-label';
            qualityEl.textContent = quality;
            cardHeader.appendChild(timeEl);
            cardHeader.appendChild(qualityEl);

            const cardBody = document.createElement('div');
            cardBody.className = 'card-body p-2';

            // 2-column metric grid
            const metricGrid = document.createElement('div');
            metricGrid.className = 'weather-metric-grid';
            metricGrid.appendChild(createForecastMetricCell('bi-thermometer-half', 'text-danger', `${temp}${i18n.t('units.temperature_celsius')}`, i18n.t('weather.temperature')));
            metricGrid.appendChild(createForecastMetricCell('bi-droplet', 'text-primary', `${humidity}${i18n.t('units.percent')}`, i18n.t('weather.humidity')));
            metricGrid.appendChild(createForecastMetricCell('bi-droplet-half', 'text-primary', `${dewPoint}${i18n.t('units.temperature_celsius')}`, i18n.t('weather.dew_point')));
            metricGrid.appendChild(createForecastMetricCell('bi-speedometer2', '', `${pressure} ${i18n.t('units.hpa')}`, i18n.t('weather.pressure')));
            metricGrid.appendChild(createForecastMetricCell('bi-wind', '', `${windSpeed} ${i18n.t('units.wind_speed_kmh')}`, i18n.t('weather.wind')));
            metricGrid.appendChild(createForecastMetricCell('bi-clouds', '', `${cloudCover}${i18n.t('units.percent')}`, i18n.t('weather.cloud_cover')));

            // Cloud layer breakdown
            const cloudLayers = document.createElement('div');
            cloudLayers.className = 'weather-cloud-layers';
            [
                [i18n.t('weather.low'),  cloudCoverL],
                [i18n.t('weather.mid'),  cloudCoverM],
                [i18n.t('weather.high'), cloudCoverH],
            ].forEach(([label, val]) => {
                const s = document.createElement('span');
                s.className = 'weather-cloud-layer-item';
                s.textContent = `${label} ${val}${i18n.t('units.percent')}`;
                cloudLayers.appendChild(s);
            });

            cardBody.appendChild(metricGrid);
            cardBody.appendChild(cloudLayers);
            card.appendChild(cardHeader);
            card.appendChild(cardBody);
            item.appendChild(card);
            container.appendChild(item);
        });
    }

    const weatherSection = container ? container.closest('.bg-sub-container') : null;
    if (weatherSection) {
        const existingFooter = weatherSection.querySelector('.js-weather-data-source-footer');
        if (existingFooter && existingFooter.parentNode) {
            existingFooter.parentNode.removeChild(existingFooter);
        }
        const footer = createDataSourceFooter({
            text: i18n.t('weather.footer_source'),
            links: [
                { href: 'https://open-meteo.com/', label: 'Open-Meteo' }
            ]
        });
        footer.classList.add('js-weather-data-source-footer');
        weatherSection.appendChild(footer);
    }
}

// Global chart instances
let cloudConditionsChartInstance = null;
let seeingConditionsChartInstance = null;
let astroChartsRequestInFlight = null;


function updateAstroChartsLoadingMessage(message) {
    const loadingDiv = document.getElementById('astro-charts-loading');
    if (!loadingDiv) return;
    loadingDiv.replaceChildren(DOMUtils.createSpinnerWrapper(message));
}


function destroyAstronomicalCharts() {
    if (cloudConditionsChartInstance) {
        cloudConditionsChartInstance.destroy();
        cloudConditionsChartInstance = null;
    }
    if (seeingConditionsChartInstance) {
        seeingConditionsChartInstance.destroy();
        seeingConditionsChartInstance = null;
    }
}

//Load Astronomical Charts
async function loadAstronomicalCharts() {
    if (astroChartsRequestInFlight) {
        return astroChartsRequestInFlight;
    }

    astroChartsRequestInFlight = (async () => {
    const loadingDiv = document.getElementById('astro-charts-loading');
    const containerDiv = document.getElementById('astro-charts-container');
    const errorDiv = document.getElementById('astro-charts-error');
    
    // Show loading, hide others
    loadingDiv.style.display = 'block';
    updateAstroChartsLoadingMessage(i18n.t('weather.loading_astro_chart'));
    errorDiv.style.display = 'none';
    
    try {
        //Fake error
        //throw('Fake');

        const data = await fetchJSONWithRetry('/api/weather/forecast', {}, {
            maxAttempts: 6,
            baseDelayMs: 1000,
            maxDelayMs: 12000,
            timeoutMs: 15000,
            shouldRetryData: (payload) => payload && payload.status === 'pending',
            onRetry: ({ reason, attempt, maxAttempts, waitMs }) => {
                const seconds = Math.max(1, Math.round(waitMs / 1000));
                const message = i18n.t('weather.loading_astro_chart');
                updateAstroChartsLoadingMessage(`${message} ${i18n.t('common.retrying_in', { seconds, attempt, maxAttempts })}`);
            }
        });

        if (data.status === 'pending') {
            throw new Error(i18n.t('weather.loading_astro_failed'));
        }

        //console.log(data);
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        // Hide loading, show charts
        loadingDiv.style.display = 'none';
        
        // Extract data for charts - skip entries already in the past
        const now = Date.now();
        const configuredTimezone = data?.location?.timezone || 'UTC';
        const futureHourly = data.hourly.filter(item => new Date(item.date).getTime() >= now);

        // Extract all chart data arrays in a single pass over futureHourly
        const labels = [], condition = [], cloudless = [], cloudHigh = [], cloudMid = [],
              cloudLow = [], calm = [], fog = [], seeing = [], transparency = [],
              liftedIndex = [], precipitation = [];
        for (const item of futureHourly) {
            labels.push(formatTimeOnlyInTimezone(item.date, configuredTimezone));
            condition.push(item.condition);
            cloudless.push(item.cloudless);
            cloudHigh.push(item.cloudless_high);
            cloudMid.push(item.cloudless_mid);
            cloudLow.push(item.cloudless_low);
            calm.push(item.calm);
            fog.push(item.fog);
            seeing.push(item.seeing);
            transparency.push(item.transparency);
            liftedIndex.push(item.lifted_index);
            precipitation.push(item.precipitation);
        }
        
        // Destroy existing charts if they exist
        destroyAstronomicalCharts();
        
        // Chart 1: Cloud Conditions & Wind
        const container1 = document.getElementById('cloudConditionsChartContainer');
        if (container1) {
            DOMUtils.clear(container1);
            container1.appendChild(createChartShell(`<i class="bi bi-clouds icon-inline" aria-hidden="true"></i>${i18n.t('weather.chart_cloud_title')}`, 'cloudConditionsChart', [
                { label: i18n.t('weather.chart_cloudless'), color: '#22c55e' },
                { label: i18n.t('weather.chart_condition'), color: '#ef4444' },
                { label: i18n.t('weather.chart_fog'), color: '#808080' }
            ], i18n.t('weather.chart_percentage')));
        }
        
        const ctx1 = document.getElementById('cloudConditionsChart');
        if (!ctx1) return;
        const ctx1_2d = ctx1.getContext('2d');
        if (!ctx1_2d) return;
        cloudConditionsChartInstance = new Chart(ctx1_2d, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: i18n.t('weather.chart_fog'),
                        data: fog,
                        type: 'bar',
                        backgroundColor: 'rgba(128, 128, 128, 0.3)',
                        borderColor: 'rgba(128, 128, 128, 0.5)',
                        borderWidth: 1,
                        order: 10,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_condition'),
                        data: condition,
                        borderColor: 'rgb(239, 68, 68)',
                        backgroundColor: 'rgba(239, 68, 68, 0.1)',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        fill: false,
                        tension: 0.4,
                        order: 1,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_cloudless'),
                        data: cloudless,
                        borderColor: 'rgb(34, 197, 94)',
                        backgroundColor: 'rgba(34, 197, 94, 0.1)',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.4,
                        order: 2,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_cloudless_high'),
                        data: cloudHigh,
                        borderColor: 'rgb(74, 222, 128)',
                        backgroundColor: 'rgba(74, 222, 128, 0.1)',
                        borderWidth: 2,
                        borderDash: [2, 2],
                        fill: false,
                        tension: 0.4,
                        order: 3,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_cloudless_mid'),
                        data: cloudMid,
                        borderColor: 'rgb(134, 239, 172)',
                        backgroundColor: 'rgba(134, 239, 172, 0.1)',
                        borderWidth: 2,
                        borderDash: [2, 2],
                        fill: false,
                        tension: 0.4,
                        order: 4,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_cloudless_low'),
                        data: cloudLow,
                        borderColor: 'rgb(187, 247, 208)',
                        backgroundColor: 'rgba(187, 247, 208, 0.1)',
                        borderWidth: 2,
                        borderDash: [2, 2],
                        fill: false,
                        tension: 0.4,
                        order: 5,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_calm'),
                        data: calm,
                        borderColor: 'rgb(220, 38, 38)',
                        backgroundColor: 'rgba(220, 38, 38, 0.1)',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.4,
                        order: 6,
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
                    },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                label += Math.round(context.parsed.y * 10) / 10 + '%';
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: {
                            display: true,
                            text: i18n.t('weather.chart_percentage'),
                        },
                        min: 0,
                        max: 105,
                        ticks: {
                            stepSize: 20,
                            callback: function(value) {
                                if (value === 105) {
                                    return '';
                                }
                                return value + i18n.t('units.percent');
                            }
                        },
                        afterBuildTicks: function(axis) {
                            axis.ticks = [0, 20, 40, 60, 80, 100, 105].map(value => ({ value }));
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: i18n.t('common.time_label'),
                        }
                    }
                }
            }
        });
        
        // Chart 2: Seeing & Atmospheric Conditions
        const container2 = document.getElementById('seeingConditionsChartContainer');
        if (container2) {
            DOMUtils.clear(container2);
            container2.appendChild(createChartShell(`<i class="bi bi-eye icon-inline" aria-hidden="true"></i>${i18n.t('weather.chart_seeing_title')}`, 'seeingConditionsChart', [
                { label: i18n.t('weather.chart_fog'), color: '#808080' },
                { label: i18n.t('weather.chart_condition'), color: '#ef4444' },
                { label: i18n.t('weather.chart_seeing'), color: '#f97316' },
                { label: i18n.t('weather.chart_transparency'), color: '#1e3a8a' },
                { label: i18n.t('weather.chart_lifted_index'), color: '#06b6d4' },
                { label: i18n.t('weather.chart_precipitation'), color: '#2563eb' }
            ], ''));
        }
        
        const ctx2 = document.getElementById('seeingConditionsChart');
        if (!ctx2) return;
        const ctx2_2d = ctx2.getContext('2d');
        if (!ctx2_2d) return;
        seeingConditionsChartInstance = new Chart(ctx2_2d, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: i18n.t('weather.chart_fog'),
                        data: fog,
                        type: 'bar',
                        backgroundColor: 'rgba(128, 128, 128, 0.3)',
                        borderColor: 'rgba(128, 128, 128, 0.5)',
                        borderWidth: 1,
                        order: 10,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_condition'),
                        data: condition,
                        borderColor: 'rgb(239, 68, 68)',
                        backgroundColor: 'rgba(239, 68, 68, 0.1)',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        fill: false,
                        tension: 0.4,
                        order: 1,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_seeing'),
                        data: seeing,
                        borderColor: 'rgb(249, 115, 22)',
                        backgroundColor: 'rgba(249, 115, 22, 0.1)',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.4,
                        order: 2,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_transparency'),
                        data: transparency,
                        borderColor: 'rgb(30, 58, 138)',
                        backgroundColor: 'rgba(30, 58, 138, 0.1)',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.4,
                        order: 3,
                        yAxisID: 'y'
                    },
                    {
                        label: i18n.t('weather.chart_lifted_index'),
                        data: liftedIndex,
                        borderColor: 'rgb(6, 182, 212)',
                        backgroundColor: 'rgba(6, 182, 212, 0.1)',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.4,
                        order: 4,
                        yAxisID: 'y1'
                    },
                    {
                        label: i18n.t('weather.chart_precipitation'),
                        data: precipitation,
                        borderColor: 'rgb(37, 99, 235)',
                        backgroundColor: 'rgba(37, 99, 235, 0.1)',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        fill: false,
                        tension: 0.4,
                        order: 5,
                        yAxisID: 'y1'
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
                    },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.dataset.yAxisID === 'y') {
                                    label += Math.round(context.parsed.y * 10) / 10 + '%';
                                } else if (context.dataset.yAxisID === 'y1') {
                                    if (context.dataset.label === i18n.t('weather.chart_precipitation')) {
                                        label += Math.round(context.parsed.y * 100) / 100 + i18n.t('units.precipitation_mm');
                                    } else {
                                        label += Math.round(context.parsed.y * 10) / 10 + i18n.t('units.temperature_celsius');
                                    }
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: {
                            display: true,
                            text: i18n.t('weather.chart_percentage')
                        },
                        min: 0,
                        max: 105,
                        ticks: {
                            stepSize: 20,
                            callback: function(value) {
                                if (value === 105) {
                                    return '';
                                }
                                return value + i18n.t('units.percent');
                            }
                        },
                        afterBuildTicks: function(axis) {
                            axis.ticks = [0, 20, 40, 60, 80, 100, 105].map(value => ({ value }));
                        }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: {
                            display: true,
                            text: i18n.t('weather.chart_temp_precip')
                        },
                        grid: {
                            drawOnChartArea: false,
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: i18n.t('common.time_label'),
                        }
                    }
                }
            }
        });

        const trendSection = containerDiv ? containerDiv.closest('.bg-sub-container') : null;
        if (trendSection) {
            const existingTrendFooter = trendSection.querySelector('.js-trend-data-source-footer');
            if (existingTrendFooter && existingTrendFooter.parentNode) {
                existingTrendFooter.parentNode.removeChild(existingTrendFooter);
            }
            const trendFooter = createDataSourceFooter({
                text: i18n.t('weather.footer_source'),
                links: [
                    { href: 'https://open-meteo.com/', label: 'Open-Meteo' }
                ]
            });
            trendFooter.classList.add('js-trend-data-source-footer');
            trendSection.appendChild(trendFooter);
        }
        
    } catch (error) {
        console.error('Error loading astronomical charts:', error);
        loadingDiv.style.display = 'none';
        containerDiv.style.display = 'none';
        // Show the actual error reason rather than the generic static text
        errorDiv.textContent = error.message || i18n.t('weather.loading_astro_failed');
        errorDiv.style.display = 'block';
    } finally {
        astroChartsRequestInFlight = null;
    }
    })();

    return astroChartsRequestInFlight;
}