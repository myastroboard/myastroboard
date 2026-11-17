/**
 * Phone sub-tab menu - each sub-tab bar collapses into one dropdown button on a narrow screen.
 *
 * A bar of eight pills wraps onto four lines on a phone and pushes the page down by half a
 * screen. Below the Bootstrap "md" breakpoint the pills are hidden (static/css/bs_main.css,
 * .subtab-menu) and this button takes their place: it shows the current sub-tab with its
 * own icon, the caret says it is a menu, and one tap lists every sub-tab. On a wider screen
 * nothing changes.
 *
 * The pills stay the single source of truth. The menu is rebuilt from them each time it
 * opens (SkyTonight and the Observatory fill their bars at run time, some entries are hidden
 * by preference or role), choosing an entry clicks the matching pill so the usual sub-tab
 * handler, history and hash navigation all run unchanged, and a MutationObserver keeps the
 * button's label on the active pill and its current language.
 */

/* global DOMUtils, i18n, bootstrap */

const SUBTAB_MENU_LIST_SELECTOR = '.main-tab-content .sub-tabs';

function _stmT(key, fallback) {
    if (typeof i18n === 'undefined' || typeof i18n.t !== 'function') return fallback;
    const translated = i18n.t(key);
    return translated && translated !== key ? translated : fallback;
}

function _stmIsHidden(element) {
    return !element || element.hidden || element.classList.contains('d-none') || element.style.display === 'none';
}

/** The pills a user can actually reach, in bar order. */
function _stmVisibleLinks(list) {
    return Array.from(list.querySelectorAll('.sub-tab-btn')).filter(
        (link) => !_stmIsHidden(link) && !_stmIsHidden(link.closest('li'))
    );
}

/** A copy of a pill's icon (if any) and its current label, for the button or a menu entry. */
function _stmContent(link) {
    const nodes = [];
    const icon = link.querySelector('i.bi');
    if (icon) nodes.push(icon.cloneNode(false));
    const label = document.createElement('span');
    label.className = 'subtab-menu-label';
    label.textContent = link.textContent.trim();
    nodes.push(label);
    return nodes;
}

function _stmSync(menu, list) {
    const toggle = menu.querySelector('.subtab-menu-toggle');
    const links = _stmVisibleLinks(list);
    menu.classList.toggle('is-empty', links.length === 0);
    if (!toggle || !links.length) return;
    const current = links.find((link) => link.classList.contains('active')) || links[0];
    DOMUtils.clear(toggle);
    DOMUtils.append(toggle, ..._stmContent(current));
    toggle.setAttribute('aria-label', `${_stmT('navbar.subtab_menu', 'Sections')}: ${current.textContent.trim()}`);
}

function _stmBuildItems(menu, list) {
    const dropdown = menu.querySelector('.subtab-menu-list');
    if (!dropdown) return;
    DOMUtils.clear(dropdown);
    _stmVisibleLinks(list).forEach((link) => {
        const item = document.createElement('li');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'dropdown-item subtab-menu-item';
        if (link.classList.contains('active')) {
            button.classList.add('active');
            button.setAttribute('aria-current', 'page');
        }
        DOMUtils.append(button, ..._stmContent(link));
        // Same path as a tap on the pill: the delegated sub-tab handler does the switch.
        button.addEventListener('click', () => link.click());
        item.appendChild(button);
        dropdown.appendChild(item);
    });
}

function _stmEnhance(list) {
    if (list.dataset.subtabMenu === 'true') return;
    list.dataset.subtabMenu = 'true';

    const menu = document.createElement('div');
    menu.className = 'dropdown subtab-menu';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'btn subtab-menu-toggle dropdown-toggle';
    toggle.setAttribute('data-bs-toggle', 'dropdown');
    // Always open downwards: flipped above the button on a short screen, the list ended up
    // under the page header. The page scrolls to it instead (see shown.bs.dropdown below).
    toggle.setAttribute('data-bs-display', 'static');
    toggle.setAttribute('aria-expanded', 'false');
    const dropdown = document.createElement('ul');
    dropdown.className = 'dropdown-menu subtab-menu-list';
    DOMUtils.append(menu, toggle, dropdown);
    list.parentNode.insertBefore(menu, list);
    // The bar's panel clips its content (overflow + backdrop filter); see .has-subtab-menu.
    list.parentNode.classList.add('has-subtab-menu');

    menu.addEventListener('show.bs.dropdown', () => _stmBuildItems(menu, list));
    menu.addEventListener('shown.bs.dropdown', () => {
        dropdown.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
    new MutationObserver(() => _stmSync(menu, list)).observe(list, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ['class', 'hidden', 'style'],
    });
    _stmSync(menu, list);
}

/** Give every sub-tab bar its phone menu. Safe to call again: a bar is enhanced once. */
function initSubtabMenus() {
    document.querySelectorAll(SUBTAB_MENU_LIST_SELECTOR).forEach(_stmEnhance);
}

window.initSubtabMenus = initSubtabMenus;
