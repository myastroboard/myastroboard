// ======================
// DOM Utilities - Centralized DOM manipulation helpers
// ======================

const DOMUtils = {
    getElement,
    clear,
    setText,
    setTrustedHTML,
    append,
    createElement,
    clearContainer,
    setLoading,
    createIcon,
    createSpinnerWrapper,
    buildStatPlate
};

/**
 * Render a page's headline figures as one plate: the figure that matters at full size,
 * the rest as a compact row beside it.
 *
 * A value may be a string or a Node, so a page that shows something richer than a number
 * (a star rating, for instance) can pass the element it already builds.
 *
 * See the ".stat-plate" component in bs_main.css for why this is not a Bootstrap card.
 *
 * @param {HTMLElement|string} containerOrId - emptied first; takes the .stat-plate class
 * @param {Object} plate
 * @param {{value: string|Node, label: string, hint?: string}} plate.hero
 * @param {Array<{value: string|Node, label: string, hint?: string, icon?: string}>} [plate.figures]
 */
function buildStatPlate(containerOrId, plate) {
    const container = getElement(containerOrId);
    if (!container || !plate || !plate.hero) return;
    clear(container);
    container.classList.add('stat-plate');

    const row = document.createElement('div');
    row.className = 'stat-plate-row';

    const hero = document.createElement('div');
    hero.className = 'stat-plate-hero';
    hero.appendChild(_statPlatePart('stat-plate-hero-value', plate.hero.value));
    hero.appendChild(_statPlatePart('stat-plate-hero-label', plate.hero.label));
    if (plate.hero.hint) {
        hero.appendChild(_statPlatePart('stat-plate-hero-hint', plate.hero.hint));
    }
    row.appendChild(hero);

    const figures = Array.isArray(plate.figures) ? plate.figures : [];
    if (figures.length) {
        const grid = document.createElement('div');
        grid.className = 'stat-plate-figures';
        figures.forEach(figure => {
            const cell = document.createElement('div');
            cell.className = 'stat-plate-figure';
            if (figure.icon) {
                cell.appendChild(createIcon(`bi ${figure.icon}`, 'stat-plate-icon'));
            }
            const text = document.createElement('div');
            text.appendChild(_statPlatePart('stat-plate-value', figure.value));
            text.appendChild(_statPlatePart('stat-plate-label', figure.label));
            if (figure.hint) {
                text.appendChild(_statPlatePart('stat-plate-hint', figure.hint));
            }
            cell.appendChild(text);
            grid.appendChild(cell);
        });
        row.appendChild(grid);
    }

    container.appendChild(row);
}

/** One line of a plate. Accepts a Node so a caller can pass a richer value than text. */
function _statPlatePart(className, value) {
    const element = document.createElement('span');
    element.className = className;
    if (value instanceof Node) {
        element.appendChild(value);
    } else {
        element.textContent = String(value ?? '');
    }
    return element;
}

/**
 * Create a Bootstrap Icons <i> element.
 * @param {string} iconClass - Icon classes (e.g. 'bi bi-sun')
 * @param {string} extraClassName - Optional extra classes
 * @returns {HTMLElement}
 */
function createIcon(iconClass, extraClassName = '') {
    const icon = document.createElement('i');
    icon.className = `${iconClass} ${extraClassName}`.trim();
    icon.setAttribute('aria-hidden', 'true');
    return icon;
}

/**
 * Set loading state on a container
 * @param {HTMLElement|string} containerOrId - Container element or ID
 * @param {string} message - Loading message
 */
function setLoading(containerOrId, message = 'Loading...') {
    const container = getElement(containerOrId);
    if (container) {
        clear(container);
        const loading = document.createElement('div');
        loading.className = 'loading';
        loading.textContent = `${message}`;
        container.appendChild(loading);
    }
}

/**
 * Clear container contents
 * @param {HTMLElement|string} containerOrId - Container element or ID
 */
function clearContainer(containerOrId) {
    clear(containerOrId);
}

/**
 * Clear element contents
 * @param {HTMLElement|string} elementOrId - Element or ID
 */
function clear(elementOrId) {
    const element = getElement(elementOrId);
    if (!element) {
        return;
    }
    element.replaceChildren();
}

/**
 * Set plain text content
 * @param {HTMLElement|string} elementOrId - Element or ID
 * @param {string} text - Text content
 */
