// ======================
// Solar Eclipse
// ======================

let solarEclipseChartInstance = null;


function destroySolarEclipseChart() {
    if (solarEclipseChartInstance) {
        solarEclipseChartInstance.destroy();
        solarEclipseChartInstance = null;
    }
}

// Load Solar Eclipse data
async function loadSolarEclipse() {
    const container = document.getElementById('solar-eclipse-display');
    const data = await fetchJSONWithUI('/api/sun/next-eclipse', container, 'Loading Solar Eclipse data...', {
        pendingMessage: i18n.t('cache.cache_not_ready_retrying')
    });
    if (!data) return;

    try {
        clearContainer(container);

        // Check if eclipse data is available
        if (!data.solar_eclipse) {
            destroySolarEclipseChart();
            DOMUtils.clear(container);
            const alert = document.createElement('div');
            alert.className = 'alert alert-info';
            alert.setAttribute('role', 'alert');
            alert.textContent = data.message || i18n.t('sun.no_solar_eclipse_data');
            container.appendChild(alert);
            return;
        }

        const eclipse = data.solar_eclipse;

        let scoreColor = 'secondary';
        if (eclipse.astrophotography_score >= 8.5) scoreColor = 'success';
        else if (eclipse.astrophotography_score >= 7) scoreColor = 'info';
        else if (eclipse.astrophotography_score >= 5) scoreColor = 'warning';
        else if (eclipse.astrophotography_score > 0) scoreColor = 'danger';

        DOMUtils.clear(container);

        const row = document.createElement('div');
        row.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-2 row-cols-xl-4 mb-3';

        const createCardCol = (iconClass, labelText) => {
            const col = document.createElement('div');
            col.className = 'col mb-3';
            const card = document.createElement('div');
            card.className = 'card h-100';
            const header = document.createElement('div');
            header.className = 'card-header fw-bold';
            DOMUtils.append(header, DOMUtils.createIcon(iconClass), labelText);
            card.appendChild(header);
            col.appendChild(card);
            return { col, card };
        };

        const createList = () => {
            const list = document.createElement('ul');
            list.className = 'list-group list-group-flush';
            return list;
        };

        const createListItem = (labelText, valueNodeOrText) => {
            const item = document.createElement('li');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            const label = document.createElement('span');
            label.textContent = labelText;
            const value = document.createElement('span');
            if (typeof valueNodeOrText === 'string') {
                value.className = 'fw-bold';
                value.textContent = valueNodeOrText;
            } else {
                value.appendChild(valueNodeOrText);
            }
            item.appendChild(label);
            item.appendChild(value);
            return item;
        };

        // i18n translaton keys for eclipse type
        const typeEclipseType = {
            'total': i18n.t('sun.eclipse_type.total'),
            'partial': i18n.t('sun.eclipse_type.partial'),
            'annular': i18n.t('sun.eclipse_type.annular')
        };

        const overview = createCardCol('bi bi-bar-chart-line icon-inline', i18n.t('sun.overview'));
        const overviewList = createList();
        overviewList.appendChild(createListItem(`${i18n.t('sun.type')}`, typeEclipseType[eclipse.type.toLowerCase()] || eclipse.type));
        const visibilityItem = document.createElement('li');
        visibilityItem.className = 'list-group-item d-flex justify-content-between align-items-center';
        const visibilityLabel = document.createElement('span');
        visibilityLabel.textContent = `${i18n.t('sun.visibility')}`;
        const visibilityValue = document.createElement('span');
        const visibilityBadgeNode = document.createElement('span');
        visibilityBadgeNode.className = `badge ${eclipse.visible ? 'bg-success' : 'bg-danger'}`;
        visibilityBadgeNode.textContent = eclipse.visible ? i18n.t('sun.visible') : i18n.t('sun.not_visible');
        visibilityValue.appendChild(visibilityBadgeNode);
        visibilityItem.appendChild(visibilityLabel);
        visibilityItem.appendChild(visibilityValue);
        overviewList.appendChild(visibilityItem);
        overviewList.appendChild(createListItem(`${i18n.t('sun.magnitude')}`, eclipse.magnitude.toFixed(4)));
        overviewList.appendChild(createListItem(`${i18n.t('sun.obscuration')}`, `${eclipse.obscuration_percent.toFixed(1)}${i18n.t('units.percent')}`));
        overview.card.appendChild(overviewList);
        row.appendChild(overview.col);

        const timing = createCardCol('bi bi-stopwatch icon-inline', i18n.t('sun.timing'));
        const timingList = createList();
        timingList.appendChild(createListItem(`${i18n.t('sun.start')}`, formatTimeThenDate(eclipse.start_time)));
        timingList.appendChild(createListItem(`${i18n.t('sun.peak')}`, formatTimeThenDate(eclipse.peak_time)));
        timingList.appendChild(createListItem(`${i18n.t('sun.end')}`, formatTimeThenDate(eclipse.end_time)));
        timingList.appendChild(createListItem(`${i18n.t('sun.duration')}`, `${eclipse.duration_minutes} ${i18n.t('units.minute')}`));
        timing.card.appendChild(timingList);
        row.appendChild(timing.col);

        const position = createCardCol('bi bi-geo-alt text-danger icon-inline', i18n.t('sun.position_at_peak'));
        const positionList = createList();
        positionList.appendChild(createListItem(`${i18n.t('sun.altitude')}`, `${eclipse.peak_altitude_deg.toFixed(2)}${i18n.t('units.degrees')}`));
        positionList.appendChild(createListItem(`${i18n.t('sun.azimuth')}`, `${eclipse.peak_azimuth_deg.toFixed(2)}${i18n.t('units.degrees')}`));
        positionList.appendChild(createListItem(`${i18n.t('sun.direction')}`, getCardinalDirection(eclipse.peak_azimuth_deg)));
        position.card.appendChild(positionList);
        row.appendChild(position.col);

        const classificationKey = `sun.eclipse_classification.${eclipse.score_classification}`;
        const classificationText = i18n.has(classificationKey)
            ? i18n.t(classificationKey)
            : i18n.t('sun.not_visible');
        
        const score = createCardCol('bi bi-star-fill text-warning icon-inline', i18n.t('sun.astrophoto_score'));
        const scoreBody = document.createElement('div');
        scoreBody.className = 'p-3';
        scoreBody.style.textAlign = 'center';
        const scoreValue = document.createElement('div');
        scoreValue.className = 'display-4 fw-bold';
        scoreValue.style.color = `var(--bs-${scoreColor})`;
        scoreValue.textContent = `${eclipse.astrophotography_score.toFixed(1)}/10`;
        const scoreBadge = document.createElement('div');
        scoreBadge.className = `badge bg-${scoreColor} mt-2`;
        scoreBadge.textContent = classificationText;
        const scoreHint = document.createElement('div');
        scoreHint.className = 'small text-muted mt-2';
        scoreHint.textContent = i18n.t('sun.astrophotography_score_hint');
        scoreBody.appendChild(scoreValue);
        scoreBody.appendChild(scoreBadge);
        scoreBody.appendChild(scoreHint);
        score.card.appendChild(scoreBody);
        row.appendChild(score.col);

        container.appendChild(row);

        if (eclipse.altitude_vs_time && eclipse.altitude_vs_time.length > 0) {
            const chartContainer = document.createElement('div');
            chartContainer.id = 'solar-eclipse-chart-container';
            container.appendChild(chartContainer);
        }

        // Create altitude vs time chart if data available
        if (eclipse.altitude_vs_time && eclipse.altitude_vs_time.length > 0) {
            renderSolarEclipseAltitudeChart(eclipse.altitude_vs_time);
        }

    } catch (error) {
        console.error('Error loading solar eclipse data:', error);
        destroySolarEclipseChart();
        DOMUtils.clear(container);
        const errorBox = document.createElement('div');
        errorBox.className = 'error-box';
        errorBox.textContent = i18n.t('sun.failed_to_load_solar_eclipse_data');
        container.appendChild(errorBox);
    }
}

