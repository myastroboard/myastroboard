// MyAstroBoard Modern Frontend JavaScript
// Core initialization and navigation

let currentConfig = {};
let isHandlingHashNavigation = false;

function getCanonicalHash(mainTab, subTab = null) {
    if (!mainTab) {
        return '';
    }
    return subTab ? `${mainTab}/${subTab}` : mainTab;
}

function cleanupReconnectQueryParam() {
    const url = new URL(window.location.href);
    if (!url.searchParams.has('reconnect')) {
        return;
    }

    url.searchParams.delete('reconnect');
    const cleanedUrl = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState(window.history.state, '', cleanedUrl || '/');
}

function getCurrentNavigationState() {
    const activeMainTabButton = document.querySelector('.main-tab-btn.active');
    if (!activeMainTabButton) {
        return { mainTab: null, subTab: null };
    }

    const mainTab = activeMainTabButton.getAttribute('data-tab');
    const activeSubTabButton = document.querySelector(`#${mainTab}-tab .sub-tab-btn.active`);
    const subTab = activeSubTabButton ? activeSubTabButton.getAttribute('data-subtab') : null;

    return { mainTab, subTab };
}

function syncNavigationHash({ replace = false } = {}) {
    if (isHandlingHashNavigation) {
        return;
    }

    const { mainTab, subTab } = getCurrentNavigationState();
    const canonicalHash = getCanonicalHash(mainTab, subTab);
    if (!canonicalHash) {
        return;
    }

    const currentHash = window.location.hash.replace(/^#/, '').toLowerCase();
    if (currentHash === canonicalHash.toLowerCase()) {
        return;
    }

    const targetUrl = `${window.location.pathname}${window.location.search}#${canonicalHash}`;
    if (replace) {
        window.history.replaceState({ myastroboard: true, hash: canonicalHash }, '', targetUrl);
    } else {
        window.history.pushState({ myastroboard: true, hash: canonicalHash }, '', targetUrl);
    }
}

function getStartupPreferenceValues() {
    const prefs = window.myastroboardUserPreferences || {};
    return {
        startupMainTab: prefs.startup_main_tab || 'forecast-astro',
        startupSubtab: prefs.startup_subtab || 'astro-weather'
    };
}

function getFallbackSubtabForMainTab(mainTab) {
    const parentElement = document.getElementById(`${mainTab}-tab`);
    if (!parentElement) {
        return null;
    }
    const firstSubTabButton = parentElement.querySelector('.sub-tab-btn');
    return firstSubTabButton ? firstSubTabButton.getAttribute('data-subtab') : null;
}

function applyUserStartupPreferences(force = false) {
    if (window.__myastroboardStartupApplied && !force) {
        return;
    }

    // If the URL already contains a valid navigable hash (set by handleHashNavigation),
    // don't override it with stored startup preferences.
    const hash = window.location.hash.replace(/^#/, '').toLowerCase();
    if (hash) {
        const firstSegment = hash.split('/')[0];
        const navigableMains = ['forecast-astro', 'forecast-weather', 'skytonight', 'spaceflight', 'astrodex', 'about', 'equipment', 'my-settings', 'parameters', 'weather', 'planmynight', 'plan-my-night', 'observatory'];
        if (navigableMains.includes(firstSegment) || navigableMains.some(m => hash.startsWith(m + '/'))) {
            window.__myastroboardStartupApplied = true;
            return;
        }
    }

    const { startupMainTab } = getStartupPreferenceValues();
    const startupSubtab = resolveSubtabAlias(getStartupPreferenceValues().startupSubtab);
    const targetMainButton = document.querySelector(`.main-tab-btn[data-tab="${startupMainTab}"]`);
    const effectiveMainTab = targetMainButton ? startupMainTab : 'forecast-astro';

    // On the initial automatic boot call (force=false), the page has not navigated
    // yet, so pushState here runs in a "trivial session history context" - Chrome
    // silently downgrades it to replaceState and logs a console warning. The
    // subsequent syncNavigationHash({replace: true}) in initializeAuthenticatedApp()
    // already sets the correct hash, so skip history sync here and let that call
    // handle it. Forced calls (user saving/resetting preferences) happen after real
    // navigation has occurred, so they keep syncing history normally.
    switchMainTab(effectiveMainTab, { syncHistory: force });

    const requestedSubtabExists = !!document.querySelector(
        `#${effectiveMainTab}-tab .sub-tab-btn[data-subtab="${startupSubtab}"]`
    );
    const fallbackSubtab = getFallbackSubtabForMainTab(effectiveMainTab);
    const effectiveSubtab = requestedSubtabExists ? startupSubtab : fallbackSubtab;

    if (effectiveSubtab) {
        // switchMainTab already activates/loads a sub-tab; only switch again if it is not the expected one.
        const currentlyActiveSubtab = document
            .querySelector(`#${effectiveMainTab}-tab .sub-tab-btn.active`)
            ?.getAttribute('data-subtab');

        if (currentlyActiveSubtab !== effectiveSubtab) {
            switchSubTab(effectiveMainTab, effectiveSubtab, { syncHistory: force });
        }
    }

    window.__myastroboardStartupApplied = true;
}

// Initialize the application - called by auth.js once authentication is confirmed.
// This prevents any authenticated API calls (e.g. scheduler status) from firing
// before the session is validated, which would generate spurious 401 warnings.
async function initializeAuthenticatedApp() {
    cleanupReconnectQueryParam();
    // Await full initialization so that loadConfiguration() and i18n are ready
    // before applyUserStartupPreferences() runs at the end of initializeApp().
    // Without this await, syncNavigationHash() below would read the HTML-default
    // active state (forecast-astro) and set the URL hash *before* user preferences
    // are applied, causing applyUserStartupPreferences to early-return and ignore them.
    await initializeApp();
    handleHashNavigation();
    window.addEventListener('hashchange', handleHashNavigation);
    syncNavigationHash({ replace: true });
}

window.initializeAuthenticatedApp = initializeAuthenticatedApp;
// ======================
// Hash Navigation Support for PWA Shortcuts
// ======================

function handleHashNavigation() {
    // Example hashes: #weather, #astrodex, #planmynight, #astrodex/plan-my-night
    const hash = window.location.hash.replace(/^#/, '').toLowerCase();
    if (!hash) return;

    // Map shortcut hash to main tab and optional subtab
    let mainTab = null;
    let subTab = null;
    if (hash === 'weather') {
        mainTab = 'forecast-weather';
    } else if (hash === 'astrodex') {
        mainTab = 'astrodex';
    } else if (hash === 'planmynight' || hash === 'plan-my-night') {
        mainTab = 'astrodex';
        subTab = 'plan-my-night';
    } else if (hash.startsWith('astrodex/')) {
        mainTab = 'astrodex';
        subTab = hash.split('/')[1];
    } else if (hash.startsWith('forecast-weather/')) {
        mainTab = 'forecast-weather';
        subTab = hash.split('/')[1];
    } else if (hash.startsWith('forecast-astro/')) {
        mainTab = 'forecast-astro';
        subTab = hash.split('/')[1];
    } else if (hash === 'spaceflight') {
        mainTab = 'spaceflight';
    } else if (hash.startsWith('spaceflight/')) {
        mainTab = 'spaceflight';
        subTab = hash.split('/')[1];
    } else if (hash === 'observatory') {
        mainTab = 'observatory';
    } else if (hash.startsWith('skytonight/')) {
        mainTab = 'skytonight';
        subTab = hash.split('/')[1];
    } else {
        // Generic resolver for all tabs (including dropdown tabs like
        // parameters, my-settings and equipment) to keep F5/hash reload stable.
        const [candidateMain, rawSub] = hash.split('/');
        const candidateSub = rawSub ? resolveSubtabAlias(rawSub) : rawSub;
        const mainButton = document.querySelector(`.main-tab-btn[data-tab="${candidateMain}"]`);
        if (mainButton) {
            mainTab = candidateMain;
            if (candidateSub) {
                const subButton = document.querySelector(
                    `#${candidateMain}-tab .sub-tab-btn[data-subtab="${candidateSub}"]`
                );
                if (subButton) {
                    subTab = candidateSub;
                }
            }
        }
    }

    if (!mainTab) {
        return;
    }

    isHandlingHashNavigation = true;
    try {
        switchMainTab(mainTab, { syncHistory: false });
        if (subTab) {
            // Delay to ensure main tab is visible before switching subtab.
            setTimeout(() => {
                switchSubTab(mainTab, subTab, { syncHistory: false });
            }, 50);
        }
    } finally {
        // Keep this async to ensure delayed sub-tab switch does not emit history entries.
        setTimeout(() => {
            isHandlingHashNavigation = false;
        }, 60);
    }
}

// ======================
// Navigation Tabs
// ======================

async function initializeApp() {
    // Ensure translations are fully loaded before any component calls i18n.t()
    await i18n.ready;
    // Wire the modal <-> history bridge so the hardware Back button closes an open
    // modal instead of switching tabs underneath it (see utils.js).
    _initModalHistory();
    setupNavLinkHrefs();
    setupMainTabs();
    setupSubTabs();
    await loadTimezones();
    await loadConfiguration();  // Wait for config to load before loading catalogues
    if (typeof loadAppSettings === 'function' && currentUser?.role === 'admin') loadAppSettings();
    if (typeof initFirstRun === 'function') initFirstRun();

    // Show the Guided Setup Wizard as soon as its own dependencies (config,
    // user preferences) are ready, rather than after the full catalogue load -
    // that chain can take several seconds (or fail outright), which previously
    // delayed or silently skipped the wizard on a user's very first session.
    if (typeof checkFirstRun === 'function') await checkFirstRun();

    await loadCatalogues();  // Also await catalogues to ensure proper sequencing
    setupEventListeners();
    loadVersion();

    // Init constraint visual guides
    if (typeof initConstraintHelp === 'function') initConstraintHelp();

    // Init SkyTonight scheduler
    SkyTonightScheduler.init();

    // Init persistent sky status widget
    if (typeof SkyWidget !== 'undefined') SkyWidget.init();

    checkCacheStatus();

    // Show Observatory nav tab only when at least one connector is installed and enabled
    if (typeof updateObservatoryNavVisibility === 'function') updateObservatoryNavVisibility();

    // Load initial page from user preferences (or fallback defaults)
    applyUserStartupPreferences();

    // Start background notification poller (runs every 5 min, tab-independent)
    if (typeof startNotificationPoller === 'function') startNotificationPoller();

    // Re-register push subscription with server on every page load if permission is already
    // granted. This recovers the dead-subscription state where the server purged an expired
    // endpoint but the browser still holds the subscription object - without waiting for the
    // user to open Settings.
    if (typeof _subscribeToPush === 'function' && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        _subscribeToPush();
    }
}

// Give every tab/sub-tab link a real "#..." href matching its data-tab/data-subtab
// so that middle-click / Ctrl+click / "open in new tab" works, instead of the
// placeholder href="#" they carry in the markup.
// Tab identifiers are always simple slugs (letters/digits/hyphens) defined in our own
// markup - this allowlist check keeps that assumption enforced rather than assumed,
// so nothing but a "#slug" fragment can ever reach the href attribute.
const _TAB_SLUG_RE = /^[a-z0-9-]+$/i;

function setupNavLinkHrefs() {
    document.querySelectorAll('.main-tab-btn[data-tab]').forEach(btn => {
        const tab = btn.getAttribute('data-tab');
        if (_TAB_SLUG_RE.test(tab)) btn.setAttribute('href', `#${tab}`);
    });
    document.querySelectorAll('.sub-tab-btn[data-subtab]').forEach(btn => {
        const parentTab = btn.closest('.main-tab-content');
        if (!parentTab) return;
        const mainTab = parentTab.id.replace('-tab', '');
        const subtab = btn.getAttribute('data-subtab');
        if (_TAB_SLUG_RE.test(mainTab) && _TAB_SLUG_RE.test(subtab)) {
            btn.setAttribute('href', `#${mainTab}/${subtab}`);
        }
    });
}

// A modified click (Ctrl/Cmd/Shift) or non-primary button is the user's way of
// asking the browser to open the link in a new tab/window - let that happen
// instead of hijacking it for in-page SPA navigation.
function isPlainLeftClick(e) {
    return e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey;
}

function setupMainTabs() {
    const mainTabBtns = document.querySelectorAll('.main-tab-btn');
    mainTabBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            if (!isPlainLeftClick(e)) return;
            e.preventDefault();
            const tabName = btn.getAttribute('data-tab');
            switchMainTab(tabName);
        });
    });
}