function setText(elementOrId, text = '') {
    const element = getElement(elementOrId);
    if (!element) {
        return;
    }
    element.textContent = `${text}`;
}

/**
 * Parse trusted HTML into DOM nodes without direct HTML assignment
 * @param {string} trustedHTML - Trusted static HTML string
 * @returns {DocumentFragment}
 */
function parseTrustedHTML(trustedHTML = '') {
    const range = document.createRange();
    range.selectNode(document.body || document.documentElement);
    return range.createContextualFragment(`${trustedHTML}`);
}

/**
 * Set content from trusted HTML
 * @param {HTMLElement|string} elementOrId - Element or ID
 * @param {string} trustedHTML - Trusted static HTML string
 */
function setTrustedHTML(elementOrId, trustedHTML = '') {
    const element = getElement(elementOrId);
    if (!element) {
        return;
    }
    const fragment = parseTrustedHTML(trustedHTML);
    element.replaceChildren(fragment);
}

/**
 * Append mixed text/nodes/fragments
 * @param {HTMLElement|string} elementOrId - Element or ID
 * @param {...(string|Node|DocumentFragment|number|boolean)} items - Items to append
 */
function append(elementOrId, ...items) {
    const element = getElement(elementOrId);
    if (!element) {
        return;
    }

    for (const item of items) {
        if (item === null || item === undefined) {
            continue;
        }
        if (item instanceof Node) {
            element.appendChild(item);
        } else {
            element.appendChild(document.createTextNode(`${item}`));
        }
    }
}

/**
 * Get element by ID or return the element itself
 * @param {HTMLElement|string} elementOrId - Element or ID
 * @returns {HTMLElement|null}
 */
function getElement(elementOrId) {
    if (typeof elementOrId === 'string') {
        return document.getElementById(elementOrId);
    }
    return elementOrId;
}

/**
 * Create element with attributes and content
 * @param {string} tag - HTML tag name
 * @param {Object} attributes - Attributes to set (className, id, etc.)
 * @param {string|HTMLElement|DocumentFragment} content - Text or child node
 * @returns {HTMLElement}
 */
function createElement(tag, attributes = {}, content = '') {
    const element = document.createElement(tag);
    
    // Set attributes
    for (const [key, value] of Object.entries(attributes)) {
        if (key === 'className') {
            element.className = value;
        } else if (key === 'textContent') {
            element.textContent = value;
        } else {
            element.setAttribute(key, value);
        }
    }
    
    // Set content
    if (typeof content === 'string') {
        setText(element, content);
    } else if (content instanceof Node) {
        element.appendChild(content);
    }
    
    return element;
}

/**
 * Create a Bootstrap spinner + text wrapper element (d-flex align-items-center gap-2).
 * Used by loading-message update functions across multiple modules.
 * @param {string} message - The loading message text
 * @param {string} [spinnerClass='text-info'] - Extra class(es) added to the spinner element
 * @returns {HTMLElement} The wrapper div
 */
function createSpinnerWrapper(message, spinnerClass = 'text-info') {
    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex align-items-center gap-2';
    const spinner = document.createElement('span');
    spinner.className = `spinner-border spinner-border-sm${spinnerClass ? ' ' + spinnerClass : ''}`;
    spinner.setAttribute('role', 'status');
    spinner.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.textContent = message;
    wrapper.appendChild(spinner);
    wrapper.appendChild(text);
    return wrapper;
}

/**
 * Shared metric cell used by weather, moon, and aurora forecast cards.
 * Renders: [icon] [bold value / small label], both white-space: nowrap.
 */
function createForecastMetricCell(iconClass, colorClass, value, label) {
    const cell = document.createElement('div');
    cell.className = 'weather-metric-cell';

    const icon = document.createElement('i');
    icon.className = `bi ${iconClass}${colorClass ? ' ' + colorClass : ''}`;
    icon.setAttribute('aria-hidden', 'true');

    const info = document.createElement('div');
    info.className = 'weather-metric-info';

    const val = document.createElement('span');
    val.className = 'weather-metric-val';
    val.textContent = value;

    const lbl = document.createElement('span');
    lbl.className = 'weather-metric-lbl';
    lbl.textContent = label;

    info.appendChild(val);
    info.appendChild(lbl);
    cell.appendChild(icon);
    cell.appendChild(info);
    return cell;
}

window.DOMUtils = DOMUtils;
