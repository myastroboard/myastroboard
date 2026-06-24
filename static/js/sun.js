// ======================
// Sun 
// ======================

//Load Sun data for today
async function loadSun() {
    const container = document.getElementById('sun-display');
    const data = await fetchJSONWithUI('/api/sun/today', container, 'Loading Sun data...', {
        pendingMessage: i18n.t('cache.cache_not_ready_retrying')
    });
    if (!data) return;

    try {
        // Empty container
        clearContainer(container);

        // Display sun information
        const header = document.createElement('div');
        header.className = 'd-flex flex-row align-items-center mb-3';

        const icon = document.createElement('div');
        icon.className = 'p-2';
        const sunVisual = document.createElement('img');
        sunVisual.src = '/static/img/sun.svg';
        sunVisual.alt = i18n.t('common.sun');
        sunVisual.width = 80;
        sunVisual.height = 80;
        sunVisual.loading = 'lazy';
        icon.appendChild(sunVisual);
        const titleWrap = document.createElement('div');
        titleWrap.className = 'p-2';
        const title = document.createElement('div');
        title.className = 'fw-bold fs-4';
        title.textContent = i18n.t('sun.sun_and_twilight');
        const subtitle = document.createElement('div');
        subtitle.textContent = i18n.t('sun.for_astronomical_observation_planning');
        titleWrap.appendChild(title);
        titleWrap.appendChild(subtitle);
        header.appendChild(icon);
        header.appendChild(titleWrap);

        const cardsRow = document.createElement('div');
        cardsRow.className = 'row row-cols-1 row-cols-sm-2 row-cols-lg-2 row-cols-xl-4 p-2 mb-3';

        const createTimeCard = (headerIconClass, headerLabelText, duskIconClass, duskLabelText, duskValue, dawnIconClass, dawnLabelText, dawnValue) => {
            const col = document.createElement('div');
            col.className = 'col mb-3';
            const card = document.createElement('div');
            card.className = 'card h-100';
            const cardHeader = document.createElement('div');
            cardHeader.className = 'card-header fw-bold';
            DOMUtils.append(cardHeader, DOMUtils.createIcon(headerIconClass), headerLabelText);

            const list = document.createElement('ul');
            list.className = 'list-group list-group-flush';

            const createItem = (iconClass, labelText, value) => {
                const li = document.createElement('li');
                li.className = 'list-group-item d-flex justify-content-between align-items-center';
                const labelSpan = document.createElement('span');
                if (iconClass) {
                    DOMUtils.append(labelSpan, DOMUtils.createIcon(iconClass), labelText);
                } else {
                    labelSpan.textContent = labelText;
                }
                const valueSpan = document.createElement('span');
                valueSpan.className = 'fw-bold';
                valueSpan.textContent = value;
                li.appendChild(labelSpan);
                li.appendChild(valueSpan);
                return li;
            };

            list.appendChild(createItem(duskIconClass, duskLabelText, duskValue));
            list.appendChild(createItem(dawnIconClass, dawnLabelText, dawnValue));
            card.appendChild(cardHeader);
            card.appendChild(list);
            col.appendChild(card);
            return col;
        };

        cardsRow.appendChild(createTimeCard(
            'bi bi-sun icon-inline', i18n.t('common.sun'),
            'bi bi-sunset icon-inline', i18n.t('sun.sunset'), formatTimeThenDate(new Date(data.sun.sunset)),
            'bi bi-sunrise icon-inline', i18n.t('sun.sunrise'), formatTimeThenDate(new Date(data.sun.sunrise))
        ));
        cardsRow.appendChild(createTimeCard(
            'bi bi-brightness-low icon-inline', i18n.t('sun.civil_twilight'),
            '', i18n.t('sun.dusk'), formatTimeThenDate(new Date(data.sun.civil_dusk)),
            '', i18n.t('sun.dawn'), formatTimeThenDate(new Date(data.sun.civil_dawn))
        ));
        cardsRow.appendChild(createTimeCard(
            'bi bi-compass icon-inline', i18n.t('sun.nautical_twilight'),
            '', i18n.t('sun.dusk'), formatTimeThenDate(new Date(data.sun.nautical_dusk)),
            '', i18n.t('sun.dawn'), formatTimeThenDate(new Date(data.sun.nautical_dawn))
        ));
        cardsRow.appendChild(createTimeCard(
            'bi bi-stars icon-inline', i18n.t('sun.astronomical_twilight'),
            '', i18n.t('sun.dusk'), formatTimeThenDate(new Date(data.sun.astronomical_dusk)),
            '', i18n.t('sun.dawn'), formatTimeThenDate(new Date(data.sun.astronomical_dawn))
        ));

        container.appendChild(header);
        container.appendChild(cardsRow);
        
    } catch (error) {
        console.error('Error loading weather:', error);
        DOMUtils.clear(container);
        const errorBox = document.createElement('div');
        errorBox.className = 'error-box';
        errorBox.textContent = 'Failed to load Sun data';
        container.appendChild(errorBox);
    }
}

function _checkSunN6(data) {
    if (typeof notificationManager === 'undefined') return;
    if (!notificationManager.isTriggerEnabled('N6')) return;

    const duskIso = data?.next_astronomical_dusk_utc;
    if (!duskIso) return;

    const dusk = new Date(duskIso).getTime();
    if (isNaN(dusk)) return;
    const now    = Date.now();
    const msUntil = dusk - now;
    const leadMs  = notificationManager.getLeadMinutes('N6') * 60 * 1000;

    if (msUntil <= 0 || msUntil > leadMs) return;
    if (notificationManager.wasRecentlyNotified('N6', 8 * 60 * 60 * 1000)) return; // once per day

    const minutes = Math.round(msUntil / 60000);
    notificationManager.notify(
        'N6',
        i18n.t('notifications.n6_title'),
        i18n.t('notifications.n6_body', { minutes }),
        { url: '#forecast-astro/astro-weather' }
    );
}