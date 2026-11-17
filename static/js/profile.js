/**
 * My settings -> Profile, and the "How others see me" step of the first-run wizard.
 *
 * One editor, two places: buildProfileEditor() renders the display name, the picture and
 * the Community choices into any container and returns a handle to read and save them.
 * The picture is uploaded as soon as it is picked (its own route); the rest is saved by
 * the Save button here, or by the wizard's Next button.
 *
 * Private by default: until "Join the Community" is on, the others only see the display
 * name and picture where a name was already shown (shared pictures and equipment).
 */

/* global DOMUtils, i18n, fetchJSON, fetchWithRetry, appUrl, buildUserAvatar, updateCurrentIdentity,
   localizeApiError, setAlertMessage, switchMainTab, switchSubTab, openCommunityProfile,
   refreshCommunityAvailability */

const PROFILE_BLOCKS = ['stats', 'badges', 'pictures', 'equipment', 'activity'];

const profileState = {
    data: null,
    editor: null,
    listenersBound: false,
};

function _pfT(key, fallback, params) {
    if (typeof i18n === 'undefined' || typeof i18n.t !== 'function') return fallback;
    const translated = i18n.t(key, params);
    return translated && translated !== key ? translated : fallback;
}

/** GET /api/profile (cached in profileState.data). */
async function fetchOwnProfile() {
    const data = await fetchJSON('/api/profile');
    profileState.data = data;
    return data;
}

function _pfErrorText(error, fallbackKey) {
    const data = error?.data || null;
    return typeof localizeApiError === 'function'
        ? localizeApiError(data, fallbackKey)
        : (data?.error || _pfT(fallbackKey, 'Error'));
}

function _pfSwitch(id, labelText, helpText, checked) {
    const wrapper = document.createElement('div');
    wrapper.className = 'form-check form-switch profile-switch';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.className = 'form-check-input';
    input.id = id;
    input.setAttribute('role', 'switch');
    input.checked = !!checked;
    const label = document.createElement('label');
    label.className = 'form-check-label';
    label.setAttribute('for', id);
    label.textContent = labelText;
    wrapper.append(input, label);
    if (helpText) {
        const help = document.createElement('div');
        help.className = 'form-text';
        help.textContent = helpText;
        wrapper.appendChild(help);
    }
    return { wrapper, input };
}

/**
 * Render the editor into container. options.mode: 'settings' (bio, save and preview buttons)
 * or 'wizard' (compact, saved by the wizard). Returns { collect, save, setMessage }.
 */
