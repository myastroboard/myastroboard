// Authentication and User Management

let currentUser = null;
let currentUserPreferences = null;
let offlineRedirectInProgress = false;
// Trusted networks: working copy edited locally in the admin panel, persisted on Save.
// Doubles as the "any trusted network configured?" answer the local-scope warning
// banner needs, so that banner's state doesn't need its own separate copy of it.
let trustedNetworksDraft = [];
// How many loaded users are scoped 'local', precomputed by displayUsers() rather than
// keeping the whole user list around just to re-filter it on every render.
let lastLocalAccountCount = 0;

function localizeApiError(data, fallbackKey) {
    const localized = data?.error_key ? i18n.t(data.error_key) : null;
    return localized || data?.error || i18n.t(fallbackKey);
}

const DEFAULT_USER_PREFERENCES = {
    startup_main_tab: 'forecast-astro',
    startup_subtab: 'astro-weather',
    time_format: 'auto',
    density: 'comfortable',
    theme_mode: 'auto',
    first_day_of_week: 'monday',
    experience_level: 'advanced',
    beginner_catalog_enabled: true,
    recommendations_enabled: true,
    mqtt_publish_enabled: false,
    wizard: { completed: false, skipped: false },
    notifications: null,
};

const startupSubtabsByMain = {
    'forecast-astro': ['astro-weather', 'window', 'moon', 'sun', 'aurora', 'calendar'],
    'forecast-weather': ['weather', 'seeing', 'trend'],
    'skytonight': [],
    'spaceflight': ['launches', 'astronauts', 'space-events', 'iss'],
    'astrodex': ['astrodex', 'plan-my-night'],
    'equipment': ['combinations', 'fov', 'telescopes', 'cameras', 'mounts', 'filters', 'accessories'],
    'my-settings': ['customize', 'notifications', 'security'],
    'parameters': ['configuration', 'logs', 'users', 'metrics']
};

function getAuthStatusRetryOptions() {
    // Keep auth probing fast to avoid long hangs before offline fallback.
    if (window.navigator && window.navigator.onLine === false) {
        return {
            maxAttempts: 1,
            timeoutMs: 1500,
            retryOnNetworkError: false
        };
    }

    return {
        maxAttempts: 2,
        timeoutMs: 3000,
        baseDelayMs: 250,
        maxDelayMs: 1000,
        retryOnNetworkError: true
    };
}

function isOfflineOrNetworkError(error) {
    if (window.navigator && window.navigator.onLine === false) {
        return true;
    }

    const message = String(error?.message || '').toLowerCase();
    return error?.code === 'ETIMEDOUT'
        || message.includes('failed to fetch')
        || message.includes('networkerror')
        || message.includes('network request failed')
        || message.includes('timed out')
        || message.includes('load failed');
}

// Check authentication status on page load
async function checkAuthStatus() {
    try {
        const data = await fetchJSONWithRetry('/api/auth/status', {
            credentials: 'include'
        }, getAuthStatusRetryOptions());
        
        if (data.authenticated) {
            currentUser = data;
            updateUserInterface();
            await loadUserPreferences();
            applyUserPreferences();
            populateCustomizeFormFromPreferences();
            if (typeof window.initializeAuthenticatedApp === 'function') {
                window.initializeAuthenticatedApp();
            }
            
            // Show warning if using default password
            if (data.using_default_password) {
                showDefaultPasswordWarning();
            }
        } else {
            // Not authenticated, redirect to login
            window.location.href = '/login';
        }
    } catch (error) {
        console.error('Error checking auth status:', error);
        if (isOfflineOrNetworkError(error)) {
            // Network unavailable: show dedicated offline page instead of login.
            if (!window.location.pathname.includes('/offline.html')) {
                window.location.href = '/offline.html';
            }
            return;
        }
        window.location.href = '/login';
    }
}

// Get current user role from api
async function getUserRole() {
    try {
        const data = await fetchJSONWithRetry('/api/auth/status', {
            credentials: 'include'
        }, getAuthStatusRetryOptions());
        
        if (data.authenticated) {
            return data.role;
        } else {
            return null;
        }
    } catch (error) {
        console.error('Error checking auth status:', error);
        return null;
    }
}

// Update UI based on user role
function updateUserInterface() {
    if (!currentUser) return;

    //console.log(`[Auth] Logged in as: ${currentUser.username} (Role: ${currentUser.role})`);
    //console.log(`[Auth] currentUser: ${JSON.stringify(currentUser)}`);
    
    // Update header with user info
    const usernameDisplay = document.getElementById('username-display');
    
    if (usernameDisplay) {
        usernameDisplay.textContent = currentUser.username;
    }
    
    // Remove parameters tab for read-only and regular users
    const parametersTab = document.querySelector('[data-tab="parameters"]');
    if ((currentUser.role === 'read-only' || currentUser.role === 'user') && parametersTab) {
        // Remove dom element
        parametersTab.remove();

        //Remove also parameters-tab
        const parametersTabContent = document.getElementById('parameters-tab');
        if (parametersTabContent) {
            parametersTabContent.remove();
        }
    }

    // Remove some tabs for read-only users
    if (currentUser.role === 'read-only') {
        // Remove equipment tab
        const equipmentLink = document.querySelector('[data-tab="equipment"]');
        const equipmentTabContent = document.getElementById('equipment-tab');
        if (equipmentLink) {
            equipmentLink.remove();
        }
        if (equipmentTabContent) {
            equipmentTabContent.remove();
        }
        // Remove astrodex button add button
        const addAstrodexBtn = document.getElementById('add-astrodex-item');
        if (addAstrodexBtn) {
            addAstrodexBtn.remove();
        }   
    }

    /*// Show/hide parameters tab for read-only users
    const parametersTab = document.querySelector('[data-tab="parameters"]');
    if (currentUser.role === 'read-only' && parametersTab) {
        parametersTab.style.display = 'none';
    }
    
    // Show users tab for admin only
    const usersTabBtn = document.getElementById('users-tab-btn');
    if (currentUser.role === 'admin' && usersTabBtn) {
        usersTabBtn.style.display = 'inline-block';
    }*/

    populateSecurityUsername();
    renderTwoFactorState();
    updateCustomizeMainTabOptions();
}

function normalizePreferences(preferences) {
    const merged = { ...DEFAULT_USER_PREFERENCES, ...(preferences || {}) };
    if (!startupSubtabsByMain[merged.startup_main_tab]) {
        merged.startup_main_tab = DEFAULT_USER_PREFERENCES.startup_main_tab;
    }
    if (!Object.values(startupSubtabsByMain).flat().includes(merged.startup_subtab)) {
        merged.startup_subtab = DEFAULT_USER_PREFERENCES.startup_subtab;
    }
    return merged;
}

async function loadUserPreferences() {
    try {
        const data = await fetchJSONWithRetry('/api/auth/preferences', {
            credentials: 'include'
        }, {
            maxAttempts: 2,
            timeoutMs: 10000
        });
        currentUserPreferences = normalizePreferences(data.preferences || {});

        // Apply language from server preference so it overrides browser/localStorage defaults.
        // This ensures the language stored in the user profile is always used on login,
        // even on a fresh browser or device where localStorage has no language set.
        const serverLang = currentUserPreferences.language;
        if (serverLang && typeof i18n !== 'undefined' && serverLang !== i18n.getCurrentLanguage()) {
            localStorage.setItem('myastroboard_language', serverLang);
            await i18n.setLanguage(serverLang);
            if (window.languageSelector) {
                window.languageSelector.setCurrentLanguage();
                window.languageSelector.updatePageTranslations();
            }
        }
    } catch (error) {
        console.error('Error loading user preferences:', error);
        currentUserPreferences = { ...DEFAULT_USER_PREFERENCES };
    }
}

function applyDensityPreference(density) {
    if (!document.body) return;
    document.body.classList.remove('density-compact');
    if (density === 'compact') {
        document.body.classList.add('density-compact');
    }
}

function applyUserPreferences() {
    const prefs = normalizePreferences(currentUserPreferences);
    currentUserPreferences = prefs;
    window.myastroboardUserPreferences = { ...prefs };
    localStorage.setItem('myastroboard_time_format', prefs.time_format);

    applyDensityPreference(prefs.density);

    if (window.MyAstroBoardTheme && typeof window.MyAstroBoardTheme.setTheme === 'function') {
        window.MyAstroBoardTheme.setTheme(prefs.theme_mode);
    }
}

// Shared by every "set this alert div's type + text, or hide it" message panel in
// this file (customize, security password, 2FA, trusted networks) - each used to
// carry its own byte-for-byte copy of this logic, differing only in the element id.
function setAlertMessage(elementId, type, message) {
    const messageDiv = document.getElementById(elementId);
    if (!messageDiv) return;

    messageDiv.className = 'alert';
    if (type === 'success') {
        messageDiv.classList.add('alert-success');
    } else if (type === 'error') {
        messageDiv.classList.add('alert-danger');
    } else {
        messageDiv.style.display = 'none';
        messageDiv.textContent = '';
        return;
    }

    messageDiv.textContent = message;
    messageDiv.style.display = 'block';
}

