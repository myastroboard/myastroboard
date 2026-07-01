// Authentication and User Management

let currentUser = null;
let currentUserPreferences = null;
let offlineRedirectInProgress = false;

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
    'parameters': ['configuration', 'advanced', 'logs', 'users', 'metrics']
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

function setCustomizeMessage(type, message) {
    const messageDiv = document.getElementById('customize-message');
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
        'advanced': 'settings.advanced',
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
            recommendations_enabled: document.getElementById('pref-recommendations-enabled')?.checked ?? DEFAULT_USER_PREFERENCES.recommendations_enabled
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
    const messageDiv = document.getElementById('security-password-message');
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
    }
}

function displayUsers(users) {
    const usersList = document.getElementById('users-list');
    if (!usersList) return;
    
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
        }

        actionsCell.appendChild(createActionButton({
            className: 'btn btn-secondary btn-small user-change-password mb-2 me-2',
            userId: user.user_id,
            username: user.username,
            iconClass: 'bi bi-lock icon-inline',
            label: i18n.t('users.password')
        }));

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
        
        try {
            const response = await fetchWithRetry('/api/users', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({ username, password, role })
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
    
    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();
    
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
                bs_modal.hide();
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
function editRole(userId, username, currentRole) {
    const titleElement = document.getElementById('modal_lg_close_title');
    DOMUtils.clear(titleElement);
    DOMUtils.append(titleElement, DOMUtils.createIcon('bi bi-key icon-inline'), i18n.t('users.edit_role'));
    
    const contentElement = document.getElementById('modal_lg_close_body');
    DOMUtils.clear(contentElement);

    const infoAlert = document.createElement('div');
    infoAlert.className = 'alert alert-info';
    infoAlert.append(i18n.t('users.edit_role_for'));
    const strong = document.createElement('strong');
    strong.textContent = username;
    infoAlert.appendChild(strong);

    const errorAlert = document.createElement('div');
    errorAlert.id = 'role-modal-error';
    errorAlert.className = 'alert alert-danger';
    errorAlert.style.display = 'none';

    const form = document.createElement('form');
    form.id = 'role-edit-form';
    form.className = 'row g-3';

    const hiddenUserId = document.createElement('input');
    hiddenUserId.type = 'hidden';
    hiddenUserId.id = 'edit-user-id';
    hiddenUserId.value = userId;

    const selectCol = document.createElement('div');
    selectCol.className = 'col-md-12';
    const label = document.createElement('label');
    label.className = 'form-label';
    label.setAttribute('for', 'new-role-select');
    label.textContent = i18n.t('users.new_role');
    const select = document.createElement('select');
    select.id = 'new-role-select';
    select.className = 'form-select';
    select.required = true;

    [
        { value: 'admin', text: 'Admin' },
        { value: 'user', text: 'User' },
        { value: 'read-only', text: 'Read-Only' }
    ].forEach((optionData) => {
        const option = document.createElement('option');
        option.value = optionData.value;
        option.textContent = optionData.text;
        option.selected = optionData.value === currentRole;
        select.appendChild(option);
    });

    selectCol.appendChild(label);
    selectCol.appendChild(select);

    const actionsCol = document.createElement('div');
    actionsCol.className = 'col-md-12 d-flex justify-content-end';
    actionsCol.style.gap = '1rem';
    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = i18n.t('users.save_role');
    actionsCol.appendChild(submitBtn);

    form.appendChild(hiddenUserId);
    form.appendChild(selectCol);
    form.appendChild(actionsCol);

    contentElement.appendChild(infoAlert);
    contentElement.appendChild(errorAlert);
    contentElement.appendChild(form);
    
    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();
    
    const formElement = document.getElementById('role-edit-form');
    const errorDiv = document.getElementById('role-modal-error');
    
    formElement.onsubmit = async function(e) {
        e.preventDefault();
        
        const newRole = document.getElementById('new-role-select').value;
        const userId = document.getElementById('edit-user-id').value;
        
        if (newRole === currentRole) {
            errorDiv.textContent = i18n.t('users.role_unchanged');
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
                body: JSON.stringify({ role: newRole })
            }, {
                maxAttempts: 1,
                timeoutMs: 15000
            });
            
            const data = await response.json();
            
            if (response.ok) {
                showMessage('success', i18n.t('users.role_updated'));
                loadUsers();
                bs_modal.hide();
            } else {
                errorDiv.textContent = localizeApiError(data, 'users.error_update_role');
                errorDiv.style.display = 'block';
            }
        } catch (error) {
            console.error('Error updating role:', error);
            errorDiv.textContent = i18n.t('users.error_update_role');
            errorDiv.style.display = 'block';
        }
    };
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
    newPasswordInput.minLength = 4;
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
    const bs_modal = new bootstrap.Modal('#modal_lg_close', {
        backdrop: 'static',
        focus: true,
        keyboard: true
    });
    bs_modal.show();
    
    setupPasswordChangeModal(bs_modal, userId);
}

// Setup password change modal
function setupPasswordChangeModal(bs_modal, userId) {
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
                    bs_modal.hide();

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
        setupGlobalErrorHandler();
    });
} else {
    checkAuthStatus();
    setupLogoutButton();
    setupCreateUserForm();
    setupCustomizeForm();
    setupThemePickerSync();
    setupSecurityPasswordForm();
    setupGlobalErrorHandler();
}
