/**
 * Horizon Graph Visualization
 * Displays sun and moon altitude vs time for the current day (00:00 to 24:00)
 * Uses Chart.js to render altitude curves
 */

let horizonChartInstance = null;
let horizonGraphRequestInFlight = null;


function updateHorizonLoadingMessage(message) {
    const loadingDiv = document.getElementById('horizon-graph-loading');
    if (!loadingDiv) return;
    loadingDiv.replaceChildren(DOMUtils.createSpinnerWrapper(message));
}


function destroyHorizonChart() {
    if (horizonChartInstance) {
        horizonChartInstance.destroy();
        horizonChartInstance = null;
    }
}

/**
 * Load and display horizon graph data
 */
async function loadHorizonGraph() {
    if (horizonGraphRequestInFlight) {
        return horizonGraphRequestInFlight;
    }

    horizonGraphRequestInFlight = (async () => {
    const container = document.getElementById('horizon-graph-display');
    if (!container) return;
    
    const loadingDiv = document.getElementById('horizon-graph-loading');
    const errorDiv = document.getElementById('horizon-graph-error');
    const mainContainer = document.getElementById('horizon-graph-main');
    
    if (loadingDiv) {
        loadingDiv.style.display = 'block';
        updateHorizonLoadingMessage(i18n.t('astro_weather.loading_horizon_graph'));
    }
    if (errorDiv) errorDiv.style.display = 'none';
    if (container) container.style.display = 'none';
    if (mainContainer) mainContainer.style.display = 'none';
    
    try {
        const data = await fetchJSONWithRetry('/api/astro/horizon-graph', {}, {
            maxAttempts: 8,
            baseDelayMs: 1000,
            maxDelayMs: 15000,
            timeoutMs: 20000,
            shouldRetryData: (payload) => payload && payload.status === 'pending',
            onRetry: ({ reason, attempt, maxAttempts, waitMs }) => {
                if (!loadingDiv) return;
                const seconds = Math.max(1, Math.round(waitMs / 1000));
                const message = i18n.t('astro_weather.loading_horizon_graph');
                updateHorizonLoadingMessage(`${message} ${i18n.t('common.retrying_in', { seconds, attempt, maxAttempts })}`);
            }
        });

        if (data.status === 'pending') {
            throw new Error(i18n.t('astro_weather.error_loading_horizon_graph'));
        }
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (container) container.style.display = 'block';
        if (mainContainer) mainContainer.style.display = 'block';
        
        // Render horizon graph
        if (data.horizon_data) {
            renderHorizonChart(data.horizon_data);
        } else {
            if (container) {
                destroyHorizonChart();
                DOMUtils.clear(container);
                const alert = document.createElement('div');
                alert.className = 'alert alert-warning';
                alert.textContent = i18n.t('astro_weather.no_horizon_data');
                container.appendChild(alert);
            }
        }
        
    } catch (error) {
        console.error('Error loading horizon graph:', error);
        
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (errorDiv) {
            errorDiv.style.display = 'block';
            DOMUtils.clear(errorDiv);
            const column = document.createElement('div');
            column.className = 'col';
            const card = document.createElement('div');
            card.className = 'card h-100 bg-danger-subtle';
            const cardBody = document.createElement('div');
            cardBody.className = 'card-body';
            const title = document.createElement('h5');
            title.className = 'card-title';
            title.textContent = i18n.t('common.error');
            const message = document.createElement('p');
            message.className = 'card-text';
            message.textContent = `${i18n.t('astro_weather.error_loading_horizon_graph')}: ${error.message}`;
            cardBody.appendChild(title);
            cardBody.appendChild(message);
            card.appendChild(cardBody);
            column.appendChild(card);
            errorDiv.appendChild(column);
        }
    } finally {
        horizonGraphRequestInFlight = null;
    }
    })();

    return horizonGraphRequestInFlight;
}

/**
 * Render horizon graph using Chart.js
 */