function buildProfileEditor(container, data, options = {}) {
    const mode = options.mode || 'settings';
    const prefix = mode === 'wizard' ? 'wizard-profile' : 'profile';
    const profile = data.profile || {};
    const community = profile.community || {};
    DOMUtils.clear(container);

    const root = document.createElement('div');
    root.className = `profile-editor profile-editor-${mode}`;

    // ── Identity: picture and name ─────────────────────────────────────────
    const identity = document.createElement('div');
    identity.className = 'profile-identity';

    const avatarColumn = document.createElement('div');
    avatarColumn.className = 'profile-avatar-column';
    const avatar = buildUserAvatar(data.identity, 'lg', _pfT('profile.avatar_alt', 'Your profile picture'));
    avatar.loading = 'eager';
    avatarColumn.appendChild(avatar);

    const avatarButtons = document.createElement('div');
    avatarButtons.className = 'profile-avatar-buttons';
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.id = `${prefix}-avatar-input`;
    fileInput.accept = 'image/png,image/jpeg,image/webp,image/gif';
    fileInput.className = 'visually-hidden';
    const pickLabel = document.createElement('label');
    pickLabel.className = 'btn btn-outline-primary btn-sm';
    pickLabel.setAttribute('for', fileInput.id);
    DOMUtils.append(pickLabel, DOMUtils.createIcon('bi bi-camera icon-inline'), ` ${_pfT('profile.avatar_change', 'Change picture')}`);
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'btn btn-outline-secondary btn-sm';
    DOMUtils.append(removeButton, DOMUtils.createIcon('bi bi-x-circle icon-inline'), ` ${_pfT('profile.avatar_remove', 'Remove')}`);
    removeButton.classList.toggle('d-none', !data.identity?.has_avatar);
    avatarButtons.append(fileInput, pickLabel, removeButton);
    avatarColumn.appendChild(avatarButtons);
    const avatarHint = document.createElement('div');
    avatarHint.className = 'form-text';
    avatarHint.textContent = _pfT('profile.avatar_hint', 'Cropped to a square. Location and camera details are removed from the picture.');
    avatarColumn.appendChild(avatarHint);
    identity.appendChild(avatarColumn);

    const fields = document.createElement('div');
    fields.className = 'profile-fields';
    const nameLabel = document.createElement('label');
    nameLabel.className = 'form-label';
    nameLabel.setAttribute('for', `${prefix}-display-name`);
    nameLabel.textContent = _pfT('profile.display_name', 'Display name');
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'form-control';
    nameInput.id = `${prefix}-display-name`;
    nameInput.maxLength = data.limits?.display_name || 40;
    nameInput.placeholder = data.username || '';
    nameInput.value = profile.display_name || '';
    nameInput.autocomplete = 'nickname';
    const nameHelp = document.createElement('div');
    nameHelp.className = 'form-text';
    nameHelp.textContent = _pfT(
        'profile.display_name_help',
        'Shown instead of your login name wherever the others see you. Your login name does not change.',
        { username: data.username || '' }
    );
    fields.append(nameLabel, nameInput, nameHelp);

    let bioInput = null;
    if (mode === 'settings') {
        const bioLabel = document.createElement('label');
        bioLabel.className = 'form-label mt-3';
        bioLabel.setAttribute('for', `${prefix}-bio`);
        bioLabel.textContent = _pfT('profile.bio', 'About me');
        bioInput = document.createElement('textarea');
        bioInput.className = 'form-control';
        bioInput.id = `${prefix}-bio`;
        bioInput.rows = 3;
        bioInput.maxLength = data.limits?.bio || 280;
        bioInput.placeholder = _pfT('profile.bio_placeholder', 'Your sky, your gear, what you like to image...');
        bioInput.value = profile.bio || '';
        const bioCounter = document.createElement('div');
        bioCounter.className = 'form-text text-end';
        const updateCounter = () => {
            bioCounter.textContent = `${bioInput.value.length} / ${bioInput.maxLength}`;
        };
        bioInput.addEventListener('input', updateCounter);
        updateCounter();
        fields.append(bioLabel, bioInput, bioCounter);
    }
    identity.appendChild(fields);
    root.appendChild(identity);

    // ── Community choices ──────────────────────────────────────────────────
    const blockInputs = {};
    let listedInput = null;
    if (data.community_enabled) {
        const section = document.createElement('div');
        section.className = 'profile-community';
        const heading = document.createElement('h3');
        heading.className = 'h5 profile-community-title';
        DOMUtils.append(heading, DOMUtils.createIcon('bi bi-people-fill text-info icon-inline'), ` ${_pfT('profile.community_title', 'Community')}`);
        section.appendChild(heading);

        const listed = _pfSwitch(
            `${prefix}-listed`,
            _pfT('profile.join', 'Join the Community'),
            _pfT('profile.join_help', 'Appear in the member directory, with the parts of your profile chosen below. You can leave at any time.'),
            community.listed
        );
        listedInput = listed.input;
        section.appendChild(listed.wrapper);

        const blocks = document.createElement('fieldset');
        blocks.className = 'profile-blocks';
        const legend = document.createElement('legend');
        legend.className = 'form-label profile-blocks-legend';
        legend.textContent = _pfT('profile.blocks_legend', 'What the members see');
        blocks.appendChild(legend);
        PROFILE_BLOCKS.forEach((block) => {
            let help = _pfT(`profile.block_${block}_help`, '');
            const disabled = block === 'pictures' && data.pictures_shared === false;
            if (disabled) help = _pfT('profile.block_pictures_private', 'The administrator keeps every Astrodex private: pictures are never shown.');
            const entry = _pfSwitch(
                `${prefix}-show-${block}`,
                _pfT(`profile.block_${block}`, block),
                help,
                community[`show_${block}`]
            );
            entry.input.disabled = disabled;
            blockInputs[block] = entry.input;
            blocks.appendChild(entry.wrapper);
        });
        section.appendChild(blocks);
        const syncBlocks = () => blocks.classList.toggle('is-off', !listedInput.checked);
        listedInput.addEventListener('change', syncBlocks);
        syncBlocks();

        const promise = document.createElement('div');
        promise.className = 'small text-muted profile-promise';
        DOMUtils.append(
            promise,
            DOMUtils.createIcon('bi bi-shield-check icon-inline'),
            ` ${_pfT('profile.promise', 'No ranking, no position: your Observation Log, locations and notes are never shown.')}`
        );
        section.appendChild(promise);
        root.appendChild(section);
    }

    // ── Buttons (settings only) ────────────────────────────────────────────
    let saveButton = null;
    if (mode === 'settings') {
        const actions = document.createElement('div');
        actions.className = 'button-group mt-3 profile-actions';
        saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.className = 'btn btn-primary';
        DOMUtils.append(saveButton, DOMUtils.createIcon('bi bi-save icon-inline'), ` ${_pfT('profile.save', 'Save profile')}`);
        actions.appendChild(saveButton);
        if (data.community_enabled) {
            const previewButton = document.createElement('button');
            previewButton.type = 'button';
            previewButton.className = 'btn btn-outline-info';
            DOMUtils.append(previewButton, DOMUtils.createIcon('bi bi-eye icon-inline'), ` ${_pfT('profile.preview', 'See my profile as the others do')}`);
            previewButton.addEventListener('click', async () => {
                if (!(await handle.save())) return;
                if (typeof switchMainTab === 'function') switchMainTab('community');
                if (typeof switchSubTab === 'function') switchSubTab('community', 'community-members');
                if (typeof openCommunityProfile === 'function') openCommunityProfile(data.identity?.user_id);
            });
            actions.appendChild(previewButton);
        }
        root.appendChild(actions);
    }

    const message = document.createElement('div');
    message.className = 'alert mt-3 d-none';
    message.setAttribute('role', 'alert');
    root.appendChild(message);

    container.appendChild(root);

    const setMessage = (type, text) => {
        message.className = `alert mt-3 ${type === 'success' ? 'alert-success' : 'alert-danger'}`;
        message.textContent = text;
        if (!text) message.classList.add('d-none');
    };

    const applyIdentity = (payload) => {
        if (!payload) return;
        profileState.data = payload;
        data.identity = payload.identity;
        avatar.src = appUrl(payload.identity.avatar_url);
        removeButton.classList.toggle('d-none', !payload.identity.has_avatar);
        if (typeof updateCurrentIdentity === 'function') updateCurrentIdentity(payload.identity);
    };

    fileInput.addEventListener('change', async () => {
        const file = fileInput.files?.[0];
        fileInput.value = '';
        if (!file) return;
        if (data.limits?.avatar_bytes && file.size > data.limits.avatar_bytes) {
            setMessage('error', _pfT('profile.error_avatar_too_large', 'This picture is too large.'));
            return;
        }
        pickLabel.classList.add('disabled');
        try {
            const formData = new FormData();
            formData.append('file', file);
            const response = await fetchWithRetry('/api/profile/avatar', {
                method: 'POST',
                body: formData,
                credentials: 'include',
            }, { maxAttempts: 1, timeoutMs: 30000 });
            const payload = await response.json().catch(() => null);
            if (!response.ok) {
                setMessage('error', _pfErrorText({ data: payload }, 'profile.error_avatar_invalid'));
                return;
            }
            applyIdentity(payload);
            setMessage('success', _pfT('profile.avatar_saved', 'Picture updated.'));
        } catch (error) {
            console.error('Avatar upload failed:', error);
            setMessage('error', _pfT('profile.error_avatar_invalid', 'This picture could not be used.'));
        } finally {
            pickLabel.classList.remove('disabled');
        }
    });

    removeButton.addEventListener('click', async () => {
        try {
            applyIdentity(await fetchJSON('/api/profile/avatar', { method: 'DELETE' }));
            setMessage('success', _pfT('profile.avatar_removed', 'Picture removed.'));
        } catch (error) {
            setMessage('error', _pfErrorText(error, 'profile.error_save'));
        }
    });

    const handle = {
        collect() {
            const body = { display_name: nameInput.value.trim() || null };
            if (bioInput) body.bio = bioInput.value;
            if (listedInput) {
                body.community = { listed: listedInput.checked };
                PROFILE_BLOCKS.forEach((block) => {
                    if (!blockInputs[block].disabled) body.community[`show_${block}`] = blockInputs[block].checked;
                });
            }
            return body;
        },
        /** PUT the profile; true on success. The message is shown in the editor. */
        async save() {
            try {
                const payload = await fetchJSON('/api/profile', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(handle.collect()),
                });
                applyIdentity(payload);
                setMessage('success', _pfT('profile.saved', 'Profile saved.'));
                return true;
            } catch (error) {
                setMessage('error', _pfErrorText(error, 'profile.error_save'));
                return false;
            }
        },
        setMessage,
    };

    if (saveButton) {
        saveButton.addEventListener('click', async () => {
            saveButton.disabled = true;
            try {
                await handle.save();
            } finally {
                saveButton.disabled = false;
            }
        });
    }
    return handle;
}

/** My settings -> Profile sub-tab. */
async function loadProfileSettings() {
    const container = document.getElementById('profile-editor');
    if (!container) return;
    if (!profileState.listenersBound) {
        profileState.listenersBound = true;
        window.addEventListener('i18nLanguageChanged', () => {
            if (profileState.data && document.getElementById('profile-subtab')?.classList.contains('active')) {
                profileState.editor = buildProfileEditor(container, profileState.data, { mode: 'settings' });
            }
        });
    }
    DOMUtils.clear(container);
    container.appendChild(DOMUtils.createSpinnerWrapper(_pfT('common.loading', 'Loading...')));
    try {
        const data = await fetchOwnProfile();
        profileState.editor = buildProfileEditor(container, data, { mode: 'settings' });
    } catch (error) {
        console.error('Error loading the profile:', error);
        DOMUtils.clear(container);
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger';
        alert.textContent = _pfT('profile.error_load', 'Could not load your profile.');
        container.appendChild(alert);
    }
}

window.fetchOwnProfile = fetchOwnProfile;
window.buildProfileEditor = buildProfileEditor;
window.loadProfileSettings = loadProfileSettings;
