// ==========================================
// Internationalization (i18n) Management
// ==========================================

/**
 * Global i18n manager for MyAstroBoard
 * Handles multi-language support with nested key access
 * 
 * Usage:
 *   i18n.t('common.loading')                    // Get string
 *   i18n.t('weather_alerts.critical_dew_risk', {time: '14:30'})  // Get with placeholders
 *   i18n.setLanguage('fr')                      // Switch language
 *   i18n.getCurrentLanguage()                   // Get current language
 */
class I18nManager {
    constructor() {
        this.translations = {};
        this.currentLanguage = this.detectLanguage();
        this.fallbackLanguage = 'en';
        this.loadedLanguages = new Set();
        this.appVersion = this.resolveAppVersion();
        
        // Initialize with default language.
        // this.ready resolves once the primary language translations are loaded,
        // allowing callers to await i18n.ready before calling i18n.t().
        this.ready = this.loadLanguage(this.currentLanguage);

        // Ensure fallback language is available for key-level fallback lookups
        if (this.currentLanguage !== this.fallbackLanguage) {
            this.loadLanguage(this.fallbackLanguage, { activate: false, persistSelection: false });
        }
    }

    /**
     * Resolve app version for static asset cache busting
     * Prioritizes window.APP_VERSION, then meta[name="app-version"], then persisted app version,
     * and finally no version query.
     */
    resolveAppVersion() {
        const globalVersion = String(window.APP_VERSION || '').trim();
        if (globalVersion) {
            return globalVersion;
        }

        const versionMeta = document.querySelector('meta[name="app-version"]');
        const metaVersion = versionMeta ? String(versionMeta.content || '').trim() : '';
        if (metaVersion) {
            return metaVersion;
        }

        const persistedVersion = String(localStorage.getItem('myastroboard_app_version') || '').trim();
        return persistedVersion;
    }

    /**
     * Detect browser language preference
     * Falls back to English if unsupported
     */
    detectLanguage() {
        // Check if language preference is stored in localStorage
        const stored = localStorage.getItem('myastroboard_language');
        if (stored) {
            return stored;
        }

        // Get browser language
        const browserLang = navigator.language || navigator.userLanguage;
        const shortLang = browserLang.split('-')[0]; // e.g., 'en' from 'en-US'

        const supportedLanguages = ['en', 'fr', 'es', 'de', 'it', 'pt'];
        return supportedLanguages.includes(shortLang) ? shortLang : 'en';
    }

    /**
     * Load translation file for a language
     */
    async loadLanguage(lang, options = {}) {
        const { activate = true, persistSelection = activate } = options;

        if (this.loadedLanguages.has(lang)) {
            if (activate) {
                this.currentLanguage = lang;
                if (persistSelection) {
                    localStorage.setItem('myastroboard_language', lang);
                }
            }
            //console.log(`[i18n] Language already loaded: ${lang}`);
            return;
        }

        try {
            const versionQuery = this.appVersion ? `?v=${encodeURIComponent(this.appVersion)}` : '';
            const url = `/static/i18n/${lang}.json${versionQuery}`;
            //console.log(`[i18n] Loading language from: ${url}`);
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`Failed to load ${lang} translations (HTTP ${response.status})`);
            }

            const translations = await response.json();
            this.translations[lang] = translations;
            this.loadedLanguages.add(lang);
            if (activate) {
                this.currentLanguage = lang;
                if (persistSelection) {
                    localStorage.setItem('myastroboard_language', lang);
                }
            }

