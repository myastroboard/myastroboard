/**
 * Wishlist (v1.5) - the Wishlist sub-tab of the Astrodex main tab.
 *
 * A wishlist item records intent: an object you want to capture. Whether it *has* been
 * captured is never stored - the API recomputes it on every read from the Observation Log
 * and the Astrodex, so editing a session is reflected immediately instead of leaving a
 * stale badge behind.
 *
 * Also exports addToWishlist(), the shared helper the SkyTonight "more" popup, the
 * beginner catalog and the catalogue collection all call.
 *
 * DOM is built with explicit element APIs and textContent only.
 */

/** Cached payload, so a sort change re-renders without refetching. */
const wishlistData = {
    items: [],
    progress: { captured: 0, total: 0 },
    maxItems: 0,
    locationName: '',
    visibilityIncluded: false,
    sort: 'visibility',
};

/**
 * Translate, falling back to the supplied English text when the key is missing.
 * @param {string} key
 * @param {string} fallback
 * @param {Object} [params]
 * @returns {string}
 */
function _wlT(key, fallback, params) {
    if (typeof i18n === 'undefined' || typeof i18n.t !== 'function') return fallback;
    const translated = i18n.t(key, params);
    return translated && translated !== key ? translated : fallback;
}

/** Localized short month name for a 1-12 number. */
function _wlMonthName(month) {
    const value = Number(month);
    if (!Number.isFinite(value) || value < 1 || value > 12) return '';
    const date = new Date(Date.UTC(2000, value - 1, 1));
    const locale = (typeof i18n !== 'undefined' && i18n.currentLanguage) || 'en';
    return new Intl.DateTimeFormat(locale, { month: 'long', timeZone: 'UTC' }).format(date);
}

/** Decimal hours as "2h30" / "40 min" / "" when there is nothing observable. */
function _wlHours(hours) {
    const value = Number(hours);
    if (!Number.isFinite(value) || value <= 0) return '';
    const whole = Math.floor(value);
    const minutes = Math.round((value - whole) * 60);
    if (whole <= 0) return _wlT('wishlist.minutes_short', `${minutes} min`, { minutes });
    return `${whole}h${String(minutes).padStart(2, '0')}`;
}

function _wlTypeLabel(type) {
    const raw = String(type || '').trim();
    if (!raw) return '';
    if (typeof strToTranslateKey === 'function') {
        return _wlT(`skytonight.type_${strToTranslateKey(raw)}`, raw);
    }
    return raw;
}

function _wlConstellationLabel(name) {
    if (typeof getConstellationDisplayName === 'function') return getConstellationDisplayName(name);
    return String(name || '');
}

/**
 * Add one or more targets to the wishlist.
 *
 * Shared by every surface that offers a wishlist button. The API always takes a list, so
 * a single object is sent as a list of one - one code path on both sides.
 *
 * @param {Object|Object[]} target - Target payload(s): name plus whatever identity fields are known.
 * @param {HTMLElement} [buttonEl] - Button to disable and relabel on success.
 * @returns {Promise<boolean>} Whether anything was actually added.
 */
async function addToWishlist(target, buttonEl) {
    const targets = Array.isArray(target) ? target : [target];
    if (buttonEl) buttonEl.disabled = true;

    try {
        const response = await fetchJSON('/api/wishlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ targets }),
        });
        const report = response?.data || {};
        const added = Array.isArray(report.added) ? report.added.length : 0;

        if (added > 0) {
            if (buttonEl) {
                buttonEl.textContent = _wlT('wishlist.on_wishlist', 'On wishlist');
                buttonEl.disabled = true;
            }
            showMessage('success', _wlT('wishlist.added', 'Added to your wishlist.'));
            return true;
        }

        if (report.skipped_duplicates) {
            if (buttonEl) {
                buttonEl.textContent = _wlT('wishlist.on_wishlist', 'On wishlist');
                buttonEl.disabled = true;
            }
            showMessage('info', _wlT('wishlist.already_there', 'Already on your wishlist.'));
            return false;
        }

        if (report.skipped_full) {
            showMessage('warning', _wlT('wishlist.full', 'Your wishlist is full.'));
        }
        if (buttonEl) buttonEl.disabled = false;
        return false;
    } catch (error) {
        console.error('Error adding to wishlist:', error);
        showMessage('error', _wlT('wishlist.add_error', 'Could not add this object to your wishlist.'));
        if (buttonEl) buttonEl.disabled = false;
        return false;
    }
}