function switchMainTab(tabName, options = {}) {
    const { syncHistory = true } = options;
    //console.log(`Switching to main tab: ${tabName}`);

    // A modal left open across a tab change would float over the wrong tab (or its
    // backdrop would strand). Close it before the navigation touches history.
    forceCleanupModals();

    if (tabName === 'about') {
        window.scrollTo({ top: 0, behavior: 'instant' });
    }

    cleanupTransientCharts();

    // Stop AllSky polling when leaving Observatory tab
    if (typeof stopAllSkyPolling === 'function') stopAllSkyPolling();

    // Forach .main-tab-dropdown remove "active" class
    document.querySelectorAll('.main-tab-dropdown').forEach(dropdown => {
        dropdown.classList.remove('active');
    });

    // Update button states
    document.querySelectorAll('.main-tab-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('data-tab') === tabName) {
            btn.classList.add('active');

            // Find the parent <li class="dropdown">
            const dropdownLi = btn.closest('.dropdown');

            if (dropdownLi) {
                // Find the toggle inside that dropdown
                const toggle = dropdownLi.querySelector('.main-tab-dropdown');
                if (toggle) {
                    toggle.classList.add('active');
                }
            }
        }
    });    
    
    // Update content visibility
    document.querySelectorAll('.main-tab-content').forEach(content => {
        content.classList.remove('active');
    });
    const parentElement = document.getElementById(`${tabName}-tab`);
    if (!parentElement) return;
    parentElement.classList.add('active');

    // Ensure a visible sub-tab content exists when this main tab has sub-tabs.
    const subTabButtons = parentElement.querySelectorAll('.sub-tab-btn');
    if (subTabButtons.length > 0) {
        const activeSubTabButton = parentElement.querySelector('.sub-tab-btn.active') || subTabButtons[0];
        const activeSubTabName = activeSubTabButton?.getAttribute('data-subtab');
        if (activeSubTabName) {
            switchSubTab(tabName, activeSubTabName, { syncHistory });
        }
    } else if (syncHistory) {
        syncNavigationHash();
    }
    
    // Load tab-specific content
    if (tabName === 'skytonight') {
        loadSkyTonightResultsTabs();
    } else if (tabName === 'astrodex') {
        loadAstrodex();
    } else if (tabName === 'spaceflight') {
        // nothing extra - subtab switch below handles initial load
    } else if (tabName === 'observatory') {
        loadObservatory();
    } else if (tabName === 'forecast-weather') {
        loadWeather();
    }
}