// Render altitude vs time chart
function renderSolarEclipseAltitudeChart(altitudeData) {
    const container = document.getElementById('solar-eclipse-chart-container');
    if (!container || !altitudeData || altitudeData.length === 0) return;

    destroySolarEclipseChart();

    const times = altitudeData.map(p => p.time);
    const altitudes = altitudeData.map(p => p.altitude_deg);

    DOMUtils.clear(container);
    const col = document.createElement('div');
    col.className = 'col-12 mb-3';
    const card = document.createElement('div');
    card.className = 'card h-100';
    const cardHeader = document.createElement('div');
    cardHeader.className = 'card-header';
    const title = document.createElement('h5');
    title.className = 'mb-0';
    DOMUtils.append(title, DOMUtils.createIcon('bi bi-graph-up icon-inline'), i18n.t('sun.eclipse_chart_title'));
    cardHeader.appendChild(title);

    const cardBody = document.createElement('div');
    cardBody.className = 'card-body';
    const chartCanvas = document.createElement('canvas');
    chartCanvas.id = 'solar-eclipse-altitude-chart';
    chartCanvas.style.width = '100%';
    chartCanvas.style.height = '300px';
    cardBody.appendChild(chartCanvas);

    const cardFooter = document.createElement('div');
    cardFooter.className = 'card-footer text-muted small';
    const footerRow = document.createElement('div');
    footerRow.className = 'row';
    const badgeCol = document.createElement('div');
    badgeCol.className = 'col-auto';
    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.style.backgroundColor = '#FDB813';
    badge.textContent = i18n.t('sun.sun_altitude');
    badgeCol.appendChild(badge);
    const textCol = document.createElement('div');
    textCol.className = 'col-auto';
    const text = document.createElement('span');
    text.className = 'text-muted';
    text.textContent = i18n.t('sun.eclipse_chart_footer');
    textCol.appendChild(text);
    footerRow.appendChild(badgeCol);
    footerRow.appendChild(textCol);
    cardFooter.appendChild(footerRow);

    card.appendChild(cardHeader);
    card.appendChild(cardBody);
    card.appendChild(cardFooter);
    col.appendChild(card);
    container.appendChild(col);

    const ctx = document.getElementById('solar-eclipse-altitude-chart');
    if (!ctx) return;
    
    const ctx_2d = ctx.getContext('2d');
    if (!ctx_2d) return;

    solarEclipseChartInstance = new Chart(ctx_2d, {
        type: 'line',
        data: {
            labels: times,
            datasets: [{
                label: i18n.t('sun.sun_altitude'),
                data: altitudes,
                borderColor: '#FDB813',
                backgroundColor: 'rgba(253, 184, 19, 0.1)',
                borderWidth: 2,
                tension: 0.1,
                fill: true,
                pointRadius: 2,
                pointBackgroundColor: '#FDB813',
                pointBorderColor: '#fff',
                pointBorderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 90,
                    title: {
                        display: true,
                        text: i18n.t('sun.sun_altitude')
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: i18n.t('common.time_label')
                    }
                }
            }
        }
    });

    appendDataSourceFooter(container, {
        text: i18n.t('sun.footer_source')
    });
}