function setCustomizeMessage(type, message) {
    setAlertMessage('customize-message', type, message);
}

function getSubtabLabelKey(subtabName) {
    const map = {
        'astro-weather': 'navbar.astro_weather',
        'window': 'navbar.best_window',
        'moon': 'navbar.moon',
        'sun': 'navbar.sun',
        'aurora': 'navbar.aurora',
        'seeing': 'navbar.seeing',
        'iss': 'navbar.iss',
        'launches': 'spaceflight.subtab_launches',
        'astronauts': 'spaceflight.subtab_astronauts',
        'space-events': 'spaceflight.subtab_events',
        'calendar': 'navbar.calendar',
        'weather': 'navbar.weather',
        'trend': 'weather.observation_conditions',
        'astrodex': 'navbar.astrodex',
        'plan-my-night': 'navbar.plan_my_night',
        'combinations': 'equipment.combinations',
        'fov': 'equipment.fov_calculator',
        'telescopes': 'equipment.telescopes',
        'cameras': 'equipment.cameras',
        'mounts': 'equipment.mounts',
        'filters': 'equipment.filters',
        'accessories': 'equipment.accessories',
        'customize': 'settings.customize',
        'security': 'settings.security',
        'configuration': 'settings.configuration',
        'logs': 'settings.logs',
        'users': 'settings.users',
        'metrics': 'settings.metrics'
    };
    return map[subtabName] || null;
}

function updateCustomizeSubtabOptions() {
    const mainSelect = document.getElementById('pref-startup-main-tab');
    const subSelect = document.getElementById('pref-startup-subtab');
    if (!mainSelect || !subSelect) return;

    const selectedMain = mainSelect.value;
    const subtabs = startupSubtabsByMain[selectedMain] || [];

    DOMUtils.clear(subSelect);
    if (subtabs.length === 0) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = i18n.t('settings.pref_startup_subtab_none');
        subSelect.appendChild(option);
        subSelect.disabled = true;
        return;
    }

    subSelect.disabled = false;
    subtabs.forEach((subtabName) => {
        const option = document.createElement('option');
        option.value = subtabName;
        const key = getSubtabLabelKey(subtabName);
        option.textContent = key ? i18n.t(key) : subtabName;
        subSelect.appendChild(option);
    });
}

function updateCustomizeMainTabOptions() {
    const mainSelect = document.getElementById('pref-startup-main-tab');
    if (!mainSelect) return;

    Array.from(mainSelect.options).forEach((option) => {
        const tabButton = document.querySelector(`.main-tab-btn[data-tab="${option.value}"]`);
        option.disabled = !tabButton;
    });
}

function populateCustomizeFormFromPreferences() {
    const form = document.getElementById('customize-preferences-form');
    if (!form) return;

    const prefs = normalizePreferences(currentUserPreferences);
    currentUserPreferences = prefs;

    updateCustomizeMainTabOptions();

    const startupMain = document.getElementById('pref-startup-main-tab');
    const startupSub = document.getElementById('pref-startup-subtab');
    const timeFormat = document.getElementById('pref-time-format');
    const density = document.getElementById('pref-density');
    const theme = document.getElementById('pref-theme-mode');

    if (startupMain) {
        if (startupMain.querySelector(`option[value="${prefs.startup_main_tab}"]`)?.disabled) {
            prefs.startup_main_tab = DEFAULT_USER_PREFERENCES.startup_main_tab;
        }
        startupMain.value = prefs.startup_main_tab;
    }

    updateCustomizeSubtabOptions();

    if (startupSub) {
        const requested = prefs.startup_subtab;
        if (requested && startupSub.querySelector(`option[value="${requested}"]`)) {
            startupSub.value = requested;
        } else if (startupSub.options.length > 0) {
            startupSub.value = startupSub.options[0].value;
        }
    }

    if (timeFormat) timeFormat.value = prefs.time_format;
    if (density) density.value = prefs.density;
    if (theme) theme.value = prefs.theme_mode;
    const firstDow = document.getElementById('pref-first-day-of-week');
    if (firstDow) firstDow.value = prefs.first_day_of_week || DEFAULT_USER_PREFERENCES.first_day_of_week;
    const experienceLevel = document.getElementById('pref-experience-level');
    if (experienceLevel) experienceLevel.value = prefs.experience_level || DEFAULT_USER_PREFERENCES.experience_level;
    const beginnerCatalogEnabled = document.getElementById('pref-beginner-catalog-enabled');
    if (beginnerCatalogEnabled) {
        beginnerCatalogEnabled.checked = prefs.beginner_catalog_enabled !== false;
    }
    const recommendationsEnabled = document.getElementById('pref-recommendations-enabled');
    if (recommendationsEnabled) {
        recommendationsEnabled.checked = prefs.recommendations_enabled !== false;
    }
    const mqttPublishEnabled = document.getElementById('pref-mqtt-publish-enabled');
    if (mqttPublishEnabled) {
        mqttPublishEnabled.checked = prefs.mqtt_publish_enabled === true;
    }
    updateMqttPublishOptionVisibility();
}

/**
 * The "publish my activity to Home Assistant" switch only makes sense once an admin has
 * enabled the MQTT connector - hidden otherwise so the Customize form is not noise on
 * installs without a broker. The preference itself is user-scoped and always saved.
 */
function updateMqttPublishOptionVisibility() {
    const wrapper = document.getElementById('pref-mqtt-publish-wrapper');
    if (!wrapper) return;
    fetchJSONOnce('/api/connectors').then(connectors => {
        const mqtt = (connectors || []).find(c => c.name === 'mqtt');
        wrapper.classList.toggle('d-none', !(mqtt && mqtt.enabled));
    }).catch(() => wrapper.classList.add('d-none'));
}

