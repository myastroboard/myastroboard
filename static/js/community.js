/**
 * Community tab: what the members are up to (activity feed and "together" totals), the
 * member directory and member profiles.
 *
 * Emulation without competition: the feed is chronological, the directory alphabetical,
 * the totals shared ("together we have 96 of 110 Messier objects"). No figure is ever put
 * next to another member's to compare them. Everything shown comes from
 * /api/community/*, which only returns members who joined and the blocks they show.
 */

/* global DOMUtils, i18n, fetchJSON, appUrl, buildUserAvatar, buildUserChip, progressBadgeTexts,
   progressCatalogueLabel, progressDateLabel, progressHours, progressClassLabel, switchMainTab,
   switchSubTab, fetchOwnProfile, currentUser */

const communityState = {
    token: 0,
    listenersBound: false,
    openProfileId: null,
    enabled: null,
};

function _cmT(key, fallback, params) {
    if (typeof i18n === 'undefined' || typeof i18n.t !== 'function') return fallback;
    const translated = i18n.t(key, params);
    return translated && translated !== key ? translated : fallback;
}

function _cmEl(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = text;
    return element;
}

function _cmDate(day) {
    return typeof progressDateLabel === 'function' ? progressDateLabel(day) : String(day || '');
}

function _cmHours(minutes) {
    return typeof progressHours === 'function' ? progressHours(minutes) : `${Math.round(Number(minutes) || 0)} min`;
}

function _cmCatalogue(catalogue) {
    return typeof progressCatalogueLabel === 'function' ? progressCatalogueLabel(catalogue) : String(catalogue || '');
}

function _cmMessage(container, text, variant = 'info', icon = 'bi bi-people') {
    const box = _cmEl('div', `alert alert-${variant} community-message`);
    DOMUtils.append(box, DOMUtils.createIcon(`${icon} icon-inline`), ` ${text}`);
    container.appendChild(box);
}

function _cmDisabled(container) {
    DOMUtils.clear(container);
    _cmMessage(container, _cmT('community.disabled', 'The administrator has turned the Community off.'), 'secondary', 'bi bi-slash-circle');
}

function _cmIsDisabledError(error) {
    return error?.status === 404 && error?.data?.error_key === 'community.disabled';
}

function _cmGoToProfileSettings() {
    if (typeof switchMainTab === 'function') switchMainTab('my-settings');
    if (typeof switchSubTab === 'function') switchSubTab('my-settings', 'profile');
}

/** A thin bar for a shared catalogue total: width is the per-instance dynamic value. */
function _cmBar(current, total, label) {
    const ratio = total > 0 ? Math.max(0, Math.min(1, Number(current) / Number(total))) : 0;
    const bar = _cmEl('div', 'progress community-bar');
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-label', label);
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', String(total));
    bar.setAttribute('aria-valuenow', String(current));
    const fill = _cmEl('div', 'progress-bar');
    // Per-instance dynamic width: the documented Bootstrap progress-bar exception.
    fill.style.width = `${Math.round(ratio * 100)}%`;
    bar.appendChild(fill);
    return bar;
}

function _cmPictureUrl(filename) {
    return appUrl(`/api/astrodex/images/${encodeURIComponent(filename)}`);
}

/** The small preview of a picture: the feed shows dozens, the originals weigh megabytes each. */
function _cmPreviewUrl(filename) {
    return `${_cmPictureUrl(filename)}?size=thumb`;
}

function _cmThumb(picture, size = 'sm') {
    const link = _cmEl('a', `community-thumb community-thumb-${size}`);
    link.href = _cmPictureUrl(picture.filename);
    link.target = '_blank';
    link.rel = 'noopener';
    link.title = picture.item_name || '';
    const img = _cmEl('img');
    img.src = _cmPreviewUrl(picture.filename);
    img.alt = picture.item_name || '';
    img.loading = 'lazy';
    img.decoding = 'async';
    link.appendChild(img);
    return link;
}

/** Clickable member name with avatar, opening their profile. */
function _cmMemberLink(identity) {
    const button = _cmEl('button', 'btn btn-link p-0 community-member-link');
    button.type = 'button';
    button.appendChild(buildUserChip(identity, 'sm'));
    button.addEventListener('click', () => {
        if (typeof switchSubTab === 'function') switchSubTab('community', 'community-members');
        openCommunityProfile(identity.user_id);
    });
    return button;
}

