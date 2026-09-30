// ======================
// API Helper - Centralized fetch utilities
// ======================

// URL prefix the app is served under: '' at the root, '/api/hassio_ingress/<token>' under
// Home Assistant ingress (the templates' <meta name="app-base">, from request.script_root).
// This file loads first on every page so appUrl() and the fetch() wrapper below exist
// before any request. No meta tag (offline.html) means no prefix.
const APP_BASE_PATH = (document.querySelector('meta[name="app-base"]')?.content || '').replace(/\/+$/, '');
const API_BASE = window.location.origin + APP_BASE_PATH;

/**
 * Prefix a root-relative app path ('/api/...', '/static/...', '/login') with APP_BASE_PATH.
 * Anything else (absolute http(s) URL, data:/blob:, protocol-relative, relative path, or a
 * path that already carries the prefix) is returned unchanged, so calling it twice is safe.
 * Every URL the frontend hands to the browser outside fetch() (img src, link href,
 * window.location, dynamically loaded scripts, downloads) must go through it.
 */
function appUrl(path) {
    if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) {
        return path;
    }
    if (APP_BASE_PATH && (path === APP_BASE_PATH || path.startsWith(`${APP_BASE_PATH}/`))) {
        return path;
    }
    return `${APP_BASE_PATH}${path}`;
}

function resolveEndpoint(endpoint) {
    if (/^https?:\/\//i.test(endpoint)) {
        return endpoint;
    }
    if (endpoint.startsWith('//')) {
        return `${window.location.protocol}${endpoint}`;
    }
    if (endpoint.startsWith('/')) {
        return `${window.location.origin}${appUrl(endpoint)}`;
    }
    return `${API_BASE}/${endpoint}`;
}

