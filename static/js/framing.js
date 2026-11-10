/**
 * Framing simulator - "what does my sensor see on this target?"
 *
 * Fetches GET /api/skytonight/framing and draws, on a canvas, a real image of the sky
 * around a target (DSS2, served by our own server) with the sensor rectangle of one to
 * three equipment combinations on top. The frame can be rotated and dragged, and the
 * view exported as a PNG. Opened from the SkyTonight DSO table, the Wishlist and an
 * Astrodex item detail. Deep-sky (fixed-coordinate) targets only.
 *
 * Geometry: the background is a gnomonic (TAN) projection centred on the target, north
 * up and east left. A camera sensor is a gnomonic projection too, so a frame is an exact
 * rectangle on the image. Everything is kept in tangent-plane units (tan of an angle):
 * the API gives each frame's half extent that way, and the frame offset is stored that
 * way, so changing the background field of view never moves anything on the sky.
 */

/* global DOMUtils, i18n, fetchJSON, API_BASE, appUrl, openModal */

const FRAMING_MODAL_ID = 'modal_xl_close';
const FRAMING_MAX_SELECTED = 3;
// The background is this many times wider than the widest selected frame, so there is
// room to rotate and move it.
const FRAMING_BACKGROUND_MARGIN = 2.2;
const FRAMING_EXPORT_FOOTER_PX = 96;
const FRAMING_FALLBACK_COLORS = ['#ffd43b', '#4dabf7', '#ff8787'];

/**
 * Translate helper with an English fallback so the simulator still renders if a key
 * is missing in the active language.
 * @param {string} key
 * @param {string} fallback
 * @param {Object} [params]
 * @returns {string}
 */
function _frT(key, fallback, params) {
    if (typeof i18n !== 'undefined' && i18n.has(key)) {
        return i18n.t(key, params || {});
    }
    let text = fallback;
    if (params) {
        Object.keys(params).forEach((name) => {
            text = text.replace(new RegExp(`\\{${name}\\}`, 'g'), params[name]);
        });
    }
    return text;
}

function _frRad(degrees) {
    return (degrees * Math.PI) / 180;
}

function _frDeg(radians) {
    return (radians * 180) / Math.PI;
}

/** @returns {number} full diagonal field of a frame, in degrees */
function _frDiagonalDeg(frame) {
    return 2 * _frDeg(Math.atan(Math.hypot(frame.half_width_tan, frame.half_height_tan)));
}

/**
 * Format a number with a sensible number of decimals for its magnitude.
 * @param {number} value
 * @returns {string}
 */
function _frNumber(value) {
    const abs = Math.abs(value);
    const digits = abs >= 10 ? 1 : 2;
    return Number(value.toFixed(digits)).toString();
}

/**
 * Right ascension in degrees to "00h 42m 44s".
 * @param {number} raDeg
 * @returns {string}
 */
function _frFormatRa(raDeg) {
    let totalSeconds = Math.round((((raDeg % 360) + 360) % 360) * 240);
    if (totalSeconds >= 86400) totalSeconds -= 86400;
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(h)}h ${pad(m)}m ${pad(s)}s`;
}

/**
 * Declination in degrees to "+41° 16' 08\"".
 * @param {number} decDeg
 * @returns {string}
 */
function _frFormatDec(decDeg) {
    const sign = decDeg < 0 ? '-' : '+';
    const totalSeconds = Math.round(Math.abs(decDeg) * 3600);
    const d = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const pad = (n) => String(n).padStart(2, '0');
    return `${sign}${pad(d)}° ${pad(m)}' ${pad(s)}"`;
}

/**
 * Inverse gnomonic projection: tangent-plane offset from the target to sky coordinates.
 * @param {number} raDeg - target right ascension
 * @param {number} decDeg - target declination
 * @param {number} xi - offset towards east, in tangent units
 * @param {number} eta - offset towards north, in tangent units
 * @returns {{ra: number, dec: number}} degrees
 */
