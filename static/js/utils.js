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

// Appends the current UTC offset to an IANA timezone name, e.g. "Pacific/Honolulu (UTC-10)"
function formatTimezoneWithOffset(timezone) {
    const tz = timezone || 'UTC';
    try {
        const parts = new Intl.DateTimeFormat('en-US', {
            timeZone: tz,
            timeZoneName: 'shortOffset'
        }).formatToParts(new Date());
        const offset = parts.find(p => p.type === 'timeZoneName')?.value.replace('GMT', 'UTC');
        return offset && offset !== 'UTC' ? `${tz} (${offset})` : tz;
    } catch (_) {
        return tz;
    }
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
 * @param {string} [cssUrl] - Optional URL of a stylesheet to inject alongside it.
 * @param {{promise: Promise|null}} state - Caller-owned box holding the memoized promise
 *   (a plain object so each caller keeps its own independent cache slot).
 * @param {string} libraryName - Used only in the rejection error message.
 */
function ensureVendorScriptLoaded(isLoaded, scriptUrl, cssUrl, state, libraryName) {
    if (isLoaded()) return Promise.resolve();
    if (state.promise) return state.promise;
    state.promise = new Promise((resolve, reject) => {
        if (cssUrl) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = cssUrl;
            document.head.appendChild(link);
        }
        const script = document.createElement('script');
        script.src = scriptUrl;
        script.onload = resolve;
        script.onerror = () => {
            state.promise = null;
            reject(new Error(`Failed to load ${libraryName}`));
        };
        document.head.appendChild(script);
    });
    return state.promise;
}