function setupSubTabs() {
    // Use event delegation for dynamically added sub-tabs
    document.addEventListener('click', (e) => {
        // Use closest() to handle clicks on children elements (e.g., <span> inside <a>)
        const btn = e.target.closest('.sub-tab-btn');
        if (!btn) return;

        const subtabName = btn.getAttribute('data-subtab');
        if (!subtabName) return;

        if (!isPlainLeftClick(e)) return;

        // prevent default link behavior
        e.preventDefault();
        
        const parentTab = btn.closest('.main-tab-content').id.replace('-tab', '');
        switchSubTab(parentTab, subtabName);
    });
}

function setupNavbarAutoCollapse() {
    const navbarCollapse = document.getElementById('navBarMyAstroBoard');
    if (!navbarCollapse) return;

    navbarCollapse.addEventListener('click', (event) => {
        const link = event.target.closest('.nav-link');
        if (!link) return;

        // Ignore dropdown toggles
        if (link.matches('[data-bs-toggle="dropdown"]')) return;

        if (!navbarCollapse.classList.contains('show')) return;

        const collapseInstance = bootstrap.Collapse.getInstance(navbarCollapse);
        (collapseInstance || new bootstrap.Collapse(navbarCollapse)).hide();
    });
}

// Sub-tabs that were merged into another one: an old bookmark, PWA shortcut or saved
// startup preference still lands on the right place.
const _SUBTAB_ALIASES = {
    'log-export': 'logs', // Parameters -> Log export now sits under Logs
};

