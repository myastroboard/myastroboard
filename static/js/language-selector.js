// ==========================================
// Language Selector - Frontend UI Controller
// ==========================================

/**
 * Language Selector initialization and event handling
 * Provides UI controls for changing the application language
 */

class LanguageSelector {
    constructor() {
        this.selectElement = null;
        this.labelElement = null;
        this.translationUpdateQueued = false;
        this.init();
    }

    init() {
        // Wait for i18n manager to be ready
        if (typeof i18n === 'undefined') {
            console.warn('[LanguageSelector] i18n manager not available, retrying...');
            setTimeout(() => this.init(), 100);
            return;
        }

        this.selectElement = document.getElementById('language-select-footer');
        this.labelElement = document.querySelector('label[for="language-select-footer"]');

        if (!this.selectElement) {
            console.warn('[LanguageSelector] Language selector element not found');
            return;
        }

        // Wait for current language translations to load before updating page
        this.waitForTranslationsAndUpdate();

        // Add event listener for language change
        this.selectElement.addEventListener('change', (e) => this.handleLanguageChange(e));

        // Listen for i18n language changes from other sources
        window.addEventListener('i18nLanguageChanged', (e) => {
            this.updateSelectorValue(e.detail.language);
        });

        //console.log('[LanguageSelector] Initialized');
    }

    /**
     * Wait for translations to load for the current language, then update the page
     */
    waitForTranslationsAndUpdate() {
        const currentLang = i18n.getCurrentLanguage();
        let attempts = 0;
        const maxAttempts = 50; // Maximum 50 attempts * 150ms = 7.5 seconds

        const check = () => {
            attempts++;
            
            // Check if current language is already loaded
            if (i18n.loadedLanguages && i18n.loadedLanguages.has(currentLang)) {
                // Translations are loaded, update immediately
                //console.log(`[LanguageSelector] Translations loaded for ${currentLang}, updating page...`);
                this.setCurrentLanguage();
                this.updateFooterLabel();
                // Single call to update all translations
                this.updatePageTranslations();
            } else if (attempts >= maxAttempts) {
                console.warn(`[LanguageSelector] Timeout waiting for ${currentLang} translations after ${maxAttempts * 150}ms`);
                // Still try to update with whatever is available
                this.updatePageTranslations();
            } else {
                // Translations not yet loaded, retry after short delay
                console.debug(`[LanguageSelector] Waiting for ${currentLang} translations (attempt ${attempts}/${maxAttempts})...`);
                setTimeout(check, 150);
            }
        };

        check();
    }

    /**
     * Set the selector to show the current language
     */
    setCurrentLanguage() {
        const currentLang = i18n.getCurrentLanguage();
        this.updateSelectorValue(currentLang);
    }

    /**
     * Update selector value without triggering change event
     */
    updateSelectorValue(lang) {
        if (this.selectElement && this.selectElement.value !== lang) {
            this.selectElement.value = lang;
        }
    }

    /**
     * Handle language selection change
     */
    async handleLanguageChange(event) {
        const selectedLang = event.target.value;
        const currentLang = i18n.getCurrentLanguage();

        // If language hasn't changed, do nothing
        if (selectedLang === currentLang) {
            return;
        }

        try {
            // Save language preference to localStorage
            localStorage.setItem('myastroboard_language', selectedLang);

            // Persist to server and await completion before reloading.
            // Firing-and-forgetting then immediately calling location.reload() causes the
            // browser to cancel the in-flight PUT on page unload. In single-threaded Flask
            // the partial PUT can block the subsequent navigation GET past the service worker's
            // 2500 ms timeout, which makes the SW fall through to the offline page in PWA mode.
            await fetch('/api/auth/preferences', {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preferences: { language: selectedLang } }),
            }).catch(() => {});

            // Reload the page to apply the new language across all dynamically-rendered content.
            location.reload();
        } catch (error) {
            console.error('[LanguageSelector] Error changing language:', error);
            // Reset selector to previous language on error
            this.setCurrentLanguage();
        }
    }

    /**
     * Update the footer language label text
     */
    updateFooterLabel() {
        if (this.labelElement) {
            const labelKey = this.labelElement.getAttribute('data-i18n') || 'common.language';
            this.labelElement.textContent = i18n.t(labelKey);
        }
    }

    /**
     * Update all page elements with data-i18n attribute
     * Uses batching and requestAnimationFrame to avoid UI freezing
     */
    updatePageTranslations() {
        // Debounce consecutive calls within the same frame
        if (this.translationUpdateQueued) {
            return;
        }
        this.translationUpdateQueued = true;

        // Schedule the update for the next animation frame to avoid blocking
        requestAnimationFrame(() => {
            try {
                const elements = document.querySelectorAll('[data-i18n], [data-i18n-placeholder], [data-i18n-title]');
                const totalElements = elements.length;
                const batchSize = 50; // Process 50 elements at a time
                
                let index = 0;

                const processBatch = () => {
                    const endIndex = Math.min(index + batchSize, totalElements);
                    
                    // Process batch of elements
                    for (let i = index; i < endIndex; i++) {
                        const element = elements[i];
                        const textKey = element.getAttribute('data-i18n');
                        const placeholderKey = element.getAttribute('data-i18n-placeholder');
                        const titleKey = element.getAttribute('data-i18n-title');

                        if (textKey) {
                            try {
                                const translated = i18n.t(textKey);
                                if (element.textContent !== translated) {
                                    element.textContent = translated;
                                }
                            } catch (error) {
                                console.warn(`[LanguageSelector] Error translating key: ${textKey}`, error);
                            }
                        }

                        if (placeholderKey) {
                            try {
                                const translatedPlaceholder = i18n.t(placeholderKey);
                                if ('placeholder' in element && element.placeholder !== translatedPlaceholder) {
                                    element.placeholder = translatedPlaceholder;
                                }
                            } catch (error) {
                                console.warn(`[LanguageSelector] Error translating placeholder key: ${placeholderKey}`, error);
                            }
                        }

                        if (titleKey) {
                            try {
                                const translatedTitle = i18n.t(titleKey);
                                if (element.getAttribute('title') !== translatedTitle) {
                                    element.setAttribute('title', translatedTitle);
                                }
                            } catch (error) {
                                console.warn(`[LanguageSelector] Error translating title key: ${titleKey}`, error);
                            }
                        }
                    }

                    index = endIndex;

                    // Process next batch if there are more elements
                    if (index < totalElements) {
                        requestAnimationFrame(processBatch);
                    } else {
                        this.translationUpdateQueued = false;
                        //console.log(`[LanguageSelector] Updated ${totalElements} elements`);
                    }
                };

                processBatch();
            } catch (error) {
                console.error('[LanguageSelector] Unexpected error updating page translations:', error);
                this.translationUpdateQueued = false;
            }
        });
    }

    /**
     * Get currently selected language
     */
    getCurrentSelection() {
        return this.selectElement ? this.selectElement.value : 'en';
    }
}

// Initialize language selector when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.languageSelector = new LanguageSelector();
    });
} else {
    // DOM already loaded
    window.languageSelector = new LanguageSelector();
}