function renderHorizonChart(horizonData) {
    const container = document.getElementById('horizon-graph-display');
    if (!container || !horizonData) return;

    destroyHorizonChart();
    
    // Prepare data
    const sunData = horizonData.sun_data || [];
    const moonData = horizonData.moon_data || [];
    
    // Extract times and altitudes (keep negative values to show below horizon)
    const sunAltitudes = sunData.map(point => ({ x: point.hour, y: point.altitude_deg })) || [];
    const moonAltitudes = moonData.map(point => ({ x: point.hour, y: point.altitude_deg })) || [];
    const now = new Date();
    const currentTimeValue = sunData.length > 0
        ? now.getHours() + now.getMinutes() / 60
        : null;
    const currentTimeLabel = currentTimeValue !== null
        ? `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
        : '';
    const currentTimeLine = currentTimeValue !== null
        ? [{ x: currentTimeValue, y: -90 }, { x: currentTimeValue, y: 90 }]
        : [];
    
    DOMUtils.clear(container);
    const col = document.createElement('div');
    col.className = 'col-12 mb-3';
    const card = document.createElement('div');
    card.className = 'card h-100';

    const cardHeader = document.createElement('div');
    cardHeader.className = 'card-header';
    const title = document.createElement('h5');
    title.className = 'mb-0';
    title.innerHTML = `<i class="bi bi-sunrise icon-inline" aria-hidden="true"></i>${i18n.t('astro_weather.title_horizon_graph')}`;
    cardHeader.appendChild(title);

    const cardBody = document.createElement('div');
    cardBody.className = 'card-body';
    const canvas = document.createElement('canvas');
    canvas.id = 'horizonCanvas';
    canvas.style.width = '100%';
    canvas.style.height = '350px';
    cardBody.appendChild(canvas);

    const cardFooter = document.createElement('div');
    cardFooter.className = 'card-footer text-muted small';
    const footerRow = document.createElement('div');
    footerRow.className = 'row';

    const createBadgeItem = (text, className, backgroundColor) => {
        const itemCol = document.createElement('div');
        itemCol.className = 'col-auto';
        const badge = document.createElement('span');
        badge.className = className;
        if (backgroundColor) {
            badge.style.backgroundColor = backgroundColor;
        }
        badge.innerHTML = text;
        itemCol.appendChild(badge);
        return itemCol;
    };

    footerRow.appendChild(createBadgeItem(`<i class="bi bi-sun icon-inline" aria-hidden="true"></i>${i18n.t('common.sun')}`, 'badge', '#FDB813'));
    footerRow.appendChild(createBadgeItem(`<i class="bi bi-moon-stars icon-inline" aria-hidden="true"></i>${i18n.t('common.moon')}`, 'badge', '#C0C0C0'));
    footerRow.appendChild(createBadgeItem(`━ ${i18n.t('astro_weather.horizon_badge')} (0°)`, 'badge bg-secondary'));
    footerRow.appendChild(createBadgeItem(`┃ ${i18n.t('astro_weather.now_badge')} ${currentTimeLabel || ''}`, 'badge', '#ef4444'));

    const detailsCol = document.createElement('div');
    detailsCol.className = 'col-auto';
    const details = document.createElement('span');
    details.className = 'text-muted';
    details.textContent = i18n.t('astro_weather.horizon_graph_details', { date: horizonData.date });
    detailsCol.appendChild(details);
    footerRow.appendChild(detailsCol);

    cardFooter.appendChild(footerRow);
    card.appendChild(cardHeader);
    card.appendChild(cardBody);
    card.appendChild(cardFooter);
    col.appendChild(card);
    container.appendChild(col);
    
    // Render chart
    const canvasElement = document.getElementById('horizonCanvas');
    if (!canvasElement) return;
    
    const ctx = canvasElement.getContext('2d');
    if (!ctx) return;
    
    horizonChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [
                {
                    label: i18n.t('common.sun'),
                    data: sunAltitudes,
                    parsing: false,
                    borderColor: '#FDB813',
                    backgroundColor: 'rgba(253, 184, 19, 0.1)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: '#FDB813',
                    pointBorderColor: '#FDB813',
                    pointHoverRadius: 5,
                    yAxisID: 'y'
                },
                {
                    label: i18n.t('common.moon'),
                    data: moonAltitudes,
                    parsing: false,
                    borderColor: '#C0C0C0',
                    backgroundColor: 'rgba(192, 192, 192, 0.1)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: '#C0C0C0',
                    pointBorderColor: '#C0C0C0',
                    pointHoverRadius: 5,
                    yAxisID: 'y'
                },
                ...(currentTimeLine.length
                    ? [{
                        label: i18n.t('astro_weather.now_badge'),
                        data: currentTimeLine,
                        parsing: false,
                        borderColor: '#ef4444',
                        borderWidth: 2,
                        borderDash: [4, 4],
                        pointRadius: 0,
                        fill: false,
                        tension: 0,
                        yAxisID: 'y'
                    }]
                    : [])
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
                    display: true,
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 15,
                        font: {
                            size: 12
                        }
                    }
                },
                tooltip: {
                    callback: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += context.parsed.y.toFixed(1) + i18n.t('units.degrees');
                            }
                            return label;
                        }
                    }
                },
                // Add horizon and current time markers
                annotation: {
                    annotations: {
                        horizon: {
                            type: 'line',
                            yMin: 0,
                            yMax: 0,
                            borderColor: '#666666',
                            borderWidth: 3,
                            borderDash: [5, 5],
                            label: {
                                display: true,
                                content: [i18n.t('astro_weather.horizon_badge')]
                            }
                        },
                        currentTime: null
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
                        text: i18n.t('astro_weather.chart_horizon_axis'),
                        font: {
                            size: 12
                        }
                    },
                    min: -90,
                    max: 90,
                    ticks: {
                        callback: function(value) {
                            return value + i18n.t('units.degrees');
                        }
                    },
                    grid: {
                        drawBorder: true,
                        color: function(context) {
                            // Make horizon line (0°) bolder
                            if (context.tick.value === 0) {
                                return 'rgba(102, 102, 102, 0.8)';
                            }
                            return 'rgba(200, 200, 200, 0.2)';
                        },
                        lineWidth: function(context) {
                            // Make horizon line (0°) thicker
                            if (context.tick.value === 0) {
                                return 3;
                            }
                            return 1;
                        }
                    }
                },
                x: {
                    type: 'linear',
                    min: 0,
                    max: 24,
                    title: {
                        display: true,
                        text: i18n.t('astro_weather.chart_time_axis'),
                        font: {
                            size: 12
                        }
                    },
                    ticks: {
                        maxTicksLimit: 12,
                        callback: function(value) {
                            const hour = Math.floor(value);
                            return `${String(hour).padStart(2, '0')}:00`;
                        }
                    }
                }
            }
        }
    });
}