/**
 * Build the "add to wishlist" button shared by the card surfaces.
 * @param {Object} target
 * @param {boolean} alreadyOnList
 * @param {string} [extraClassName]
 * @returns {HTMLButtonElement}
 */
function buildWishlistButton(target, alreadyOnList, extraClassName = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `btn btn-sm btn-outline-warning ${extraClassName}`.trim();

    const icon = document.createElement('i');
    icon.className = 'bi bi-bookmark-star me-1';
    icon.setAttribute('aria-hidden', 'true');
    button.appendChild(icon);

    const label = document.createElement('span');
    label.textContent = alreadyOnList
        ? _wlT('wishlist.on_wishlist', 'On wishlist')
        : _wlT('wishlist.add_action', 'Wishlist');
    button.appendChild(label);

    if (alreadyOnList) {
        button.disabled = true;
    } else {
        button.addEventListener('click', async () => {
            const added = await addToWishlist(target, button);
            if (added) label.textContent = _wlT('wishlist.on_wishlist', 'On wishlist');
        });
    }
    return button;
}

// ============================================
// Rendering
// ============================================

function _wlRenderHeader(container) {
    const header = document.createElement('div');
    header.className = 'd-flex flex-wrap align-items-center gap-3 mb-3';

    const progressWrapper = document.createElement('div');
    progressWrapper.className = 'wishlist-progress-wrapper flex-grow-1';

    const label = document.createElement('div');
    label.className = 'small mb-1';
    label.textContent = _wlT('wishlist.progress', '{captured} of {total} captured', {
        captured: wishlistData.progress.captured,
        total: wishlistData.progress.total,
    });
    progressWrapper.appendChild(label);

    const progress = document.createElement('div');
    progress.className = 'progress';
    progress.setAttribute('role', 'progressbar');
    progress.setAttribute('aria-valuemin', '0');
    progress.setAttribute('aria-valuemax', String(wishlistData.progress.total || 0));
    progress.setAttribute('aria-valuenow', String(wishlistData.progress.captured || 0));
    const bar = document.createElement('div');
    bar.className = 'progress-bar bg-success';
    const percent = wishlistData.progress.total
        ? Math.round((wishlistData.progress.captured / wishlistData.progress.total) * 100)
        : 0;
    // Bootstrap's own documented progress-bar pattern: a computed per-instance width.
    bar.style.width = `${percent}%`;
    progress.appendChild(bar);
    progressWrapper.appendChild(progress);
    header.appendChild(progressWrapper);

    const sortSelect = document.createElement('select');
    sortSelect.className = 'form-select form-select-sm w-auto';
    sortSelect.id = 'wishlist-sort';
    [
        { value: 'visibility', label: _wlT('wishlist.sort_visibility', 'Sort by visibility') },
        { value: 'priority', label: _wlT('wishlist.sort_priority', 'Sort by priority') },
        { value: 'name', label: _wlT('wishlist.sort_name', 'Sort by name') },
    ].forEach(option => {
        const element = document.createElement('option');
        element.value = option.value;
        element.textContent = option.label;
        if (option.value === wishlistData.sort) element.selected = true;
        sortSelect.appendChild(element);
    });
    sortSelect.addEventListener('change', () => {
        wishlistData.sort = sortSelect.value;
        loadWishlist();
    });
    header.appendChild(sortSelect);

    if (wishlistData.progress.captured > 0) {
        const archiveBtn = document.createElement('button');
        archiveBtn.type = 'button';
        archiveBtn.className = 'btn btn-sm btn-outline-secondary';
        archiveBtn.id = 'wishlist-archive-captured';
        archiveBtn.textContent = _wlT('wishlist.archive_captured', 'Remove captured');
        archiveBtn.addEventListener('click', () => _wlArchiveCaptured(archiveBtn));
        header.appendChild(archiveBtn);
    }

    container.appendChild(header);
}

