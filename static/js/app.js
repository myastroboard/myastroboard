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
        const navigableMains = ['forecast-astro', 'forecast-weather', 'skytonight', 'spaceflight', 'astrodex', 'about', 'equipment', 'my-settings', 'parameters', 'weather', 'planmynight', 'plan-my-night'];
        if (navigableMains.includes(firstSegment) || navigableMains.some(m => hash.startsWith(m + '/'))) {
            window.__myastroboardStartupApplied = true;
            return;
        }
    }

    const { startupMainTab, startupSubtab } = getStartupPreferenceValues();
    const targetMainButton = document.querySelector(`.main-tab-btn[data-tab="${startupMainTab}"]`);
    const effectiveMainTab = targetMainButton ? startupMainTab : 'forecast-astro';

    switchMainTab(effectiveMainTab);

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
            switchSubTab(effectiveMainTab, effectiveSubtab);
        }
    }

    window.__myastroboardStartupApplied = true;
}

// Initialize the application — called by auth.js once authentication is confirmed.
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
    } else if (hash.startsWith('skytonight/')) {
        mainTab = 'skytonight';
        subTab = hash.split('/')[1];
    } else {
        // Generic resolver for all tabs (including dropdown tabs like
        // parameters, my-settings and equipment) to keep F5/hash reload stable.
        const [candidateMain, candidateSub] = hash.split('/');
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
    setupMainTabs(); 
    setupSubTabs();
    await loadTimezones();
    await loadConfiguration();  // Wait for config to load before loading catalogues
    await loadCatalogues();  // Also await catalogues to ensure proper sequencing
    setupEventListeners();
    loadVersion();

    // Init constraint visual guides
    if (typeof initConstraintHelp === 'function') initConstraintHelp();

    // Init SkyTonight scheduler
    SkyTonightScheduler.init();

    checkCacheStatus();

    // Load initial page from user preferences (or fallback defaults)
    applyUserStartupPreferences();

    // Start background notification poller (runs every 5 min, tab-independent)
    if (typeof startNotificationPoller === 'function') startNotificationPoller();
}

function setupMainTabs() {
    const mainTabBtns = document.querySelectorAll('.main-tab-btn');
    mainTabBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const tabName = btn.getAttribute('data-tab');
            switchMainTab(tabName);
        });
    });
}

function switchMainTab(tabName, options = {}) {
    const { syncHistory = true } = options;
    //console.log(`Switching to main tab: ${tabName}`);

    if (tabName === 'about') {
        window.scrollTo({ top: 0, behavior: 'instant' });
    }

    cleanupTransientCharts();

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
        // nothing extra — subtab switch below handles initial load
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

function switchSubTab(parentTab, subtabName, options = {}) {
    const { syncHistory = true } = options;
    cleanupTransientCharts();

    activateSubTab(parentTab, subtabName);

    //console.log(`Switched to sub-tab: ${subtabName} under main tab: ${parentTab}`);

    // Stop metrics auto-refresh when switching away from metrics tab
    if (subtabName !== 'metrics') {
        stopMetricsAutoRefresh();
    }

    // Load subtab-specific content
    switch (subtabName) {
        case 'logs':
            loadLogs();
            break; // Parameters tab
        case 'users':
            loadUsers();
            break; // Parameters tab
        case 'metrics':
            startMetricsAutoRefresh();
            break; // Parameters tab
        case 'log-export':
            loadLogLevel();
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
        case 'iss':
            loadIss();
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
            loadMoonCalendar();
            loadSeeingWeek();
            loadPlanMyNight();
            break; // Plan My Night tab
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
}

function setupModalAccessibility() {
    const modalIds = ['modal_sm_close', 'modal_lg_close', 'modal_xl_close', 'modal_full_close'];
    
    modalIds.forEach(modalId => {
        const modalElement = document.getElementById(modalId);
        if (!modalElement) return;
        
        // When modal is shown, set aria-hidden to false
        modalElement.addEventListener('show.bs.modal', () => {
            modalElement.setAttribute('aria-hidden', 'false');
        });
        
        // When modal is hidden, set aria-hidden to true
        modalElement.addEventListener('hide.bs.modal', () => {
            modalElement.setAttribute('aria-hidden', 'true');
        });
    });
}

function setupEventListeners() {
    setupNavbarAutoCollapse();
    setupModalAccessibility();

    // Configuration save
    document.getElementById('save-config')?.addEventListener('click', saveConfiguration);
    document.getElementById('save-advanced')?.addEventListener('click', saveConfiguration);
    document.getElementById('export-config-main')?.addEventListener('click', exportConfiguration);

    // Backup / Restore
    document.getElementById('backup-download-btn')?.addEventListener('click', downloadBackup);
    document.getElementById('backup-restore-btn')?.addEventListener('click', restoreBackup);
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
    
    // Logs
    document.getElementById('refresh-logs')?.addEventListener('click', loadLogs);
    document.getElementById('clear-logs-display')?.addEventListener('click', clearLogsDisplay);
    document.getElementById('log-level')?.addEventListener('change', loadLogs);
    document.getElementById('log-limit')?.addEventListener('change', loadLogs);
    
    // Config modal
    const modal = document.getElementById('config-modal');
    const closeBtn = document.querySelector('.close');
    
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            modal.style.display = 'none';
        });
    }
    
    // Image modal
    const imageModal = document.getElementById('image-modal');
    const closeImageBtn = document.querySelector('.close-image');
    
    if (closeImageBtn) {
        closeImageBtn.addEventListener('click', () => {
            imageModal.style.display = 'none';
        });
    }
    
    // Close modals when clicking outside
    window.addEventListener('click', (event) => {
        if (event.target === modal) {
            modal.style.display = 'none';
        }
        if (event.target === imageModal) {
            imageModal.style.display = 'none';
        }
    });
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
            showUpdateNotification(updateInfo.release_url, updateInfo.latest_version);
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

function showUpdateNotification(releaseUrl, version) {
    const notification = document.getElementById('update-notification');
    const link = document.getElementById('update-link');
    
    if (notification && link) {
        link.href = releaseUrl;
        link.textContent = i18n.t('common.update_version_link', { version });
        notification.style.display = 'block';
        //console.debug(`Update notification shown for version v${version}`);
    } else {
        console.warn('Update notification elements not found in DOM');
        if (!notification) console.warn('Missing element: update-notification');
        if (!link) console.warn('Missing element: update-link');
    }
}

window.applyUserStartupPreferences = applyUserStartupPreferences;