function resolveSubtabAlias(subtabName) {
    return _SUBTAB_ALIASES[subtabName] || subtabName;
}

function switchSubTab(parentTab, subtabName, options = {}) {
    const { syncHistory = true } = options;
    subtabName = resolveSubtabAlias(subtabName);
    // Close any open modal before the sub-tab change touches history (no-op when
    // reached via switchMainTab, which already did this).
    forceCleanupModals();
    cleanupTransientCharts();

    activateSubTab(parentTab, subtabName);

    //console.log(`Switched to sub-tab: ${subtabName} under main tab: ${parentTab}`);

    // Stop metrics auto-refresh when switching away from metrics tab
    if (subtabName !== 'metrics') {
        stopMetricsAutoRefresh();
    }

    // Load subtab-specific content
    switch (subtabName) {
        case 'locations':
            if (typeof loadLocationsAdmin === 'function') loadLocationsAdmin();
            break; // Parameters tab (admin, v1.2)
        case 'location':
            if (typeof loadMyLocationSettings === 'function') loadMyLocationSettings();
            break; // My Settings tab (v1.2)
        case 'configuration':
            if (typeof loadMqttConnections === 'function') loadMqttConnections();
            break; // Parameters tab (the rest of the page is loaded at startup by loadConfiguration)
        case 'logs':
            loadLogs();
            loadLogLevels();
            break; // Parameters tab (log levels and the log export sit under the viewer)
        case 'users':
            loadUsers();
            break; // Parameters tab
        case 'metrics':
            startMetricsAutoRefresh();
            break; // Parameters tab
        case 'backup-restore':
            loadMigrationBackups();
            break; // Parameters tab
        case 'connectors':
            loadConnectorsStore();
            break; // Parameters tab
        case 'weather':
            loadWeather();
            break; // Weather Forecast tab
        case 'seeing':
            loadSeeingForecast();
            break; // Weather Forecast tab
        case 'trend':
            loadAstronomicalCharts();
            break; // Weather Forecast tab
        case 'astro-weather':
            loadAstroWeather();
            break; // Astro Forecast tab
        case 'window':
            loadBestDarkWindow();
            break; // Astro Forecast tab
        case 'moon':
            loadMoon();
            loadNextMoonPhases();
            loadMoonPhaseCalendar();
            loadLunarEclipse();
            break; // Astro Forecast tab
        case 'sun':
            loadSun();
            loadSolarEclipse();
            break; // Astro Forecast tab
        case 'aurora':
            loadAurora();
            break; // Astro Forecast tab
        case 'calendar':
            clearEventsCache();
            loadAndDisplayEvents();
            break; // Astro Forecast tab
        case 'orbital-stations':
            loadOrbitalStations();
            break; // Spaceflight tab
        case 'launches':
            loadSpaceflightLaunches();
            break; // Spaceflight tab
        case 'astronauts':
            loadSpaceflightAstronauts();
            break; // Spaceflight tab
        case 'space-events':
            loadSpaceflightEvents();
            break; // Spaceflight tab
        case 'plan-my-night':
            loadPlanMyNight();
            break; // Plan My Night tab
        case 'observation-log':
            if (typeof loadObservationSessions === 'function') loadObservationSessions();
            break; // Astrodex tab
        case 'analytics':
            if (typeof loadSessionAnalytics === 'function') loadSessionAnalytics();
            break; // Astrodex tab (v1.5)
        case 'wishlist':
            if (typeof loadWishlist === 'function') loadWishlist();
            break; // Astrodex tab (v1.5)
        case 'photo-map':
            if (typeof loadAstrodexPhotoMap === 'function') loadAstrodexPhotoMap();
            break; // Astrodex tab
        case 'catalogue-collection':
            if (typeof loadCatalogueCollection === 'function') loadCatalogueCollection();
            break; // Astrodex tab
        case 'notifications':
            if (typeof initNotificationSettingsUI === 'function') initNotificationSettingsUI();
            break; // My Settings tab
        default:
            if (subtabName.startsWith('skytonight-')) { // SkyTonight section tabs
                const skytSection = subtabName.slice('skytonight-'.length);
                if (typeof _showSkyTonightSectionData === 'function') {
                    _showSkyTonightSectionData(skytSection);
                }
            }
    }

    if (syncHistory) {
        syncNavigationHash();
    }
}