// ── Activity ─────────────────────────────────────────────────────────────────

function _cmRenderJoinBanner(listed) {
    const container = document.getElementById('community-join-banner');
    if (!container) return;
    DOMUtils.clear(container);
    if (listed) return;
    const banner = _cmEl('div', 'community-join');
    const text = _cmEl('div', 'community-join-text');
    text.appendChild(_cmEl('div', 'fw-semibold', _cmT('community.join_title', 'You have not joined the Community yet')));
    text.appendChild(_cmEl('div', 'small text-muted', _cmT(
        'community.join_text',
        'Join to appear in the directory and share your progress with the others. You choose what they see.'
    )));
    banner.appendChild(text);
    const button = _cmEl('button', 'btn btn-primary btn-sm');
    button.type = 'button';
    DOMUtils.append(button, DOMUtils.createIcon('bi bi-person-plus icon-inline'), ` ${_cmT('community.join_button', 'Set up my profile')}`);
    button.addEventListener('click', _cmGoToProfileSettings);
    banner.appendChild(button);
    container.appendChild(banner);
}

/** Admin alone on the instance: the tab has nobody to show, say where it can be turned off. */
function _cmRenderSingleAccountNote(accountCount) {
    const banner = document.getElementById('community-join-banner');
    if (!banner || accountCount !== 1) return;
    const note = _cmEl('div', 'alert alert-info community-message');
    DOMUtils.append(note, DOMUtils.createIcon('bi bi-info-circle icon-inline'), ` ${_cmT(
        'community.single_account_note',
        'You are the only account on this instance: the Community comes to life with several members. If you do not need it, you can turn it off.'
    )} `);
    const link = _cmEl('a', 'alert-link', _cmT('community.single_account_link', 'App settings -> Configuration'));
    link.href = '#parameters/configuration';
    link.addEventListener('click', (event) => {
        event.preventDefault();
        if (typeof switchMainTab === 'function') switchMainTab('parameters');
        if (typeof switchSubTab === 'function') switchSubTab('parameters', 'configuration');
        // Scroll the window itself: scrollIntoView() would scroll the nearest overflow:hidden
        // panel instead and shift its content out of view. Once the tab is laid out.
        requestAnimationFrame(() => {
            const target = document.getElementById('feature-community-wrapper');
            if (!target) return;
            const top = target.getBoundingClientRect().top + window.scrollY - window.innerHeight / 3;
            window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
        });
    });
    note.appendChild(link);
    banner.prepend(note);
}

function _cmRenderTogether(together) {
    const container = document.getElementById('community-together');
    if (!container) return;
    DOMUtils.clear(container);
    if (!together || together.members === 0) return;

    container.appendChild(_cmEl('h3', 'h5 community-section-title', _cmT('community.together_title', 'Together')));
    const plate = _cmEl('div');
    container.appendChild(plate);
    DOMUtils.buildStatPlate(plate, {
        hero: {
            value: String(together.objects),
            label: _cmT('community.together_objects', 'objects captured together'),
            hint: _cmT('community.together_members', 'Members taking part: {count}', { count: together.members }),
        },
        figures: [
            { icon: 'bi-hourglass-split', value: _cmHours(together.integration_minutes), label: _cmT('community.together_integration', 'integration time') },
            { icon: 'bi-moon-stars', value: String(together.nights), label: _cmT('community.together_nights', 'nights under the stars') },
            { icon: 'bi-diagram-3', value: String(together.constellations), label: _cmT('community.together_constellations', 'constellations') },
        ],
    });

    if (!together.catalogues?.length) return;
    const list = _cmEl('div', 'community-catalogues');
    together.catalogues.forEach((row) => {
        const item = _cmEl('div', 'community-catalogue');
        const head = _cmEl('div', 'community-catalogue-head');
        head.appendChild(_cmEl('span', 'fw-semibold', _cmCatalogue(row.catalogue)));
        head.appendChild(_cmEl('span', 'small text-muted', `${row.captured} / ${row.total}`));
        item.appendChild(head);
        item.appendChild(_cmBar(row.captured, row.total, _cmCatalogue(row.catalogue)));
        if (row.remaining_examples?.length) {
            const remaining = row.total - row.captured;
            item.appendChild(_cmEl('div', 'small text-muted community-remaining', _cmT(
                'community.remaining',
                'Still to capture together ({count}): {names}',
                { count: remaining, names: row.remaining_examples.join(', ') + (remaining > row.remaining_examples.length ? ', ...' : '') }
            )));
        } else if (row.captured >= row.total) {
            item.appendChild(_cmEl('div', 'small community-complete', _cmT('community.catalogue_complete', 'Complete, together!')));
        }
        list.appendChild(item);
    });
    container.appendChild(list);
}

