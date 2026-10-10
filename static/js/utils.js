/* =====================
   Utils
   ===================== */


function showMessage(type, message) {
    //type available: 'success', 'error', 'warning', 'info'
    const colorMap = {
        success: '#10b981',
        error: '#ef4444',
        warning: '#f59e0b',
        info: '#3b82f6'
    };
    const color = colorMap[type] || '#ef4444';
    const messageDiv = document.createElement('div');
    messageDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${color};
        color: white;
        padding: 15px 25px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 10000;
        font-weight: 600;
        animation: slideIn 0.3s ease-out;
    `;
    messageDiv.textContent = message;
    document.body.appendChild(messageDiv);

    setTimeout(() => {
        messageDiv.style.animation = 'slideOut 0.3s ease-in';
        setTimeout(() => messageDiv.remove(), 300);
    }, 3000);
}

function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

// =======================
// Leaflet maps: loading and basemaps (OpenStreetMap, proxied and cached by the server)
// =======================

// The browser only talks to our own server: /api/map-tiles fetches every map resource from the
// OpenStreetMap servers once and caches it (backend/utils/map_tiles.py).
//
// With WebGL, the basemap is OpenStreetMap vector tiles drawn by MapLibre GL JS inside a Leaflet
// layer (maplibre-gl-leaflet), with one style per look in static/map-styles/ (built by
// scripts/build_map_styles.py): light, dark, and red for the night vision theme, which overrides
// the light/dark choice. Without WebGL, it falls back to raster tiles recoloured by CSS classes.
const _LEAFLET_VERSION = '1.9.4';
const _MAPLIBRE_VERSION = '6.13.0';
const _MAPLIBRE_LEAFLET_VERSION = '0.1.4';
const _leafletLibLoadState = { promise: null };
const _maplibreLoadState = { promise: null };
const _maplibreLeafletLoadState = { promise: null };
let _vectorBasemapAvailable = false;

const _OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
const _RASTER_TILES_URL = appUrl('/api/map-tiles/raster/{z}/{x}/{y}.png'); // appUrl: Home Assistant ingress prefix
// Placeholder origin of every URL inside static/map-styles/*.json (see scripts/build_map_styles.py)
const _MAP_STYLE_ORIGIN = 'https://myastroboard.invalid';
// Bump after running scripts/build_map_styles.py so browsers fetch the new styles
const _MAP_STYLES_VERSION = '2';

const _LEAFLET_BASEMAPS = {
    light: { maxZoom: 19, rasterClassName: 'map-tiles-raster' },
    dark: { maxZoom: 19, rasterClassName: 'map-tiles-raster map-tiles-dark' },
};

// Vector basemap layers on screen, restyled when the theme switches to or from red
const _vectorBasemapLayers = new Map();

function _supportsWebGL() {
    try {
        const canvas = document.createElement('canvas');
        return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
    } catch (_) {
        return false;
    }
}

function _ensureVectorBasemapLoaded() {
    if (!_supportsWebGL()) return Promise.resolve(false);
    return ensureVendorScriptLoaded(
        () => typeof maplibregl !== 'undefined',
        appUrl(`/static/js/maplibre_loader.mjs?v=${_MAPLIBRE_VERSION}`),
        appUrl(`/static/vendor/maplibre-gl/dist/maplibre-gl.css?v=${_MAPLIBRE_VERSION}`),
        _maplibreLoadState,
        'MapLibre GL JS',
        'module'
    ).then(() => ensureVendorScriptLoaded(
        () => typeof L.maplibreGL === 'function',
        appUrl(`/static/vendor/maplibre-gl-leaflet/leaflet-maplibre-gl.js?v=${_MAPLIBRE_LEAFLET_VERSION}`),
        null,
        _maplibreLeafletLoadState,
        'maplibre-gl-leaflet'
    )).then(() => true);
}

/**
 * Load Leaflet, plus the vector basemap libraries when the browser supports WebGL.
 * Rejects only when Leaflet itself fails; a vector basemap failure falls back to raster tiles.
 * @returns {Promise<void>}
 */
async function ensureLeafletLoaded() {
    await ensureVendorScriptLoaded(
        () => typeof L !== 'undefined',
        appUrl(`/static/vendor/leaflet/dist/leaflet.min.js?v=${_LEAFLET_VERSION}`),
        appUrl(`/static/vendor/leaflet/dist/leaflet.min.css?v=${_LEAFLET_VERSION}`),
        _leafletLibLoadState,
        'Leaflet'
    );
    try {
        _vectorBasemapAvailable = await _ensureVectorBasemapLoaded();
    } catch (error) {
        console.warn('Vector basemap unavailable, using raster tiles', error);
        _vectorBasemapAvailable = false;
    }
}

function _isRedTheme() {
    return document.documentElement.getAttribute('data-theme') === 'red';
}

function _mapStyleUrl(variant) {
    const style = _isRedTheme() ? 'red' : variant;
    return window.location.origin + appUrl(`/static/map-styles/${style}.json?v=${_MAP_STYLES_VERSION}`);
}

// Swap the styles' placeholder origin for this server (with its ingress prefix, if any)
function _mapStyleTransformRequest(url) {
    if (url.startsWith(_MAP_STYLE_ORIGIN)) {
        return { url: window.location.origin + appUrl(url.slice(_MAP_STYLE_ORIGIN.length)) };
    }
    return { url };
}

function _addVectorBasemap(map, variant, layerOptions) {
    // Leaflet only reads maxZoom from tile layers, so the limit goes on the map itself; MapLibre
    // keeps its own (higher) limit and simply follows Leaflet's view.
    const { maxZoom, ...glOptions } = layerOptions;
    if (Number.isFinite(maxZoom)) map.setMaxZoom(maxZoom);
    const layer = L.maplibreGL({
        style: _mapStyleUrl(variant),
        transformRequest: _mapStyleTransformRequest,
        ...glOptions,
    }).addTo(map);
    _vectorBasemapLayers.set(layer, variant);
    layer.on('remove', () => _vectorBasemapLayers.delete(layer));
    return layer;
}

// Follow the theme live: entering or leaving the red theme swaps the style of every vector basemap.
new MutationObserver(() => {
    _vectorBasemapLayers.forEach((variant, layer) => {
        const glMap = layer.getMaplibreMap();
        if (glMap) glMap.setStyle(_mapStyleUrl(variant));
    });
}).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

/**
 * Add the OpenStreetMap basemap to a Leaflet map (call ensureLeafletLoaded() first).
 * @param {object} map - Leaflet map instance
 * @param {'light'|'dark'} variant - Basemap variant (the red theme overrides it)
 * @param {object} tileOptions - Optional layer option overrides
 * @returns {object|null} Leaflet layer instance or null
 */
function addLeafletBasemap(map, variant = 'light', tileOptions = {}) {
    if (!map || typeof L === 'undefined') return null;

    const knownVariant = _LEAFLET_BASEMAPS[variant] ? variant : 'light';
    const profile = _LEAFLET_BASEMAPS[knownVariant];
    if (_vectorBasemapAvailable && typeof L.maplibreGL === 'function') {
        return _addVectorBasemap(map, knownVariant, { maxZoom: profile.maxZoom, ...tileOptions });
    }
    return L.tileLayer(_RASTER_TILES_URL, {
        maxZoom: profile.maxZoom,
        attribution: _OSM_ATTRIBUTION,
        className: profile.rasterClassName,
        ...tileOptions,
    }).addTo(map);
}

/**
 * Leaflet options for a static preview map (location cards, picture and session
 * locations): no pan, zoom or keyboard focus of any kind, so it never traps a scroll,
 * a drag or a pinch meant for the page. Use STATIC_LEAFLET_MARKER_OPTIONS for its marker.
 */
const STATIC_LEAFLET_MAP_OPTIONS = Object.freeze({
    zoomControl: false,
    scrollWheelZoom: false,
    dragging: false,
    touchZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
});

const STATIC_LEAFLET_MARKER_OPTIONS = Object.freeze({ interactive: false, keyboard: false });

function _normalizeLeafletBasemapVariant(variant, fallback = 'light') {
    if (!variant || !_LEAFLET_BASEMAPS[variant]) return fallback;
    return variant;
}

function _getLeafletBasemapPreference(storageKey, fallback = 'light') {
    if (!storageKey) return _normalizeLeafletBasemapVariant(fallback, 'light');
    try {
        const saved = localStorage.getItem(storageKey);
        return _normalizeLeafletBasemapVariant(saved, fallback);
    } catch (_) {
        return _normalizeLeafletBasemapVariant(fallback, 'light');
    }
}

function _setLeafletBasemapPreference(storageKey, variant) {
    if (!storageKey) return;
    try {
        localStorage.setItem(storageKey, variant);
    } catch (_) { /* localStorage unavailable */ }
}

/**
 * Attach a light/dark style switcher to a Leaflet map and persist the choice.
 * @param {object} map - Leaflet map instance
 * @param {object} options - Switcher options
 * @returns {object|null} Control API
 */
function attachLeafletBasemapStyleControl(map, options = {}) {
    if (!map || typeof L === 'undefined') return null;

    const {
        storageKey = '',
        defaultVariant = 'light',
        variants = ['light', 'dark'],
        position = 'topright',
        labels = { light: 'Light', dark: 'Dark' },
        tileOptions = {},
        onVariantChange = null,
    } = options;

    const validVariants = variants.filter(variant => Boolean(_LEAFLET_BASEMAPS[variant]));
    const fallbackVariant = validVariants[0] || 'light';
    let activeVariant = _getLeafletBasemapPreference(storageKey, _normalizeLeafletBasemapVariant(defaultVariant, fallbackVariant));
    let activeLayer = null;
    let buttonRefs = {};

    const setVariant = (variant) => {
        const nextVariant = _normalizeLeafletBasemapVariant(variant, fallbackVariant);
        if (activeLayer) {
            try { map.removeLayer(activeLayer); } catch (_) { /* already removed */ }
        }
        activeLayer = addLeafletBasemap(map, nextVariant, tileOptions);
        activeVariant = nextVariant;
        _setLeafletBasemapPreference(storageKey, nextVariant);
        if (typeof onVariantChange === 'function') {
            try { onVariantChange(nextVariant); } catch (_) { /* ignore callback failures */ }
        }
        Object.entries(buttonRefs).forEach(([key, button]) => {
            if (!button) return;
            const isActive = key === nextVariant;
            button.classList.toggle('active', isActive);
            button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
    };

    const BasemapControl = L.Control.extend({
        options: { position },
        onAdd: () => {
            const container = L.DomUtil.create('div', 'premium-map-style-control leaflet-control');
            L.DomEvent.disableClickPropagation(container);
            L.DomEvent.disableScrollPropagation(container);

            validVariants.forEach((variant) => {
                const button = L.DomUtil.create('button', 'map-style-btn', container);
                button.type = 'button';
                button.textContent = labels[variant] || variant;
                button.setAttribute('aria-label', `${labels[variant] || variant} basemap`);
                buttonRefs[variant] = button;
                L.DomEvent.on(button, 'click', () => setVariant(variant));
            });

            return container;
        },
    });

    const control = new BasemapControl();
    map.addControl(control);
    setVariant(activeVariant);

    return {
        control,
        setVariant,
        getVariant: () => activeVariant,
    };
}

/**
 * Check and display cache status information.
 * Cache is managed entirely server-side with TTL-based expiration.
 * No browser-side cache refresh required - F5 works normally.
 */
async function checkCacheStatus() {
    const banner = document.getElementById('global-cache-banner');
    const bannerText = document.getElementById('cache-banner-text');
    const bannerDetail = document.getElementById('cache-banner-detail');
    if (!banner) return;

    try {
        const data = await fetchJSONWithRetry('/api/cache', {}, {
            maxAttempts: 2,
            baseDelayMs: 500,
            maxDelayMs: 2000,
            timeoutMs: 5000
        });

        if (data.cache_status === true) {
            // Cache is ready, hide the banner and keep polling slowly for future refresh cycles
            banner.style.display = 'none';
            setTimeout(checkCacheStatus, 30000);
        } else if (data.in_progress === true) {
            const progress = data.progress_percent || 0;
            const currentStep = data.current_step || 0;
            const totalSteps = data.total_steps || 0;
            const stepName = data.step_name || '';
            const hasInfo = progress > 0 || !!stepName;

            if (hasInfo) {
                banner.style.display = 'block';
                if (bannerText) {
                    bannerText.textContent = i18n.t('cache.updating_data_progress', { progress });
                }
                if (bannerDetail && stepName) {
                    const [rawStepKey, rawStepLocation = ''] = String(stepName).split('@', 2);
                    const stepKey = (rawStepKey || '').trim();
                    const stepLocation = (rawStepLocation || '').trim();
                    const translatedStep = stepKey ? i18n.t(`cache.step_${stepKey}`) : '';
                    const baseLabel = (stepKey && translatedStep !== `cache.step_${stepKey}`)
                        ? translatedStep
                        : (stepKey || stepName);
                    const locationLabel = stepLocation
                        ? ` (${capitalizeWords(stepLocation.replace(/[-_]+/g, ' '))})`
                        : '';
                    const label = `${baseLabel}${locationLabel}`;
                    bannerDetail.textContent = (stepKey === 'parallel_network' && totalSteps > 0)
                        ? `${label} (${currentStep}/${totalSteps})`
                        : label;
                    bannerDetail.style.display = '';
                } else if (bannerDetail) {
                    bannerDetail.style.display = 'none';
                }
            }
            // No real info yet: stay hidden and poll fast to catch completion quickly
            const pollInterval = hasInfo ? 10000 : 2000;
            setTimeout(checkCacheStatus, pollInterval);
        } else {
            // Cache expired but not yet refreshing - will refresh soon
            // Hide banner to avoid confusion, data will still work with stale cache
            banner.style.display = 'none';
            // Check again soon (every 5 seconds) to catch when refresh starts
            setTimeout(checkCacheStatus, 5000);
        }
    } catch (error) {
        // If API fails, hide banner and don't block UI
        banner.style.display = 'none';
        console.debug('Cache status check unavailable (server-side cached data will still be used)');
    }
}

// =======================
// Helpers strings manipulation
// =======================

// Helper function to capitalize each word in a string, including accented characters
function capitalizeWords(str) {
    return str.replace(/\b[a-zA-ZÀ-ÿ](?:(?:'[a-zA-ZÀ-ÿ])|(?:-[a-zA-ZÀ-ÿ]))*/g, word => {
        return word
            .split(/([-'])/) // kept separator - and '
            .map(part => part.match(/[-']/) ? part : part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
            .join('');
    });
}

/**
 * Copy the value of a text <input> to the clipboard. Resolves to true when it was copied.
 *
 * navigator.clipboard only exists in a secure context (HTTPS, or exactly "localhost") -
 * on a plain http:// LAN address, which is the normal way this self-hosted app is reached,
 * the object is undefined outright, not just permission-denied. Fall back to the legacy
 * execCommand('copy'), which is the only copy mechanism that still works there.
 */
async function copyInputToClipboard(input) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(input.value);
            return true;
        } catch (error) {
            console.warn('navigator.clipboard write failed, falling back to execCommand:', error);
        }
    }

    input.select();
    input.setSelectionRange(0, input.value.length);
    try {
        return document.execCommand('copy');
    } catch (error) {
        console.warn('execCommand("copy") failed:', error);
        return false;
    }
}

// Helper function to escape HTML
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// Helper function to escape text for JavaScript string context
function escapeForJs(text) {
    return text.replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/"/g, '\\"')
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r');
}

/**
 * Build a standardized data-source footer paragraph for data-driven sections.
 * Pass plain text plus optional links to avoid unsafe HTML insertion.
 */
function createDataSourceFooter({ text, links = [] }) {
    const footer = document.createElement('p');
    footer.className = 'sf-data-source text-muted small mt-4 text-center';

    const icon = document.createElement('i');
    icon.className = 'bi bi-database me-1';
    footer.appendChild(icon);

    if (text) {
        footer.appendChild(document.createTextNode(text));
    }

    links.forEach((entry, index) => {
        if (index === 0 && text) {
            footer.appendChild(document.createTextNode(' '));
        } else if (index > 0) {
            footer.appendChild(document.createTextNode(' | '));
        }
        const link = document.createElement('a');
        link.href = entry.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = entry.label;
        footer.appendChild(link);
    });

    return footer;
}

function appendDataSourceFooter(container, options) {
    if (!container) return;
    container.appendChild(createDataSourceFooter(options));
}

// =======================
// Helpers date formating
// =======================

function getUserTimeFormatPreference() {
    const prefs = window.myastroboardUserPreferences;
    if (prefs && typeof prefs.time_format === 'string') {
        return prefs.time_format;
    }
    return localStorage.getItem('myastroboard_time_format') || 'auto';
}

function getHour12Option() {
    const formatPreference = getUserTimeFormatPreference();
    if (formatPreference === '12h') {
        return true;
    }
    if (formatPreference === '24h') {
        return false;
    }
    return undefined;
}

// Returns the configured observation timezone (e.g. "Europe/Paris") if available,
// falling back to undefined so Intl uses the browser's local timezone.
function _getObservationTimezone() {
    return (typeof currentConfig !== 'undefined' && currentConfig?.location?.timezone)
        ? currentConfig.location.timezone
        : undefined;
}

// Helper function to format ISO date to local time string
// Uses the configured observation timezone (Parameters → Configuration) so times are
// always shown in the observer's location regardless of the browser's own timezone.
// Example output: "9:30 PM (6/30)" in US locale, "21:30 (30/06)" in many European locales
function formatTimeThenDate(isoString, locale = navigator.language) {
    if (!isoString || isoString === 'Not found') return 'N/A';
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return 'N/A';

    const tz = _getObservationTimezone();
    const tzOpt = tz ? { timeZone: tz } : {};

    const timeFormatter = new Intl.DateTimeFormat(locale, {
        hour: '2-digit',
        minute: '2-digit',
        hour12: getHour12Option(),
        ...tzOpt
    });

    const dateFormatter = new Intl.DateTimeFormat(locale, {
        month: 'numeric',
        day: 'numeric',
        ...tzOpt
    });

    return `${timeFormatter.format(date)} (${dateFormatter.format(date)})`;
}

// Format time, then date with seconds — same timezone handling as formatTimeThenDate.
// Example output: "9:30:45 PM (6/30)" in US locale, "21:30:45 (30/06)" in many European locales
function formatTimeThenDateWithSeconds(isoString, locale = navigator.language) {
    if (!isoString || isoString === 'Not found') return 'N/A';
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return 'N/A';

    const tz = _getObservationTimezone();
    const tzOpt = tz ? { timeZone: tz } : {};

    const timeFormatter = new Intl.DateTimeFormat(locale, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: getHour12Option(),
        ...tzOpt
    });

    const dateFormatter = new Intl.DateTimeFormat(locale, {
        month: 'numeric',
        day: 'numeric',
        ...tzOpt
    });

    return `${timeFormatter.format(date)} (${dateFormatter.format(date)})`;
}

// True when the given date falls in the current calendar year, evaluated in the observation
// timezone so the comparison uses the observer's clock rather than the browser's.
function _isCurrentYear(date, tz) {
    const yearFormatter = new Intl.DateTimeFormat('en-US', {
        year: 'numeric',
        ...(tz ? { timeZone: tz } : {})
    });
    return yearFormatter.format(date) === yearFormatter.format(new Date());
}

// Same as formatTimeThenDate, but appends a 2-digit year when the date is not in the current
// year. Rare events (eclipses) can be years away, and a bare "02/08" reads as "in a few days".
// Example output: "21:30 (30/06)" for this year, "21:30 (02/08/27)" for a 2027 event (fr locale)
function formatTimeThenDateSmartYear(isoString, locale = navigator.language) {
    if (!isoString || isoString === 'Not found') return 'N/A';
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return 'N/A';

    const tz = _getObservationTimezone();
    const tzOpt = tz ? { timeZone: tz } : {};

    const timeFormatter = new Intl.DateTimeFormat(locale, {
        hour: '2-digit',
        minute: '2-digit',
        hour12: getHour12Option(),
        ...tzOpt
    });

    const dateFormatter = new Intl.DateTimeFormat(locale, {
        month: 'numeric',
        day: 'numeric',
        ...(_isCurrentYear(date, tz) ? {} : { year: '2-digit' }),
        ...tzOpt
    });

    return `${timeFormatter.format(date)} (${dateFormatter.format(date)})`;
}

// Helper function to format ISO date to localized date string
// Example output: "6/30/2024" in US locale, "30/06/2024" in many European locales
function formatDateFull(isoString, locale = navigator.language) {
    if (!isoString) return 'N/A';
    const date = new Date(isoString);

    const tz = _getObservationTimezone();
    const dateFormatter = new Intl.DateTimeFormat(locale, {
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        ...(tz ? { timeZone: tz } : {})
    });

    return dateFormatter.format(date);
}

// Helper function to format ISO datetime to localized date string
// Example output: "6/30/2024, 9:30 PM" in US locale, "30/06/2024, 21:30" in many European locales
function formatDateTime(isoString, locale = navigator.language) {
    if (!isoString) return 'N/A';
    const date = new Date(isoString);

    const tz = _getObservationTimezone();
    const dateTimeFormatter = new Intl.DateTimeFormat(locale, {
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: getHour12Option(),
        ...(tz ? { timeZone: tz } : {})
    });

    return dateTimeFormatter.format(date);
}

// Helper function to format ISO date to localized time string HH:MM
// Example output: "21:30" in many locales
function formatTimeOnly(isoString, locale = navigator.language) {
    if (!isoString) return 'N/A';
    const date = new Date(isoString);
    const tz = _getObservationTimezone();
    const timeFormatter = new Intl.DateTimeFormat(locale, {
        hour: '2-digit',
        minute: '2-digit',
        hour12: getHour12Option(),
        ...(tz ? { timeZone: tz } : {})
    });
    return timeFormatter.format(date);
}

// Like formatTimeOnly but renders in a specific IANA timezone instead of browser local time
function formatTimeOnlyInTimezone(isoString, timezone, locale = navigator.language) {
    if (!isoString) return 'N/A';
    const date = new Date(isoString);
    try {
        return new Intl.DateTimeFormat(locale, {
            hour: '2-digit',
            minute: '2-digit',
            hour12: getHour12Option(),
            timeZone: timezone || 'UTC'
        }).format(date);
    } catch (_) {
        return formatTimeOnly(isoString, locale);
    }
}

// Returns the UTC offset for a timezone at a given instant, e.g. "UTC-10" -
// or null when the timezone is unavailable/invalid or the offset is 0.
function getUtcOffsetLabel(timezone, date = new Date()) {
    if (!timezone) return null;
    try {
        const parts = new Intl.DateTimeFormat('en-US', {
            timeZone: timezone,
            timeZoneName: 'shortOffset'
        }).formatToParts(date);
        const offset = parts.find(p => p.type === 'timeZoneName')?.value.replace('GMT', 'UTC');
        return offset && offset !== 'UTC' ? offset : null;
    } catch (_) {
        return null;
    }
}

// Appends the current UTC offset to an IANA timezone name, e.g. "Pacific/Honolulu (UTC-10)"
function formatTimezoneWithOffset(timezone) {
    const tz = timezone || 'UTC';
    const offset = getUtcOffsetLabel(tz);
    return offset ? `${tz} (${offset})` : tz;
}


// Helper function to format date from YYYY-MM-DD to DD/MM/YYYY
function formatStringToDate(dateInput, locale = navigator.language) {
    if (!dateInput) return '';

    // Convert string to Date if needed
    const date = (dateInput instanceof Date) ? dateInput : new Date(dateInput);

    // If invalid date, return original input
    if (isNaN(date)) return dateInput;

    // Format the date
    return new Intl.DateTimeFormat(locale, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    }).format(date);
}


// ======================
// Helpers for calculations
// ======================

// Helper function to get cardinal direction from azimuth
function getCardinalDirection(azimuth) {
    const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
        'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    const index = Math.round((azimuth % 360) / 22.5);
    const direction = directions[index % 16];
    return i18n.t(`cardinal_directions.${direction}`);
}

function formatAltAz(altitudeDeg, azimuthCardinal, azimuthDeg) {
    const safeAlt = Number.isFinite(Number(altitudeDeg)) ? `${Number(altitudeDeg).toFixed(1)}${i18n.t('units.degrees')}` : i18n.t('units.na');
    const cardinalKey = azimuthCardinal ? `cardinal_directions.${azimuthCardinal}` : null;
    const safeCardinal = (cardinalKey && i18n.has(cardinalKey))
        ? escapeHtml(i18n.t(cardinalKey))
        : i18n.t('units.na');
    const safeAz = Number.isFinite(Number(azimuthDeg)) ? `${Number(azimuthDeg).toFixed(1)}${i18n.t('units.degrees')}` : i18n.t('units.na');
    return `${safeAlt} / ${safeCardinal} (${safeAz})`;
}

// ---------------------------------------------------------------------------
// SkyTonight / Catalogue shared translation helpers
// Single canonical definitions - loaded before astrodex.js, plan_my_night.js,
// and skytonight.js so all three can reference these without re-declaring them.
// ---------------------------------------------------------------------------

function tSkyTonightCompat(key, params = {}) {
    return i18n.t(`skytonight.${key}`, params);
}

function tSkyTonightType(value) {
    const normalizedValue = (value || '').toString().trim();
    if (!normalizedValue) return '-';
    const suffix = strToTranslateKey(normalizedValue);
    const skytonightKey = `skytonight.type_${suffix}`;
    return i18n.has(skytonightKey) ? i18n.t(skytonightKey) : normalizedValue;
}

// ---------------------------------------------------------------------------
// Lazy vendor-script loader
// Single canonical definition - loaded before orbital_stations.js and
// skytonight.js so both can use it to lazy-load Leaflet/Plotly on demand
// instead of duplicating the same "load once, memoize the promise" logic.
// ---------------------------------------------------------------------------

/**
 * Lazily load a vendor <script> (and optional <link rel="stylesheet">), only once,
 * memoizing the in-flight/completed load as a Promise so concurrent callers share it.
 *
 * @param {() => boolean} isLoaded - Returns true if the library global is already present.
 * @param {string} scriptUrl - URL of the vendor script to inject.
 * @param {string|string[]} [cssUrl] - Optional stylesheet URL, or array of URLs, to inject alongside it.
 * @param {{promise: Promise|null}} state - Caller-owned box holding the memoized promise
 *   (a plain object so each caller keeps its own independent cache slot).
 * @param {string} libraryName - Used only in the rejection error message.
 * @param {'classic'|'module'} [scriptType] - 'module' for an ES module script.
 */
function ensureVendorScriptLoaded(isLoaded, scriptUrl, cssUrl, state, libraryName, scriptType = 'classic') {
    if (isLoaded()) return Promise.resolve();
    if (state.promise) return state.promise;
    state.promise = new Promise((resolve, reject) => {
        if (cssUrl) {
            const cssUrls = Array.isArray(cssUrl) ? cssUrl : [cssUrl];
            cssUrls.forEach((href) => {
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = appUrl(href);
                document.head.appendChild(link);
            });
        }
        const script = document.createElement('script');
        if (scriptType === 'module') script.type = 'module';
        script.src = appUrl(scriptUrl);
        script.onload = resolve;
        script.onerror = () => {
            state.promise = null;
            reject(new Error(`Failed to load ${libraryName}`));
        };
        document.head.appendChild(script);
    });
    return state.promise;
}

// =======================
// Bootstrap modal helpers
// =======================
//
// Bootstrap 5.3 does not support stacked modals: _hideModal() unconditionally
// clears `modal-open` from <body> and resets the scrollbar padding, so hiding one
// modal while another is still open unlocks page scroll behind it and can strand a
// `.modal-backdrop`. Several features also share the generic #modal_lg_close /
// #modal_xl_close / #modal_full_close shells and open one straight after another.
// Every modal show/hide goes through these helpers so exactly one modal is ever on
// screen, each instance is disposed on hide (no orphaned focus-traps piling up on a
// shared shell), and the hardware Back button closes the modal instead of switching
// tabs underneath it.

/**
 * Resolve a modal argument (element, id, or "#id") to its `.modal` element.
 * @param {HTMLElement|string} elementOrId
 * @returns {HTMLElement|null}
 */
function _resolveModalElement(elementOrId) {
    if (elementOrId instanceof HTMLElement) return elementOrId;
    if (typeof elementOrId === 'string') {
        return document.getElementById(elementOrId.replace(/^#/, ''));
    }
    return null;
}

/**
 * Hide one modal through its Bootstrap instance - never by tearing `.modal-backdrop`
 * nodes out of the DOM by hand. Bootstrap's `hide()` is a silent no-op while the
 * show transition is still running (`_isTransitioning`), which is how a quick
 * open-then-close leaves a modal stuck open; defer the hide until it settles.
 * @param {HTMLElement} el
 */
function _hideModalInstance(el) {
    const instance = bootstrap.Modal.getInstance(el);
    if (!instance) {
        el.classList.remove('show');
        return;
    }
    if (instance._isTransitioning || el.dataset.mabSettled === 'false') {
        el.addEventListener('shown.bs.modal', () => instance.hide(), { once: true });
    } else {
        instance.hide();
    }
}

/**
 * Hide a modal and resolve once it has fully finished its close transition.
 * Resolves immediately when the modal is not currently shown.
 * @param {HTMLElement|string} elementOrId
 * @returns {Promise<void>}
 */
function closeModalAndWait(elementOrId) {
    const el = _resolveModalElement(elementOrId);
    if (!el || !el.classList.contains('show')) return Promise.resolve();
    if (!bootstrap.Modal.getInstance(el)) {
        el.classList.remove('show');
        return Promise.resolve();
    }
    return new Promise(resolve => {
        el.addEventListener('hidden.bs.modal', () => resolve(), { once: true });
        _hideModalInstance(el);
    });
}

/**
 * Hide a modal (or every shown modal when called with no argument).
 * @param {HTMLElement|string} [elementOrId]
 */
function closeModal(elementOrId) {
    if (elementOrId !== undefined) {
        const el = _resolveModalElement(elementOrId);
        if (el) _hideModalInstance(el);
        return;
    }
    document.querySelectorAll('.modal.show').forEach(_hideModalInstance);
}

/**
 * Show a Bootstrap modal, first fully closing any modal already on screen (Bootstrap
 * 5.3 cannot safely stack them). The instance is disposed on hide so the next open
 * starts clean. The modal's content must already be in place before calling.
 *
 * @param {HTMLElement|string} elementOrId
 * @param {object} [options]
 * @param {'static'|boolean} [options.backdrop=true]
 * @param {boolean} [options.keyboard=true]
 * @param {boolean} [options.focus=true]
 * @param {() => void} [options.onShown] - runs on shown.bs.modal
 * @param {() => void} [options.onHidden] - runs on hidden.bs.modal
 * @param {boolean} [options.history=true] - push a history entry so Back closes the modal
 * @param {boolean} [options.persistent=false] - only closeModal() on this modal closes it: a
 *   tab change (forceCleanupModals) or the Back button leave it on screen
 * @returns {Promise<object|null>} the bootstrap.Modal instance (null when the element is missing)
 *
 * Re-opening a modal that is ALREADY on screen (common for the shared #modal_lg_close /
 * #modal_xl_close shells) only refreshes its content and re-runs `onShown` - Bootstrap
 * cannot reconfigure a live modal, so `backdrop` / `keyboard` / `onHidden` from the new
 * call are ignored. `closeModal(el)` first if a re-use needs different behaviour; the
 * helper logs a dev warning when options would be silently dropped.
 */
async function openModal(elementOrId, options = {}) {
    const el = _resolveModalElement(elementOrId);
    if (!el) {
        console.warn('openModal: no element for', elementOrId);
        return null;
    }

    const {
        backdrop = true,
        keyboard = true,
        focus = true,
        onShown = null,
        onHidden = null,
        history: useHistory = true,
        persistent = false,
    } = options;

    el.dataset.mabNoHistory = String(useHistory === false);
    el.dataset.mabPersistent = String(persistent === true);

    if (el.classList.contains('show')) {
        // Same modal reopened with refreshed content - don't flicker it closed/open.
        // Bootstrap can't reconfigure a live modal, so backdrop/keyboard/onHidden from
        // this call don't take effect; surface that instead of failing silently.
        const live = bootstrap.Modal.getInstance(el);
        const cfg = live && live._config;
        const optionsDropped = typeof onHidden === 'function'
            || (!!cfg && (backdrop !== cfg.backdrop || keyboard !== cfg.keyboard));
        if (optionsDropped) {
            console.warn(
                `openModal: "${el.id || '(modal)'}" is already shown - backdrop/keyboard/onHidden `
                + 'options ignored. closeModal() it first if you need to reconfigure.'
            );
        }
        if (typeof onShown === 'function') onShown();
        return live;
    }

    const onScreen = document.querySelector('.modal.show');
    if (onScreen && onScreen !== el) {
        await closeModalAndWait(onScreen);
    }

    bootstrap.Modal.getInstance(el)?.dispose();
    const instance = new bootstrap.Modal(el, { backdrop, keyboard, focus });

    // `mabSettled` tracks whether the show transition has finished - a hide fired
    // before then is deferred (see _hideModalInstance).
    el.dataset.mabSettled = 'false';
    el.addEventListener('shown.bs.modal', () => {
        el.dataset.mabSettled = 'true';
        if (typeof onShown === 'function') onShown();
    }, { once: true });
    el.addEventListener('hidden.bs.modal', function _cleanup() {
        el.removeEventListener('hidden.bs.modal', _cleanup);
        delete el.dataset.mabSettled;
        if (typeof onHidden === 'function') {
            try { onHidden(); } catch (err) { console.error('openModal onHidden failed', err); }
        }
        bootstrap.Modal.getInstance(el)?.dispose();
    });

    instance.show();
    return instance;
}

// --- Back button / swipe-back closes an open modal --------------------------------
// The first modal to open pushes ONE same-URL history entry (same URL => no
// `hashchange`, so no tab switch); a second modal opened straight after the first
// reuses it. `popstate` with a modal open closes every open modal instead of
// navigating. A user-driven close (X / footer button / backdrop), once nothing is
// left on screen, pops that synthetic entry so history stays balanced. The Guided
// Setup Wizard opts out via data-mab-no-history / { history: false }.
let _modalHistoryEntryActive = false;
let _suppressNextPopstate = false;

function _modalUsesHistory(target) {
    return target instanceof HTMLElement && target.dataset.mabNoHistory !== 'true';
}

// After a modal closes: if our synthetic entry is still "ours" (not already
// consumed by the Back button or dropped by a tab navigation) and nothing is left
// on screen, pop it so history stays balanced. The setTimeout lets a modal-to-modal
// swap start showing the next modal first so we can detect it and keep the entry.
// Bootstrap only adds `.modal.show` after the backdrop's fade-in (~150ms), long
// after this 0ms callback runs, so `.modal.show` alone would miss an in-flight
// swap - openModal() marks the incoming modal `data-mab-settled="false"`
// synchronously (before its show transition), which is visible here.
function _reconcileModalHistoryEntry() {
    window.setTimeout(() => {
        if (!_modalHistoryEntryActive) return;
        if (document.querySelector('.modal.show')) return;
        if (document.querySelector('.modal[data-mab-settled="false"]')) return;
        _modalHistoryEntryActive = false;
        // Only step back if we are actually sitting on our own synthetic entry -
        // otherwise a stray history.back() could leave the app.
        if (window.history.state && window.history.state.mabModal) {
            _suppressNextPopstate = true;
            window.history.back();
        }
    }, 0);
}

/** Shown modals that navigation may close - every one but a persistent modal. */
function _dismissableShownModals() {
    return [...document.querySelectorAll('.modal.show')].filter(el => el.dataset.mabPersistent !== 'true');
}

/**
 * Close every shown modal. Used before tab navigation (which changes history
 * itself) and as a stuck-state safety net - clears any stranded backdrop / scroll lock.
 * A persistent modal (the Guided Setup Wizard) is left alone, backdrop included: the
 * startup tab is applied right after the wizard opens on a first visit.
 */
function forceCleanupModals() {
    const openModals = _dismissableShownModals();
    const persistentOnScreen = document.querySelector(
        '.modal[data-mab-persistent="true"].show, .modal[data-mab-persistent="true"][data-mab-settled="false"]'
    );
    if (!openModals.length && (persistentOnScreen || !document.querySelector('.modal-backdrop'))) return;
    // The caller is about to push its own history entry - abandon our synthetic one
    // in place (it carries the current URL, so it stays transparent to Back/Forward).
    _modalHistoryEntryActive = false;
    openModals.forEach(_hideModalInstance);
    window.setTimeout(() => {
        // Something still on screen, or still opening, owns the backdrop
        if (document.querySelector('.modal.show, .modal[data-mab-settled="false"]')) return;
        document.querySelectorAll('.modal-backdrop').forEach(node => node.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
    }, 400);
}

/** Wire the modal bridges (history + close-vector robustness). Called once from
 * app.js initializeApp(). */
function _initModalHistory() {
    // Bootstrap's own hide() is a silent no-op while the show transition is still
    // running, so a dismiss button (header X / footer Close) hit right after the
    // modal appears does nothing. Intercept it in the capture phase and route
    // through _hideModalInstance(), which defers the hide until the modal settles.
    document.addEventListener('click', event => {
        const dismiss = event.target.closest?.('[data-bs-dismiss="modal"]');
        if (!dismiss) return;
        const modalEl = dismiss.closest('.modal');
        if (modalEl && modalEl.classList.contains('show')) _hideModalInstance(modalEl);
    }, true);

    document.addEventListener('show.bs.modal', event => {
        if (!_modalUsesHistory(event.target)) return;
        if (_modalHistoryEntryActive) return; // reuse the one entry for a modal-to-modal swap
        _modalHistoryEntryActive = true;
        window.history.pushState({ ...window.history.state, mabModal: true }, '');
    });

    document.addEventListener('hidden.bs.modal', event => {
        if (!_modalUsesHistory(event.target)) return;
        _reconcileModalHistoryEntry();
    });

    window.addEventListener('popstate', () => {
        if (_suppressNextPopstate) {
            _suppressNextPopstate = false;
            return;
        }
        const shown = _dismissableShownModals();
        if (!shown.length) return;
        // The browser already stepped past our synthetic entry - close every modal
        // instead of letting the navigation through.
        _modalHistoryEntryActive = false;
        shown.forEach(_hideModalInstance);
    });
}