function _wlVisibilityCell(item) {
    const cell = document.createElement('div');
    cell.className = 'wishlist-visibility-cell';

    if (item.moving) {
        cell.textContent = _wlT('wishlist.visibility_moving', 'Moves across the sky - no fixed window');
        cell.classList.add('text-muted');
        return cell;
    }
    if (!item.placed) {
        cell.textContent = _wlT('wishlist.visibility_unknown', 'Coordinates unknown');
        cell.classList.add('text-muted');
        return cell;
    }
    if (!wishlistData.visibilityIncluded || item.observable_hours_next == null) {
        cell.textContent = '';
        return cell;
    }

    const tonight = _wlHours(item.observable_hours_next);
    if (tonight) {
        const line = document.createElement('div');
        line.className = 'text-success';
        line.textContent = _wlT('wishlist.visibility_tonight', '{hours} tonight', { hours: tonight });
        cell.appendChild(line);
    } else {
        const line = document.createElement('div');
        line.className = 'text-muted';
        line.textContent = _wlT('wishlist.visibility_not_tonight', 'Not observable tonight');
        cell.appendChild(line);
    }

    if (item.best_month) {
        const best = document.createElement('div');
        best.className = 'text-muted';
        best.textContent = _wlT('wishlist.visibility_best_month', 'Best ahead: {month}', {
            month: _wlMonthName(item.best_month),
        });
        cell.appendChild(best);
    }
    return cell;
}

