/**
 * Events Alert System for MyAstroBoard
 * 
 * Displays upcoming astronomical events as alerts/banners on the dashboard
 * with options to share as images on social media
 */

const API_ENDPOINT_EVENTS = `${API_BASE}/api/events/upcoming`;

// Cache for events data
let cachedEvents = null;
let lastEventsUpdate = null;
const EVENTS_CACHE_DURATION = 5 * 60 * 1000; // 5 minutes
const EVENTS_ROTARY_INTERVAL = 5000; // 5 seconds
let eventsRotaryIntervalId = null;

function resolveEventIconClass(event) {
    return event?.icon_class || 'bi bi-star-fill';
}

function resolveEventBannerModifier(event) {
    const map = {
        'text-danger':    'critical',
        'text-warning':   'high',
        'text-info':      'medium',
        'text-secondary': 'low',
    };
    return map[event?.icon_color_class] || 'medium';
}

/**
 * Initialize events alert system
 */
function initializeEventsSystem() {
    loadAndDisplayEvents();
    
    // Refresh events periodically
    setInterval(loadAndDisplayEvents, 10 * 60 * 1000); // Every 10 minutes
}

/**
 * Clear events cache to force refresh
 */
function clearEventsCache() {
    cachedEvents = null;
    lastEventsUpdate = null;
}

/**
 * Load upcoming events from API
 */
async function loadAndDisplayEvents() {
    try {
        // Ensure translations are loaded before rendering any i18n strings
        await i18n.ready;

        // Check cache first
        const now = new Date().getTime();
        if (cachedEvents && lastEventsUpdate && (now - lastEventsUpdate) < EVENTS_CACHE_DURATION) {
            displayEvents(cachedEvents);
            return;
        }

        const currentLang = (typeof i18n !== 'undefined' && typeof i18n.getCurrentLanguage === 'function')
            ? i18n.getCurrentLanguage()
            : 'en';
        const response = await fetch(`${API_ENDPOINT_EVENTS}?lang=${encodeURIComponent(currentLang)}`);
        
        if (!response.ok) {
            console.warn(`Failed to fetch events: ${response.status}`);
            return;
        }

        const eventsData = await response.json();
        cachedEvents = eventsData;
        lastEventsUpdate = new Date().getTime();
        displayEvents(eventsData);
    } catch (error) {
        console.error("Error loading events:", error);
    }
}

/**
 * Display events in the alerts container & timeline section
 */
function displayEvents(eventsData) {
    const container = document.getElementById('events-alerts-container');
    if (!container) {
        console.warn("Events alert container not found in DOM");
        return;
    }

    const timelineContainer = document.getElementById('calendar-display');
    if (!timelineContainer) {
        console.warn("Events timeline container not found in DOM");
        return;
    }

    // Clear existing alerts
    DOMUtils.clear(container);
    DOMUtils.clear(timelineContainer);
    stopEventsRotary();

    // Check if we have any upcoming events
    const nextEvent = eventsData.next_event;
    const eventsIn30Days = eventsData.events_next_30_days || [];    
    const visibleEvents = eventsIn30Days.filter(event => event.visibility);
    //const visibleEvents = eventsIn30Days; // Debug to see some events regardless of visibility for now

    //console.log("Events data received:", eventsData);
    //console.log("Next event:", nextEvent);
    //console.log("All events in next 30 days:", eventsIn30Days);
    //console.log("Visible events in next 30 days:", visibleEvents);


    // TIMELINE EVENTS MANAGEMENTS
    // No events to display in timeline
    if (!nextEvent || eventsIn30Days.length === 0) {
        const noEventsMsg = document.createElement('div');
        noEventsMsg.className = 'alert alert-info';
        noEventsMsg.textContent = i18n.t('calendar.no_significant_events');
        timelineContainer.appendChild(noEventsMsg);

    // Events to display in timeline 
    } else {
        // Create event timeline
        const eventTimelineItems = createEventTimeline(eventsIn30Days);        
        timelineContainer.appendChild(eventTimelineItems);
    }

    // BANNER EVENTS MANAGEMENT
    // If no next event or no visible events, hide the events banner
    if (!nextEvent || visibleEvents.length === 0) {
        // No events to display
        container.style.display = 'none';
        return;
    }

    // Show the events banner
    container.style.display = 'block';

    // Display up to first 3 events in continuous rotary banner
    if (visibleEvents && visibleEvents.length > 0) {
        const rotaryEvents = visibleEvents.slice(0, 3);
        startEventsRotary(container, rotaryEvents);
    }
}