async function saveUserPreferences(preferences) {
    const response = await fetchWithRetry('/api/auth/preferences', {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'include',
        body: JSON.stringify({ preferences })
    }, {
        maxAttempts: 1,
        timeoutMs: 15000
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const localizedMessage = data.error_key ? i18n.t(data.error_key) : null;
        throw new Error(localizedMessage || data.error || i18n.t('settings.pref_save_error'));
    }
    return normalizePreferences(data.preferences || preferences);
}

// Other scripts (e.g. first_run.js) that update the shared preferences state after
// calling saveUserPreferences() must go through this setter rather than assigning
// the bare `currentUserPreferences` identifier - from their file alone that looks
// like a missing declaration, when it's actually this `let` above being shared
// across script tags.
function setCurrentUserPreferences(preferences) {
    currentUserPreferences = preferences;
    return currentUserPreferences;
}

function setupCustomizeForm() {
    const form = document.getElementById('customize-preferences-form');
    if (!form) return;

    const startupMain = document.getElementById('pref-startup-main-tab');
    const startupSub = document.getElementById('pref-startup-subtab');
    const resetButton = document.getElementById('customize-reset-defaults-btn');

    startupMain?.addEventListener('change', () => {
        updateCustomizeSubtabOptions();
        if (startupSub && startupSub.options.length > 0) {
            startupSub.value = startupSub.options[0].value;
        }
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const preferences = {
            startup_main_tab: document.getElementById('pref-startup-main-tab')?.value || DEFAULT_USER_PREFERENCES.startup_main_tab,
            startup_subtab: document.getElementById('pref-startup-subtab')?.value || DEFAULT_USER_PREFERENCES.startup_subtab,
            time_format: document.getElementById('pref-time-format')?.value || DEFAULT_USER_PREFERENCES.time_format,
            density: document.getElementById('pref-density')?.value || DEFAULT_USER_PREFERENCES.density,
            theme_mode: document.getElementById('pref-theme-mode')?.value || DEFAULT_USER_PREFERENCES.theme_mode,
            first_day_of_week: document.getElementById('pref-first-day-of-week')?.value || DEFAULT_USER_PREFERENCES.first_day_of_week,
            experience_level: document.getElementById('pref-experience-level')?.value || DEFAULT_USER_PREFERENCES.experience_level,
            beginner_catalog_enabled: document.getElementById('pref-beginner-catalog-enabled')?.checked ?? DEFAULT_USER_PREFERENCES.beginner_catalog_enabled,
            recommendations_enabled: document.getElementById('pref-recommendations-enabled')?.checked ?? DEFAULT_USER_PREFERENCES.recommendations_enabled,
            mqtt_publish_enabled: document.getElementById('pref-mqtt-publish-enabled')?.checked ?? DEFAULT_USER_PREFERENCES.mqtt_publish_enabled
        };

        try {
            currentUserPreferences = await saveUserPreferences(preferences);
            applyUserPreferences();
            if (typeof window.applyUserStartupPreferences === 'function') {
                window.applyUserStartupPreferences(true);
            }
            setCustomizeMessage('success', i18n.t('settings.pref_save_success'));
        } catch (error) {
            console.error('Error saving preferences:', error);
            setCustomizeMessage('error', error.message || i18n.t('settings.pref_save_error'));
        }
    });

    resetButton?.addEventListener('click', async () => {
        try {
            currentUserPreferences = await saveUserPreferences({ ...DEFAULT_USER_PREFERENCES });
            applyUserPreferences();
            populateCustomizeFormFromPreferences();
            if (typeof window.applyUserStartupPreferences === 'function') {
                window.applyUserStartupPreferences(true);
            }
            setCustomizeMessage('success', i18n.t('settings.pref_reset_success'));
        } catch (error) {
            console.error('Error resetting preferences:', error);
            setCustomizeMessage('error', error.message || i18n.t('settings.pref_save_error'));
        }
    });

    window.addEventListener('i18nLanguageChanged', () => {
        updateCustomizeSubtabOptions();
        populateCustomizeFormFromPreferences();
    });

    const redoWizardBtn = document.getElementById('customize-redo-wizard-btn');
    redoWizardBtn?.addEventListener('click', async () => {
        if (typeof window.restartWizard === 'function') {
            await window.restartWizard();
        }
    });
}

function setupThemePickerSync() {
    const footerPicker = document.getElementById('theme-select-footer');
    if (!footerPicker) return;

    footerPicker.addEventListener('change', async (event) => {
        if (!currentUserPreferences) return;
        const newTheme = event.target.value;
        try {
            const updated = { ...currentUserPreferences, theme_mode: newTheme };
            currentUserPreferences = await saveUserPreferences(updated);
        } catch (_) {
            // Non-blocking: theme is already applied locally via theme.js
        }
    });
}

function populateSecurityUsername() {
    const usernameInput = document.getElementById('security-username');
    if (!usernameInput || !currentUser?.username) {
        return;
    }
    usernameInput.value = currentUser.username;
}

function setSecurityPasswordMessage(type, message) {
    setAlertMessage('security-password-message', type, message);
}

function setupSecurityPasswordForm() {
    const form = document.getElementById('security-change-password-form');
    if (!form) return;

    populateSecurityUsername();

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const currentPassword = document.getElementById('security-current-password')?.value || '';
        const newPassword = document.getElementById('security-new-password')?.value || '';
        const confirmPassword = document.getElementById('security-confirm-password')?.value || '';

        if (newPassword !== confirmPassword) {
            setSecurityPasswordMessage('error', i18n.t('users.passwords_do_not_match'));
            return;
        }

        if (newPassword.length < 6) {
            setSecurityPasswordMessage('error', i18n.t('users.password_too_short'));
            return;
        }

        if (currentPassword === newPassword) {
            setSecurityPasswordMessage('error', i18n.t('users.password_must_be_different'));
            return;
        }

        try {
            const response = await fetchWithRetry('/api/auth/change-password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword
                })
            }, {
                maxAttempts: 1,
                timeoutMs: 15000
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const localizedMessage = data.error_key ? i18n.t(data.error_key) : null;
                setSecurityPasswordMessage('error', localizedMessage || data.error || i18n.t('users.error_update_password'));
                return;
            }

            form.reset();
            populateSecurityUsername();
            setSecurityPasswordMessage('success', i18n.t('users.password_updated'));

            // Hide default-password warning once password changed successfully.
            const warningBanner = document.getElementById('default-password-warning');
            if (warningBanner) {
                warningBanner.style.display = 'none';
            }
        } catch (error) {
            console.error('Error updating own password:', error);
            setSecurityPasswordMessage('error', i18n.t('users.error_update_password'));
        }
    });
}

// Show default password warning
function showDefaultPasswordWarning() {
    const warningBanner = document.getElementById('default-password-warning');
    if (warningBanner) {
        warningBanner.style.display = 'block';
    }
}

// Logout handler
async function handleLogout(event) {
    // Prevent default link behavior
    event.preventDefault();
    try {
        await fetchJSONWithRetry('/api/auth/logout', {
            method: 'POST',
            credentials: 'include'
        }, {
            maxAttempts: 1,
            timeoutMs: 10000
        });
        window.location.href = '/login';
    } catch (error) {
        console.error('Logout error:', error);
        window.location.href = '/login';
    }
}

// Setup logout button
function setupLogoutButton() {
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
    }
}

// ============================================================
// User Management (Admin only)
// ============================================================

async function loadUsers() {
    if (currentUser?.role !== 'admin') return;

    // Kicked off together, not one after the other: the local-scope warning banner
    // depends on both this and the security settings, and each independently renders
    // as soon as its own request resolves - starting both at once is what actually
    // gives it its "whichever lands first" behavior, rather than always waiting on
    // this one first.
    const securitySettingsPromise = loadSecuritySettings();

    try {
        const response = await fetchWithRetry('/api/users', {
            credentials: 'include'
        }, {
            maxAttempts: 3,
            timeoutMs: 10000
        });

        if (response.status === 401 || response.status === 403) {
            window.location.href = '/login';
            return;
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(localizeApiError(errorData, 'users.failed_to_load_users'));
        }

        const users = await response.json();
        displayUsers(users);
    } catch (error) {
        console.error('Error loading users:', error);
        showMessage('error', i18n.t('users.failed_to_load_users'));
    } finally {
        await securitySettingsPromise;
    }
}

