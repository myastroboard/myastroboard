// ======================
// Lunar Eclipse
// ======================

let lunarEclipseChartInstance = null;


function destroyLunarEclipseChart() {
    if (lunarEclipseChartInstance) {
        lunarEclipseChartInstance.destroy();
        lunarEclipseChartInstance = null;
    }
}

// Load Lunar Eclipse data
async function loadLunarEclipse() {
    const container = document.getElementById('lunar-eclipse-display');
    const data = await fetchJSONWithUI('/api/moon/next-eclipse', container, 'Loading Lunar Eclipse data...', {
        pendingMessage: i18n.t('cache.cache_not_ready_retrying')
    });
    if (!data) return;

    try {
        clearContainer(container);

        //console.log('Lunar Eclipse data:', data);

        // Check if eclipse data is available
        if (!data.lunar_eclipse) {
            destroyLunarEclipseChart();
            DOMUtils.clear(container);
            const alert = document.createElement('div');
            alert.className = 'alert alert-info';
            alert.setAttribute('role', 'alert');
            alert.textContent = data.message || i18n.t('moon.no_lunar_eclipse_data');
            container.appendChild(alert);
            return;
        }

        const eclipse = data.lunar_eclipse;        

        let visibilityBadge = '';
        if (!eclipse.visible) {
            visibilityBadge = `<span class="badge bg-danger">${i18n.t('moon.not_visible')}</span>`;
        } else {
            visibilityBadge = `<span class="badge bg-success">${i18n.t('moon.visible')}</span>`;
        }

        let scoreColor = 'secondary';
        if (eclipse.astrophotography_score >= 9) scoreColor = 'success';
        else if (eclipse.astrophotography_score >= 7.5) scoreColor = 'info';
        else if (eclipse.astrophotography_score >= 6) scoreColor = 'warning';
        else if (eclipse.astrophotography_score > 0) scoreColor = 'danger';

        DOMUtils.clear(container);

        const row = document.createElement('div');
        row.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-2 row-cols-xl-4 mb-3';

        const createCardCol = (titleText) => {
            const col = document.createElement('div');
            col.className = 'col mb-3';
            const card = document.createElement('div');
            card.className = 'card h-100';
            const header = document.createElement('div');
            header.className = 'card-header fw-bold';
            header.innerHTML = titleText;
            card.appendChild(header);
            col.appendChild(card);
            return { col, card };
        };

        const createList = () => {
            const list = document.createElement('ul');
            list.className = 'list-group list-group-flush';
            return list;
        };

        const createListItem = (labelText, valueText) => {
            const item = document.createElement('li');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            const label = document.createElement('span');
            label.textContent = labelText;
            const value = document.createElement('span');
            value.className = 'fw-bold';
            value.textContent = valueText;
            item.appendChild(label);
            item.appendChild(value);
            return item;
        };

        // i18n translaton keys for eclipse type
        const typeEclipseType = {
            'total': i18n.t('moon.eclipse_type.total'),
            'partial': i18n.t('moon.eclipse_type.partial'),
            'penumbral': i18n.t('moon.eclipse_type.penumbral')
        };

        const overview = createCardCol(`<i class="bi bi-bar-chart-line icon-inline" aria-hidden="true"></i>${i18n.t('moon.overview')}`);
        const overviewList = createList();
        overviewList.appendChild(createListItem(`${i18n.t('moon.type')}`, typeEclipseType[eclipse.type.toLowerCase()] || eclipse.type));
        const visibilityItem = document.createElement('li');
        visibilityItem.className = 'list-group-item d-flex justify-content-between align-items-center';
        const visibilityLabel = document.createElement('span');
        visibilityLabel.textContent = `${i18n.t('moon.visibility')}`;
        const visibilityValue = document.createElement('span');
        const visibilityBadgeNode = document.createElement('span');
        visibilityBadgeNode.className = `badge ${eclipse.visible ? 'bg-success' : 'bg-danger'}`;
        visibilityBadgeNode.textContent = eclipse.visible ? i18n.t('moon.visible') : i18n.t('moon.not_visible');
        visibilityValue.appendChild(visibilityBadgeNode);
        visibilityItem.appendChild(visibilityLabel);
        visibilityItem.appendChild(visibilityValue);
        overviewList.appendChild(visibilityItem);
        overviewList.appendChild(createListItem(
            `${i18n.t('moon.total_duration')}`,
            eclipse.total_duration_minutes > 0 ? `${eclipse.total_duration_minutes} ${i18n.t('units.minute')}` : i18n.t('moon.none')
        ));
        overviewList.appendChild(createListItem(
            `${i18n.t('moon.partial_duration')}`,
            eclipse.partial_duration_minutes > 0 ? `${eclipse.partial_duration_minutes} ${i18n.t('units.minute')}` : i18n.t('moon.none')
        ));
        overview.card.appendChild(overviewList);
        row.appendChild(overview.col);

        const timing = createCardCol(`<i class="bi bi-stopwatch icon-inline" aria-hidden="true"></i>${i18n.t('moon.timing')}`);
        const timingList = createList();
        timingList.appendChild(createListItem(`${i18n.t('moon.partial_begin')}`, formatTimeThenDate(eclipse.partial_begin)));
        if (eclipse.total_begin) {
            timingList.appendChild(createListItem(`${i18n.t('moon.total_begin')}`, formatTimeThenDate(eclipse.total_begin)));
            timingList.appendChild(createListItem(`${i18n.t('moon.total_end')}`, formatTimeThenDate(eclipse.total_end)));
        }
        timingList.appendChild(createListItem(`${i18n.t('moon.partial_end')}`, formatTimeThenDate(eclipse.partial_end)));
        timing.card.appendChild(timingList);
        row.appendChild(timing.col);

        const position = createCardCol(`<i class="bi bi-geo-alt text-danger icon-inline" aria-hidden="true"></i>${i18n.t('moon.position_at_peak')}`);
        const positionList = createList();
        positionList.appendChild(createListItem(`${i18n.t('moon.peak_time')}`, formatTimeThenDate(eclipse.peak_time)));
        positionList.appendChild(createListItem(`${i18n.t('moon.altitude')}`, `${eclipse.peak_altitude_deg.toFixed(2)}${i18n.t('units.degrees')}`));
        positionList.appendChild(createListItem(`${i18n.t('moon.azimuth')}`, `${eclipse.peak_azimuth_deg.toFixed(2)}${i18n.t('units.degrees')}`));
        positionList.appendChild(createListItem(`${i18n.t('moon.direction')}`, getCardinalDirection(eclipse.peak_azimuth_deg)));
        position.card.appendChild(positionList);
        row.appendChild(position.col);

        const classificationKey = `moon.eclipse_classification.${eclipse.score_classification}`;
        const classificationText = i18n.has(classificationKey)
            ? i18n.t(classificationKey)
            : i18n.t('moon.not_visible');

        const score = createCardCol(`<i class="bi bi-star-fill text-warning icon-inline" aria-hidden="true"></i>${i18n.t('moon.astrophoto_score')}`);
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
        scoreHint.textContent = i18n.t('moon.astrophotography_score_hint');
        scoreBody.appendChild(scoreValue);
        scoreBody.appendChild(scoreBadge);
        scoreBody.appendChild(scoreHint);
        score.card.appendChild(scoreBody);
        row.appendChild(score.col);

        container.appendChild(row);

        if (eclipse.altitude_vs_time && eclipse.altitude_vs_time.length > 0) {
            const chartContainer = document.createElement('div');
            chartContainer.id = 'lunar-eclipse-chart-container';
            container.appendChild(chartContainer);
        }

        // Create altitude vs time chart if data available
        if (eclipse.altitude_vs_time && eclipse.altitude_vs_time.length > 0) {
            renderLunarEclipseAltitudeChart(eclipse.altitude_vs_time);
        }

    } catch (error) {
        console.error('Error loading lunar eclipse data:', error);
        destroyLunarEclipseChart();
        DOMUtils.clear(container);
        const errorBox = document.createElement('div');
        errorBox.className = 'error-box';
        errorBox.textContent = i18n.t('moon.failed_to_load_lunar_eclipse_data');
        container.appendChild(errorBox);
    }
}

