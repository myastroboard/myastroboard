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
    createSpinnerWrapper
};

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

window.DOMUtils = DOMUtils;