function activateSubTab(parentTab, subtabName) {
    const parentElement = document.getElementById(`${parentTab}-tab`);
    if (!parentElement) return;

    const buttons = parentElement.querySelectorAll('.sub-tab-btn');
    const contents = parentElement.querySelectorAll('.sub-tab-content');

    buttons.forEach(b => b.classList.remove('active'));
    contents.forEach(c => c.classList.remove('active'));

    const btn = parentElement.querySelector(`.sub-tab-btn[data-subtab="${subtabName}"]`);
    const content = document.getElementById(`${subtabName}-subtab`);

    if (btn) btn.classList.add('active');
    if (content) content.classList.add('active');
}


function cleanupTransientCharts() {
    if (typeof destroyAstronomicalCharts === 'function') {
        destroyAstronomicalCharts();
    }
    if (typeof destroyAstroWeatherCharts === 'function') {
        destroyAstroWeatherCharts();
    }
    if (typeof destroyHorizonChart === 'function') {
        destroyHorizonChart();
    }
    if (typeof destroyLunarEclipseChart === 'function') {
        destroyLunarEclipseChart();
    }
    if (typeof destroySolarEclipseChart === 'function') {
        destroySolarEclipseChart();
    }
    if (typeof destroyDebugAlttimeChart === 'function') {
        destroyDebugAlttimeChart();
    }
    if (typeof destroyAstrodexPhotoMap === 'function') {
        destroyAstrodexPhotoMap();
    }
    if (typeof destroySessionAnalyticsCharts === 'function') {
        destroySessionAnalyticsCharts();
    }
}