function _cmBadgeLine(badge) {
    const texts = typeof progressBadgeTexts === 'function' ? progressBadgeTexts(badge) : { name: badge.id };
    const line = _cmEl('span', 'community-badge');
    const icon = _cmEl('span', 'progress-badge-icon is-earned community-badge-icon');
    icon.appendChild(DOMUtils.createIcon(`bi ${badge.icon}`));
    line.appendChild(icon);
    line.appendChild(_cmEl('span', 'community-badge-name', texts.name));
    return line;
}

/** One feed card: a member's day, with what they captured, pictured and earned. */
function _cmDigest(digest, { showMember = true } = {}) {
    const card = _cmEl('article', 'community-digest');
    const head = _cmEl('div', 'community-digest-head');
    if (showMember) head.appendChild(_cmMemberLink(digest.member));
    head.appendChild(_cmEl('time', 'small text-muted community-digest-date', _cmDate(digest.date)));
    head.lastChild.setAttribute('datetime', digest.date);
    card.appendChild(head);

    if (digest.new_objects_count > 0) {
        const line = _cmEl('div', 'community-digest-line');
        line.appendChild(DOMUtils.createIcon('bi bi-stars text-warning icon-inline'));
        const names = digest.new_objects.map((item) => item.name).join(', ');
        const more = digest.new_objects_count > digest.new_objects.length ? ', ...' : '';
        line.appendChild(_cmEl('span', '', ` ${_cmT('community.digest_new_objects', 'New objects ({count}): {names}', {
            count: digest.new_objects_count,
            names: names + more,
        })}`));
        card.appendChild(line);
    }
    if (digest.pictures_count > 0) {
        const line = _cmEl('div', 'community-digest-line');
        line.appendChild(DOMUtils.createIcon('bi bi-image text-info icon-inline'));
        line.appendChild(_cmEl('span', '', ` ${_cmT('community.digest_pictures', 'Pictures added: {count}', { count: digest.pictures_count })}`));
        card.appendChild(line);
        const strip = _cmEl('div', 'community-thumbs');
        digest.pictures.forEach((picture) => strip.appendChild(_cmThumb(picture)));
        card.appendChild(strip);
    }
    if (digest.badges?.length) {
        const line = _cmEl('div', 'community-digest-line community-digest-badges');
        line.appendChild(DOMUtils.createIcon('bi bi-trophy-fill text-warning icon-inline'));
        line.appendChild(_cmEl('span', '', ` ${_cmT('community.digest_badges', 'Badge earned:')}`));
        digest.badges.forEach((badge) => line.appendChild(_cmBadgeLine(badge)));
        card.appendChild(line);
    }
    return card;
}

function _cmRenderFeed(container, feed, emptyText, options) {
    DOMUtils.clear(container);
    if (!feed?.length) {
        container.appendChild(_cmEl('div', 'text-muted community-empty', emptyText));
        return;
    }
    const list = _cmEl('div', 'community-feed');
    feed.forEach((digest) => list.appendChild(_cmDigest(digest, options)));
    container.appendChild(list);
}

async function loadCommunityActivity() {
    const feedContainer = document.getElementById('community-feed');
    if (!feedContainer) return;
    _cmBindListeners();
    const token = ++communityState.token;
    DOMUtils.clear(feedContainer);
    feedContainer.appendChild(DOMUtils.createSpinnerWrapper(_cmT('common.loading', 'Loading...')));
    try {
        const payload = await fetchJSON('/api/community/activity');
        if (token !== communityState.token) return;
        _cmRenderJoinBanner(payload.you_listed);
        _cmRenderSingleAccountNote(payload.account_count);
        _cmRenderTogether(payload.together);
        const title = _cmEl('h3', 'h5 community-section-title', _cmT('community.feed_title', 'Latest activity'));
        _cmRenderFeed(feedContainer, payload.feed, _cmT('community.feed_empty', 'Nothing yet. The first captures of the members who joined will appear here.'));
        feedContainer.prepend(title);
    } catch (error) {
        if (token !== communityState.token) return;
        if (_cmIsDisabledError(error)) {
            _cmDisabled(feedContainer);
            return;
        }
        console.error('Error loading the Community activity:', error);
        DOMUtils.clear(feedContainer);
        _cmMessage(feedContainer, _cmT('community.error_load', 'Could not load the Community.'), 'danger', 'bi bi-exclamation-triangle');
    }
}