function stopEventsRotary() {
    if (eventsRotaryIntervalId) {
        clearInterval(eventsRotaryIntervalId);
        eventsRotaryIntervalId = null;
    }
}

function startEventsRotary(container, events) {
    if (!container || !events || events.length === 0) {
        return;
    }

    let currentIndex = 0;
    DOMUtils.clear(container);
    container.appendChild(createEventAlertCard(events[currentIndex]));

    if (events.length === 1) {
        return;
    }

    // Build dots navigation
    const dotsNav = document.createElement('div');
    dotsNav.className = 'event-banner-dots';
    events.forEach((_, i) => {
        const dot = document.createElement('span');
        dot.className = 'event-banner-dot' + (i === 0 ? ' active' : '');
        dot.addEventListener('click', () => {
            currentIndex = i;
            if (eventsRotaryIntervalId) {
                clearInterval(eventsRotaryIntervalId);
                eventsRotaryIntervalId = null;
            }
            showEvent(currentIndex);
            eventsRotaryIntervalId = setInterval(() => {
                currentIndex = (currentIndex + 1) % events.length;
                showEvent(currentIndex);
            }, EVENTS_ROTARY_INTERVAL);
        });
        dotsNav.appendChild(dot);
    });
    container.appendChild(dotsNav);

    function showEvent(idx) {
        const existing = container.querySelector('.event-banner');
        if (existing) existing.remove();
        container.insertBefore(createEventAlertCard(events[idx]), dotsNav);
        dotsNav.querySelectorAll('.event-banner-dot').forEach((dot, i) => {
            dot.classList.toggle('active', i === idx);
        });
    }

    eventsRotaryIntervalId = setInterval(() => {
        currentIndex = (currentIndex + 1) % events.length;
        showEvent(currentIndex);
    }, EVENTS_ROTARY_INTERVAL);
}

/**
 * Create a prominent banner card for an event
 */
function createEventAlertCard(event) {
    const banner = document.createElement('div');
    banner.className = `event-banner event-banner--${resolveEventBannerModifier(event)}`;

    // Left icon circle
    const iconWrap = document.createElement('div');
    iconWrap.className = 'event-banner__icon';
    iconWrap.appendChild(DOMUtils.createIcon(resolveEventIconClass(event), 'icon-inline'));
    banner.appendChild(iconWrap);

    // Content area
    const content = document.createElement('div');
    content.className = 'event-banner__content';

    const titleEl = document.createElement('div');
    titleEl.className = 'event-banner__title';
    titleEl.textContent = event.title || '';
    content.appendChild(titleEl);

    if (event.description) {
        const descEl = document.createElement('div');
        descEl.className = 'event-banner__desc';
        descEl.textContent = event.description;
        content.appendChild(descEl);
    }

    if (event.peak_time && event.days_until_event !== undefined) {
        const metaEl = document.createElement('div');
        metaEl.className = 'event-banner__meta';
        metaEl.appendChild(DOMUtils.createIcon('bi bi-calendar-event text-danger', 'icon-inline me-1'));
        metaEl.appendChild(document.createTextNode(`${formatTimeThenDate(new Date(event.peak_time))} · ${getDaysUntilText(event.days_until_event)}`));
        content.appendChild(metaEl);
    }

    banner.appendChild(content);

    // Action button
    const actionEl = document.createElement('div');
    actionEl.className = 'event-banner__action';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm event-banner__btn';
    btn.appendChild(DOMUtils.createIcon('bi bi-journal-text', 'icon-inline'));
    btn.appendChild(document.createTextNode(' ' + i18n.t('calendar.details')));
    btn.addEventListener('click', (e) => {
        e.preventDefault();
        scrollToEventDetails(event.event_type, event.structure_key);
    });
    actionEl.appendChild(btn);
    banner.appendChild(actionEl);

    return banner;
}