function displayUsers(users) {
    const usersList = document.getElementById('users-list');
    if (!usersList) return;

    // Precomputed so the local-scope warning banner can re-render as soon as either
    // this or the security-settings request resolves, whichever lands first (both are
    // kicked off together in loadUsers()) without re-filtering the full user list.
    lastLocalAccountCount = users.filter((user) => user.account_scope === 'local').length;
    renderLocalScopeWarning();
    
    if (users.length === 0) {
        DOMUtils.clear(usersList);
        const alert = document.createElement('div');
        alert.className = 'alert alert-warning';
        alert.textContent = i18n.t('users.no_users_found');
        usersList.appendChild(alert);
        return;
    }

    const table = document.createElement('div');
    table.className = 'table-responsive';

    const tableElement = document.createElement('table');
    tableElement.className = 'table table-sm table-hover';
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    const headers = [
        { text: i18n.t('users.username') },
        { text: i18n.t('users.role') },
        { text: i18n.t('users.account_scope') },
        { text: i18n.t('users.two_factor_status'), className: 'd-none d-md-table-cell' },
        { text: i18n.t('users.created'), className: 'd-none d-md-table-cell' },
        { text: i18n.t('users.last_login'), className: 'd-none d-md-table-cell' },
        { text: i18n.t('users.actions'), className: 'text-center' }
    ];
    headers.forEach((header) => {
        const th = document.createElement('th');
        th.textContent = header.text;
        if (header.className) {
            th.className = header.className;
        }
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);

    const tbody = document.createElement('tbody');
    tbody.id = 'users-table-body';
    tableElement.appendChild(thead);
    tableElement.appendChild(tbody);
    table.appendChild(tableElement);
    
    users.forEach(user => {
        const row = document.createElement('tr');
        
        const createdDate = user.created_at ? formatDateFull(new Date(user.created_at)) : i18n.t('users.na');
        const lastLogin = user.last_login ? formatDateTime(new Date(user.last_login)) : i18n.t('users.never');
        
        const isCurrentUser = user.user_id === currentUser?.user_id;

        const usernameCell = document.createElement('th');
        usernameCell.textContent = user.username;

        const roleCell = document.createElement('td');
        roleCell.textContent = user.role;

        // Entries written before this field existed load as 'global'.
        const accountScope = user.account_scope === 'local' ? 'local' : 'global';
        const scopeCell = document.createElement('td');
        scopeCell.textContent = i18n.t(
            accountScope === 'local' ? 'users.account_scope_local_short' : 'users.account_scope_global_short'
        );

        // Plain text, matching the Role/Scope cells beside it - not a badge, so the
        // row's status columns stay one consistent style instead of two.
        const twoFactorCell = document.createElement('td');
        twoFactorCell.className = 'd-none d-md-table-cell';
        twoFactorCell.textContent = i18n.t(
            user.totp_enabled ? 'users.two_factor_enabled_yes' : 'users.two_factor_enabled_no'
        );

        const createdCell = document.createElement('td');
        createdCell.className = 'd-none d-md-table-cell';
        createdCell.textContent = createdDate;

        const lastLoginCell = document.createElement('td');
        lastLoginCell.className = 'd-none d-md-table-cell';
        lastLoginCell.textContent = lastLogin;

        const actionsCell = document.createElement('td');
        actionsCell.className = 'text-center';

        const createActionButton = ({ className, userId, username, role, iconClass, label }) => {
            const button = document.createElement('button');
            button.className = className;
            button.setAttribute('data-user-id', userId);
            button.setAttribute('data-username', username);
            if (role) {
                button.setAttribute('data-role', role);
            }
            DOMUtils.append(button, DOMUtils.createIcon(iconClass), label);
            return button;
        };

        actionsCell.appendChild(createActionButton({
            className: 'btn btn-primary btn-small user-edit-username mb-2 me-2',
            userId: user.user_id,
            username: user.username,
            iconClass: 'bi bi-pencil-square icon-inline',
            label: i18n.t('users.username')
        }));

        if (!isCurrentUser) {
            actionsCell.appendChild(createActionButton({
                className: 'btn btn-info btn-small user-edit-role mb-2 me-2',
                userId: user.user_id,
                username: user.username,
                role: user.role,
                iconClass: 'bi bi-key icon-inline',
                label: i18n.t('users.role')
            }));

            const scopeButton = createActionButton({
                className: 'btn btn-info btn-small user-edit-scope mb-2 me-2',
                userId: user.user_id,
                username: user.username,
                iconClass: 'bi bi-geo icon-inline',
                label: i18n.t('users.account_scope')
            });
            scopeButton.setAttribute('data-account-scope', accountScope);
            actionsCell.appendChild(scopeButton);
        }

        actionsCell.appendChild(createActionButton({
            className: 'btn btn-secondary btn-small user-change-password mb-2 me-2',
            userId: user.user_id,
            username: user.username,
            iconClass: 'bi bi-lock icon-inline',
            label: i18n.t('users.password')
        }));

        // An admin manages their own 2FA from My Settings, not from this table.
        if (!isCurrentUser && user.totp_enabled) {
            actionsCell.appendChild(createActionButton({
                className: 'btn btn-warning btn-small user-disable-2fa mb-2 me-2',
                userId: user.user_id,
                username: user.username,
                iconClass: 'bi bi-shield-slash icon-inline',
                label: i18n.t('users.disable_2fa_for_user')
            }));
        }

        if (!isCurrentUser) {
            actionsCell.appendChild(createActionButton({
                className: 'btn btn-danger btn-small user-delete mb-2 me-2',
                userId: user.user_id,
                username: user.username,
                iconClass: 'bi bi-trash icon-inline',
                label: i18n.t('users.delete')
            }));
        }

        row.appendChild(usernameCell);
        row.appendChild(roleCell);
        row.appendChild(scopeCell);
        row.appendChild(twoFactorCell);
        row.appendChild(createdCell);
        row.appendChild(lastLoginCell);
        row.appendChild(actionsCell);
        
        tbody.appendChild(row);
    });
    
    DOMUtils.clear(usersList);
    usersList.appendChild(table);
    
    // Attach event listeners to buttons
    usersList.querySelectorAll('.user-edit-username').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const userId = e.target.getAttribute('data-user-id');
            const username = e.target.getAttribute('data-username');
            editUsername(userId, username);
        });
    });
    
    usersList.querySelectorAll('.user-edit-role').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const userId = e.target.getAttribute('data-user-id');
            const username = e.target.getAttribute('data-username');
            const role = e.target.getAttribute('data-role');
            editRole(userId, username, role);
        });
    });
    
    usersList.querySelectorAll('.user-edit-scope').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const button = e.target.closest('.user-edit-scope');
            editAccountScope(
                button.getAttribute('data-user-id'),
                button.getAttribute('data-username'),
                button.getAttribute('data-account-scope')
            );
        });
    });

    usersList.querySelectorAll('.user-disable-2fa').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const button = e.target.closest('.user-disable-2fa');
            adminDisableUserTwoFactor(
                button.getAttribute('data-user-id'),
                button.getAttribute('data-username')
            );
        });
    });

    usersList.querySelectorAll('.user-change-password').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const userId = e.target.getAttribute('data-user-id');
            const username = e.target.getAttribute('data-username');
            changePassword(userId, username);
        });
    });
    
    usersList.querySelectorAll('.user-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const userId = e.target.getAttribute('data-user-id');
            const username = e.target.getAttribute('data-username');
            deleteUser(userId, username);
        });
    });
}

// Create user form handler
function setupCreateUserForm() {
    const form = document.getElementById('create-user-form');
    if (!form) return;
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const username = document.getElementById('new-username').value;
        const password = document.getElementById('new-password').value;
        const role = document.getElementById('new-role').value;
        const accountScope = document.getElementById('new-account-scope')?.value || 'global';
        
        try {
            const response = await fetchWithRetry('/api/users', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({ username, password, role, account_scope: accountScope })
            }, {
                maxAttempts: 1,
                timeoutMs: 15000
            });
            
            const data = await response.json();
            
            if (response.ok) {
                showMessage('success', i18n.t('users.success_create'));
                form.reset();
                loadUsers();
            } else {
                showMessage('error', localizeApiError(data, 'users.error_create'));
            }
        } catch (error) {
            console.error('Error creating user:', error);
            showMessage('error', i18n.t('users.error_create'));
        }
    });
}

// Edit username using modal dialog
function editUsername(userId, currentUsername) {
    const titleElement = document.getElementById('modal_lg_close_title');
    DOMUtils.clear(titleElement);
    DOMUtils.append(titleElement, DOMUtils.createIcon('bi bi-pencil-square icon-inline'), i18n.t('users.edit_username'));
    
    const contentElement = document.getElementById('modal_lg_close_body');
    DOMUtils.clear(contentElement);

    const infoAlert = document.createElement('div');
    infoAlert.className = 'alert alert-info';
    infoAlert.append(i18n.t('users.edit_username_for'));
    const strong = document.createElement('strong');
    strong.textContent = currentUsername;
    infoAlert.appendChild(strong);

    const errorAlert = document.createElement('div');
    errorAlert.id = 'username-modal-error';
    errorAlert.className = 'alert alert-danger';
    errorAlert.style.display = 'none';

    const form = document.createElement('form');
    form.id = 'username-edit-form';
    form.className = 'row g-3';

    const hiddenUserId = document.createElement('input');
    hiddenUserId.type = 'hidden';
    hiddenUserId.id = 'edit-user-id';
    hiddenUserId.value = userId;

    const fieldCol = document.createElement('div');
    fieldCol.className = 'col-md-12';
    const label = document.createElement('label');
    label.className = 'form-label';
    label.setAttribute('for', 'new-username-input');
    label.textContent = i18n.t('users.new_username');
    const input = document.createElement('input');
    input.type = 'text';
    input.id = 'new-username-input';
    input.required = true;
    input.minLength = 3;
    input.placeholder = i18n.t('users.new_username_placeholder');
    input.autocomplete = 'username';
    input.className = 'form-control';
    input.value = currentUsername;
    fieldCol.appendChild(label);
    fieldCol.appendChild(input);

    const actionsCol = document.createElement('div');
    actionsCol.className = 'col-md-12 d-flex justify-content-end';
    actionsCol.style.gap = '1rem';
    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = i18n.t('users.save_username');
    actionsCol.appendChild(submitBtn);

    form.appendChild(hiddenUserId);
    form.appendChild(fieldCol);
    form.appendChild(actionsCol);

    contentElement.appendChild(infoAlert);
    contentElement.appendChild(errorAlert);
    contentElement.appendChild(form);
    
    openModal('#modal_lg_close', { backdrop: 'static' });

    const formElement = document.getElementById('username-edit-form');
    const errorDiv = document.getElementById('username-modal-error');
    
    formElement.onsubmit = async function(e) {
        e.preventDefault();
        
        const newUsername = document.getElementById('new-username-input').value;
        const userId = document.getElementById('edit-user-id').value;
        
        if (newUsername === currentUsername) {
            errorDiv.textContent = i18n.t('users.username_unchanged');
            errorDiv.style.display = 'block';
            return;
        }
        
        if (newUsername.length < 3) {
            errorDiv.textContent = i18n.t('users.username_too_short');
            errorDiv.style.display = 'block';
            return;
        }
        
        try {
            const response = await fetchWithRetry(`/api/users/${userId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({ username: newUsername })
            }, {
                maxAttempts: 1,
                timeoutMs: 15000
            });
            
            const data = await response.json();
            
            if (response.ok) {
                showMessage('success', i18n.t('users.username_updated'));
                loadUsers();
                closeModal('#modal_lg_close');
            } else {
                errorDiv.textContent = localizeApiError(data, 'users.error_update_username');
                errorDiv.style.display = 'block';
            }
        } catch (error) {
            console.error('Error updating username:', error);
            errorDiv.textContent = i18n.t('users.error_update_username');
            errorDiv.style.display = 'block';
        }
    };
}

// Edit user role using modal dialog
// Build and open the shared "edit one <select> field for this user" modal: title +
// icon, an info alert naming the user, a single select populated from *options*, and
// a submit handler that PUTs {[fieldName]: value} to /api/users/<id> - success shows
// a global message, reloads the table and closes the modal; failure shows an inline
// error. Shared by editRole() and editAccountScope(), which used to each carry an
// almost line-for-line copy of this (title/body setup, alerts, select, submit
// handler shape), differing only in the field name, i18n keys and option list.
function openEditFieldModal({
    userId, username, currentValue, fieldName, iconClass, titleKey, infoForKey,
    selectLabelKey, submitLabelKey, unchangedKey, successKey, errorFallbackKey, options
}) {
    const titleElement = document.getElementById('modal_lg_close_title');
    DOMUtils.clear(titleElement);
    DOMUtils.append(titleElement, DOMUtils.createIcon(iconClass), i18n.t(titleKey));

    const contentElement = document.getElementById('modal_lg_close_body');
    DOMUtils.clear(contentElement);

    const infoAlert = document.createElement('div');
    infoAlert.className = 'alert alert-info';
    infoAlert.append(i18n.t(infoForKey));
    const strong = document.createElement('strong');
    strong.textContent = username;
    infoAlert.appendChild(strong);

    const errorAlert = document.createElement('div');
    errorAlert.className = 'alert alert-danger';
    errorAlert.style.display = 'none';

    const form = document.createElement('form');
    form.className = 'row g-3';

    const selectCol = document.createElement('div');
    selectCol.className = 'col-md-12';
    const select = document.createElement('select');
    select.className = 'form-select';
    select.id = `edit-field-select-${fieldName}`;
    select.required = true;
    const label = document.createElement('label');
    label.className = 'form-label';
    label.setAttribute('for', select.id);
    label.textContent = i18n.t(selectLabelKey);

    options.forEach((optionData) => {
        const option = document.createElement('option');
        option.value = optionData.value;
        option.textContent = optionData.textKey ? i18n.t(optionData.textKey) : optionData.text;
        option.selected = optionData.value === currentValue;
        select.appendChild(option);
    });

    selectCol.appendChild(label);
    selectCol.appendChild(select);

    const actionsCol = document.createElement('div');
    actionsCol.className = 'col-md-12 d-flex justify-content-end modal-actions-gap';
    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = i18n.t(submitLabelKey);
    actionsCol.appendChild(submitBtn);

    form.appendChild(selectCol);
    form.appendChild(actionsCol);

    contentElement.appendChild(infoAlert);
    contentElement.appendChild(errorAlert);
    contentElement.appendChild(form);

    openModal('#modal_lg_close', { backdrop: 'static' });

    form.onsubmit = async (e) => {
        e.preventDefault();

        const newValue = select.value;
        if (newValue === currentValue) {
            errorAlert.textContent = i18n.t(unchangedKey);
            errorAlert.style.display = 'block';
            return;
        }

        try {
            const response = await fetchWithRetry(`/api/users/${userId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ [fieldName]: newValue })
            }, {
                maxAttempts: 1,
                timeoutMs: 15000
            });

            const data = await response.json();

            if (response.ok) {
                showMessage('success', i18n.t(successKey));
                loadUsers();
                closeModal('#modal_lg_close');
            } else {
                errorAlert.textContent = localizeApiError(data, errorFallbackKey);
                errorAlert.style.display = 'block';
            }
        } catch (error) {
            console.error(`Error updating ${fieldName}:`, error);
            errorAlert.textContent = i18n.t(errorFallbackKey);
            errorAlert.style.display = 'block';
        }
    };
}