function _wlPrioritySelect(item) {
    const select = document.createElement('select');
    select.className = 'form-select form-select-sm w-auto';
    select.setAttribute('aria-label', _wlT('wishlist.priority', 'Priority'));
    [
        { value: 'high', label: _wlT('wishlist.priority_high', 'High') },
        { value: 'normal', label: _wlT('wishlist.priority_normal', 'Normal') },
        { value: 'low', label: _wlT('wishlist.priority_low', 'Low') },
    ].forEach(option => {
        const element = document.createElement('option');
        element.value = option.value;
        element.textContent = option.label;
        if (option.value === item.priority) element.selected = true;
        select.appendChild(element);
    });

    select.addEventListener('change', async () => {
        const previous = item.priority;
        select.disabled = true;
        try {
            await fetchJSON(`/api/wishlist/${encodeURIComponent(item.id)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ priority: select.value }),
            });
            item.priority = select.value;
            if (wishlistData.sort === 'priority') loadWishlist();
        } catch (error) {
            console.error('Error updating wishlist priority:', error);
            select.value = previous;
            showMessage('error', _wlT('wishlist.update_error', 'Could not update this wish.'));
        } finally {
            select.disabled = false;
        }
    });
    return select;
}

function _wlBuildRow(item) {
    const row = document.createElement('div');
    row.className = 'wishlist-item-row';
    if (item.captured) row.classList.add('wishlist-item-captured');

    const top = document.createElement('div');
    top.className = 'd-flex flex-wrap align-items-center gap-2';

    const name = document.createElement('span');
    name.className = 'wishlist-item-name';
    name.textContent = item.name || '';
    top.appendChild(name);

    if (item.captured) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-success';
        badge.textContent = _wlT('wishlist.captured', 'Captured');
        top.appendChild(badge);
    }

    const typeLabel = _wlTypeLabel(item.type);
    if (typeLabel) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-secondary';
        badge.textContent = typeLabel;
        top.appendChild(badge);
    }

    const constellationLabel = _wlConstellationLabel(item.constellation);
    if (constellationLabel) {
        const badge = document.createElement('span');
        badge.className = 'badge bg-light text-dark border';
        badge.textContent = constellationLabel;
        top.appendChild(badge);
    }

    const spacer = document.createElement('span');
    spacer.className = 'flex-grow-1';
    top.appendChild(spacer);

    top.appendChild(_wlPrioritySelect(item));

    if (item.placed && !item.moving && typeof openVisibilityCalendar === 'function') {
        const calendarBtn = document.createElement('button');
        calendarBtn.type = 'button';
        calendarBtn.className = 'btn btn-sm btn-outline-info';
        calendarBtn.title = _wlT('wishlist.open_calendar', 'Visibility calendar');
        const icon = document.createElement('i');
        icon.className = 'bi bi-calendar3';
        icon.setAttribute('aria-hidden', 'true');
        calendarBtn.appendChild(icon);
        calendarBtn.addEventListener('click', () => openVisibilityCalendar(item.name));
        top.appendChild(calendarBtn);
    }

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn btn-sm btn-outline-danger';
    removeBtn.title = _wlT('wishlist.remove', 'Remove');
    const removeIcon = document.createElement('i');
    removeIcon.className = 'bi bi-trash';
    removeIcon.setAttribute('aria-hidden', 'true');
    removeBtn.appendChild(removeIcon);
    removeBtn.addEventListener('click', () => _wlRemove(item, removeBtn));
    top.appendChild(removeBtn);

    row.appendChild(top);

    const meta = document.createElement('div');
    meta.className = 'wishlist-item-meta d-flex flex-wrap align-items-center gap-3 mt-1';
    meta.appendChild(_wlVisibilityCell(item));
    if (item.notes) {
        const notes = document.createElement('span');
        notes.textContent = item.notes;
        meta.appendChild(notes);
    }
    row.appendChild(meta);

    return row;
}

async function _wlRemove(item, buttonEl) {
    buttonEl.disabled = true;
    try {
        await fetchJSON(`/api/wishlist/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
        await loadWishlist();
    } catch (error) {
        console.error('Error removing wishlist item:', error);
        buttonEl.disabled = false;
        showMessage('error', _wlT('wishlist.remove_error', 'Could not remove this wish.'));
    }
}

async function _wlArchiveCaptured(buttonEl) {
    buttonEl.disabled = true;
    try {
        const response = await fetchJSON('/api/wishlist/archive-captured', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const removed = Number(response?.removed || 0);
        showMessage('success', _wlT('wishlist.archived', '{count} captured objects removed.', { count: removed }));
        await loadWishlist();
    } catch (error) {
        console.error('Error archiving captured wishlist items:', error);
        buttonEl.disabled = false;
        showMessage('error', _wlT('wishlist.archive_error', 'Could not remove the captured objects.'));
    }
}

function _wlRenderEmpty(container) {
    const wrapper = document.createElement('div');
    wrapper.className = 'session-analytics-empty';
    const icon = document.createElement('i');
    icon.className = 'bi bi-bookmark-star session-analytics-empty-icon';
    icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('div');
    text.textContent = _wlT(
        'wishlist.empty',
        'Nothing on your wishlist yet. Add objects from SkyTonight, the catalogue collection or the beginner catalog.'
    );
    wrapper.appendChild(icon);
    wrapper.appendChild(text);
    container.appendChild(wrapper);
}

// ============================================
// Entry point
// ============================================

/**
 * Load and render the Wishlist sub-tab.
 * @returns {Promise<void>}
 */
async function loadWishlist() {
    const container = document.getElementById('wishlist-display');
    if (!container) return;
    DOMUtils.setLoading(container, _wlT('common.loading', 'Loading...'));

    let payload = null;
    try {
        payload = await fetchJSON(`/api/wishlist?sort=${encodeURIComponent(wishlistData.sort)}`);
    } catch (error) {
        console.error('Error loading wishlist:', error);
    }

    DOMUtils.clear(container);

    if (!payload) {
        const failed = document.createElement('div');
        failed.className = 'alert alert-warning';
        failed.textContent = _wlT('wishlist.load_error', 'Could not load your wishlist.');
        container.appendChild(failed);
        return;
    }

    wishlistData.items = Array.isArray(payload.items) ? payload.items : [];
    wishlistData.progress = payload.progress || { captured: 0, total: 0 };
    wishlistData.maxItems = Number(payload.max_items || 0);
    wishlistData.locationName = payload.location_name || '';
    wishlistData.visibilityIncluded = Boolean(payload.visibility_included);

    if (!wishlistData.items.length) {
        _wlRenderEmpty(container);
        return;
    }

    _wlRenderHeader(container);

    const list = document.createElement('div');
    wishlistData.items.forEach(item => list.appendChild(_wlBuildRow(item)));
    container.appendChild(list);

    if (wishlistData.visibilityIncluded && wishlistData.locationName) {
        const note = document.createElement('div');
        note.className = 'text-muted small mt-2';
        note.textContent = _wlT('wishlist.visibility_note', 'Visibility is computed for {location}.', {
            location: wishlistData.locationName,
        });
        container.appendChild(note);
    }
}