/**
 * Create timeline items for a list of events
 */
function createEventTimeline(events) {
    const timelineListUl = document.createElement('ul');
    timelineListUl.className = 'timeline-with-icons ms-3';

    events.forEach(event => {
        //console.log(event);

        const item = document.createElement('li');
        item.className = 'timeline-item mb-3 rounded p-2 ps-3';

        // Icon
        const iconSpan = document.createElement('span');
        iconSpan.className = 'timeline-icon';
        iconSpan.appendChild(DOMUtils.createIcon(resolveEventIconClass(event), 'text-white'));        
        // Class following the event visibility true/false
        const visibilityBadge = document.createElement('span');
        visibilityBadge.classList.add('badge', 'ms-2', 'bg-opacity-75');
        if (event.visibility) {
            iconSpan.classList.add('bg-success');
            visibilityBadge.classList.add('bg-success');
            visibilityBadge.textContent = i18n.t('calendar.visible');
        } else {
            iconSpan.classList.add('bg-danger');
            visibilityBadge.classList.add('bg-danger');
            visibilityBadge.textContent = i18n.t('calendar.invisible');
        }
        // Add opacity to bg
        //iconSpan.classList.add('bg-opacity-50');
        item.appendChild(iconSpan);
        
        //Second badge after visible for importance level
        const importanceBadge = document.createElement('span');
        importanceBadge.classList.add('badge', 'ms-1', 'bg-opacity-75');
        // inline replace string text-* by bg-* for badge color        
        importanceBadge.classList.add(event.icon_color_class.replace('text-', 'bg-'));
        if (event.importance === 'critical') {
            importanceBadge.appendChild(DOMUtils.createIcon('bi bi-star-fill', 'icon-inline me-1'));
        }
        importanceBadge.appendChild(document.createTextNode(i18n.t(`calendar.importance.${event.importance}`)));

        // Title
        const title = document.createElement('h5');
        title.className = 'fw-bold';
        title.textContent = `${event.title || ''}`;
        title.appendChild(visibilityBadge);
        title.appendChild(importanceBadge);
        item.appendChild(title);

        // Add timing information if available
        if (event.peak_time && event.days_until_event !== undefined) {
            const date = document.createElement('p');
            date.className = 'text-muted fw-bold';
            date.appendChild(DOMUtils.createIcon('bi bi-calendar-event text-danger', 'icon-inline'));
            date.appendChild(document.createTextNode(`${formatTimeThenDate(new Date(event.peak_time))} - ${getDaysUntilText(event.days_until_event)}`));
            item.appendChild(date);
        }

        // Description
        const description = document.createElement('p');
        description.className = 'text-muted';
        description.textContent = event.description ?? '';
        item.appendChild(description);

        timelineListUl.appendChild(item);
    });

    return timelineListUl;
}


/**
 * Get human-readable text for days until event
 */
function getDaysUntilText(daysUntil) {
    if (daysUntil < 0) return i18n.t('calendar.happening_now');
    if (daysUntil === 0) return i18n.t('calendar.today');
    if (daysUntil === 1) return i18n.t('calendar.tomorrow');
    if (daysUntil <= 7) return i18n.t('calendar.in_days', { days: daysUntil });
    return i18n.t('calendar.in_days', { days: daysUntil });
}

/**
 * Generate and download shareable image for an event
 */
/**
 * Scroll to event details section
 */