function editRole(userId, username, currentRole) {
    openEditFieldModal({
        userId,
        username,
        currentValue: currentRole,
        fieldName: 'role',
        iconClass: 'bi bi-key icon-inline',
        titleKey: 'users.edit_role',
        infoForKey: 'users.edit_role_for',
        selectLabelKey: 'users.new_role',
        submitLabelKey: 'users.save_role',
        unchangedKey: 'users.role_unchanged',
        successKey: 'users.role_updated',
        errorFallbackKey: 'users.error_update_role',
        options: [
            { value: 'admin', text: 'Admin' },
            { value: 'user', text: 'User' },
            { value: 'read-only', text: 'Read-Only' }
        ]
    });
}

// Change password using modal dialog
function changePassword(userId, username) {
    //Prepare modal title
    const titleElement = document.getElementById('modal_lg_close_title');
    DOMUtils.clear(titleElement);
    DOMUtils.append(titleElement, DOMUtils.createIcon('bi bi-lock icon-inline'), i18n.t('users.change_password'));
    
    //Prepare modal content
    const contentElement = document.getElementById('modal_lg_close_body');
    DOMUtils.clear(contentElement);

    const infoAlert = document.createElement('div');
    infoAlert.className = 'alert alert-info';
    infoAlert.append(i18n.t('users.change_password_for'));
    const strong = document.createElement('strong');
    strong.id = 'password-modal-username';
    infoAlert.appendChild(strong);

    const errorAlert = document.createElement('div');
    errorAlert.id = 'password-modal-error';
    errorAlert.className = 'alert alert-danger';
    errorAlert.style.display = 'none';

    const form = document.createElement('form');
    form.id = 'password-change-form';
    form.className = 'row g-3';

    const hiddenUserId = document.createElement('input');
    hiddenUserId.type = 'hidden';
    hiddenUserId.id = 'password-change-user-id';
    hiddenUserId.value = userId;

    const hiddenUsername = document.createElement('input');
    hiddenUsername.type = 'text';
    hiddenUsername.id = 'password-change-username';
    hiddenUsername.autocomplete = 'username';
    hiddenUsername.style.display = 'none';
    hiddenUsername.readOnly = true;
    hiddenUsername.value = username;

    const newPasswordCol = document.createElement('div');
    newPasswordCol.className = 'col-md-12';
    const newPasswordLabel = document.createElement('label');
    newPasswordLabel.className = 'form-label';
    newPasswordLabel.setAttribute('for', 'new-password-input');
    newPasswordLabel.textContent = i18n.t('users.new_password');
    const newPasswordInput = document.createElement('input');
    newPasswordInput.type = 'password';
    newPasswordInput.id = 'new-password-input';
    newPasswordInput.required = true;
    newPasswordInput.minLength = 6;
    newPasswordInput.placeholder = i18n.t('users.new_password_placeholder');
    newPasswordInput.autocomplete = 'new-password';
    newPasswordInput.className = 'form-control';
    newPasswordCol.appendChild(newPasswordLabel);
    newPasswordCol.appendChild(newPasswordInput);

    const confirmPasswordCol = document.createElement('div');
    confirmPasswordCol.className = 'col-md-12';
    const confirmPasswordLabel = document.createElement('label');
    confirmPasswordLabel.className = 'form-label';
    confirmPasswordLabel.setAttribute('for', 'confirm-password-input');
    confirmPasswordLabel.textContent = i18n.t('users.confirm_password');
    const confirmPasswordInput = document.createElement('input');
    confirmPasswordInput.type = 'password';
    confirmPasswordInput.id = 'confirm-password-input';
    confirmPasswordInput.required = true;
    confirmPasswordInput.minLength = 4;
    confirmPasswordInput.placeholder = i18n.t('users.confirm_password_placeholder');
    confirmPasswordInput.autocomplete = 'new-password';
    confirmPasswordInput.className = 'form-control';
    confirmPasswordCol.appendChild(confirmPasswordLabel);
    confirmPasswordCol.appendChild(confirmPasswordInput);

    const actionsCol = document.createElement('div');
    actionsCol.className = 'col-md-12 d-flex justify-content-end';
    actionsCol.style.gap = '1rem';
    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = i18n.t('users.save_password');
    actionsCol.appendChild(submitBtn);

    form.appendChild(hiddenUserId);
    form.appendChild(hiddenUsername);
    form.appendChild(newPasswordCol);
    form.appendChild(confirmPasswordCol);
    form.appendChild(actionsCol);

    contentElement.appendChild(infoAlert);
    contentElement.appendChild(errorAlert);
    contentElement.appendChild(form);

    const usernameDisplay = document.getElementById('password-modal-username');
    const usernameInput = document.getElementById('password-change-username');
    const errorDiv = document.getElementById('password-modal-error');
    const formElement = document.getElementById('password-change-form');
    
    // Set username
    if (usernameDisplay) {
        usernameDisplay.textContent = username;
    }
    if (usernameInput) {
        usernameInput.value = username;
    }
    
    // Clear form
    formElement.reset();
    // Re-set username after reset
    if (usernameInput) {
        usernameInput.value = username;
    }
    errorDiv.style.display = 'none';
    errorDiv.textContent = '';
    
    
    // Display the modal modal_lg_close
    openModal('#modal_lg_close', { backdrop: 'static' });

    setupPasswordChangeModal(userId);
}