function _frOffsetToSky(raDeg, decDeg, xi, eta) {
    const rho = Math.hypot(xi, eta);
    if (rho === 0) return { ra: raDeg, dec: decDeg };
    const c = Math.atan(rho);
    const dec0 = _frRad(decDeg);
    const dec = Math.asin(Math.cos(c) * Math.sin(dec0) + (eta * Math.sin(c) * Math.cos(dec0)) / rho);
    const ra =
        _frRad(raDeg) +
        Math.atan2(xi * Math.sin(c), rho * Math.cos(dec0) * Math.cos(c) - eta * Math.sin(dec0) * Math.sin(c));
    return { ra: ((_frDeg(ra) % 360) + 360) % 360, dec: _frDeg(dec) };
}

/**
 * Pick the background field of view: the smallest allowed step that leaves room around
 * the widest selected frame (or around the target when no frame is selected).
 * @param {number[]} ladder - allowed fields of view, ascending, degrees
 * @param {Object[]} selectedFrames
 * @param {number|null} sizeArcmin - target apparent size
 * @returns {number} degrees
 */
function _frPickBackgroundFov(ladder, selectedFrames, sizeArcmin) {
    const sizeDeg = sizeArcmin ? sizeArcmin / 60 : 0;
    let needed;
    if (selectedFrames.length) {
        const widest = Math.max(...selectedFrames.map(_frDiagonalDeg));
        needed = Math.max(widest * FRAMING_BACKGROUND_MARGIN, sizeDeg * 1.5);
    } else {
        needed = sizeDeg ? sizeDeg * 3 : 1;
    }
    const step = ladder.find((fov) => fov >= needed);
    return step !== undefined ? step : ladder[ladder.length - 1];
}

/**
 * Choose the frame selected when the simulator opens: the caller's own combination when
 * it can be framed (Plan My Night passes the plan's), else the best fit the server picked.
 * @param {Object} data - GET /api/skytonight/framing payload
 * @param {string|null} preferredId - combination id asked for by the caller
 * @returns {Object|null}
 */
function _frDefaultFrame(data, preferredId) {
    const frames = data.frames || [];
    const byId = (id) => (id ? frames.find((frame) => frame.combination_id === id) : undefined);
    return byId(preferredId) || byId(data.default_combination_id) || frames[0] || null;
}

/**
 * Verdict sentence of one frame.
 * @param {Object} frame
 * @returns {string}
 */
function _frVerdictText(frame) {
    const percent = frame.fill_ratio !== null && frame.fill_ratio !== undefined ? Math.round(frame.fill_ratio * 100) : 0;
    switch (frame.verdict) {
        case 'good':
            return _frT('framing.verdict_good', "Good fit: the target fills {percent}% of the field's short side.", {
                percent,
            });
        case 'tight':
            return _frT(
                'framing.verdict_tight',
                "Tight fit: the target fills {percent}% of the field's short side, with little margin.",
                { percent }
            );
        case 'too_large':
            return _frT(
                'framing.verdict_too_large',
                "Larger than the field ({percent}% of its short side). A mosaic of about {columns} x {rows} panels would cover it (estimated from the target's longest dimension).",
                { percent, columns: frame.mosaic_columns, rows: frame.mosaic_rows }
            );
        case 'small':
            return _frT(
                'framing.verdict_small',
                "Small in the field ({percent}% of its short side): about {pixels} px across on the sensor.",
                { percent, pixels: frame.target_size_px }
            );
        default:
            return _frT('framing.verdict_unknown', 'The catalogue gives no size for this target.');
    }
}

/**
 * Fetch the framing data of a target and render the simulator into a container.
 * @param {string} identifier - catalogue id or name
 * @param {HTMLElement} containerEl
 * @param {Object} [options]
 * @param {string} [options.combinationId] - combination to select on opening, when it can be framed
 * @returns {Promise<Function>} a teardown function releasing the simulator's listeners
 */