// ── Members ──────────────────────────────────────────────────────────────────

function _cmMemberCard(member) {
    const card = _cmEl('button', 'community-member-card');
    card.type = 'button';
    card.appendChild(buildUserAvatar(member, 'md'));
    const body = _cmEl('div', 'community-member-body');
    const name = _cmEl('div', 'community-member-name', member.display_name);
    if (member.is_you) name.appendChild(_cmEl('span', 'badge rounded-pill text-bg-secondary ms-2', _cmT('community.you', 'You')));
    body.appendChild(name);
    if (member.bio) body.appendChild(_cmEl('div', 'small community-member-bio', member.bio));
    if (member.member_since) {
        body.appendChild(_cmEl('div', 'small text-muted', _cmT('community.member_since', 'Member since {date}', {
            date: _cmDate(member.member_since),
        })));
    }
    card.appendChild(body);
    card.addEventListener('click', () => openCommunityProfile(member.user_id));
    return card;
}

async function loadCommunityMembers() {
    const container = document.getElementById('community-members-content');
    if (!container) return;
    _cmBindListeners();
    if (communityState.openProfileId) {
        openCommunityProfile(communityState.openProfileId);
        return;
    }
    const token = ++communityState.token;
    DOMUtils.clear(container);
    container.appendChild(DOMUtils.createSpinnerWrapper(_cmT('common.loading', 'Loading...')));
    try {
        const payload = await fetchJSON('/api/community/members');
        if (token !== communityState.token) return;
        DOMUtils.clear(container);
        if (!payload.you_listed) {
            const note = _cmEl('div', 'community-join');
            note.appendChild(_cmEl('div', 'small', _cmT('community.members_not_listed', 'You are not in the directory: join from My settings -> Profile.')));
            const button = _cmEl('button', 'btn btn-outline-primary btn-sm');
            button.type = 'button';
            button.textContent = _cmT('community.join_button', 'Set up my profile');
            button.addEventListener('click', _cmGoToProfileSettings);
            note.appendChild(button);
            container.appendChild(note);
        }
        if (!payload.members.length) {
            container.appendChild(_cmEl('div', 'text-muted community-empty', _cmT('community.members_empty', 'Nobody has joined yet.')));
            return;
        }
        container.appendChild(_cmEl('div', 'small text-muted mb-2', _cmT('community.members_count', 'Members: {count}, in alphabetical order', {
            count: payload.members.length,
        })));
        const grid = _cmEl('div', 'community-members');
        payload.members.forEach((member) => grid.appendChild(_cmMemberCard(member)));
        container.appendChild(grid);
    } catch (error) {
        if (token !== communityState.token) return;
        if (_cmIsDisabledError(error)) {
            _cmDisabled(container);
            return;
        }
        console.error('Error loading the Community members:', error);
        DOMUtils.clear(container);
        _cmMessage(container, _cmT('community.error_load', 'Could not load the Community.'), 'danger', 'bi bi-exclamation-triangle');
    }
}

// ── Profile ──────────────────────────────────────────────────────────────────

function _cmSection(parent, icon, title) {
    const section = _cmEl('section', 'community-profile-section');
    const heading = _cmEl('h3', 'h5 community-section-title');
    DOMUtils.append(heading, DOMUtils.createIcon(`bi ${icon} icon-inline`), ` ${title}`);
    section.appendChild(heading);
    parent.appendChild(section);
    return section;
}