function scrollToEventDetails(eventType, structureKey = null) {
    const normalizedEventType = String(eventType || '').toLowerCase();
    const normalizedStructureKey = String(structureKey || '').toLowerCase();

    let mainTabName = 'forecast-astro';
    let subTabName = '';

    if (normalizedStructureKey) {
        const structureMap = {
            moon: 'moon',
            sun: 'sun',
            aurora: 'aurora',
            iss: 'orbital-stations',
            css: 'orbital-stations',
            calendar: 'calendar'
        };
        subTabName = structureMap[normalizedStructureKey] || '';
    }

    // Map event types to corresponding tabs
    if (!subTabName && normalizedEventType.includes('eclipse')) {
        subTabName = normalizedEventType.includes('solar') ? 'sun' : 'moon';
    } else if (!subTabName && normalizedEventType === 'aurora') {
        subTabName = 'aurora';
    } else if (!subTabName && (normalizedEventType.includes('iss') || normalizedEventType.includes('css'))) {
        subTabName = 'orbital-stations';
    } else if (!subTabName && normalizedEventType === 'moon phase') {
        subTabName = 'moon';
    } else if (!subTabName && (normalizedEventType.includes('planetary') || 
               normalizedEventType.includes('conjunction') || 
               normalizedEventType.includes('opposition') || 
               normalizedEventType.includes('elongation') || 
               normalizedEventType.includes('retrograde'))) {
        // Navigate to calendar for planetary events overview
        subTabName = 'calendar';
    } else if (!subTabName && (normalizedEventType.includes('equinox') || 
               normalizedEventType.includes('solstice') || 
               normalizedEventType.includes('zodiacal light') || 
               normalizedEventType.includes('milky way'))) {
        // Navigate to calendar for special phenomena overview
        subTabName = 'calendar';
    } else if (!subTabName && (normalizedEventType.includes('meteor shower') || 
               normalizedEventType.includes('comet') || 
               normalizedEventType.includes('asteroid occultation'))) {
        // Navigate to calendar for solar system events overview
        subTabName = 'calendar';
    } else if (!subTabName && normalizedEventType.includes('sidereal')) {
        // Navigate to calendar for sidereal time info
        subTabName = 'calendar';
    } else if (!subTabName) {
        // Default to calendar for any unknown event types
        subTabName = 'calendar';
    }

    if (subTabName === 'orbital-stations') {
        // Orbital Stations details live under Spaceflight tab, not Astrophotography.
        mainTabName = 'spaceflight';
    }

    // First, make sure the target main tab is active
    const mainTab = document.querySelector(`[data-tab="${mainTabName}"]`);
    if (mainTab) {
        mainTab.click();
    }
    
    // Then trigger the sub-tab switch
    setTimeout(() => {
        const subTab = document.querySelector(`[data-subtab="${subTabName}"]`);
        if (subTab) {
            subTab.click();
            // Scroll to top after tab switch
            setTimeout(() => window.scrollTo(0, 0), 100);
        }
    }, 100);
}

// Initialize when document is ready
document.addEventListener('DOMContentLoaded', initializeEventsSystem);

window.addEventListener('i18nLanguageChanged', () => {
    clearEventsCache();
    loadAndDisplayEvents();
});

function _checkEclipseNotifications(eventsData) {
    if (typeof notificationManager === 'undefined') return;
    const events = eventsData?.events;
    if (!Array.isArray(events)) return;

    const now    = Date.now();

    for (const event of events) {
        const peakTime = event.peak_time ? new Date(event.peak_time).getTime() : null;
        if (!peakTime || peakTime <= now) continue;

        const type = event.event_type;
        let triggerId, titleKey, bodyKey;

        if (type === 'Lunar Eclipse' && notificationManager.isTriggerEnabled('N4')) {
            triggerId = 'N4'; titleKey = 'notifications.n4_title'; bodyKey = 'notifications.n4_body';
        } else if (type === 'Solar Eclipse' && notificationManager.isTriggerEnabled('N5')) {
            triggerId = 'N5'; titleKey = 'notifications.n5_title'; bodyKey = 'notifications.n5_body';
        } else {
            continue;
        }

        const leadMs  = notificationManager.getLeadMinutes(triggerId) * 60 * 1000;
        const msUntil = peakTime - now;
        if (msUntil > leadMs) continue;
        if (notificationManager.wasRecentlyNotified(triggerId, 4 * 60 * 60 * 1000)) continue;

        const minutes = Math.round(msUntil / 60000);
        notificationManager.notify(
            triggerId,
            i18n.t(titleKey),
            i18n.t(bodyKey, { minutes }),
            { url: '#forecast-astro/moon' }
        );
        break; // one eclipse notification per check cycle
    }
}
