/**
 * The public /privacy page: translates its few fixed labels. The notice itself is the
 * administrator's own text, shown as written.
 */

/* global i18n */

async function applyPrivacyPageTranslations() {
    if (typeof i18n === 'undefined') return;
    try {
        await i18n.ready;
    } catch (error) {
        console.error('[Privacy] Could not load translations:', error);
        return;
    }
    document.documentElement.lang = i18n.getCurrentLanguage();
    document.querySelectorAll('[data-i18n]').forEach((element) => {
        element.textContent = i18n.t(element.getAttribute('data-i18n'));
    });
}

applyPrivacyPageTranslations();