function _cmRenderProfile(container, profile) {
    DOMUtils.clear(container);
    const back = _cmEl('button', 'btn btn-outline-secondary btn-sm mb-3');
    back.type = 'button';
    DOMUtils.append(back, DOMUtils.createIcon('bi bi-arrow-left icon-inline'), ` ${_cmT('community.back_to_members', 'All members')}`);
    back.addEventListener('click', () => {
        communityState.openProfileId = null;
        loadCommunityMembers();
    });
    container.appendChild(back);

    if (profile.is_you && !profile.listed) {
        const preview = _cmEl('div', 'alert alert-warning');
        DOMUtils.append(preview, DOMUtils.createIcon('bi bi-eye icon-inline'), ` ${_cmT(
            'community.preview_unlisted',
            'Preview: this is what the members will see once you join the Community. Nobody sees it yet.'
        )}`);
        container.appendChild(preview);
    }

    const header = _cmEl('div', 'community-profile-header');
    header.appendChild(buildUserAvatar(profile, 'lg', profile.display_name));
    const identity = _cmEl('div', 'community-profile-identity');
    identity.appendChild(_cmEl('h3', 'community-profile-name', profile.display_name));
    if (profile.member_since) {
        identity.appendChild(_cmEl('div', 'small text-muted', _cmT('community.member_since', 'Member since {date}', {
            date: _cmDate(profile.member_since),
        })));
    }
    if (profile.bio) identity.appendChild(_cmEl('p', 'community-profile-bio', profile.bio));
    if (profile.is_you) {
        const edit = _cmEl('button', 'btn btn-outline-primary btn-sm');
        edit.type = 'button';
        DOMUtils.append(edit, DOMUtils.createIcon('bi bi-pencil icon-inline'), ` ${_cmT('community.edit_profile', 'Edit my profile')}`);
        edit.addEventListener('click', _cmGoToProfileSettings);
        identity.appendChild(edit);
    }
    header.appendChild(identity);
    container.appendChild(header);

    const blocks = profile.blocks || {};
    if (!Object.keys(blocks).length) {
        container.appendChild(_cmEl('div', 'text-muted community-empty', _cmT('community.profile_nothing_shown', 'This member shares nothing more for now.')));
        return;
    }

    if (blocks.stats) {
        const section = _cmSection(container, 'bi-bar-chart-fill text-info', _cmT('community.block_stats', 'In figures'));
        const plate = _cmEl('div');
        section.appendChild(plate);
        DOMUtils.buildStatPlate(plate, {
            hero: { value: String(blocks.stats.objects), label: _cmT('community.stat_objects', 'objects captured') },
            figures: [
                { icon: 'bi-hourglass-split', value: _cmHours(blocks.stats.integration_minutes), label: _cmT('community.together_integration', 'integration time') },
                { icon: 'bi-moon-stars', value: String(blocks.stats.nights), label: _cmT('community.stat_nights', 'nights') },
                { icon: 'bi-diagram-3', value: String(blocks.stats.constellations), label: _cmT('community.together_constellations', 'constellations') },
            ],
        });
        if (blocks.stats.catalogues?.length) {
            const list = _cmEl('div', 'community-catalogues');
            blocks.stats.catalogues.forEach((row) => {
                const item = _cmEl('div', 'community-catalogue');
                const head = _cmEl('div', 'community-catalogue-head');
                head.appendChild(_cmEl('span', 'fw-semibold', _cmCatalogue(row.catalogue)));
                head.appendChild(_cmEl('span', 'small text-muted', `${row.captured} / ${row.total}`));
                item.appendChild(head);
                item.appendChild(_cmBar(row.captured, row.total, _cmCatalogue(row.catalogue)));
                list.appendChild(item);
            });
            section.appendChild(list);
        }
    }

    if (blocks.badges) {
        const section = _cmSection(container, 'bi-trophy-fill text-warning', _cmT('community.block_badges', 'Badges'));
        if (!blocks.badges.length) {
            section.appendChild(_cmEl('div', 'text-muted small', _cmT('community.no_badges', 'No badge yet.')));
        } else {
            const grid = _cmEl('div', 'community-badges');
            blocks.badges.forEach((badge) => {
                const item = _cmEl('div', 'community-badge-card');
                item.appendChild(_cmBadgeLine(badge));
                if (badge.earned_on) item.appendChild(_cmEl('div', 'small text-muted', _cmDate(badge.earned_on)));
                grid.appendChild(item);
            });
            section.appendChild(grid);
        }
    }

    if (blocks.pictures) {
        const section = _cmSection(container, 'bi-images text-info', _cmT('community.block_pictures', 'Latest pictures'));
        if (!blocks.pictures.length) {
            section.appendChild(_cmEl('div', 'text-muted small', _cmT('community.no_pictures', 'No picture yet.')));
        } else {
            const grid = _cmEl('div', 'community-gallery');
            blocks.pictures.forEach((picture) => {
                const figure = _cmEl('figure', 'community-gallery-item');
                figure.appendChild(_cmThumb(picture, 'lg'));
                figure.appendChild(_cmEl('figcaption', 'small', picture.item_name));
                grid.appendChild(figure);
            });
            section.appendChild(grid);
        }
    }

    if (blocks.equipment) {
        const section = _cmSection(container, 'bi-binoculars-fill', _cmT('community.block_equipment', 'Equipment'));
        if (!blocks.equipment.length) {
            section.appendChild(_cmEl('div', 'text-muted small', _cmT('community.no_equipment', 'No equipment yet.')));
        } else {
            const list = _cmEl('ul', 'community-equipment');
            blocks.equipment.forEach((row) => {
                const item = _cmEl('li');
                item.appendChild(_cmEl('span', 'fw-semibold', row.name));
                const parts = [row.telescope, row.camera].filter(Boolean).join(' + ');
                if (parts) item.appendChild(_cmEl('span', 'small text-muted', ` - ${parts}`));
                list.appendChild(item);
            });
            section.appendChild(list);
        }
    }

    if (blocks.activity) {
        const section = _cmSection(container, 'bi-activity text-info', _cmT('community.block_activity', 'Recent activity'));
        const feed = _cmEl('div');
        section.appendChild(feed);
        _cmRenderFeed(feed, blocks.activity, _cmT('community.no_activity', 'No activity yet.'), { showMember: false });
    }
}

