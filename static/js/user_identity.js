/**
 * How a member is shown everywhere: avatar picture and display name.
 *
 * The server always answers /api/users/<id>/avatar with a picture (the uploaded avatar,
 * else generated initials), so an avatar never needs a fallback here. Names come from the
 * server too: the display name, else the login name (see backend/utils/user_identity.py).
 */

/* global appUrl, currentUser */

/** Avatar URL of a member: from an identity object, or built from a bare user id. */
function userAvatarUrl(identityOrId) {
    if (identityOrId && typeof identityOrId === 'object' && identityOrId.avatar_url) {
        return appUrl(identityOrId.avatar_url);
    }
    const userId = typeof identityOrId === 'object' ? identityOrId?.user_id : identityOrId;
    return userId ? appUrl(`/api/users/${encodeURIComponent(userId)}/avatar`) : '';
}

/**
 * Round avatar picture. size: 'xs' (navbar, labels), 'sm' (lists), 'md' (cards), 'lg' (profile header).
 * The image is decorative next to the name, so its alt text is empty unless asked.
 */
function buildUserAvatar(identityOrId, size = 'sm', altText = '') {
    const img = document.createElement('img');
    img.className = `user-avatar user-avatar-${size}`;
    img.src = userAvatarUrl(identityOrId);
    img.alt = altText;
    img.loading = 'lazy';
    img.decoding = 'async';
    return img;
}

/** Avatar plus name, inline: the one way a member is labelled in a list. */
function buildUserChip(identity, size = 'xs') {
    const chip = document.createElement('span');
    chip.className = 'user-chip';
    if (identity?.user_id) chip.appendChild(buildUserAvatar(identity, size));
    const name = document.createElement('span');
    name.className = 'user-chip-name';
    name.textContent = identity?.display_name || identity?.username || '';
    chip.appendChild(name);
    return chip;
}

/** Name of the signed-in member, as the others see it. */
function currentDisplayName() {
    if (typeof currentUser === 'undefined' || !currentUser) return '';
    return currentUser.display_name || currentUser.username || '';
}

/** Refresh the navbar avatar and name (after login, or after a profile change). */
function renderNavbarIdentity() {
    if (typeof currentUser === 'undefined' || !currentUser) return;
    const nameNode = document.getElementById('username-display');
    if (nameNode) nameNode.textContent = currentDisplayName();
    const avatar = document.getElementById('navbar-avatar');
    if (avatar) {
        avatar.src = userAvatarUrl(currentUser);
        avatar.classList.remove('d-none');
        document.getElementById('navbar-user-icon')?.classList.add('d-none');
    }
}

/** Apply a fresh identity (from /api/profile) to the signed-in member and the navbar. */
function updateCurrentIdentity(identity) {
    if (typeof currentUser === 'undefined' || !currentUser || !identity) return;
    currentUser.display_name = identity.display_name;
    currentUser.avatar_url = identity.avatar_url;
    renderNavbarIdentity();
    window.dispatchEvent(new CustomEvent('userIdentityChanged', { detail: identity }));
}

window.userAvatarUrl = userAvatarUrl;
window.buildUserAvatar = buildUserAvatar;
window.buildUserChip = buildUserChip;
window.renderNavbarIdentity = renderNavbarIdentity;
window.updateCurrentIdentity = updateCurrentIdentity;
window.currentDisplayName = currentDisplayName;