async function renderFramingInto(identifier, containerEl, options = {}) {
    const id = (identifier || '').trim();
    if (!id || !containerEl) return () => {};

    DOMUtils.clear(containerEl);
    containerEl.appendChild(DOMUtils.createSpinnerWrapper(_frT('common.loading', 'Loading...')));

    let data;
    try {
        const params = new URLSearchParams({ target: id });
        data = await fetchJSON(`${API_BASE}/api/skytonight/framing?${params.toString()}`);
        if (data && data.error) throw new Error(data.error);
    } catch (err) {
        console.error('Failed to load framing data:', err);
        DOMUtils.clear(containerEl);
        containerEl.appendChild(_frAlert('danger', _frT('framing.error', 'Failed to load the framing simulator.')));
        return () => {};
    }

    DOMUtils.clear(containerEl);
    if (!data.supported) {
        const key = data.reason === 'moving_target' ? 'framing.unsupported_moving' : 'framing.unsupported_not_found';
        const fallback =
            data.reason === 'moving_target'
                ? 'This is a solar-system body or comet - it moves against the stars, so a fixed sky image does not apply.'
                : 'Could not resolve coordinates for this target.';
        containerEl.appendChild(_frAlert('info', _frT(key, fallback)));
        return () => {};
    }
    return _frBuildSimulator(data, containerEl, options.combinationId || null);
}

/**
 * Open the framing simulator in the shared modal_xl_close shell.
 * @param {string} identifier - catalogue id or name
 * @param {Object} [options]
 * @param {string} [options.combinationId] - combination to select on opening, when it can be framed
 */
async function openFraming(identifier, options = {}) {
    const id = (identifier || '').trim();
    if (!id) return;

    const modalEl = document.getElementById(FRAMING_MODAL_ID);
    const titleEl = document.getElementById(`${FRAMING_MODAL_ID}_title`);
    const bodyEl = document.getElementById(`${FRAMING_MODAL_ID}_body`);
    if (!modalEl || !titleEl || !bodyEl) return;

    titleEl.textContent = `${id} - ${_frT('framing.title', 'Framing')}`;

    let teardown = () => {};
    let closed = false;
    openModal(modalEl, {
        backdrop: true,
        onHidden: () => {
            closed = true;
            teardown();
        },
    });

    teardown = await renderFramingInto(id, bodyEl, options);
    if (closed) teardown();
}

function _frAlert(level, text) {
    const alert = document.createElement('div');
    alert.className = `alert alert-${level} mb-0`;
    alert.textContent = text;
    return alert;
}

/**
 * Build the simulator (canvas + controls) from an API payload.
 * @param {Object} data - GET /api/skytonight/framing payload (supported)
 * @param {HTMLElement} containerEl
 * @param {string|null} preferredId - combination to select on opening, when it can be framed
 * @returns {Function} teardown
 */