/** Show one member's profile in the Members sub-tab (the owner may preview their own). */
async function openCommunityProfile(userId) {
    const container = document.getElementById('community-members-content');
    if (!container || !userId) return;
    communityState.openProfileId = userId;
    const token = ++communityState.token;
    DOMUtils.clear(container);
    container.appendChild(DOMUtils.createSpinnerWrapper(_cmT('common.loading', 'Loading...')));
    try {
        const profile = await fetchJSON(`/api/community/members/${encodeURIComponent(userId)}`);
        if (token !== communityState.token) return;
        _cmRenderProfile(container, profile);
    } catch (error) {
        if (token !== communityState.token) return;
        communityState.openProfileId = null;
        if (_cmIsDisabledError(error)) {
            _cmDisabled(container);
            return;
        }
        DOMUtils.clear(container);
        const notFound = error?.status === 404;
        _cmMessage(
            container,
            notFound ? _cmT('community.profile_not_found', 'This profile is not shared.') : _cmT('community.error_load', 'Could not load the Community.'),
            notFound ? 'secondary' : 'danger',
            notFound ? 'bi bi-eye-slash' : 'bi bi-exclamation-triangle'
        );
        const back = _cmEl('button', 'btn btn-outline-secondary btn-sm');
        back.type = 'button';
        back.textContent = _cmT('community.back_to_members', 'All members');
        back.addEventListener('click', () => loadCommunityMembers());
        container.appendChild(back);
    }
}

// ── Availability and wiring ──────────────────────────────────────────────────

/** Show or hide the Community tab according to the admin switch. */
async function refreshCommunityAvailability() {
    try {
        const data = typeof fetchOwnProfile === 'function' ? await fetchOwnProfile() : await fetchJSON('/api/profile');
        communityState.enabled = data.community_enabled !== false;
        if (data.identity && typeof currentUser !== 'undefined' && currentUser && typeof updateCurrentIdentity === 'function') {
            updateCurrentIdentity(data.identity);
        }
    } catch (error) {
        console.warn('Could not read the Community availability:', error);
        communityState.enabled = false;
    }
    document.querySelectorAll('.community-nav-item').forEach((item) => item.classList.toggle('d-none', !communityState.enabled));
    return communityState.enabled;
}

function _cmBindListeners() {
    if (communityState.listenersBound) return;
    communityState.listenersBound = true;
    window.addEventListener('i18nLanguageChanged', () => {
        if (document.getElementById('community-activity-subtab')?.classList.contains('active')) loadCommunityActivity();
        if (document.getElementById('community-members-subtab')?.classList.contains('active')) loadCommunityMembers();
    });
}

window.loadCommunityActivity = loadCommunityActivity;
window.loadCommunityMembers = loadCommunityMembers;
window.openCommunityProfile = openCommunityProfile;
window.refreshCommunityAvailability = refreshCommunityAvailability;