// Render altitude vs time chart
function renderLunarEclipseAltitudeChart(altitudeData) {
    const container = document.getElementById('lunar-eclipse-chart-container');
    if (!container || !altitudeData || altitudeData.length === 0) return;

    destroyLunarEclipseChart();

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
    title.innerHTML = `<i class="bi bi-graph-up icon-inline" aria-hidden="true"></i>${i18n.t('moon.eclipse_chart_title')}`;
    cardHeader.appendChild(title);

    const cardBody = document.createElement('div');
    cardBody.className = 'card-body';
    const chartCanvas = document.createElement('canvas');
    chartCanvas.id = 'lunar-eclipse-altitude-chart';
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
    badge.style.backgroundColor = '#C0C0C0';
    badge.textContent = i18n.t('moon.moon_altitude');
    badgeCol.appendChild(badge);
    const textCol = document.createElement('div');
    textCol.className = 'col-auto';
    const text = document.createElement('span');
    text.className = 'text-muted';
    text.textContent = i18n.t('moon.eclipse_chart_footer');
    textCol.appendChild(text);
    footerRow.appendChild(badgeCol);
    footerRow.appendChild(textCol);
    cardFooter.appendChild(footerRow);

    card.appendChild(cardHeader);
    card.appendChild(cardBody);
    card.appendChild(cardFooter);
    col.appendChild(card);
    container.appendChild(col);

    const ctx = document.getElementById('lunar-eclipse-altitude-chart');
    if (!ctx) return;
    
    const ctx_2d = ctx.getContext('2d');
    if (!ctx_2d) return;

    lunarEclipseChartInstance = new Chart(ctx_2d, {
        type: 'line',
        data: {
            labels: times,
            datasets: [{
                label: i18n.t('moon.moon_altitude'),
                data: altitudes,
                borderColor: '#C0C0C0',
                backgroundColor: 'rgba(192, 192, 192, 0.1)',
                borderWidth: 2,
                tension: 0.1,
                fill: true,
                pointRadius: 2,
                pointBackgroundColor: '#C0C0C0',
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
                        text: i18n.t('moon.moon_altitude')
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
        text: i18n.t('moon.footer_source_planner')
    });
}