            //console.log(`[i18n] Language loaded successfully: ${lang}`, translations);
        } catch (error) {
            console.error(`[i18n] Error loading language ${lang}:`, error);
            // Fall back to English if loading fails
            if (lang !== this.fallbackLanguage && !this.loadedLanguages.has(lang)) {
                console.log(`[i18n] Falling back to ${this.fallbackLanguage}`);
                await this.loadLanguage(this.fallbackLanguage, { activate: false, persistSelection: false });
            }
        }
    }

    /**
     * Get translated string by key path (e.g., 'common.loading')
     * Supports nested objects with dot notation
     * 
     * @param {string} key - The translation key (dot-separated path)
     * @param {object} params - Optional parameters for placeholder replacement
     * @returns {string} The translated string or key if not found
     */
    t(key, params = {}) {
        const requestedLanguage = this.currentLanguage;
        const requestedTranslation = this.getValueByPath(this.translations[requestedLanguage], key);
        const fallbackTranslations = this.translations[this.fallbackLanguage];
        const fallbackTranslation = this.getValueByPath(fallbackTranslations, key);

        let current = requestedTranslation;

        if (requestedTranslation === undefined && requestedLanguage !== this.fallbackLanguage) {
            console.warn(
                `[i18n] Missing key "${key}" in requested translation file: ${requestedLanguage}.json`
            );
            current = fallbackTranslation;
        }

        if (current === undefined) {
            if (requestedLanguage !== this.fallbackLanguage && !fallbackTranslations) {
                console.warn(
                    `[i18n] Fallback language ${this.fallbackLanguage}.json is not loaded yet for key "${key}"`
                );
                this.loadLanguage(this.fallbackLanguage, { activate: false, persistSelection: false });
                return key;
            }

            console.warn(
                `[i18n] Missing key "${key}" in default translation file: ${this.fallbackLanguage}.json`
            );
            return key;
        }

        let result = typeof current === 'string' ? current : key;

        // Replace placeholders in the format {key}
        for (const [paramKey, paramValue] of Object.entries(params)) {
            const placeholder = `{${paramKey}}`;
            result = result.replaceAll(placeholder, String(paramValue));
        }

        return result;
    }

    /**
     * Resolve a dot-notated translation path from an object
     *
     * @param {object} source - Source translation object
     * @param {string} key - Dot-notated translation key
     * @returns {string|undefined} Translation value if found
     */
    getValueByPath(source, key) {
        if (!source || typeof source !== 'object') {
            return undefined;
        }

        const keys = key.split('.');
        let current = source;

        for (const k of keys) {
            if (current && typeof current === 'object' && k in current) {
                current = current[k];
            } else {
                return undefined;
            }
        }

        return typeof current === 'string' ? current : undefined;
    }

    /**
     * Get all translations for a namespace
     * Useful for bulk operations
     * 
     * @param {string} namespace - The namespace (e.g., 'common')
     * @returns {object} The translation object or empty object if not found
     */
    getNamespace(namespace) {
        const trans = this.translations[this.currentLanguage];
        return (trans && trans[namespace]) ? trans[namespace] : {};
    }

    /**
     * Set current language
     * 
     * @param {string} lang - Language code to set
     */
    async setLanguage(lang) {
        if (lang === this.currentLanguage) return;
        await this.loadLanguage(lang);
        this.dispatchLanguageChangeEvent();
    }

    /**
     * Get current language
     * 
     * @returns {string} Current language code
     */
    getCurrentLanguage() {
        return this.currentLanguage;
    }

    /**
     * Get list of supported languages
     * 
     * @returns {array} Array of language codes
     */
    getSupportedLanguages() {
        return ['en', 'fr', 'es', 'de', 'it', 'pt'];
    }

    /**
     * Check if a translation key exists
     * 
     * @param {string} key - The translation key
     * @returns {boolean} True if key exists
     */
    has(key) {
        const keys = key.split('.');
        let current = this.translations[this.currentLanguage];

        for (const k of keys) {
            if (current && typeof current === 'object' && k in current) {
                current = current[k];
            } else {
                return false;
            }
        }

        return typeof current === 'string';
    }

    /**
     * Dispatch custom event when language changes
     * Allows UI components to update when language changes
     */
    dispatchLanguageChangeEvent() {
        const event = new CustomEvent('i18nLanguageChanged', {
            detail: { language: this.currentLanguage }
        });
        window.dispatchEvent(event);
    }

    /**
     * Get HTML lang attribute value
     * @returns {string} Language code for html lang attribute
     */
    getHtmlLang() {
        // Map internal codes to html lang codes
        const htmlLangMap = {
            'en': 'en-US',
            'fr': 'fr-FR',
            'es': 'es-ES',
            'de': 'de-DE'
        };
        return htmlLangMap[this.currentLanguage] || this.currentLanguage;
    }
}

// Initialize global i18n instance
const i18n = new I18nManager();

// Set html lang attribute when language changes
window.addEventListener('i18nLanguageChanged', (e) => {
    document.documentElement.lang = i18n.getHtmlLang();
});

// Set initial html lang
document.documentElement.lang = i18n.getHtmlLang();

/**
 * Utility function to update element text content with translation
 * Useful for dynamic content updates
 * 
 * @param {HTMLElement} element - The element to update
 * @param {string} key - The translation key
 * @param {object} params - Optional parameters for placeholders
 */
function updateElementText(element, key, params = {}) {
    if (element) {
        element.textContent = i18n.t(key, params);
    }
}

/**
 * Utility function to update element HTML with translation
 * Use carefully to avoid XSS - only use with static translation keys, never with dynamic content
 * 
 * @param {HTMLElement} element - The element to update
 * @param {string} key - The translation key
 * @param {object} params - Optional parameters for placeholders
 */
function updateElementHTML(element, key, params = {}) {
    if (element) {
        element.textContent = i18n.t(key, params);
    }
}

/**
 * Convert a string to a translation key format
 * Example: "More Info" -> "more_info"
 * 
 * @param {string} str 
 * @returns {string} Translation key
 */
function strToTranslateKey(str) {
    return str
        .trim()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

// Listen for language changes and update UI
window.addEventListener('i18nLanguageChanged', () => {
    console.log('[i18n] Language changed, triggering UI update');
    // This event can be used by individual components to refresh their content
});