function setupEventListeners() {
    setupNavbarAutoCollapse();

    // Configuration save
    document.getElementById('save-astrodex')?.addEventListener('click', saveConfiguration);
    document.getElementById('save-advanced')?.addEventListener('click', saveConfiguration);
    document.getElementById('export-config-main')?.addEventListener('click', exportConfiguration);

    // Backup / Restore
    document.getElementById('backup-download-btn')?.addEventListener('click', downloadBackup);
    document.getElementById('backup-restore-btn')?.addEventListener('click', restoreBackup);
    document.getElementById('migration-backups-report-btn')?.addEventListener('click', downloadMigrationReport);
    document.getElementById('migration-backups-delete-btn')?.addEventListener('click', deleteMigrationBackups);

    // Metrics - database integrity check
    document.getElementById('db-integrity-btn')?.addEventListener('click', runDatabaseIntegrityCheck);
    initRestoreFileInput();

    // Log Export
    document.getElementById('log-export-btn')?.addEventListener('click', downloadLogExport);
    
    // Run Now button
    document.getElementById('run-now')
        ?.addEventListener('click', SkyTonightScheduler.trigger);
    
    // Coordinate conversion
    document.getElementById('latitude-input')?.addEventListener('blur', () => convertCoordinate('latitude'));
    document.getElementById('longitude-input')?.addEventListener('blur', () => convertCoordinate('longitude'));

    // Geolocation auto-fill
    document.getElementById('geolocate-btn')?.addEventListener('click', async () => {
        if (!navigator.geolocation) {
            showMessage('warning', i18n.t('settings.geolocation_unsupported') || 'Geolocation is not supported by your browser.');
            return;
        }
        navigator.geolocation.getCurrentPosition(async (position) => {
            const lat = position.coords.latitude.toFixed(6);
            const lon = position.coords.longitude.toFixed(6);
            let locationName = null;
            try {
                const resp = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`, {
                    headers: { 'Accept-Language': i18n.currentLocale || 'en' }
                });
                const geo = await resp.json();
                locationName = geo.address?.city || geo.address?.town || geo.address?.village || geo.address?.county || null;
            } catch (_) { /* reverse geocoding is optional */ }

            const lines = [
                i18n.t('settings.geolocation_confirm') || 'Use this location?',
                `Latitude: ${lat}`,
                `Longitude: ${lon}`,
            ];
            if (locationName) lines.push(`Name: ${locationName}`);

            if (confirm(lines.join('\n'))) {
                const latInput = document.getElementById('latitude-input');
                const lonInput = document.getElementById('longitude-input');
                const nameInput = document.getElementById('location-name');
                if (latInput) { latInput.value = lat; convertCoordinate('latitude'); }
                if (lonInput) { lonInput.value = lon; convertCoordinate('longitude'); }
                if (nameInput && locationName && !nameInput.value) nameInput.value = locationName;
            }
        }, () => {
            showMessage('warning', i18n.t('settings.geolocation_error') || 'Unable to retrieve your location.');
        });
    });

    // Horizon profile buttons (replaced onclick= attributes)
    document.getElementById('add-horizon-row-btn')?.addEventListener('click', () => addHorizonRow());
    document.getElementById('clear-horizon-profile-btn')?.addEventListener('click', clearHorizonProfile);
    document.getElementById('horizon-profile-tbody')?.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-action="delete-horizon-row"]');
        if (btn) { btn.closest('tr').remove(); _updateHorizonTableVisibility(); }
    });

    // Multi-location profiles UI (admin grid + modal + my-settings, v1.2)
    if (typeof initLocationsUI === 'function') initLocationsUI();

    // Logs
    document.getElementById('refresh-logs')?.addEventListener('click', loadLogs);
    document.getElementById('clear-logs-display')?.addEventListener('click', clearLogsDisplay);
    document.getElementById('log-level')?.addEventListener('change', loadLogs);
    document.getElementById('log-limit')?.addEventListener('change', loadLogs);
}

// ======================
// Version Management
// ======================

async function loadVersion() {
    try {
        const data = await fetchJSON('/api/version');
        const versionElement = document.getElementById('version');
        if (versionElement) {
            versionElement.textContent = `v${data.version}`;
        }
        
        // Check for updates immediately after page load
        checkForUpdates();
        
        // Set up periodic update check every 4 hours (4 * 60 * 60 * 1000 ms)
        setInterval(checkForUpdates, 4 * 60 * 60 * 1000);
        
    } catch (error) {
        console.error('Error loading version:', error);
    }
}

async function checkForUpdates() {
    try {
        // Call backend API which handles caching and GitHub rate limits
        const updateInfo = await fetchJSONWithRetry('/api/version/check-updates', {}, {
            maxAttempts: 2,
            baseDelayMs: 1000,
            maxDelayMs: 3000,
            timeoutMs: 15000
        });
        
        // Defensive guard: never show a downgrade/stale notification.
        const currentVersion = String(updateInfo.current_version || '').trim();
        const latestVersion = String(updateInfo.latest_version || '').trim();
        const isActuallyNewer = isVersionNewer(currentVersion, latestVersion);

        // Show notification if update is available and semver confirms it.
        if (updateInfo.update_available && updateInfo.release_url && isActuallyNewer) {
            showUpdateNotification(updateInfo);
        }
    } catch (error) {
        // Silently fail - update checks are not critical
        console.debug('Update check failed (non-critical):', error);
    }
}

function isVersionNewer(currentVersion, latestVersion) {
    const normalize = (value) => String(value || '').replace(/^v/i, '').trim();
    const parseParts = (value) => normalize(value)
        .split('.')
        .map((part) => parseInt(part, 10))
        .map((num) => (Number.isFinite(num) ? num : 0));

    const currentParts = parseParts(currentVersion);
    const latestParts = parseParts(latestVersion);
    const maxLen = Math.max(currentParts.length, latestParts.length);

    for (let i = 0; i < maxLen; i++) {
        const c = currentParts[i] ?? 0;
        const l = latestParts[i] ?? 0;
        if (l > c) return true;
        if (l < c) return false;
    }
    return false;
}

// Last update-check payload shown in the footer, kept so the what's-new modal can be (re)built
// on click and on language change.
let latestUpdateInfo = null;

function showUpdateNotification(updateInfo) {
    const notification = document.getElementById('update-notification');
    const text = document.getElementById('update-text');
    const button = document.getElementById('update-whats-new-btn');

    if (!notification || !text || !button) {
        console.warn('Update notification elements not found in DOM');
        return;
    }
    latestUpdateInfo = updateInfo;
    text.textContent = i18n.t('whats_new.footer_available', { version: updateInfo.latest_version });
    if (!button.dataset.bound) {
        button.dataset.bound = '1';
        button.addEventListener('click', openWhatsNewModal);
    }
    notification.style.display = 'block';
}

window.addEventListener('i18nLanguageChanged', () => {
    if (!latestUpdateInfo) return;
    const text = document.getElementById('update-text');
    if (text) text.textContent = i18n.t('whats_new.footer_available', { version: latestUpdateInfo.latest_version });
    const modal = document.getElementById('whats-new-modal');
    if (modal && modal.classList.contains('show')) renderWhatsNew(latestUpdateInfo);
});

function openWhatsNewModal() {
    if (!latestUpdateInfo) return;
    renderWhatsNew(latestUpdateInfo);
    openModal('whats-new-modal');
}

/**
 * Append a changelog entry (one markdown line) to `parent` as DOM nodes.
 * Only the inline subset the changelog uses is rendered: `code`, **strong**, *em* and
 * [text](https://...) links; everything else stays plain text.
 */
function appendChangelogMarkdown(parent, markdown) {
    const pattern = /`([^`]+)`|\[([^\]]+)\]\((https:\/\/[^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*/g;
    let last = 0;
    let match;
    while ((match = pattern.exec(markdown)) !== null) {
        if (match.index > last) parent.appendChild(document.createTextNode(markdown.slice(last, match.index)));
        let node;
        if (match[1] !== undefined) {
            node = document.createElement('code');
            node.textContent = match[1];
        } else if (match[2] !== undefined) {
            node = document.createElement('a');
            node.href = match[3];
            node.target = '_blank';
            node.rel = 'noopener noreferrer';
            node.textContent = match[2];
        } else if (match[4] !== undefined) {
            node = document.createElement('strong');
            node.textContent = match[4];
        } else {
            node = document.createElement('em');
            node.textContent = match[5];
        }
        parent.appendChild(node);
        last = pattern.lastIndex;
    }
    if (last < markdown.length) parent.appendChild(document.createTextNode(markdown.slice(last)));
}

function _whatsNewIcon(name) {
    const icon = document.createElement('i');
    icon.className = `bi ${name}`;
    icon.setAttribute('aria-hidden', 'true');
    return icon;
}

function _whatsNewBadge(className, text) {
    const badge = document.createElement('span');
    badge.className = `badge ${className}`;
    badge.textContent = text;
    return badge;
}

function _whatsNewList(entries, suffixFn) {
    const list = document.createElement('ul');
    list.className = 'whats-new-list';
    entries.forEach((entry) => {
        const item = document.createElement('li');
        appendChangelogMarkdown(item, entry.text ?? entry);
        const suffix = suffixFn ? suffixFn(entry) : '';
        if (suffix) {
            const span = document.createElement('span');
            span.className = 'opacity-75';
            span.textContent = ` (${suffix})`;
            item.appendChild(span);
        }
        list.appendChild(item);
    });
    return list;
}

function _whatsNewGroup(className, iconName, titleKey, entries) {
    const group = document.createElement('div');
    const title = document.createElement('div');
    title.className = `whats-new-group-title ${className}`;
    title.appendChild(_whatsNewIcon(iconName));
    title.appendChild(document.createTextNode(i18n.t(titleKey)));
    group.appendChild(title);
    group.appendChild(_whatsNewList(entries));
    return group;
}

function _formatReleaseDate(isoDate) {
    if (!isoDate) return '';
    const date = new Date(`${isoDate}T00:00:00Z`);
    if (Number.isNaN(date.getTime())) return isoDate;
    return new Intl.DateTimeFormat(i18n.getHtmlLang(), {
        day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
    }).format(date);
}

function renderWhatsNew(updateInfo) {
    const range = document.getElementById('whats-new-range');
    const body = document.getElementById('whats-new-modal-body');
    const releaseLink = document.getElementById('whats-new-release-link');
    if (!range || !body) return;

    const releases = Array.isArray(updateInfo.changes) ? updateInfo.changes : null;
    if (releaseLink && updateInfo.release_url) releaseLink.href = updateInfo.release_url;

    DOMUtils.clear(range);
    range.appendChild(_whatsNewBadge('text-bg-secondary', `v${updateInfo.current_version}`));
    range.appendChild(_whatsNewIcon('bi-arrow-right'));
    range.appendChild(_whatsNewBadge('text-bg-primary', `v${updateInfo.latest_version}`));
    if (releases && releases.length) {
        const count = document.createElement('span');
        count.className = 'whats-new-range-count';
        count.textContent = releases.length > 1
            ? i18n.t('whats_new.version_count', { count: releases.length })
            : i18n.t('whats_new.version_count_one');
        range.appendChild(count);
    }

    DOMUtils.clear(body);
    if (!releases || !releases.length) {
        // Changelog could not be fetched: the footer link to the GitHub release is all we have
        const message = document.createElement('p');
        message.className = 'mb-2';
        message.textContent = i18n.t('whats_new.unavailable');
        const hint = document.createElement('p');
        hint.className = 'mb-0 small opacity-75';
        hint.textContent = i18n.t('whats_new.unavailable_hint', { version: updateInfo.latest_version });
        body.append(message, hint);
    } else {
        // Breaking changes of every skipped release are gathered on top: the reason to read this first
        const breaking = [];
        releases.forEach((release) => {
            (release.breaking || []).forEach((text) => breaking.push({ text, version: release.version }));
        });
        if (breaking.length) {
            const alert = document.createElement('div');
            alert.className = 'alert alert-warning whats-new-breaking mb-3';
            alert.setAttribute('role', 'alert');
            const title = document.createElement('strong');
            title.appendChild(_whatsNewIcon('bi-exclamation-triangle-fill'));
            title.appendChild(document.createTextNode(` ${i18n.t('whats_new.breaking_title')}`));
            alert.appendChild(title);
            alert.appendChild(_whatsNewList(breaking, (entry) => (releases.length > 1 ? `v${entry.version}` : '')));
            body.appendChild(alert);
        }

        releases.forEach((release, index) => {
            const details = document.createElement('details');
            details.className = 'whats-new-release';
            details.open = index === 0;

            const summary = document.createElement('summary');
            const version = document.createElement('span');
            version.className = 'whats-new-version';
            version.textContent = `v${release.version}`;
            summary.appendChild(version);
            if (release.date) {
                const date = document.createElement('span');
                date.className = 'whats-new-date';
                date.textContent = _formatReleaseDate(release.date);
                summary.appendChild(date);
            }
            if (index === 0) summary.appendChild(_whatsNewBadge('text-bg-primary', i18n.t('whats_new.latest')));

            const counts = document.createElement('span');
            counts.className = 'whats-new-counts';
            const features = release.features || [];
            const fixes = release.fixes || [];
            if (features.length) {
                const badge = _whatsNewBadge('rounded-pill text-bg-success', '');
                badge.append(_whatsNewIcon('bi-plus-circle'), ` ${features.length}`);
                badge.title = i18n.t('whats_new.features');
                counts.appendChild(badge);
            }
            if (fixes.length) {
                const badge = _whatsNewBadge('rounded-pill text-bg-info', '');
                badge.append(_whatsNewIcon('bi-wrench-adjustable'), ` ${fixes.length}`);
                badge.title = i18n.t('whats_new.fixes');
                counts.appendChild(badge);
            }
            if ((release.breaking || []).length) {
                counts.appendChild(_whatsNewBadge('rounded-pill text-bg-danger', i18n.t('whats_new.breaking_badge')));
            }
            summary.appendChild(counts);
            details.appendChild(summary);

            const content = document.createElement('div');
            content.className = 'whats-new-release-body';
            if (features.length) content.appendChild(_whatsNewGroup('is-feature', 'bi-plus-circle', 'whats_new.features', features));
            if (fixes.length) content.appendChild(_whatsNewGroup('is-fix', 'bi-wrench-adjustable', 'whats_new.fixes', fixes));
            details.appendChild(content);
            body.appendChild(details);
        });
    }

    // Only an admin can act on an update
    if (currentUser?.role === 'admin') {
        const howto = document.createElement('div');
        howto.className = 'whats-new-howto';
        howto.appendChild(_whatsNewIcon('bi-arrow-repeat'));
        const text = document.createElement('span');
        const label = document.createElement('strong');
        label.textContent = i18n.t('whats_new.how_to_update');
        const command = document.createElement('code');
        command.textContent = 'docker compose pull && docker compose up -d';
        text.append(label, ' ', command, i18n.t('whats_new.how_to_update_ha'));
        howto.appendChild(text);
        body.appendChild(howto);
    }
}

window.applyUserStartupPreferences = applyUserStartupPreferences;