// Setup password change modal
function setupPasswordChangeModal(userId) {
    const form = document.getElementById('password-change-form');
    const errorDiv = document.getElementById('password-modal-error');
    
    
    // Handle form submission
    if (form) {
        form.onsubmit = async function(e) {
            e.preventDefault();
            
            const userId = document.getElementById('password-change-user-id').value;
            const newPassword = document.getElementById('new-password-input').value;
            const confirmPassword = document.getElementById('confirm-password-input').value;
            
            // Validate passwords match
            if (newPassword !== confirmPassword) {
                errorDiv.textContent = i18n.t('users.passwords_do_not_match');
                errorDiv.style.display = 'block';
                return;
            }
            
            // Validate password length
            if (newPassword.length < 6) {
                errorDiv.textContent = i18n.t('users.password_too_short');
                errorDiv.style.display = 'block';
                return;
            }
            
            try {
                const response = await fetchWithRetry(`/api/users/${userId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    credentials: 'include',
                    body: JSON.stringify({ password: newPassword })
                }, {
                    maxAttempts: 1,
                    timeoutMs: 15000
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showMessage('success', i18n.t('users.password_updated'));
                    loadUsers();

                    // Close bootstrap modal
                    closeModal('#modal_lg_close');

                } else {
                    errorDiv.textContent = localizeApiError(data, 'users.error_update_password');
                    errorDiv.style.display = 'block';
                }
            } catch (error) {
                console.error('Error updating password:', error);
                errorDiv.textContent = i18n.t('users.error_update_password');
                errorDiv.style.display = 'block';
            }
        };
    }
}

// Delete user
async function deleteUser(userId, username) {
    if (!confirm(i18n.t('users.confirm_delete_user', { username }))) {
        return;
    }
    
    try {
        const response = await fetchWithRetry(`/api/users/${userId}`, {
            method: 'DELETE',
            credentials: 'include'
        }, {
            maxAttempts: 1,
            timeoutMs: 15000
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage('success', i18n.t('users.user_deleted_successfully'));
            loadUsers();
        } else {
            showMessage('error', localizeApiError(data, 'users.error_delete_user'));
        }
    } catch (error) {
        console.error('Error deleting user:', error);
        showMessage('error', i18n.t('users.error_delete_user'));
    }
}

// ============================================================
// Two-factor authentication - self-service (My Settings -> Security)
// ============================================================

function setSecurityTwoFactorMessage(type, message) {
    setAlertMessage('security-2fa-message', type, message);
}

// Render the panel from the current /api/auth/status snapshot: the admin switch
// decides whether 2FA is offered at all, the per-user flag whether it is active.
function renderTwoFactorState() {
    const unavailable = document.getElementById('security-2fa-unavailable');
    const panel = document.getElementById('security-2fa-panel');
    if (!unavailable || !panel) return;

    const available = !!currentUser?.two_factor_available;
    unavailable.style.display = available ? 'none' : 'block';
    panel.style.display = available ? 'block' : 'none';
    if (!available) return;

    const enabled = !!currentUser?.totp_enabled;
    const inactiveBlock = document.getElementById('security-2fa-inactive');
    const activeBlock = document.getElementById('security-2fa-active');
    if (inactiveBlock) inactiveBlock.style.display = enabled ? 'none' : 'block';
    if (activeBlock) activeBlock.style.display = enabled ? 'block' : 'none';

    const confirmedAt = document.getElementById('security-2fa-confirmed-at');
    if (confirmedAt) {
        confirmedAt.textContent = (enabled && currentUser?.totp_confirmed_at)
            ? i18n.t('settings.2fa_confirmed_at', { date: formatDateTime(new Date(currentUser.totp_confirmed_at)) })
            : '';
    }
}

// Draw the otpauth:// URI into a canvas with the vendored generator. Always black
// on white: a themed QR code is not reliably scannable.
function renderTwoFactorQrCode(container, otpauthUri) {
    if (typeof qrcode !== 'function') {
        console.warn('QR code library unavailable, falling back to the manual key only');
        return false;
    }

    try {
        const qr = qrcode(0, 'M');
        qr.addData(otpauthUri);
        qr.make();

        const moduleCount = qr.getModuleCount();
        const cellSize = 6;
        const quietZone = 4 * cellSize;
        const size = moduleCount * cellSize + quietZone * 2;

        const canvas = document.createElement('canvas');
        canvas.width = size;
        canvas.height = size;
        canvas.className = 'totp-qr-canvas';
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', i18n.t('settings.2fa_setup_scan_qr'));

        const context = canvas.getContext('2d');
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, size, size);
        context.fillStyle = '#000000';
        for (let row = 0; row < moduleCount; row++) {
            for (let col = 0; col < moduleCount; col++) {
                if (qr.isDark(row, col)) {
                    context.fillRect(quietZone + col * cellSize, quietZone + row * cellSize, cellSize, cellSize);
                }
            }
        }

        container.appendChild(canvas);
        return true;
    } catch (error) {
        console.error('Failed to render 2FA QR code:', error);
        return false;
    }
}

function buildTwoFactorSetupModal(secret, otpauthUri) {
    const titleElement = document.getElementById('modal_lg_close_title');
    DOMUtils.clear(titleElement);
    DOMUtils.append(titleElement, DOMUtils.createIcon('bi bi-shield-lock icon-inline'), i18n.t('settings.2fa_setup_title'));

    const contentElement = document.getElementById('modal_lg_close_body');
    DOMUtils.clear(contentElement);

    // 1. QR code - scanned from a second device.
    const qrWrapper = document.createElement('div');
    qrWrapper.className = 'text-center mb-3';
    const qrCaption = document.createElement('p');
    qrCaption.textContent = i18n.t('settings.2fa_setup_scan_qr');
    qrWrapper.appendChild(qrCaption);
    if (!renderTwoFactorQrCode(qrWrapper, otpauthUri)) {
        const qrFallback = document.createElement('div');
        qrFallback.className = 'alert alert-warning';
        qrFallback.textContent = i18n.t('settings.2fa_qr_unavailable');
        qrWrapper.appendChild(qrFallback);
    }

    // 2. Manual key - the one path that works identically on desktop and mobile,
    //    including when the authenticator app runs on the same phone.
    const manualWrapper = document.createElement('div');
    manualWrapper.className = 'mb-3';
    const manualLabel = document.createElement('label');
    manualLabel.className = 'form-label';
    manualLabel.setAttribute('for', 'totp-manual-secret');
    manualLabel.textContent = i18n.t('settings.2fa_setup_manual_key');
    const manualInput = document.createElement('input');
    manualInput.type = 'text';
    manualInput.id = 'totp-manual-secret';
    manualInput.className = 'form-control font-monospace totp-secret';
    manualInput.value = secret;
    manualInput.readOnly = true;
    manualInput.addEventListener('focus', () => manualInput.select());
    manualWrapper.appendChild(manualLabel);
    manualWrapper.appendChild(manualInput);

    // 3. Best-effort deep link: not every authenticator registers the otpauth:// scheme.
    const openLink = document.createElement('a');
    openLink.className = 'btn btn-outline-secondary btn-sm mb-3';
    openLink.href = otpauthUri;
    openLink.rel = 'noopener noreferrer';
    DOMUtils.append(openLink, DOMUtils.createIcon('bi bi-box-arrow-up-right icon-inline'), i18n.t('settings.2fa_setup_open_in_app'));

    const errorAlert = document.createElement('div');
    errorAlert.id = 'totp-setup-error';
    errorAlert.className = 'alert alert-danger';
    errorAlert.style.display = 'none';

    // 4. Confirmation: the code proves the secret really reached the authenticator.
    const form = document.createElement('form');
    form.id = 'totp-confirm-form';
    form.className = 'row g-3 align-items-end';

    const codeCol = document.createElement('div');
    codeCol.className = 'col-md-6';
    const codeLabel = document.createElement('label');
    codeLabel.className = 'form-label';
    codeLabel.setAttribute('for', 'totp-confirm-code');
    codeLabel.textContent = i18n.t('settings.2fa_setup_confirm_code');
    const codeInput = document.createElement('input');
    codeInput.type = 'text';
    codeInput.id = 'totp-confirm-code';
    codeInput.className = 'form-control';
    codeInput.setAttribute('inputmode', 'numeric');
    codeInput.setAttribute('pattern', '[0-9]*');
    codeInput.setAttribute('maxlength', '6');
    codeInput.setAttribute('autocomplete', 'one-time-code');
    codeInput.required = true;
    codeInput.addEventListener('input', () => {
        codeInput.value = codeInput.value.replace(/[^0-9]/g, '').slice(0, 6);
    });
    codeCol.appendChild(codeLabel);
    codeCol.appendChild(codeInput);

    const actionsCol = document.createElement('div');
    actionsCol.className = 'col-md-6';
    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    DOMUtils.append(submitBtn, DOMUtils.createIcon('bi bi-check2-circle icon-inline'), i18n.t('settings.2fa_setup_confirm_btn'));
    actionsCol.appendChild(submitBtn);

    form.appendChild(codeCol);
    form.appendChild(actionsCol);

    contentElement.appendChild(qrWrapper);
    contentElement.appendChild(manualWrapper);
    contentElement.appendChild(openLink);
    contentElement.appendChild(errorAlert);
    contentElement.appendChild(form);

    return form;
}

async function startTwoFactorSetup() {
    setSecurityTwoFactorMessage(null);

    try {
        const response = await fetchWithRetry('/api/auth/2fa/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include'
        }, {
            maxAttempts: 1,
            timeoutMs: 15000
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            setSecurityTwoFactorMessage('error', localizeApiError(data, 'settings.2fa_setup_error'));
            return;
        }

        const form = buildTwoFactorSetupModal(data.secret, data.otpauth_uri);
        openModal('#modal_lg_close', {
            backdrop: 'static',
            onShown: () => document.getElementById('totp-confirm-code')?.focus()
        });

        form.onsubmit = (event) => {
            event.preventDefault();
            confirmTwoFactorSetup(document.getElementById('totp-confirm-code')?.value || '');
        };
    } catch (error) {
        console.error('Error starting 2FA setup:', error);
        setSecurityTwoFactorMessage('error', i18n.t('settings.2fa_setup_error'));
    }
}

async function confirmTwoFactorSetup(code) {
    const errorDiv = document.getElementById('totp-setup-error');
    const showModalError = (message) => {
        if (!errorDiv) return;
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    };

    if (code.trim().length !== 6) {
        showModalError(i18n.t('auth.invalid_otp_code'));
        return;
    }

    try {
        const response = await fetchWithRetry('/api/auth/2fa/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ code: code.trim() })
        }, {
            maxAttempts: 1,
            timeoutMs: 15000
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            showModalError(localizeApiError(data, 'settings.2fa_setup_error'));
            return;
        }

        if (currentUser) {
            currentUser.totp_enabled = true;
            currentUser.totp_confirmed_at = new Date().toISOString();
        }
        closeModal('#modal_lg_close');
        renderTwoFactorState();
        setSecurityTwoFactorMessage('success', i18n.t('settings.2fa_activated'));
    } catch (error) {
        console.error('Error confirming 2FA setup:', error);
        showModalError(i18n.t('settings.2fa_setup_error'));
    }
}

async function disableTwoFactor(password) {
    setSecurityTwoFactorMessage(null);

    try {
        const response = await fetchWithRetry('/api/auth/2fa/disable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ password })
        }, {
            maxAttempts: 1,
            timeoutMs: 15000
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            setSecurityTwoFactorMessage('error', localizeApiError(data, 'settings.2fa_setup_error'));
            return;
        }

        if (currentUser) {
            currentUser.totp_enabled = false;
            currentUser.totp_confirmed_at = null;
        }
        renderTwoFactorState();
        setSecurityTwoFactorMessage('success', i18n.t('settings.2fa_deactivated'));
    } catch (error) {
        console.error('Error disabling 2FA:', error);
        setSecurityTwoFactorMessage('error', i18n.t('settings.2fa_setup_error'));
    }
}

function setupTwoFactorPanel() {
    document.getElementById('security-2fa-enable-btn')?.addEventListener('click', startTwoFactorSetup);

    const disableForm = document.getElementById('security-2fa-disable-form');
    disableForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const passwordInput = document.getElementById('security-2fa-password');
        const password = passwordInput?.value || '';
        if (!password) {
            setSecurityTwoFactorMessage('error', i18n.t('users.current_password_incorrect'));
            return;
        }
        await disableTwoFactor(password);
        disableForm.reset();
    });
}

// ============================================================
// Instance security settings - trusted networks (Parameters -> Users, admin only)
// ============================================================

function setSecuritySettingsMessage(type, message) {
    setAlertMessage('security-settings-message', type, message);
}

// Same table markup/classes as the Users table (displayUsers) above it, so the two
// lists in this sub-tab read as one consistent style rather than a table next to a
// plain list-group.
function renderTrustedNetworksList() {
    const list = document.getElementById('trusted-networks-list');
    if (!list) return;

    DOMUtils.clear(list);

    if (trustedNetworksDraft.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'text-muted small';
        empty.textContent = i18n.t('settings.trusted_networks_empty');
        list.appendChild(empty);
    } else {
        const tableWrapper = document.createElement('div');
        tableWrapper.className = 'table-responsive';

        const table = document.createElement('table');
        table.className = 'table table-sm table-hover';

        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        [
            { text: i18n.t('settings.trusted_networks_input_label') },
            { text: i18n.t('users.actions'), className: 'text-center' }
        ].forEach((header) => {
            const th = document.createElement('th');
            th.textContent = header.text;
            if (header.className) th.className = header.className;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);

        const tbody = document.createElement('tbody');
        trustedNetworksDraft.forEach((network) => {
            const row = document.createElement('tr');

            const networkCell = document.createElement('th');
            networkCell.className = 'font-monospace';
            networkCell.textContent = network;

            const actionsCell = document.createElement('td');
            actionsCell.className = 'text-center';
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn btn-danger btn-small';
            removeBtn.setAttribute('data-network', network);
            removeBtn.setAttribute('title', i18n.t('settings.trusted_networks_remove'));
            DOMUtils.append(removeBtn, DOMUtils.createIcon('bi bi-trash icon-inline'), i18n.t('users.delete'));
            removeBtn.addEventListener('click', () => removeTrustedNetwork(network));
            actionsCell.appendChild(removeBtn);

            row.appendChild(networkCell);
            row.appendChild(actionsCell);
            tbody.appendChild(row);
        });

        table.appendChild(thead);
        table.appendChild(tbody);
        tableWrapper.appendChild(table);
        list.appendChild(tableWrapper);
    }

    // 2FA cannot be switched on without a trusted network to exempt.
    const toggle = document.getElementById('security-2fa-enabled');
    const hint = document.getElementById('security-2fa-requires-network');
    const hasNetwork = trustedNetworksDraft.length > 0;
    if (toggle) {
        toggle.disabled = !hasNetwork;
        if (!hasNetwork) {
            toggle.checked = false;
        }
    }
    if (hint) {
        hint.style.display = hasNetwork ? 'none' : 'block';
    }
}

// A permissive but format-correct check: catches obvious typos (wrong octet count,
// out-of-range values, a bad prefix) immediately on Add, before a round trip to the
// server. The server's ipaddress.ip_network() stays the actual authority - this only
// improves the failure mode from "silently accepted, rejected later on Save" to
// "rejected right here, with the input still in the box to fix".
function isValidIPv4Address(value) {
    const octets = value.split('.');
    if (octets.length !== 4) return false;
    return octets.every((octet) => /^\d{1,3}$/.test(octet) && Number(octet) >= 0 && Number(octet) <= 255);
}

// Standard IPv6 forms, including "::" compression and a trailing embedded IPv4
// (e.g. "::ffff:192.168.1.1"). Deliberately permissive - a false positive here just
// falls through to the server's stricter check on Save.
const IPV6_PATTERN = new RegExp(
    '^(' +
    '([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|' +
    '([0-9a-fA-F]{1,4}:){1,7}:|' +
    '([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|' +
    '([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|' +
    '([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|' +
    '([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|' +
    '([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|' +
    '[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|' +
    ':((:[0-9a-fA-F]{1,4}){1,7}|:)|' +
    '::(ffff(:0{1,4})?:)?((25[0-5]|(2[0-4]|1?[0-9])?[0-9])\\.){3}(25[0-5]|(2[0-4]|1?[0-9])?[0-9])|' +
    '([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1?[0-9])?[0-9])\\.){3}(25[0-5]|(2[0-4]|1?[0-9])?[0-9])' +
    ')$'
);

function isValidNetworkInput(value) {
    const slashIndex = value.lastIndexOf('/');
    const address = slashIndex === -1 ? value : value.slice(0, slashIndex);
    const prefixText = slashIndex === -1 ? null : value.slice(slashIndex + 1);

    const isIPv4 = isValidIPv4Address(address);
    const isIPv6 = !isIPv4 && IPV6_PATTERN.test(address);
    if (!isIPv4 && !isIPv6) {
        return false;
    }

    if (prefixText !== null) {
        if (!/^\d{1,3}$/.test(prefixText)) return false;
        const prefix = Number(prefixText);
        const maxPrefix = isIPv4 ? 32 : 128;
        if (prefix < 0 || prefix > maxPrefix) return false;
    }

    return true;
}

// Same thresholds as the server's _UNUSUALLY_BROAD_PREFIX in security_settings.py.
// Duplicated rather than shared (client and server are different languages) so a
// dropped digit ("/24" typed as "/2") gets a chance to be caught right when it's
// entered, not only after Save.
function isUnusuallyBroadNetwork(value) {
    const slashIndex = value.lastIndexOf('/');
    if (slashIndex === -1) return false; // a bare address is a single host, never broad

    const address = value.slice(0, slashIndex);
    const prefix = Number(value.slice(slashIndex + 1));
    const threshold = isValidIPv4Address(address) ? 8 : 32;
    return prefix < threshold;
}

function addTrustedNetwork() {
    const input = document.getElementById('trusted-network-input');
    if (!input) return;

    const value = input.value.trim();
    if (!value) return;

    if (!isValidNetworkInput(value)) {
        setSecuritySettingsMessage('error', `${i18n.t('settings.invalid_trusted_network')} (${value})`);
        return;
    }

    if (isUnusuallyBroadNetwork(value) && !confirm(i18n.t('settings.trusted_networks_broad_confirm', { network: value }))) {
        return;
    }

    if (trustedNetworksDraft.includes(value)) {
        setSecuritySettingsMessage('error', i18n.t('settings.trusted_networks_duplicate'));
        return;
    }

    setSecuritySettingsMessage(null);
    trustedNetworksDraft.push(value);
    input.value = '';
    renderTrustedNetworksList();
}

function removeTrustedNetwork(network) {
    const toggle = document.getElementById('security-2fa-enabled');
    const isLastEntry = trustedNetworksDraft.length === 1;

    // Every removal confirms first, same as deleteUser() - losing the last entry
    // while 2FA is on shows the more specific warning about that side effect instead
    // of the generic one.
    const confirmMessage = (isLastEntry && toggle?.checked)
        ? i18n.t('settings.trusted_networks_remove_last_confirm')
        : i18n.t('settings.trusted_networks_remove_confirm', { network });

    if (!confirm(confirmMessage)) {
        return;
    }

    setSecuritySettingsMessage(null);
    trustedNetworksDraft = trustedNetworksDraft.filter((entry) => entry !== network);
    renderTrustedNetworksList();
}

// Shown only when the fallback is actually active AND somebody relies on it:
// no configured network, but at least one account is restricted to "local".
function renderLocalScopeWarning() {
    const banner = document.getElementById('security-local-scope-warning');
    if (!banner) return;

    const show = trustedNetworksDraft.length === 0 && lastLocalAccountCount > 0;

    banner.textContent = show ? i18n.t('settings.local_scope_warning_banner', { count: lastLocalAccountCount }) : '';
    banner.style.display = show ? 'block' : 'none';
}

async function loadSecuritySettings() {
    if (currentUser?.role !== 'admin') return;

    try {
        const settings = await fetchJSON('/api/auth/security-settings');
        trustedNetworksDraft = settings.trusted_networks || [];

        const toggle = document.getElementById('security-2fa-enabled');
        if (toggle) {
            toggle.checked = !!settings.two_factor_enabled;
        }
        renderTrustedNetworksList();
        renderLocalScopeWarning();
    } catch (error) {
        console.error('Failed to load security settings:', error);
        setSecuritySettingsMessage('error', i18n.t('settings.security_settings_load_error'));
    }
}

async function saveSecuritySettings() {
    const toggle = document.getElementById('security-2fa-enabled');
    setSecuritySettingsMessage(null);

    try {
        const response = await fetchWithRetry('/api/auth/security-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                trusted_networks: trustedNetworksDraft,
                two_factor_enabled: toggle ? toggle.checked : false
            })
        }, {
            maxAttempts: 1,
            timeoutMs: 15000
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const message = data?.error_key === 'settings.invalid_trusted_network' && data?.invalid_entry
                ? `${i18n.t('settings.invalid_trusted_network')} (${data.invalid_entry})`
                : localizeApiError(data, 'settings.security_settings_save_error');
            setSecuritySettingsMessage('error', message);
            return;
        }

        // Adopt the server's normalized list (192.168.1.5/24 comes back as 192.168.1.0/24).
        trustedNetworksDraft = data.trusted_networks || [];
        if (toggle) {
            toggle.checked = !!data.two_factor_enabled;
        }
        renderTrustedNetworksList();
        renderLocalScopeWarning();

        const feedback = document.getElementById('security-settings-feedback');
        if (feedback) {
            feedback.style.display = 'inline';
            setTimeout(() => { feedback.style.display = 'none'; }, 3000);
        }
    } catch (error) {
        console.error('Failed to save security settings:', error);
        setSecuritySettingsMessage('error', i18n.t('settings.security_settings_save_error'));
    }
}

function setupSecuritySettingsForm() {
    document.getElementById('trusted-network-add')?.addEventListener('click', addTrustedNetwork);
    document.getElementById('save-security-settings')?.addEventListener('click', saveSecuritySettings);

    document.getElementById('trusted-network-input')?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            // The input is not inside a form, but Enter would still submit the
            // create-user form above it in some browsers - handle it explicitly.
            event.preventDefault();
            addTrustedNetwork();
        }
    });
}

// ============================================================
// Account scope + admin 2FA removal (Parameters -> Users, admin only)
// ============================================================

function editAccountScope(userId, username, currentScope) {
    openEditFieldModal({
        userId,
        username,
        currentValue: currentScope,
        fieldName: 'account_scope',
        iconClass: 'bi bi-geo icon-inline',
        titleKey: 'users.edit_account_scope',
        infoForKey: 'users.edit_account_scope_for',
        selectLabelKey: 'users.new_account_scope',
        submitLabelKey: 'users.save_account_scope',
        unchangedKey: 'users.account_scope_unchanged',
        successKey: 'users.account_scope_updated',
        errorFallbackKey: 'users.error_update_account_scope',
        options: [
            { value: 'global', textKey: 'users.account_scope_global' },
            { value: 'local', textKey: 'users.account_scope_local' }
        ]
    });
}

// Recovery path when a user loses their authenticator: no password check here,
// admin authority is the check.
async function adminDisableUserTwoFactor(userId, username) {
    if (!confirm(i18n.t('users.confirm_disable_2fa_for_user', { username }))) {
        return;
    }

    try {
        const response = await fetchWithRetry(`/api/users/${userId}/2fa`, {
            method: 'DELETE',
            credentials: 'include'
        }, {
            maxAttempts: 1,
            timeoutMs: 15000
        });

        const data = await response.json().catch(() => ({}));

        if (response.ok) {
            showMessage('success', i18n.t('users.2fa_disabled_for_user'));
            loadUsers();
        } else {
            showMessage('error', localizeApiError(data, 'users.error_disable_2fa_for_user'));
        }
    } catch (error) {
        console.error('Error disabling 2FA for user:', error);
        showMessage('error', i18n.t('users.error_disable_2fa_for_user'));
    }
}

// Error handler - only redirect on authentication failures (401), not authorization (403)
function setupGlobalErrorHandler() {
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
        // Extract URL from fetch arguments for logging
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || 'unknown';
        const method = args[1]?.method || 'GET';

        try {
            const response = await originalFetch(...args);

            // Only redirect on 401 (Unauthorized - not logged in)
            if (response.status === 401) {
                console.warn(`[Auth] 401 Unauthorized: ${method} ${url} - Redirecting to login`);
                // Only redirect if not already on login page
                if (!window.location.pathname.includes('/login')) {
                    window.location.href = '/login';
                }
            }

            // Log 403 (Forbidden - insufficient permissions) for debugging
            // Don't redirect - this prevents read-only users from being logged out when they
            // inadvertently trigger admin-only endpoints
            if (response.status === 403) {
                console.warn(
                    `[Auth] 403 Forbidden: ${method} ${url}\n` +
                    `Reason: Insufficient permissions for this endpoint.\n` +
                    `This is expected for read-only users accessing admin-only endpoints.`
                );
            }

            return response;
        } catch (error) {
            const isApiCall = String(url).includes('/api/');
            const onOfflinePage = window.location.pathname.includes('/offline.html');
            const onLoginPage = window.location.pathname.includes('/login');

            if (isApiCall && !onOfflinePage && !onLoginPage && isOfflineOrNetworkError(error) && !offlineRedirectInProgress) {
                offlineRedirectInProgress = true;
                console.warn(`[Auth] Network error on ${method} ${url} - Redirecting to offline page`);
                window.location.href = '/offline.html';
            }

            throw error;
        }
    };
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        checkAuthStatus();
        setupLogoutButton();
        setupCreateUserForm();
        setupCustomizeForm();
        setupThemePickerSync();
        setupSecurityPasswordForm();
        setupTwoFactorPanel();
        setupSecuritySettingsForm();
        setupGlobalErrorHandler();
    });
} else {
    checkAuthStatus();
    setupLogoutButton();
    setupCreateUserForm();
    setupCustomizeForm();
    setupThemePickerSync();
    setupSecurityPasswordForm();
    setupTwoFactorPanel();
    setupSecuritySettingsForm();
    setupGlobalErrorHandler();
}
