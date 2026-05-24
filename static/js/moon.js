// ======================
// Moon 
// ======================

let moonSvgTemplatePromise = null;

function getAppVersionQuery() {
    const versionMeta = document.querySelector('meta[name="app-version"]');
    const version = versionMeta ? String(versionMeta.content || '').trim() : '';
    return version ? `?v=${encodeURIComponent(version)}` : '';
}

function getMoonSvgTemplate() {
    if (!moonSvgTemplatePromise) {
        moonSvgTemplatePromise = fetch(`/static/img/moon.svg${getAppVersionQuery()}`)
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Unable to load moon.svg (${response.status})`);
                }
                return response.text();
            })
            .then((svgText) => {
                const parser = new DOMParser();
                const svgDoc = parser.parseFromString(svgText, 'image/svg+xml');
                    const svg = svgDoc.querySelector('svg');
                    if (!svg) {
                    throw new Error('moon.svg does not contain a root <svg> element');
                }
                return svg;
            });
    }
    return moonSvgTemplatePromise;
}

async function createMoonPhaseSvg(illumination, waxing) {
    //console.log(`Creating moon SVG with illumination=${illumination}, waxing=${waxing}`);
    //illumination = 0.3; // Temporary fixed value for testing, replace with actual illumination when available
    const svgTemplate = await getMoonSvgTemplate();
    const moonSvg = svgTemplate.cloneNode(true);
    const terminator = moonSvg.querySelector('#terminator');
    if (terminator) {
        const clampedIllumination = Math.max(0, Math.min(1, Number.isFinite(illumination) ? illumination : 0));
        const radius = 44;
        const targetShadowFraction = 1 - clampedIllumination;

        const overlapFractionForDistance = (distance) => {
            const d = Math.max(0, Math.min(2 * radius, distance));
            if (d <= 0) {
                return 1;
            }
            if (d >= 2 * radius) {
                return 0;
            }
            const term = d / (2 * radius);
            const overlapArea =
                2 * radius * radius * Math.acos(term) -
                (d / 2) * Math.sqrt(4 * radius * radius - d * d);
            return overlapArea / (Math.PI * radius * radius);
        };

        // Find the circle offset that yields the expected shadow coverage.
        let low = 0;
        let high = 2 * radius;
        for (let i = 0; i < 24; i += 1) {
            const mid = (low + high) / 2;
            const currentFraction = overlapFractionForDistance(mid);
            if (currentFraction > targetShadowFraction) {
                low = mid;
            } else {
                high = mid;
            }
        }
        const distance = (low + high) / 2;

        terminator.setAttribute('rx', String(radius));
        // Waxing is lit on the right, so shadow sits on the left.
        terminator.setAttribute('cx', String(waxing ? 50 - distance : 50 + distance));
    }
    moonSvg.setAttribute('width', '80');
    return moonSvg;
}

//Load moon data
async function loadMoon() {
    const container = document.getElementById('moon-display');
    const data = await fetchJSONWithUI('/api/moon/report', container, 'Loading Moon data...');
    if (!data) return;

    // Display moon information if moon data is available
    if (data.moon) {
        const moon = data.moon;
        
        const waxingPhases = new Set(["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous"]);
        const waxing = waxingPhases.has(moon.phase_name);
        const illumination = moon.illumination_percent / 100;

        const phaseTextMap = {
            "New Moon": i18n.t('moon.new_moon'),
            "Waxing Crescent": i18n.t('moon.waxing_crescent'),
            "First Quarter": i18n.t('moon.first_quarter'),
            "Waxing Gibbous": i18n.t('moon.waxing_gibbous'),
            "Full Moon": i18n.t('moon.full_moon'),
            "Waning Gibbous": i18n.t('moon.waning_gibbous'),
            "Last Quarter": i18n.t('moon.last_quarter'),
            "Waning Crescent": i18n.t('moon.waning_crescent')
        };

        DOMUtils.clear(container);

        const header = document.createElement('div');
        header.className = 'd-flex flex-row align-items-center mb-3';
        const icon = document.createElement('div');
        icon.className = 'p-2';
        const moonVisual = document.createElement('div');
        moonVisual.setAttribute('role', 'img');
        moonVisual.setAttribute('aria-label', phaseTextMap[moon.phase_name] || moon.phase_name);
        const moonSvg = await createMoonPhaseSvg(illumination, waxing);
        moonVisual.appendChild(moonSvg);
        icon.appendChild(moonVisual);
        const titleWrap = document.createElement('div');
        titleWrap.className = 'p-2';
        const phaseTitle = document.createElement('div');
        phaseTitle.className = 'fw-bold fs-4';
        phaseTitle.textContent = phaseTextMap[moon.phase_name] || moon.phase_name;
        const illum = document.createElement('div');
        illum.textContent = i18n.t('moon.illumination_prc', { illumination: moon.illumination_percent.toFixed(0) });
        titleWrap.appendChild(phaseTitle);
        titleWrap.appendChild(illum);
        header.appendChild(icon);
        header.appendChild(titleWrap);

        const row = document.createElement('div');
        row.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-2 row-cols-xl-3 p-2 mb-3';

        const createCard = (titleText, lines) => {
            const col = document.createElement('div');
            col.className = 'col mb-3';
            const card = document.createElement('div');
            card.className = 'card h-100';
            const cardHeader = document.createElement('div');
            cardHeader.className = 'card-header fw-bold';
            cardHeader.innerHTML = titleText;
            const list = document.createElement('ul');
            list.className = 'list-group list-group-flush';
            lines.forEach(({ label, value }) => {
                const li = document.createElement('li');
                li.className = 'list-group-item d-flex justify-content-between align-items-center';
                const left = document.createElement('span');
                left.innerHTML = label;
                const right = document.createElement('span');
                right.className = 'fw-bold';
                right.textContent = value;
                li.appendChild(left);
                li.appendChild(right);
                list.appendChild(li);
            });
            card.appendChild(cardHeader);
            card.appendChild(list);
            col.appendChild(card);
            return col;
        };

        row.appendChild(createCard(`<i class="bi bi-moon-stars icon-inline" aria-hidden="true"></i>${i18n.t('common.moon')}`, [
            { label: `<i class="bi bi-sunrise icon-inline" aria-hidden="true"></i>${i18n.t('moon.rise')}`, value: formatTimeThenDate(moon.next_moonrise) },
            { label: `<i class="bi bi-sunset icon-inline" aria-hidden="true"></i>${i18n.t('moon.set')}`, value: formatTimeThenDate(moon.next_moonset) }
        ]));
        row.appendChild(createCard(`<i class="bi bi-compass icon-inline" aria-hidden="true"></i>${i18n.t('moon.position')}`, [
            { label: `<i class="bi bi-rulers icon-inline" aria-hidden="true"></i>${i18n.t('moon.distance')}`, value: moon.distance_km ? `${Math.round(moon.distance_km).toLocaleString()} ${i18n.t('units.km')}` : i18n.t('units.na') },
            { label: `<i class="bi bi-arrows-angle-expand icon-inline" aria-hidden="true"></i>${i18n.t('moon.altitude')}`, value: moon.altitude_deg ? `${moon.altitude_deg.toFixed(2)}${i18n.t('units.degrees')}` : i18n.t('units.na') },
            { label: `<i class="bi bi-compass icon-inline" aria-hidden="true"></i>${i18n.t('moon.azimuth')}`, value: moon.azimuth_deg ? `${moon.azimuth_deg.toFixed(2)}${i18n.t('units.degrees')}` : i18n.t('units.na') }
        ]));

        const next_full_moon_txt = moon.next_full_moon === 'Not found' ? i18n.t('best_window.not_found') : formatTimeThenDate(new Date(moon.next_full_moon));
        const next_new_moon_txt = moon.next_new_moon === 'Not found' ? i18n.t('best_window.not_found') : formatTimeThenDate(new Date(moon.next_new_moon));
        const next_dark_night_start_txt = moon.next_dark_night_start === 'Not found' ? i18n.t('best_window.not_found') : formatTimeThenDate(new Date(moon.next_dark_night_start));

        row.appendChild(createCard(`<i class="bi bi-calendar-event text-danger icon-inline" aria-hidden="true"></i>${i18n.t('moon.next_events')}`, [
            { label: `<i class="bi bi-moon-stars-fill icon-inline" aria-hidden="true"></i>${i18n.t('moon.next_full_moon')}`, value: next_full_moon_txt },
            { label: `<i class="bi bi-moon-fill icon-inline" aria-hidden="true"></i>${i18n.t('moon.next_new_moon')}`, value: next_new_moon_txt },
            { label: `<i class="bi bi-stars icon-inline" aria-hidden="true"></i>${i18n.t('moon.next_dark_night')}`, value: next_dark_night_start_txt }
        ]));

        container.appendChild(header);
        container.appendChild(row);
    }
}

//Load next moon phases
async function loadNextMoonPhases() {
    const container = document.getElementById('moon-planner-display');
    const data = await fetchJSONWithUI('/api/moon/next-7-nights', container, 'Loading Moon planner data...', {
        pendingMessage: i18n.t('cache.cache_not_ready_retrying'),
    });
    if (!data) return;

    try {
        // Check if container has weather-grid class, if not add it
        if (!container.classList.contains('weather-grid')) {
            container.classList.add('weather-grid');
        }

        clearContainer(container);

        // if forecast list is available
        if (data.next_7_nights && data.next_7_nights.length > 0) {
            // Class grid to container
            container.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-4 row-cols-xl-5 row-cols-xxl-6 mb-3';

            // We receive up to 12 hours of data, display all
            data.next_7_nights.forEach(moon => {
                const date = new Date(moon.date);
                const astrophoto_score = moon.astrophoto_score.toFixed(0);
                const dark_hours_illumination = moon.dark_hours.illumination.toFixed(2);
                const dark_hours_practical = moon.dark_hours.practical.toFixed(2);
                const dark_hours_strict = moon.dark_hours.strict.toFixed(2);
                const illumination_percent = moon.moon.illumination_percent.toFixed(0);
                const max_altitude = moon.moon.max_altitude;

                // Determine observation quality based on condition
                let quality = '';
                let qualityClass = '';
                if (astrophoto_score >= 90) {
                    quality = `${i18n.t('common.quality_scale.excellent')} - ${astrophoto_score}%`;
                    qualityClass = 'quality-excellent';
                } else if (astrophoto_score >= 70) {
                    quality = `${i18n.t('common.quality_scale.good')} - ${astrophoto_score}%`;
                    qualityClass = 'quality-good';
                } else if (astrophoto_score >= 50) {
                    quality = `${i18n.t('common.quality_scale.fair')} - ${astrophoto_score}%`;
                    qualityClass = 'quality-fair';
                } else if (astrophoto_score > 30) {
                    quality = `${i18n.t('common.quality_scale.poor')} - ${astrophoto_score}%`;
                    qualityClass = 'quality-poor';
                } else {
                    quality = `${i18n.t('common.quality_scale.bad')} - ${astrophoto_score}%`;
                    qualityClass = 'quality-bad';
                }

                const item = document.createElement('div');
                item.className = 'col mb-3';
                const card = document.createElement('div');
                card.className = 'card h-100';
                const cardHeader = document.createElement('div');
                cardHeader.className = `card-header quality-box ${qualityClass}`;
                const strong = document.createElement('strong');
                strong.textContent = quality;
                cardHeader.appendChild(strong);

                const cardBody = document.createElement('div');
                cardBody.className = 'card-body';
                const title = document.createElement('h5');
                title.className = 'card-title card-title-weather mb-2';
                title.textContent = formatDateFull(date);
                const list = document.createElement('ul');
                list.className = 'list-group list-group-flush';

                const addItem = (label, value = null) => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item d-flex justify-content-between align-items-center';
                    const labelSpan = document.createElement('span');
                    labelSpan.innerHTML = label;
                    li.appendChild(labelSpan);
                    if (value !== null) {
                        const span = document.createElement('span');
                        span.textContent = value;
                        li.appendChild(span);
                    }
                    list.appendChild(li);
                };

                addItem(`<i class="bi bi-moon text-warning icon-inline" aria-hidden="true"></i>${i18n.t('moon.illumination')}`, `${illumination_percent}${i18n.t('units.percent')}`);
                addItem(`<i class="bi bi-arrows-angle-expand icon-inline" aria-hidden="true"></i>${i18n.t('moon.max_altitude')}`, `${max_altitude}${i18n.t('units.degrees')}`);
                addItem(`<i class="bi bi-stars icon-inline" aria-hidden="true"></i>${i18n.t('moon.dark_time')}`);
                addItem(` > ${i18n.t('best_window.strict')}`, `${dark_hours_strict} ${i18n.t('units.hour')}`);
                addItem(` > ${i18n.t('best_window.practical')}`, `${dark_hours_practical} ${i18n.t('units.hour')}`);
                addItem(` > ${i18n.t('best_window.illumination')}`, `${dark_hours_illumination} ${i18n.t('units.hour')}`);

                cardBody.appendChild(title);
                cardBody.appendChild(list);
                card.appendChild(cardHeader);
                card.appendChild(cardBody);
                item.appendChild(card);
                container.appendChild(item);
            });
        }

    } catch (error) {
        console.error('Error loading moon data:', error);
        DOMUtils.clear(container);
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger';
        alert.textContent = 'Failed to load moon data';
        container.appendChild(alert);
    }
}

// Guard to prevent concurrent calls to loadBestDarkWindow
let isLoadingBestDarkWindow = false;

//Load best observing nights
async function loadBestDarkWindow() {
    // Prevent concurrent calls
    if (isLoadingBestDarkWindow) {
        console.log('loadBestDarkWindow already in progress, skipping...');
        return;
    }
    
    isLoadingBestDarkWindow = true;
    
    try {
        const container = document.getElementById('window-display');
        const containerLoader = document.getElementById('window-loader-info-notice');
        const sectionContainer = document.getElementById('save-actions-section');

        // Ensure we do not keep stale/duplicate footer nodes between reloads.
        if (sectionContainer) {
            const existingFooter = sectionContainer.querySelector('.js-window-data-source-footer');
            if (existingFooter && existingFooter.parentNode) {
                existingFooter.parentNode.removeChild(existingFooter);
            }
        }
        
        // Clear container and reset loader at the very beginning
        DOMUtils.clear(container);
        containerLoader.className = 'alert alert-info';
        containerLoader.textContent = i18n.t('best_window.loading_best_window');
        containerLoader.style.display = 'block';

        const retryOptions = {
            maxAttempts: 6,
            baseDelayMs: 1000,
            maxDelayMs: 12000,
            timeoutMs: 15000,
            shouldRetryData: (payload) => payload && payload.status === 'pending',
            onRetry: ({ reason, attempt, maxAttempts, waitMs, data }) => {
                const seconds = Math.max(1, Math.round(waitMs / 1000));
                if (reason === 'data' && data && data.message) {
                    containerLoader.textContent = `${data.message} ${i18n.t('common.retrying_in', { seconds, attempt, maxAttempts })}`;
                    return;
                }
                containerLoader.textContent = i18n.t('common.retrying_in', { seconds, attempt, maxAttempts });
            }
        };

        try {
            // Fake error to catch error display
            //throw new Error('Test error');

            // Get dark window
            const data = await fetchJSONWithRetry('/api/moon/dark-window', {}, retryOptions);

        // Cache pending (retries exhausted)
        if (data.status && data.status === 'pending') {
            DOMUtils.clear(container);
            const infoNotice = document.createElement('div');
            infoNotice.className = 'info-notice';
            infoNotice.textContent = data.message || '';
            container.appendChild(infoNotice);
            containerLoader.style.display = 'none';
            return;
        }

        // Check if dark window data exists
        if (!data.next_dark_night || !data.next_dark_night.start || !data.next_dark_night.end) {
            DOMUtils.clear(container);
            const errorBox = document.createElement('div');
            errorBox.className = 'error-box';
            errorBox.textContent = i18n.t('best_window.no_dark_window_data');
            container.appendChild(errorBox);
            containerLoader.style.display = 'none';
            return;
        }

        const start_txt = data.next_dark_night.start === 'Not found' ? i18n.t('best_window.not_found') : formatTimeThenDate(new Date(data.next_dark_night.start));
        const end_txt = data.next_dark_night.end === 'Not found' ? i18n.t('best_window.not_found') : formatTimeThenDate(new Date(data.next_dark_night.end));

        // Bloc normal
        const item = document.createElement("div");
        item.className = "col mb-3";
        const card = document.createElement('div');
        card.className = 'card h-100';
        const header = document.createElement('div');
        header.className = 'card-header';
        header.innerHTML = `<i class="bi bi-stars icon-inline" aria-hidden="true"></i>${i18n.t('best_window.next_window')}`;
        const list = document.createElement('ul');
        list.className = 'list-group list-group-flush';
        const addTiming = (labelText, valueText) => {
            const li = document.createElement('li');
            li.className = 'list-group-item d-flex justify-content-between align-items-center';
            const label = document.createElement('span');
            label.innerHTML = labelText;
            const value = document.createElement('span');
            value.textContent = valueText;
            li.appendChild(label);
            li.appendChild(value);
            list.appendChild(li);
        };
        addTiming(`<i class="bi bi-sunset icon-inline" aria-hidden="true"></i>${i18n.t('best_window.start')}`, start_txt);
        addTiming(`<i class="bi bi-sunrise icon-inline" aria-hidden="true"></i>${i18n.t('best_window.end')}`, end_txt);
        card.appendChild(header);
        card.appendChild(list);
        item.appendChild(card);
        container.appendChild(item);


        
        const modes = ["strict", "practical", "illumination"];

        const bestWindowsResponse = await fetchJSONWithRetry('/api/tonight/best-window?mode=all', {}, {
            ...retryOptions,
            onRetry: null
        });

        const bestWindowsByMode = bestWindowsResponse && bestWindowsResponse.modes
            ? bestWindowsResponse.modes
            : {};

        for (const mode of modes) {
            const modeData = bestWindowsByMode[mode];

            if (!modeData || modeData.status === 'pending' || modeData.error || !modeData.best_window || !modeData.best_window.start) {
                const errorItem = document.createElement("div");
                errorItem.className = "col mb-3";
                const message = modeData && modeData.status === 'pending'
                    ? modeData.message || i18n.t('cache.cache_updating')
                    : i18n.t('best_window.no_dark_window');
                const errorCard = document.createElement('div');
                errorCard.className = 'card h-100';
                const errorHeader = document.createElement('div');
                errorHeader.className = 'card-header';
                errorHeader.textContent = mode.toUpperCase();
                const errorBody = document.createElement('div');
                errorBody.className = 'card-body';
                const errorText = document.createElement('div');
                errorText.className = 'card-text';
                errorText.textContent = message;
                errorBody.appendChild(errorText);
                errorCard.appendChild(errorHeader);
                errorCard.appendChild(errorBody);
                errorItem.appendChild(errorCard);
                container.appendChild(errorItem);
                continue;
            }

            let start_txt = "";
            let end_txt = "";

            if(modeData.best_window.start == 'Not found') {
                start_txt = i18n.t('best_window.not_found');
            } else {
                const start = new Date(modeData.best_window.start);
                start_txt = `${formatTimeThenDate(start)}`;
                
            }
            if(modeData.best_window.end == 'Not found') {
                end_txt = i18n.t('best_window.not_found');
            } else {
                const end = new Date(modeData.best_window.end);
                end_txt = `${formatTimeThenDate(end)}`;
                
            }

            // Mode Translate            
            let modeTranslated = "";
            switch (mode.toLowerCase()) {
                case 'strict': 
                    modeTranslated = i18n.t('best_window.strict');
                    break;
                case 'practical':
                    modeTranslated = i18n.t('best_window.practical');
                    break;
                case 'illumination':
                    modeTranslated = i18n.t('best_window.illumination');
                    break;
                case 'unfavorable':
                    modeTranslated = i18n.t('best_window.unfavorable');
                    break;
                default:
                    modeTranslated = mode;
                    break;
            }

            // Bloc normal
            const item = document.createElement("div");
            item.className = "col mb-3";
            const modeCard = document.createElement('div');
            modeCard.className = 'card h-100';
            const modeHeader = document.createElement('div');
            modeHeader.className = 'card-header';
            modeHeader.textContent = modeTranslated.toUpperCase();
            const modeList = document.createElement('ul');
            modeList.className = 'list-group list-group-flush';
            const addModeItem = (labelText, valueText) => {
                const li = document.createElement('li');
                li.className = 'list-group-item d-flex justify-content-between align-items-center';
                const label = document.createElement('span');
                label.innerHTML = labelText;
                li.appendChild(label);
                const span = document.createElement('span');
                span.textContent = valueText;
                li.appendChild(span);
                modeList.appendChild(li);
            };
            let moonConditionText = "";
            switch (modeData.best_window.moon_condition.toLowerCase()) {
                case 'strict': 
                    moonConditionText = i18n.t('best_window.strict');
                    break;
                case 'practical':
                    moonConditionText = i18n.t('best_window.practical');
                    break;
                case 'illumination':
                    moonConditionText = i18n.t('best_window.illumination');
                    break;
                case 'unfavorable':
                    moonConditionText = i18n.t('best_window.unfavorable');
                    break;
                default:
                    moonConditionText = modeData.best_window.moon_condition;
                    break;
            }
            addModeItem(`<i class="bi bi-activity icon-inline" aria-hidden="true"></i>${i18n.t('best_window.score')}`, String(modeData.best_window.score));
            addModeItem(`<i class="bi bi-moon-stars icon-inline" aria-hidden="true"></i>${i18n.t('best_window.moon_condition')}`, moonConditionText);
            addModeItem(`<i class="bi bi-sunset icon-inline" aria-hidden="true"></i>${i18n.t('best_window.start')}`, start_txt);
            addModeItem(`<i class="bi bi-sunrise icon-inline" aria-hidden="true"></i>${i18n.t('best_window.end')}`, end_txt);
            modeCard.appendChild(modeHeader);
            modeCard.appendChild(modeList);
            item.appendChild(modeCard);

            container.appendChild(item);
        }

        if (sectionContainer) {
            const footer = createDataSourceFooter({
                text: i18n.t('moon.footer_source_best_window')
            });
            footer.classList.add('js-window-data-source-footer');
            sectionContainer.appendChild(footer);
        }

        
            containerLoader.style.display = 'none';

        } catch (error) {
            console.error('Error loading dark window data:', error);
            DOMUtils.clear(container);
            containerLoader.className = 'alert alert-danger';
            containerLoader.textContent = i18n.t('best_window.failed_to_load_dark_window_data');
            containerLoader.style.display = 'block';
        }
    } finally {
        // Always reset the loading flag
        isLoadingBestDarkWindow = false;
    }
}