// Under a prefix, every fetch('/api/...') in the codebase has to reach the prefixed URL too:
// wrap fetch() once instead of touching each call site (and every future one).
if (APP_BASE_PATH && typeof window.fetch === 'function') {
    const unprefixedFetch = window.fetch.bind(window);
    window.fetch = (resource, ...rest) => unprefixedFetch(appUrl(resource), ...rest);
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function getBackoffDelayMs(attempt, baseDelayMs, maxDelayMs) {
    const expDelay = Math.min(maxDelayMs, baseDelayMs * Math.pow(2, attempt - 1));
    const jitter = Math.floor(Math.random() * Math.min(250, Math.max(50, expDelay / 4)));
    return expDelay + jitter;
}

/**
 * Fetch JSON data from an API endpoint with error handling
 * @param {string} endpoint - API endpoint (e.g., '/api/weather/forecast')
 * @param {Object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<Object>} - Parsed JSON response
 * @throws {Error} - If fetch fails or response is not ok
 */
async function fetchJSONOnce(endpoint, options = {}) {
    const { timeoutMs, ...fetchOptions } = options;
    const controller = !fetchOptions.signal && timeoutMs ? new AbortController() : null;
    const timeoutId = controller
        ? setTimeout(() => controller.abort(), timeoutMs)
        : null;

    if (controller) {
        fetchOptions.signal = controller.signal;
    }

    try {
        const response = await fetch(resolveEndpoint(endpoint), fetchOptions);

        if (!response.ok) {
            const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
            error.status = response.status;
            throw error;
        }

        return await response.json();
    } catch (error) {
        if (error.name === 'AbortError') {
            const timeoutError = new Error('Request timed out');
            timeoutError.code = 'ETIMEDOUT';
            throw timeoutError;
        }
        console.error(`Error fetching ${endpoint}:`, error);
        throw error;
    } finally {
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
    }
}

async function fetchJSON(endpoint, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const retryOptions = method === 'GET'
        ? { maxAttempts: 4, baseDelayMs: 1000, maxDelayMs: 8000, timeoutMs: 15000 }
        : { maxAttempts: 1, timeoutMs: 15000 };

    return fetchJSONWithRetry(endpoint, options, retryOptions);
}

async function fetchWithRetry(endpoint, options = {}, retryOptions = {}) {
    const {
        maxAttempts = 4,
        baseDelayMs = 1000,
        maxDelayMs = 8000,
        timeoutMs = 15000,
        retryOnStatuses = [408, 429, 500, 502, 503, 504],
        retryOnNetworkError = true,
        onRetry = null
    } = retryOptions;

    let attempt = 0;

    while (attempt < maxAttempts) {
        attempt += 1;

        const { timeoutMs: optTimeoutMs, ...fetchOptions } = options;
        const effectiveTimeout = optTimeoutMs || timeoutMs;
        const controller = !fetchOptions.signal && effectiveTimeout ? new AbortController() : null;
        const timeoutId = controller
            ? setTimeout(() => controller.abort(), effectiveTimeout)
            : null;

        if (controller) {
            fetchOptions.signal = controller.signal;
        }

        try {
            const response = await fetch(resolveEndpoint(endpoint), fetchOptions);
            const isRetryableStatus = retryOnStatuses.includes(response.status);

            if (isRetryableStatus && attempt < maxAttempts) {
                const waitMs = getBackoffDelayMs(attempt, baseDelayMs, maxDelayMs);
                if (onRetry) {
                    onRetry({
                        reason: 'status',
                        attempt,
                        maxAttempts,
                        waitMs,
                        response
                    });
                }
                await sleep(waitMs);
                continue;
            }

            return response;
        } catch (error) {
            let finalError = error;
            if (error.name === 'AbortError') {
                finalError = new Error('Request timed out');
                finalError.code = 'ETIMEDOUT';
            }

            const shouldRetry = attempt < maxAttempts && retryOnNetworkError;
            if (!shouldRetry) {
                throw finalError;
            }

            const waitMs = getBackoffDelayMs(attempt, baseDelayMs, maxDelayMs);
            if (onRetry) {
                onRetry({
                    reason: 'error',
                    attempt,
                    maxAttempts,
                    waitMs,
                    error: finalError
                });
            }
            await sleep(waitMs);
        } finally {
            if (timeoutId) {
                clearTimeout(timeoutId);
            }
        }
    }

    throw new Error('Retry attempts exhausted');
}

async function fetchJSONWithRetry(endpoint, options = {}, retryOptions = {}) {
    const {
        maxAttempts = 6,
        baseDelayMs = 1000,
        maxDelayMs = 10000,
        timeoutMs = 15000,
        retryOnStatuses = [408, 429, 500, 502, 503, 504],
        retryOnNetworkError = true,
        shouldRetryData = null,
        onRetry = null
    } = retryOptions;

    let attempt = 0;

    while (attempt < maxAttempts) {
        attempt += 1;

        try {
            const data = await fetchJSONOnce(endpoint, { ...options, timeoutMs });

            if (shouldRetryData && shouldRetryData(data)) {
                if (attempt >= maxAttempts) {
                    return data;
                }

                const waitMs = getBackoffDelayMs(attempt, baseDelayMs, maxDelayMs);
                if (onRetry) {
                    onRetry({
                        reason: 'data',
                        attempt,
                        maxAttempts,
                        waitMs,
                        data
                    });
                }
                await sleep(waitMs);
                continue;
            }

            return data;
        } catch (error) {
            const status = error.status;
            const isRetryableStatus = status && retryOnStatuses.includes(status);
            const isRetryableNetwork = !status && retryOnNetworkError;
            const shouldRetry = attempt < maxAttempts && (isRetryableStatus || isRetryableNetwork);

            if (!shouldRetry) {
                throw error;
            }

            const waitMs = getBackoffDelayMs(attempt, baseDelayMs, maxDelayMs);
            if (onRetry) {
                onRetry({
                    reason: 'error',
                    attempt,
                    maxAttempts,
                    waitMs,
                    error
                });
            }
            await sleep(waitMs);
        }
    }

    throw new Error('Retry attempts exhausted');
}

/**
 * Fetch JSON data with automatic error display in a container
 * @param {string} endpoint - API endpoint
 * @param {HTMLElement} container - Container element to show loading/error states
 * @param {string} loadingMessage - Message to show while loading
 * @returns {Promise<Object|null>} - Parsed JSON response or null on error
 */
async function fetchJSONWithUI(endpoint, container, loadingMessage = 'Loading...', retryOptions = {}) {
    const {
        retryOnPending = true,
        pendingMessage: _pendingMsg,
        retryMessage: _retryMsg,
        wrapInCard = false,
        cardTitle = null,
        cardIcon = null
    } = retryOptions;
    const pendingMessage = _pendingMsg !== undefined ? _pendingMsg
        : (typeof i18n !== 'undefined' ? i18n.t('cache.cache_not_ready_retrying') : 'Cache not ready. Retrying...');
    const retryMessage = _retryMsg !== undefined ? _retryMsg
        : (typeof i18n !== 'undefined' ? i18n.t('cache.cache_not_ready_retrying') : 'Temporary error. Retrying...');

    const renderAlert = (variant, message) => {
        if (!container) {
            return;
        }
        DOMUtils.clear(container);
        if (wrapInCard && cardTitle) {
            const defaultIcon = variant === 'danger' ? 'bi-exclamation-triangle-fill' : 'bi-clouds';
            const col = document.createElement('div');
            col.className = 'col';
            const card = document.createElement('div');
            card.className = 'card h-100';
            const body = document.createElement('div');
            body.className = 'card-body';
            const h3 = document.createElement('h3');
            h3.className = 'card-title';
            const icon = document.createElement('i');
            icon.className = `bi ${cardIcon || defaultIcon} icon-inline`;
            icon.setAttribute('aria-hidden', 'true');
            const titleSpan = document.createElement('span');
            titleSpan.textContent = cardTitle;
            h3.appendChild(icon);
            h3.appendChild(document.createTextNode(' '));
            h3.appendChild(titleSpan);
            const p = document.createElement('p');
            p.className = 'card-text';
            p.textContent = message;
            body.appendChild(h3);
            body.appendChild(p);
            card.appendChild(body);
            col.appendChild(card);
            container.appendChild(col);
        } else if (wrapInCard) {
            const col = document.createElement('div');
            col.className = 'col';
            const card = document.createElement('div');
            card.className = 'card h-100';
            const body = document.createElement('div');
            body.className = 'card-body';
            const alert = document.createElement('div');
            alert.className = `alert alert-${variant} mb-0`;
            alert.setAttribute('role', 'alert');
            alert.textContent = message;
            body.appendChild(alert);
            card.appendChild(body);
            col.appendChild(card);
            container.appendChild(col);
        } else {
            const alert = document.createElement('div');
            alert.className = `alert alert-${variant}`;
            alert.setAttribute('role', 'alert');
            alert.textContent = message;
            container.appendChild(alert);
        }
    };

    if (container) {
        renderAlert('info', loadingMessage);
    }

    try {
        const data = await fetchJSONWithRetry(endpoint, {}, {
            ...retryOptions,
            shouldRetryData: retryOnPending
                ? (payload) => payload && payload.status === 'pending'
                : null,
            onRetry: ({ reason, attempt, maxAttempts, waitMs, data: retryData, error }) => {
                if (!container) {
                    return;
                }

                const seconds = Math.max(1, Math.round(waitMs / 1000));
                const message = reason === 'data'
                    ? pendingMessage
                    : (retryMessage || (error ? error.message : pendingMessage));
                const retrySuffix = typeof i18n !== 'undefined'
                    ? i18n.t('common.retrying_in', { seconds, attempt, maxAttempts })
                    : `Retrying in ${seconds}s (${attempt}/${maxAttempts})`;

                renderAlert('info', `${message} ${retrySuffix}`);
            }
        });

        // Handle error in response
        if (data && data.error) {
            if (container) {
                renderAlert('danger', data.error);
            }
            return null;
        }

        // Handle pending status when retries are exhausted
        if (data && data.status === 'pending') {
            if (container) {
                renderAlert('info', pendingMessage);
            }
            return null;
        }

        return data;
    } catch (error) {
        if (container) {
            renderAlert('danger', `Failed to load data: ${error.message}`);
        }
        return null;
    }
}