function _frBuildSimulator(data, containerEl, preferredId) {
    const size = data.image.size_px;
    const frames = data.frames || [];
    const state = {
        selectedIds: [],
        rotationDeg: 0,
        offsetXi: 0, // towards east, tangent units
        offsetEta: 0, // towards north, tangent units
        backgroundFov: null,
        image: null,
        imageToken: 0,
        imageFailed: false,
        colors: FRAMING_FALLBACK_COLORS.slice(),
    };
    const defaultFrame = _frDefaultFrame(data, preferredId);
    if (defaultFrame) state.selectedIds.push(defaultFrame.combination_id);

    const selectedFrames = () => frames.filter((frame) => state.selectedIds.includes(frame.combination_id));
    const colorOf = (frame) => state.colors[state.selectedIds.indexOf(frame.combination_id) % state.colors.length];

    // ── Layout ───────────────────────────────────────────────────────────────
    const root = document.createElement('div');
    root.className = 'framing-root';

    const heading = document.createElement('p');
    heading.className = 'framing-target mb-2';
    const targetName = document.createElement('strong');
    targetName.textContent = data.target.name;
    heading.appendChild(targetName);
    const targetMeta = [];
    if (data.target.object_type) targetMeta.push(data.target.object_type);
    targetMeta.push(
        data.target.size_arcmin
            ? _frT('framing.target_size', "apparent size {size}'", { size: _frNumber(data.target.size_arcmin) })
            : _frT('framing.size_unknown', 'apparent size unknown')
    );
    targetMeta.push(`${_frFormatRa(data.target.ra_deg)}, ${_frFormatDec(data.target.dec_deg)}`);
    heading.appendChild(document.createTextNode(` - ${targetMeta.join(' - ')}`));
    root.appendChild(heading);

    const row = document.createElement('div');
    row.className = 'row g-3';
    root.appendChild(row);

    const stageCol = document.createElement('div');
    stageCol.className = 'col-12 col-lg-7';
    row.appendChild(stageCol);
    const sideCol = document.createElement('div');
    sideCol.className = 'col-12 col-lg-5';
    row.appendChild(sideCol);

    // ── Stage: canvas + status ───────────────────────────────────────────────
    const stage = document.createElement('div');
    stage.className = 'framing-stage';
    const canvas = document.createElement('canvas');
    canvas.className = 'framing-canvas';
    canvas.width = size;
    canvas.height = size;
    canvas.tabIndex = 0;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute(
        'aria-label',
        _frT(
            'framing.canvas_label',
            'Sky around {name} with the sensor frame. Drag, or use the arrow keys, to move the frame.',
            { name: data.target.name }
        )
    );
    stage.appendChild(canvas);
    const stageStatus = document.createElement('div');
    stageStatus.className = 'framing-stage-status';
    stage.appendChild(stageStatus);
    stageCol.appendChild(stage);

    const caption = document.createElement('p');
    caption.className = 'framing-caption small text-muted mt-2 mb-0';
    stageCol.appendChild(caption);

    // ── Side: combinations, controls, verdicts ───────────────────────────────
    const combosTitle = document.createElement('h6');
    combosTitle.textContent = _frT('framing.combinations_label', 'Equipment combinations');
    sideCol.appendChild(combosTitle);

    const combosList = document.createElement('div');
    combosList.className = 'framing-combos mb-3';
    sideCol.appendChild(combosList);

    const swatches = [];
    for (let index = 0; index < FRAMING_MAX_SELECTED; index += 1) {
        // Hidden probes: the frame colours live in CSS (.framing-swatch-N), the canvas reads them from here.
        const probe = document.createElement('span');
        probe.className = `framing-swatch framing-swatch-${index} d-none`;
        combosList.appendChild(probe);
        swatches.push(probe);
    }

    if (!frames.length) {
        const message = data.has_combinations
            ? _frT(
                'framing.no_frameable_combinations',
                'None of your equipment combinations has both a camera sensor and a focal length. Complete one in the Equipment tab to see your field here.'
            )
            : _frT(
                'framing.no_combinations',
                'Add an equipment combination with a camera in the Equipment tab to see your field here.'
            );
        combosList.appendChild(_frAlert('info', message));
    }

    const checkboxes = [];
    frames.forEach((frame, index) => {
        const item = document.createElement('div');
        item.className = 'form-check framing-combo';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'form-check-input';
        input.id = `framing-combo-${index}-${Math.random().toString(36).slice(2, 8)}`;
        input.checked = state.selectedIds.includes(frame.combination_id);
        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.htmlFor = input.id;
        const swatch = document.createElement('span');
        swatch.className = 'framing-swatch';
        const name = document.createElement('span');
        name.textContent = frame.combination_name;
        const field = document.createElement('span');
        field.className = 'framing-combo-field text-muted small';
        field.textContent = `${_frNumber(frame.fov_h_deg)}° x ${_frNumber(frame.fov_v_deg)}°`;
        DOMUtils.append(label, swatch, name, field);
        DOMUtils.append(item, input, label);
        combosList.appendChild(item);
        checkboxes.push({ frame, input, swatch });

        input.addEventListener('change', () => {
            if (input.checked) {
                state.selectedIds.push(frame.combination_id);
            } else {
                state.selectedIds = state.selectedIds.filter((id) => id !== frame.combination_id);
            }
            refresh();
        });
    });

    const maxNote = document.createElement('p');
    maxNote.className = 'small text-muted mb-3';
    maxNote.textContent = _frT('framing.max_selected', 'Up to {max} combinations can be compared.', {
        max: FRAMING_MAX_SELECTED,
    });
    if (frames.length > 1) sideCol.appendChild(maxNote);

    const rotationGroup = document.createElement('div');
    rotationGroup.className = 'mb-3';
    const rotationLabel = document.createElement('label');
    rotationLabel.className = 'form-label mb-1';
    const rotationInput = document.createElement('input');
    rotationInput.type = 'range';
    rotationInput.className = 'form-range';
    rotationInput.min = '0';
    rotationInput.max = '179';
    rotationInput.step = '1';
    rotationInput.value = '0';
    rotationInput.id = `framing-rotation-${Math.random().toString(36).slice(2, 8)}`;
    rotationLabel.htmlFor = rotationInput.id;
    DOMUtils.append(rotationGroup, rotationLabel, rotationInput);
    sideCol.appendChild(rotationGroup);
    rotationInput.addEventListener('input', () => {
        state.rotationDeg = Number(rotationInput.value) || 0;
        refresh();
    });

    const centreLine = document.createElement('p');
    centreLine.className = 'small mb-2';
    sideCol.appendChild(centreLine);

    const buttons = document.createElement('div');
    buttons.className = 'd-flex flex-wrap gap-2 mb-3';
    const recentreBtn = document.createElement('button');
    recentreBtn.type = 'button';
    recentreBtn.className = 'btn btn-sm btn-outline-secondary';
    DOMUtils.append(
        recentreBtn,
        DOMUtils.createIcon('bi bi-bullseye icon-inline'),
        ` ${_frT('framing.recentre', 'Centre on target')}`
    );
    const downloadBtn = document.createElement('button');
    downloadBtn.type = 'button';
    downloadBtn.className = 'btn btn-sm btn-primary';
    DOMUtils.append(
        downloadBtn,
        DOMUtils.createIcon('bi bi-download icon-inline'),
        ` ${_frT('framing.download', 'Download image')}`
    );
    DOMUtils.append(buttons, recentreBtn, downloadBtn);
    sideCol.appendChild(buttons);

    const verdicts = document.createElement('div');
    verdicts.className = 'framing-verdicts';
    sideCol.appendChild(verdicts);

    containerEl.appendChild(root);

    // The swatch colours are only computed once the probes are in the document.
    state.colors = swatches.map((probe, index) => {
        const color = window.getComputedStyle(probe).backgroundColor;
        return color && color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent' ? color : FRAMING_FALLBACK_COLORS[index];
    });

    // ── Drawing ──────────────────────────────────────────────────────────────
    const ctx = canvas.getContext('2d');

    function draw() {
        const half = size / 2;
        const tanHalf = Math.tan(_frRad(state.backgroundFov / 2));
        const scale = half / tanHalf; // canvas pixels per tangent unit

        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.fillStyle = '#05070d';
        ctx.fillRect(0, 0, size, size);
        if (state.image) ctx.drawImage(state.image, 0, 0, size, size);

        // Target extent (dashed circle) and position (cross).
        ctx.lineWidth = 2;
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.75)';
        if (data.target.size_arcmin) {
            const radius = Math.tan(_frRad(data.target.size_arcmin / 120)) * scale;
            ctx.setLineDash([10, 8]);
            ctx.beginPath();
            ctx.arc(half, half, radius, 0, 2 * Math.PI);
            ctx.stroke();
            ctx.setLineDash([]);
        }
        ctx.beginPath();
        ctx.moveTo(half - 12, half);
        ctx.lineTo(half + 12, half);
        ctx.moveTo(half, half - 12);
        ctx.lineTo(half, half + 12);
        ctx.stroke();

        // Frames. East is left on the image, so a positive xi moves the frame to the left;
        // the position angle runs from north through east, i.e. counter-clockwise here.
        const centreX = half - state.offsetXi * scale;
        const centreY = half - state.offsetEta * scale;
        selectedFrames().forEach((frame) => {
            const halfWidth = frame.half_width_tan * scale;
            const halfHeight = frame.half_height_tan * scale;
            ctx.save();
            ctx.translate(centreX, centreY);
            ctx.rotate(-_frRad(state.rotationDeg));
            ctx.strokeStyle = colorOf(frame);
            ctx.lineWidth = 4;
            ctx.strokeRect(-halfWidth, -halfHeight, 2 * halfWidth, 2 * halfHeight);
            // A tick on the top edge shows which side of the sensor is up.
            ctx.beginPath();
            ctx.moveTo(0, -halfHeight);
            ctx.lineTo(0, -halfHeight - Math.min(24, halfHeight * 0.25));
            ctx.stroke();
            ctx.restore();
        });
    }

    function loadBackground(fov) {
        state.backgroundFov = fov;
        state.image = null;
        state.imageFailed = false;
        state.imageToken += 1;
        const token = state.imageToken;
        setStageStatus(_frT('framing.loading_image', 'Loading the sky image...'), false);

        const image = new Image();
        image.onload = () => {
            if (token !== state.imageToken) return;
            state.image = image;
            setStageStatus('', false);
            draw();
        };
        image.onerror = () => {
            if (token !== state.imageToken) return;
            state.imageFailed = true;
            setStageStatus(
                _frT('framing.image_unavailable', 'The sky image is unavailable for now. The frame is still to scale.'),
                true
            );
            draw();
        };
        image.src = appUrl(`/api/skytonight/framing/image/${data.image.key}_${fov.toFixed(2)}.jpg`);
    }

    function setStageStatus(text, isWarning) {
        stageStatus.textContent = text;
        stageStatus.classList.toggle('d-none', !text);
        stageStatus.classList.toggle('framing-stage-status--warning', Boolean(isWarning));
    }

    function refresh() {
        // Selection: enforce the maximum and paint the swatches.
        const full = state.selectedIds.length >= FRAMING_MAX_SELECTED;
        checkboxes.forEach(({ frame, input, swatch }) => {
            const position = state.selectedIds.indexOf(frame.combination_id);
            input.disabled = full && position === -1;
            swatch.className = position === -1 ? 'framing-swatch framing-swatch-off' : `framing-swatch framing-swatch-${position}`;
        });

        const selected = selectedFrames();
        rotationInput.disabled = !selected.length;
        rotationLabel.textContent = _frT('framing.rotation_label', 'Sensor rotation: {deg}°', {
            deg: state.rotationDeg,
        });

        const moved = state.offsetXi !== 0 || state.offsetEta !== 0;
        recentreBtn.disabled = !moved;
        const centre = _frOffsetToSky(data.target.ra_deg, data.target.dec_deg, state.offsetXi, state.offsetEta);
        centreLine.textContent = selected.length
            ? _frT('framing.centre_label', 'Frame centre: {ra}, {dec}', {
                ra: _frFormatRa(centre.ra),
                dec: _frFormatDec(centre.dec),
            })
            : '';

        // Verdicts.
        DOMUtils.clear(verdicts);
        selected.forEach((frame) => {
            const card = document.createElement('div');
            card.className = 'framing-verdict';
            const head = document.createElement('div');
            head.className = 'framing-verdict-head';
            const swatch = document.createElement('span');
            swatch.className = `framing-swatch framing-swatch-${state.selectedIds.indexOf(frame.combination_id)}`;
            const name = document.createElement('strong');
            name.textContent = frame.combination_name;
            DOMUtils.append(head, swatch, name);
            const summary = document.createElement('div');
            summary.className = 'small text-muted';
            summary.textContent = _frT(
                'framing.frame_summary',
                'Field {w}° x {h}°, {scale}"/px, {focal} mm focal length',
                {
                    w: _frNumber(frame.fov_h_deg),
                    h: _frNumber(frame.fov_v_deg),
                    scale: _frNumber(frame.image_scale_arcsec_per_px),
                    focal: _frNumber(frame.focal_length_mm),
                }
            );
            const verdict = document.createElement('div');
            verdict.className = `framing-verdict-text framing-verdict-text--${frame.verdict}`;
            verdict.textContent = _frVerdictText(frame);
            DOMUtils.append(card, head, summary, verdict);
            verdicts.appendChild(card);
        });

        // Background: reload only when the needed field of view changes.
        const fov = _frPickBackgroundFov(data.image.fovs_deg, selected, data.target.size_arcmin);
        const widest = selected.length ? Math.max(...selected.map(_frDiagonalDeg)) : 0;
        const captionParts = [
            _frT('framing.orientation', 'North up, east left'),
            _frT('framing.background_field', 'background {fov}° wide', { fov: _frNumber(fov) }),
            _frT('framing.credit', 'sky image: {credit}', { credit: data.image.credit }),
        ];
        if (widest > fov) {
            captionParts.push(
                _frT('framing.wider_than_preview', 'the frame is wider than the largest available background')
            );
        }
        caption.textContent = captionParts.join(' - ');

        if (fov !== state.backgroundFov) {
            loadBackground(fov);
        }
        draw();
    }

    // ── Interaction: drag and keyboard ───────────────────────────────────────
    function moveBy(deltaCanvasX, deltaCanvasY) {
        if (!selectedFrames().length) return;
        const tanHalf = Math.tan(_frRad(state.backgroundFov / 2));
        const perPixel = tanHalf / (size / 2);
        const clamp = (value) => Math.max(-tanHalf, Math.min(tanHalf, value));
        state.offsetXi = clamp(state.offsetXi - deltaCanvasX * perPixel);
        state.offsetEta = clamp(state.offsetEta - deltaCanvasY * perPixel);
        refresh();
    }

    let drag = null;
    const onPointerDown = (event) => {
        if (!selectedFrames().length) return;
        drag = { x: event.clientX, y: event.clientY };
        canvas.setPointerCapture(event.pointerId);
        canvas.classList.add('framing-canvas--dragging');
    };
    const onPointerMove = (event) => {
        if (!drag) return;
        const ratio = size / canvas.getBoundingClientRect().width;
        moveBy((event.clientX - drag.x) * ratio, (event.clientY - drag.y) * ratio);
        drag = { x: event.clientX, y: event.clientY };
    };
    const onPointerUp = (event) => {
        if (!drag) return;
        drag = null;
        canvas.classList.remove('framing-canvas--dragging');
        if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    };
    const onKeyDown = (event) => {
        const step = event.shiftKey ? 50 : 10;
        const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
        const move = moves[event.key];
        if (!move) return;
        event.preventDefault();
        moveBy(move[0], move[1]);
    };
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointercancel', onPointerUp);
    canvas.addEventListener('keydown', onKeyDown);

    recentreBtn.addEventListener('click', () => {
        state.offsetXi = 0;
        state.offsetEta = 0;
        refresh();
    });

    downloadBtn.addEventListener('click', () => {
        _frDownload(canvas, data, selectedFrames(), colorOf);
    });

    refresh();

    return () => {
        state.imageToken += 1; // drop any image still loading
        canvas.removeEventListener('pointerdown', onPointerDown);
        canvas.removeEventListener('pointermove', onPointerMove);
        canvas.removeEventListener('pointerup', onPointerUp);
        canvas.removeEventListener('pointercancel', onPointerUp);
        canvas.removeEventListener('keydown', onKeyDown);
    };
}

