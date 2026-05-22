// ======================
// Aurora Borealis Predictions
// ======================

/**
 * Load aurora borealis predictions
 */
async function loadAurora() {
    const container = document.getElementById('aurora-display');
    const data = await fetchJSONWithUI('/api/aurora/predictions', container, i18n.t('aurora.loading_predictions'));
    if (!data) return;

    //console.log("Aurora data received:", data);
    
    // Display aurora information if data is available
    if (data.current) {
        const current = data.current;
        const location = data.location;
        
        // Determine icon based on visibility level
        const visibilityIconMap = {
            "None": "bi bi-moon",
            "Very Low": "bi bi-stars",
            "Low": "bi bi-stars",
            "Moderate": "bi bi-stars",
            "Good": "bi bi-stars",
            "Excellent": "bi bi-brightness-high",
            "Severe Storm": "bi bi-lightning-charge"
        };

        const visibilityTextMap = {
            "None": i18n.t('aurora.visibility.none'),
            "Very Low": i18n.t('aurora.visibility.very_low'),
            "Low": i18n.t('aurora.visibility.low'),
            "Moderate": i18n.t('aurora.visibility.moderate'),
            "Good": i18n.t('aurora.visibility.good'),
            "Excellent": i18n.t('aurora.visibility.excellent'),
            "Severe Storm": i18n.t('aurora.visibility.severe_storm')
        };

        const probabilityLevelMap = {
            "Very Low": i18n.t('aurora.probability.very_low'),
            "Low": i18n.t('aurora.probability.low'),
            "Moderate": i18n.t('aurora.probability.moderate'),
            "High": i18n.t('aurora.probability.high'),
            "Very High": i18n.t('aurora.probability.very_high')
        };

        const visibilityDescriptionMap = {
            "None": i18n.t('aurora.description.none'),
            "Very Low": i18n.t('aurora.description.very_low'),
            "Low": i18n.t('aurora.description.low'),
            "Moderate": i18n.t('aurora.description.moderate'),
            "Good": i18n.t('aurora.description.good'),
            "Excellent": i18n.t('aurora.description.excellent'),
            "Severe Storm": i18n.t('aurora.description.severe_storm')
        };

        const visibilityIconClass = visibilityIconMap[current.visibility_level] || 'bi bi-stars';
        current.visibility_description = visibilityDescriptionMap[current.visibility_level] || current.visibility_description || '';
        current.probability_level = probabilityLevelMap[current.probability_level] || current.probability_level || '';  
        current.visibility_level = visibilityTextMap[current.visibility_level] || current.visibility_level || '';

        //console.log(current);
        // Determine color for probability bar
        const probability = current.probability || 0;
        const probabilityLevel = current.probability_level || '';
        let probabilityColor = '#dc3545'; // red
        if (probability > 70) {
            probabilityColor = '#28a745'; // green
        } else if (probability > 40) {
            probabilityColor = '#ffc107'; // yellow
        }
        DOMUtils.clear(container);

        const topRow = document.createElement('div');
        topRow.className = 'row row-cols-1 mb-3';
        const topCol = document.createElement('div');
        topCol.className = 'col';
        const topFlex = document.createElement('div');
        topFlex.className = 'd-flex flex-row align-items-center';
        const emojiDiv = document.createElement('div');
        emojiDiv.className = 'p-2 icon-weather-lg';
        emojiDiv.appendChild(DOMUtils.createIcon(visibilityIconClass));
        const textWrap = document.createElement('div');
        textWrap.className = 'p-2';
        const level = document.createElement('div');
        level.className = 'fw-bold fs-4';
        level.textContent = current.visibility_level;
        const description = document.createElement('div');
        description.className = 'text-muted';
        description.textContent = current.visibility_description;
        textWrap.appendChild(level);
        textWrap.appendChild(description);
        topFlex.appendChild(emojiDiv);
        topFlex.appendChild(textWrap);
        topCol.appendChild(topFlex);
        topRow.appendChild(topCol);
        container.appendChild(topRow);

        const cardsRow = document.createElement('div');
        cardsRow.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-2 row-cols-xl-3';
        const createCard = (titleText) => {
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

        const geomagnetic = createCard(`<i class="bi bi-lightning-charge icon-inline" aria-hidden="true"></i>${i18n.t('aurora.geomagnetic_activity')}`);
        const geomagneticList = document.createElement('ul');
        geomagneticList.className = 'list-group list-group-flush';
        const geomag1 = document.createElement('li');
        geomag1.className = 'list-group-item d-flex justify-content-between align-items-center';
        geomag1.innerText = '';
        const g1Label = document.createElement('span');
        g1Label.innerHTML = `<i class="bi bi-circle-fill text-danger icon-inline" aria-hidden="true"></i>${i18n.t('aurora.kp_index')}`;
        const g1Value = document.createElement('span');
        g1Value.className = 'fw-bold';
        g1Value.textContent = `${current.kp_index.toFixed(1)} / ${current.kp_index_max.toFixed(1)}`;
        geomag1.appendChild(g1Label);
        geomag1.appendChild(g1Value);

        const geomag2 = document.createElement('li');
        geomag2.className = 'list-group-item d-flex justify-content-between align-items-center';
        const g2Label = document.createElement('span');
        g2Label.innerHTML = `<i class="bi bi-bar-chart-line icon-inline" aria-hidden="true"></i>${i18n.t('aurora.aurora_probability')}`;
        const g2Value = document.createElement('span');
        g2Value.className = 'fw-bold';
        g2Value.textContent = `${probability.toFixed(0)}%${probabilityLevel ? ` (${probabilityLevel})` : ''}`;
        geomag2.appendChild(g2Label);
        geomag2.appendChild(g2Value);

        const geomag3 = document.createElement('li');
        geomag3.className = 'list-group-item';
        const progress = document.createElement('div');
        progress.className = 'progress mb-2 mt-1';
        progress.setAttribute('role', 'progressbar');
        progress.setAttribute('aria-valuenow', probability.toFixed(0));
        progress.setAttribute('aria-valuemin', '0');
        progress.setAttribute('aria-valuemax', '100');
        const progressBar = document.createElement('div');
        progressBar.className = 'progress-bar';
        progressBar.style.width = `${probability.toFixed(0)}%`;
        progressBar.style.backgroundColor = probabilityColor;
        progress.appendChild(progressBar);
        geomag3.appendChild(progress);

        geomagneticList.appendChild(geomag1);
        geomagneticList.appendChild(geomag2);
        geomagneticList.appendChild(geomag3);
        geomagnetic.card.appendChild(geomagneticList);
        cardsRow.appendChild(geomagnetic.col);

        const windowCard = createCard(`<i class="bi bi-clock-history icon-inline" aria-hidden="true"></i>${i18n.t('aurora.best_viewing_window')}`);
        const windowList = document.createElement('ul');
        windowList.className = 'list-group list-group-flush';
        const w1 = document.createElement('li');
        w1.className = 'list-group-item d-flex justify-content-between align-items-center';
        const w1Label = document.createElement('span');
        w1Label.innerHTML = `<i class="bi bi-clock icon-inline" aria-hidden="true"></i>${i18n.t('aurora.local_time')}`;
        const w1Value = document.createElement('span');
        w1Value.className = 'fw-bold';
        w1Value.textContent = `${current.best_viewing_window.start_hour}:00 - ${current.best_viewing_window.end_hour}:00`;
        w1.appendChild(w1Label);
        w1.appendChild(w1Value);
        const w2 = document.createElement('li');
        w2.className = 'list-group-item';
        const small = document.createElement('small');
        small.className = 'text-muted';
        const strong = document.createElement('strong');
        strong.innerHTML = `<i class="bi bi-geo-alt text-danger icon-inline" aria-hidden="true"></i>${i18n.t('aurora.location')}`;
        small.appendChild(strong);
        small.append(` ${location.latitude.toFixed(2)}°, ${location.longitude.toFixed(2)}°`);
        w2.appendChild(small);
        windowList.appendChild(w1);
        windowList.appendChild(w2);
        windowCard.card.appendChild(windowList);
        cardsRow.appendChild(windowCard.col);

        const colorsCard = createCard(`<i class="bi bi-palette icon-inline" aria-hidden="true"></i>${i18n.t('aurora.expected_colors')}`);
        const colorsList = document.createElement('ul');
        colorsList.className = 'list-group list-group-flush';
        Object.entries(current.color_description || {}).forEach(([index, colorDescription]) => {
            const li = document.createElement('li');
            li.className = 'list-group-item';
            const smallText = document.createElement('small');
            smallText.textContent = i18n.t(`aurora.colors.${index}`) || colorDescription;
            li.appendChild(smallText);
            colorsList.appendChild(li);
        });
        colorsCard.card.appendChild(colorsList);
        cardsRow.appendChild(colorsCard.col);
        container.appendChild(cardsRow);

        const guideRow = document.createElement('div');
        guideRow.className = 'row row-cols-1 mb-3';
        const guideCol = document.createElement('div');
        guideCol.className = 'col';
        const guideCard = document.createElement('div');
        guideCard.className = 'card h-100';
        const guideHeader = document.createElement('div');
        guideHeader.className = 'card-header fw-bold';
        guideHeader.innerHTML = `<i class="bi bi-graph-up icon-inline" aria-hidden="true"></i>${i18n.t('aurora.scale_guide')}`;
        const guideBody = document.createElement('div');
        guideBody.className = 'card-body';
        const guideBodyRow = document.createElement('div');
        guideBodyRow.className = 'row';
        const makeGuideCol = (lines) => {
            const col = document.createElement('div');
            col.className = 'col-auto';
            const small = document.createElement('small');
            lines.forEach(({ left, right }) => {
                const line = document.createElement('div');
                const strong = document.createElement('strong');
                strong.textContent = left;
                line.appendChild(strong);
                line.append(` ${right}`);
                small.appendChild(line);
            });
            col.appendChild(small);
            return col;
        };
        guideBodyRow.appendChild(makeGuideCol([
            { left: '0-2:', right: i18n.t('aurora.guide.0') },
            { left: '3:', right: i18n.t('aurora.guide.3') },
            { left: '4:', right: i18n.t('aurora.guide.4') }
        ]));
        guideBodyRow.appendChild(makeGuideCol([
            { left: '5:', right: i18n.t('aurora.guide.5') },
            { left: '6:', right: i18n.t('aurora.guide.6') },
            { left: '7+:', right: i18n.t('aurora.guide.7') }
        ]));
        guideBody.appendChild(guideBodyRow);
        guideCard.appendChild(guideHeader);
        guideCard.appendChild(guideBody);
        guideCol.appendChild(guideCard);
        guideRow.appendChild(guideCol);
        container.appendChild(guideRow);

        if (data.forecast && data.forecast.length > 0) {
            const forecastRow = document.createElement('div');
            forecastRow.className = 'row row-cols-1 mb-3';
            const forecastCol = document.createElement('div');
            forecastCol.className = 'col';
            const forecastCard = document.createElement('div');
            forecastCard.className = 'card h-100';
            const forecastHeader = document.createElement('div');
            forecastHeader.className = 'card-header fw-bold';
            forecastHeader.innerHTML = `<i class="bi bi-calendar-event text-danger icon-inline" aria-hidden="true"></i>${i18n.t('aurora.forecast')}`;
            const forecastBody = document.createElement('div');
            forecastBody.className = 'card-body';
            const forecastAlert = document.createElement('div');
            forecastAlert.className = 'alert alert-info';
            forecastAlert.setAttribute('role', 'alert');
            forecastAlert.append(i18n.t('aurora.alert_1'));
            forecastAlert.appendChild(document.createElement('br'));
            forecastAlert.append(i18n.t('aurora.alert_2'));
            forecastBody.appendChild(forecastAlert);

            const bubblesRow = document.createElement('div');
            bubblesRow.className = 'row row-cols-2 row-cols-sm-3 row-cols-lg-4 text-center g-3';
            data.forecast.slice(0, 8).forEach((f) => {
                const kp = f.kp_index || 0;
                let bubbleColor = 'danger';
                if (kp >= 7) bubbleColor = 'success';
                else if (kp >= 5) bubbleColor = 'warning';
                const size = 24 + kp * 2;

                const bubbleCol = document.createElement('div');
                bubbleCol.className = 'col d-flex flex-column align-items-center';
                const ts = document.createElement('div');
                ts.className = 'fw-bold small mb-1';
                ts.textContent = formatTimeThenDate(new Date(f.timestamp));
                const bubble = document.createElement('div');
                bubble.className = `rounded-circle bg-${bubbleColor} shadow-sm mb-1`;
                bubble.style.width = `${size}px`;
                bubble.style.height = `${size}px`;
                bubble.style.lineHeight = `${size}px`;
                const kpLabel = document.createElement('div');
                kpLabel.className = 'small';
                kpLabel.append(`Kp ${kp.toFixed(1)}`);
                kpLabel.appendChild(document.createElement('br'));
                kpLabel.append(`${probability.toFixed(0)}%${probabilityLevel ? ` (${probabilityLevel})` : ''}`);

                bubbleCol.appendChild(ts);
                bubbleCol.appendChild(bubble);
                bubbleCol.appendChild(kpLabel);
                bubblesRow.appendChild(bubbleCol);
            });
            forecastBody.appendChild(bubblesRow);
            forecastCard.appendChild(forecastHeader);
            forecastCard.appendChild(forecastBody);
            forecastCol.appendChild(forecastCard);
            forecastRow.appendChild(forecastCol);
            container.appendChild(forecastRow);
        }

        const tipsRow = document.createElement('div');
        tipsRow.className = 'row row-cols-1 mb-3';
        const tipsCol = document.createElement('div');
        tipsCol.className = 'col';
        const tipsAlert = document.createElement('div');
        tipsAlert.className = 'alert alert-info';
        tipsAlert.setAttribute('role', 'alert');
        const tipsTitle = document.createElement('strong');
        tipsTitle.innerHTML = `<i class="bi bi-pin-angle icon-inline" aria-hidden="true"></i>${i18n.t('aurora.tips_for_aurora_hunting')}`;
        const tipsList = document.createElement('ul');
        tipsList.className = 'mb-0 mt-2';
        [
            i18n.t('aurora.tips.1'),
            i18n.t('aurora.tips.2'),
            i18n.t('aurora.tips.3'),
            i18n.t('aurora.tips.4'),
            i18n.t('aurora.tips.5'),
            i18n.t('aurora.tips.6')
        ].forEach((tip) => {
            const li = document.createElement('li');
            li.textContent = tip;
            tipsList.appendChild(li);
        });
        tipsAlert.appendChild(tipsTitle);
        tipsAlert.appendChild(tipsList);
        tipsCol.appendChild(tipsAlert);
        tipsRow.appendChild(tipsCol);
        container.appendChild(tipsRow);

        appendDataSourceFooter(container, {
            text: i18n.t('aurora.footer_source'),
            links: [
                { href: 'https://www.swpc.noaa.gov/', label: 'NOAA SWPC' }
            ]
        });
    } else {
        // Error block
        const errorBlock = document.createElement('div');
        errorBlock.className = 'alert alert-warning';
        errorBlock.setAttribute('role', 'alert');
        errorBlock.textContent = i18n.t('aurora.failed_to_load_predictions');
        container.appendChild(errorBlock);
    }
}