/**
 * Export the current view as a PNG: the canvas plus a footer naming the target, the
 * combinations and the image credit.
 * @param {HTMLCanvasElement} canvas
 * @param {Object} data
 * @param {Object[]} selected
 * @param {Function} colorOf
 */
function _frDownload(canvas, data, selected, colorOf) {
    const size = canvas.width;
    const output = document.createElement('canvas');
    output.width = size;
    output.height = size + FRAMING_EXPORT_FOOTER_PX;
    const ctx = output.getContext('2d');
    ctx.drawImage(canvas, 0, 0);

    ctx.fillStyle = '#0b1020';
    ctx.fillRect(0, size, size, FRAMING_EXPORT_FOOTER_PX);
    const fontFamily = window.getComputedStyle(document.body).fontFamily || 'sans-serif';
    ctx.textBaseline = 'middle';

    ctx.fillStyle = '#ffffff';
    ctx.font = `600 28px ${fontFamily}`;
    ctx.fillText(data.target.name, 24, size + 32, size - 48);

    // Combination names, each preceded by its frame colour.
    ctx.font = `20px ${fontFamily}`;
    let x = 24;
    const y = size + 70;
    selected.forEach((frame) => {
        const label = `${frame.combination_name} (${_frNumber(frame.fov_h_deg)}° x ${_frNumber(frame.fov_v_deg)}°)`;
        const width = ctx.measureText(label).width;
        if (x + 28 + width > size - 24) return;
        ctx.fillStyle = colorOf(frame);
        ctx.fillRect(x, y - 8, 16, 16);
        ctx.fillStyle = '#d0d7e2';
        ctx.fillText(label, x + 24, y);
        x += 24 + width + 28;
    });

    ctx.textAlign = 'right';
    ctx.fillStyle = '#8b96a8';
    ctx.font = `16px ${fontFamily}`;
    ctx.fillText(`${data.image.credit} - myastroboard.org`, size - 24, size + 32);

    output.toBlob((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        const slug = String(data.target.name || 'target')
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '');
        link.download = `framing-${slug || 'target'}.png`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }, 'image/png');
}
