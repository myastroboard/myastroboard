/**
 * Share cards - a ready-to-post image made from data the application already holds.
 *
 * One engine draws every card on a canvas, in the browser: nothing is uploaded. A card is
 * described by a plain model (heading, optional picture, optional hero figure, facts,
 * list, paragraph); openShareCard() shows it in a modal with a preview, lets the user pick
 * the format (the shapes social networks show uncropped: 4:5, 1:1, 16:9, 9:16) and the
 * theme and drop any fact, then downloads the PNG or hands it to the system share sheet.
 *
 * Privacy: a model never carries coordinates or a location name. The callers below do
 * not pass them, and the engine has no field for them.
 *
 * Model:
 *   {
 *     title: string,                      modal title
 *     filename: string,                   download name, without extension
 *     kicker: string,                     small line above the heading ("Astrodex")
 *     heading: string,
 *     subheading?: string,
 *     imageUrl?: string,                  same-origin picture, drawn uncropped
 *     hero?: { value, unit?, label },     one large figure
 *     facts?: [{ id, label, value }],     each can be unchecked by the user
 *     list?: { title, items: string[] },
 *     paragraph?: string,
 *   }
 */

/* global DOMUtils, i18n, openModal, fetchJSON, appUrl */

const SHARE_MODAL_ID = 'modal_lg_close';
const SHARE_BRAND_NAME = 'MyAstroBoard';
const SHARE_BRAND_URL = 'myastroboard.org';
// The shapes the main image networks show without cropping. `hint` names where each one
// fits, as an i18n key.
const SHARE_FORMATS = {
    '4x5': { width: 1080, height: 1350, label: '4:5', hint: 'share.format_hint_4x5' },
    '1x1': { width: 1080, height: 1080, label: '1:1', hint: 'share.format_hint_1x1' },
    '16x9': { width: 1920, height: 1080, label: '16:9', hint: 'share.format_hint_16x9' },
    '9x16': { width: 1080, height: 1920, label: '9:16', hint: 'share.format_hint_9x16' },
};
const SHARE_DEFAULT_FORMAT = '4x5';
const SHARE_FORMAT_HINT_FALLBACKS = {
    '4x5': 'Feed post in portrait: Instagram, Facebook, Threads',
    '1x1': 'Square: accepted everywhere',
    '16x9': 'Landscape: X, Facebook, forums',
    '9x16': 'Full screen: stories and reels',
};
const SHARE_PALETTES = {
    dark: {
        background: ['#070b1a', '#131c3a'],
        stage: '#000000',
        text: '#ffffff',
        muted: '#9aa7bd',
        accent: '#ffd43b',
        rule: 'rgba(255, 255, 255, 0.16)',
        star: 'rgba(255, 255, 255, 0.85)',
    },
    light: {
        background: ['#f6f8fc', '#e6ebf5'],
        stage: '#0b1020',
        text: '#0f172a',
        muted: '#52607a',
        accent: '#9a6700',
        rule: 'rgba(15, 23, 42, 0.16)',
        star: 'rgba(15, 23, 42, 0)',
    },
};
const SHARE_MARGIN = 64;
const SHARE_MIN_IMAGE_HEIGHT = 380;
const SHARE_MAX_LIST_ITEMS = 6;
const SHARE_MAX_PARAGRAPH_LINES = 5;

// Number of share modals opened so far, used to build unique element ids.
let _shModalCount = 0;

/**
 * Translate helper with an English fallback so a card still renders if a key is missing
 * in the active language.
 * @param {string} key
 * @param {string} fallback
 * @param {Object} [params]
 * @returns {string}
 */
function _shT(key, fallback, params) {
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

/** @returns {string} the page's own font stack, so the card matches the application */
function _shFontFamily() {
    return window.getComputedStyle(document.body).fontFamily || 'sans-serif';
}

function _shFont(weight, size) {
    return `${weight} ${size}px ${_shFontFamily()}`;
}

/**
 * Break a text into lines no wider than maxWidth, for the font currently set on ctx.
 * A single word wider than the line is kept whole (the caller shrinks or clips it).
 * @param {CanvasRenderingContext2D} ctx
 * @param {string} text
 * @param {number} maxWidth
 * @returns {string[]}
 */
function _shWrap(ctx, text, maxWidth) {
    const words = String(text || '').split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    words.forEach((word) => {
        const candidate = line ? `${line} ${word}` : word;
        if (line && ctx.measureText(candidate).width > maxWidth) {
            lines.push(line);
            line = word;
        } else {
            line = candidate;
        }
    });
    if (line) lines.push(line);
    return lines;
}

/**
 * Wrap a text into at most maxLines; the last line ends with "..." when text is left over.
 * @returns {string[]}
 */
function _shWrapClamped(ctx, text, maxWidth, maxLines) {
    const lines = _shWrap(ctx, text, maxWidth);
    if (lines.length <= maxLines) return lines;
    const kept = lines.slice(0, maxLines);
    let last = kept[maxLines - 1];
    while (last && ctx.measureText(`${last}...`).width > maxWidth) {
        last = last.slice(0, -1);
    }
    kept[maxLines - 1] = `${last.trimEnd()}...`;
    return kept;
}

/**
 * Largest font size, between minSize and startSize, at which text fits maxWidth on
 * at most maxLines.
 * @returns {{size: number, lines: string[]}}
 */
function _shFitText(ctx, text, maxWidth, weight, startSize, minSize, maxLines) {
    let size = startSize;
    for (; size > minSize; size -= 2) {
        ctx.font = _shFont(weight, size);
        if (_shWrap(ctx, text, maxWidth).length <= maxLines) break;
    }
    ctx.font = _shFont(weight, size);
    return { size, lines: _shWrapClamped(ctx, text, maxWidth, maxLines) };
}

/** Small deterministic generator, so a card's star field is the same at every redraw. */
function _shRandom(seed) {
    let state = seed >>> 0 || 1;
    return () => {
        state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
        return state / 4294967296;
    };
}

function _shSeedFrom(text) {
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
        hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
    }
    return hash >>> 0;
}

/**
 * Plan the text block of a card: every line with its font, colour and height. Drawing is
 * done later from this plan, once the block's total height is known - that height decides
 * how much room a picture gets.
 * @param {number} inner - width available to the text, in pixels
 * @returns {{blocks: Object[], height: number}}
 */
function _shPlanInfo(ctx, model, options, inner, palette, compact) {
    const blocks = [];
    const push = (block) => blocks.push(block);
    const gap = (height) => push({ kind: 'gap', height });

    if (model.kicker) {
        push({ kind: 'text', text: model.kicker.toUpperCase(), font: _shFont(700, 26), color: palette.accent, height: 38, spacing: 3 });
    }
    const heading = _shFitText(ctx, model.heading || '', inner, 700, compact ? 56 : 68, 36, 2);
    heading.lines.forEach((line) => {
        push({ kind: 'text', text: line, font: _shFont(700, heading.size), color: palette.text, height: Math.round(heading.size * 1.2) });
    });
    if (model.subheading) {
        ctx.font = _shFont(400, 30);
        _shWrapClamped(ctx, model.subheading, inner, 2).forEach((line) => {
            push({ kind: 'text', text: line, font: _shFont(400, 30), color: palette.muted, height: 42 });
        });
    }

    if (model.hero) {
        gap(compact ? 18 : 34);
        push({ kind: 'hero', hero: model.hero, height: compact ? 130 : 170, size: compact ? 104 : 136 });
    }

    const facts = (model.facts || []).filter((fact) => options.facts[fact.id] !== false && fact.value);
    if (facts.length) {
        gap(compact ? 20 : 30);
        for (let index = 0; index < facts.length; index += 2) {
            push({ kind: 'facts', left: facts[index], right: facts[index + 1] || null, height: 92 });
        }
    }

    if (model.list && model.list.items && model.list.items.length) {
        gap(compact ? 16 : 26);
        push({ kind: 'text', text: model.list.title.toUpperCase(), font: _shFont(700, 22), color: palette.muted, height: 36, spacing: 2 });
        const items = model.list.items.slice(0, SHARE_MAX_LIST_ITEMS);
        const extra = model.list.items.length - items.length;
        items.forEach((item, index) => {
            push({ kind: 'item', index: index + 1, text: item, height: 46 });
        });
        if (extra > 0) {
            push({
                kind: 'text',
                text: _shT('share.and_more', 'and {count} more', { count: extra }),
                font: _shFont(400, 26),
                color: palette.muted,
                height: 40,
            });
        }
    }

    if (model.paragraph) {
        gap(compact ? 16 : 26);
        ctx.font = _shFont(400, 30);
        _shWrapClamped(ctx, model.paragraph, inner, SHARE_MAX_PARAGRAPH_LINES).forEach((line) => {
            push({ kind: 'text', text: line, font: _shFont(400, 30), color: palette.text, height: 44 });
        });
    }

    const height = blocks.reduce((total, block) => total + block.height, 0);
    return { blocks, height };
}

function _shDrawInfo(ctx, plan, left, top, inner, palette) {
    let y = top;
    // The blocks are laid out from SHARE_MARGIN; shift them to the block's real left edge.
    ctx.save();
    ctx.translate(left - SHARE_MARGIN, 0);
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    plan.blocks.forEach((block) => {
        if (block.kind === 'text') {
            ctx.font = block.font;
            ctx.fillStyle = block.color;
            if (block.spacing && 'letterSpacing' in ctx) ctx.letterSpacing = `${block.spacing}px`;
            ctx.fillText(block.text, SHARE_MARGIN, y + block.height * 0.76, inner);
            if ('letterSpacing' in ctx) ctx.letterSpacing = '0px';
        } else if (block.kind === 'hero') {
            ctx.font = _shFont(700, block.size);
            ctx.fillStyle = palette.accent;
            const value = String(block.hero.value);
            ctx.fillText(value, SHARE_MARGIN, y + block.size * 0.86);
            const valueWidth = ctx.measureText(value).width;
            if (block.hero.unit) {
                ctx.font = _shFont(600, Math.round(block.size * 0.36));
                ctx.fillStyle = palette.muted;
                ctx.fillText(block.hero.unit, SHARE_MARGIN + valueWidth + 14, y + block.size * 0.86);
            }
            ctx.font = _shFont(400, 28);
            ctx.fillStyle = palette.muted;
            ctx.fillText(block.hero.label, SHARE_MARGIN, y + block.height - 8, inner);
        } else if (block.kind === 'facts') {
            // A fact alone on its row (a long date range) takes the whole width.
            const column = block.right ? (inner - 32) / 2 : inner;
            [block.left, block.right].forEach((fact, position) => {
                if (!fact) return;
                const x = SHARE_MARGIN + position * (column + 32);
                ctx.font = _shFont(400, 22);
                ctx.fillStyle = palette.muted;
                ctx.fillText(String(fact.label), x, y + 26, column);
                const fitted = _shFitText(ctx, String(fact.value), column, 600, 34, 22, 1);
                ctx.font = _shFont(600, fitted.size);
                ctx.fillStyle = palette.text;
                ctx.fillText(fitted.lines[0] || '', x, y + 68, column);
            });
        } else if (block.kind === 'item') {
            ctx.font = _shFont(700, 28);
            ctx.fillStyle = palette.accent;
            ctx.fillText(String(block.index), SHARE_MARGIN, y + 34);
            ctx.font = _shFont(400, 30);
            ctx.fillStyle = palette.text;
            const lines = _shWrapClamped(ctx, block.text, inner - 44, 1);
            ctx.fillText(lines[0] || '', SHARE_MARGIN + 44, y + 34, inner - 44);
        }
        y += block.height;
    });
    ctx.restore();
}

/**
 * Draw the model's picture whole inside a box. Where the picture does not fill the box
 * (a tall photo in a wide box), the bands are filled with a blurred, darkened copy of the
 * picture instead of plain black - on browsers whose canvas supports filters.
 */
function _shDrawPicture(ctx, image, x, y, boxWidth, boxHeight, palette) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, boxWidth, boxHeight);
    ctx.clip();
    ctx.fillStyle = palette.stage;
    ctx.fillRect(x, y, boxWidth, boxHeight);
    const ratio = image.naturalWidth / image.naturalHeight;
    if ('filter' in ctx && Math.abs(ratio - boxWidth / boxHeight) > 0.02) {
        const cover = Math.max(boxWidth / image.naturalWidth, boxHeight / image.naturalHeight) * 1.15;
        ctx.filter = 'blur(36px) brightness(0.45)';
        ctx.drawImage(
            image,
            x + (boxWidth - image.naturalWidth * cover) / 2,
            y + (boxHeight - image.naturalHeight * cover) / 2,
            image.naturalWidth * cover,
            image.naturalHeight * cover
        );
        ctx.filter = 'none';
    }
    const scale = Math.min(boxWidth / image.naturalWidth, boxHeight / image.naturalHeight);
    const drawWidth = image.naturalWidth * scale;
    const drawHeight = image.naturalHeight * scale;
    ctx.drawImage(image, x + (boxWidth - drawWidth) / 2, y + (boxHeight - drawHeight) / 2, drawWidth, drawHeight);
    ctx.restore();
}

/**
 * Draw a card on a canvas.
 *
 * Upright formats stack the picture above the text; the landscape format puts them side
 * by side. Either way the text block is planned first and the picture gets what is left,
 * never more than its own shape needs - so a wide photo in a tall card leaves no black
 * band, the text simply sits in the middle of the remaining room.
 * @param {HTMLCanvasElement} canvas
 * @param {Object} model
 * @param {Object} options - { format, theme, brand, facts: {id: boolean} }
 * @param {HTMLImageElement|null} image - the model's picture, already loaded
 */
function drawShareCard(canvas, model, options, image) {
    const format = SHARE_FORMATS[options.format] || SHARE_FORMATS[SHARE_DEFAULT_FORMAT];
    const palette = SHARE_PALETTES[options.theme] || SHARE_PALETTES.dark;
    const { width, height } = format;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');

    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, palette.background[0]);
    gradient.addColorStop(1, palette.background[1]);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);

    const footerHeight = options.brand ? 96 : 40;
    const bodyHeight = height - footerHeight;
    const landscape = width > height;
    const compact = height < 1600;

    if (!image) {
        // No picture: a quiet star field, the same at every redraw of the same card.
        const random = _shRandom(_shSeedFrom(model.heading || model.kicker || 'card'));
        ctx.fillStyle = palette.star;
        for (let index = 0; index < 220; index += 1) {
            const radius = random() < 0.9 ? 1.2 : 2.4;
            ctx.globalAlpha = 0.25 + random() * 0.6;
            ctx.beginPath();
            ctx.arc(random() * width, random() * height, radius, 0, 2 * Math.PI);
            ctx.fill();
        }
        ctx.globalAlpha = 1;
    }

    // Where the text block goes: its left edge, its width, and the band it is centred in.
    let textLeft = SHARE_MARGIN;
    let textWidth = width - 2 * SHARE_MARGIN;
    let bandTop = 0;
    let plan;

    if (image && landscape) {
        // As wide as the picture needs at full height, within bounds: a tall photo leaves
        // more room to the text instead of sitting between two bands.
        const natural = bodyHeight * (image.naturalWidth / image.naturalHeight);
        const stageWidth = Math.round(Math.min(width * 0.58, Math.max(width * 0.34, natural)));
        _shDrawPicture(ctx, image, 0, 0, stageWidth, bodyHeight, palette);
        textLeft = stageWidth + 48;
        textWidth = width - textLeft - 48;
        plan = _shPlanInfo(ctx, model, options, textWidth, palette, compact);
    } else if (image) {
        plan = _shPlanInfo(ctx, model, options, textWidth, palette, compact);
        const available = bodyHeight - plan.height - 2 * 44;
        const natural = width / (image.naturalWidth / image.naturalHeight);
        const stageHeight = Math.round(Math.max(SHARE_MIN_IMAGE_HEIGHT, Math.min(available, natural)));
        _shDrawPicture(ctx, image, 0, 0, width, stageHeight, palette);
        bandTop = stageHeight;
    } else {
        if (landscape) textWidth = Math.round(width * 0.62);
        plan = _shPlanInfo(ctx, model, options, textWidth, palette, compact);
    }

    // Centred in its band; a little above centre in a tall card without picture, where it
    // reads better. Never above the band's own top margin.
    const free = bodyHeight - bandTop - plan.height;
    const bias = !image && !compact ? 0.4 : 0.5;
    const infoTop = bandTop + Math.max(image && !landscape ? 44 : SHARE_MARGIN, Math.round(free * bias));

    // If the text block is taller than the room left, keep what fits above the footer.
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, width, bodyHeight);
    ctx.clip();
    _shDrawInfo(ctx, plan, textLeft, infoTop, textWidth, palette);
    ctx.restore();

    if (options.brand) {
        const ruleY = bodyHeight;
        if (image && landscape) {
            // The picture runs to the footer: give the signature its own plain band.
            ctx.fillStyle = palette.background[1];
            ctx.fillRect(0, ruleY, width, footerHeight);
        }
        ctx.strokeStyle = palette.rule;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(SHARE_MARGIN, ruleY);
        ctx.lineTo(width - SHARE_MARGIN, ruleY);
        ctx.stroke();
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        ctx.font = _shFont(700, 28);
        ctx.fillStyle = palette.text;
        ctx.fillText(SHARE_BRAND_NAME, SHARE_MARGIN, ruleY + footerHeight / 2);
        ctx.textAlign = 'right';
        ctx.font = _shFont(400, 24);
        ctx.fillStyle = palette.muted;
        ctx.fillText(SHARE_BRAND_URL, width - SHARE_MARGIN, ruleY + footerHeight / 2);
        ctx.textAlign = 'left';
    }
}

/**
 * Load a same-origin picture for a card.
 * @param {string} url
 * @returns {Promise<HTMLImageElement|null>} null when the picture cannot be loaded
 */
function _shLoadImage(url) {
    return new Promise((resolve) => {
        if (!url) {
            resolve(null);
            return;
        }
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => resolve(null);
        image.src = url;
    });
}

function _shCanvasToBlob(canvas) {
    return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
}

function _shSlug(text) {
    const slug = String(text || '')
        .toLowerCase()
        .normalize('NFD')
        .replace(/[̀-ͯ]/g, '')
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return slug || 'card';
}

function _shRadioGroup(name, legend, choices, current, onChange) {
    const group = document.createElement('div');
    group.className = 'share-card-group';
    const label = document.createElement('div');
    label.className = 'share-card-group-label';
    label.textContent = legend;
    group.appendChild(label);
    const buttons = document.createElement('div');
    buttons.className = 'btn-group btn-group-sm';
    buttons.setAttribute('role', 'group');
    buttons.setAttribute('aria-label', legend);
    choices.forEach((choice) => {
        const input = document.createElement('input');
        input.type = 'radio';
        input.className = 'btn-check';
        input.name = name;
        input.id = `${name}-${choice.value}`;
        input.checked = choice.value === current;
        input.addEventListener('change', () => onChange(choice.value));
        const button = document.createElement('label');
        button.className = 'btn btn-outline-secondary';
        button.htmlFor = input.id;
        button.textContent = choice.label;
        DOMUtils.append(buttons, input, button);
    });
    group.appendChild(buttons);
    return group;
}

function _shCheckbox(id, text, checked, onChange) {
    const wrapper = document.createElement('div');
    wrapper.className = 'form-check';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.className = 'form-check-input';
    input.id = id;
    input.checked = checked;
    input.addEventListener('change', () => onChange(input.checked));
    const label = document.createElement('label');
    label.className = 'form-check-label';
    label.htmlFor = id;
    label.textContent = text;
    DOMUtils.append(wrapper, input, label);
    return wrapper;
}

/**
 * Open the share modal for a card model: preview, format, theme, facts to include,
 * then download or share.
 * @param {Object} model - see the file header
 */
async function openShareCard(model) {
    const modalEl = document.getElementById(SHARE_MODAL_ID);
    const titleEl = document.getElementById(`${SHARE_MODAL_ID}_title`);
    const bodyEl = document.getElementById(`${SHARE_MODAL_ID}_body`);
    if (!modalEl || !titleEl || !bodyEl || !model) return;

    titleEl.textContent = model.title || _shT('share.title', 'Share');
    DOMUtils.clear(bodyEl);
    bodyEl.appendChild(DOMUtils.createSpinnerWrapper(_shT('common.loading', 'Loading...')));
    openModal(modalEl, { backdrop: true });

    const [image] = await Promise.all([
        _shLoadImage(model.imageUrl),
        document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve(),
    ]);

    // Suffix that keeps the ids of this modal's controls unique if it is opened again.
    _shModalCount += 1;
    const uid = String(_shModalCount);
    const options = { format: SHARE_DEFAULT_FORMAT, theme: 'dark', brand: true, facts: {} };
    (model.facts || []).forEach((fact) => {
        options.facts[fact.id] = true;
    });

    DOMUtils.clear(bodyEl);
    const root = document.createElement('div');
    root.className = 'row g-3 share-card';

    const previewCol = document.createElement('div');
    previewCol.className = 'col-12 col-md-7';
    const stage = document.createElement('div');
    stage.className = `share-card-stage share-card-stage--${options.format}`;
    const canvas = document.createElement('canvas');
    canvas.className = 'share-card-canvas';
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', _shT('share.preview_label', 'Preview of the card: {name}', { name: model.heading || '' }));
    stage.appendChild(canvas);
    previewCol.appendChild(stage);
    if (model.imageUrl && !image) {
        const warning = document.createElement('p');
        warning.className = 'small text-warning mt-2 mb-0';
        warning.textContent = _shT('share.image_unavailable', 'The picture could not be loaded; the card is drawn without it.');
        previewCol.appendChild(warning);
    }

    const sideCol = document.createElement('div');
    sideCol.className = 'col-12 col-md-5';

    const redraw = () => drawShareCard(canvas, model, options, image);

    const formatHint = document.createElement('div');
    formatHint.className = 'small text-muted mt-1';
    const showFormatHint = () => {
        formatHint.textContent = _shT(SHARE_FORMATS[options.format].hint, SHARE_FORMAT_HINT_FALLBACKS[options.format]);
    };
    const formatGroup = _shRadioGroup(
        `share-format-${uid}`,
        _shT('share.format', 'Format'),
        Object.keys(SHARE_FORMATS).map((value) => ({ value, label: SHARE_FORMATS[value].label })),
        options.format,
        (value) => {
            Object.keys(SHARE_FORMATS).forEach((key) => stage.classList.toggle(`share-card-stage--${key}`, key === value));
            options.format = value;
            showFormatHint();
            redraw();
        }
    );
    formatGroup.appendChild(formatHint);
    showFormatHint();
    sideCol.appendChild(formatGroup);
    sideCol.appendChild(
        _shRadioGroup(
            `share-theme-${uid}`,
            _shT('share.theme', 'Theme'),
            [
                { value: 'dark', label: _shT('share.theme_dark', 'Dark') },
                { value: 'light', label: _shT('share.theme_light', 'Light') },
            ],
            options.theme,
            (value) => {
                options.theme = value;
                redraw();
            }
        )
    );

    const facts = (model.facts || []).filter((fact) => fact.value);
    if (facts.length) {
        const group = document.createElement('div');
        group.className = 'share-card-group';
        const label = document.createElement('div');
        label.className = 'share-card-group-label';
        label.textContent = _shT('share.include', 'Show on the card');
        group.appendChild(label);
        facts.forEach((fact) => {
            group.appendChild(
                _shCheckbox(`share-fact-${uid}-${fact.id}`, `${fact.label}: ${fact.value}`, true, (checked) => {
                    options.facts[fact.id] = checked;
                    redraw();
                })
            );
        });
        sideCol.appendChild(group);
    }

    const brandGroup = document.createElement('div');
    brandGroup.className = 'share-card-group';
    brandGroup.appendChild(
        _shCheckbox(`share-brand-${uid}`, _shT('share.brand', 'MyAstroBoard signature'), true, (checked) => {
            options.brand = checked;
            redraw();
        })
    );
    sideCol.appendChild(brandGroup);

    const privacy = document.createElement('p');
    privacy.className = 'small text-muted';
    privacy.textContent = _shT(
        'share.privacy_note',
        'The card is made in your browser and never contains your location. Nothing is sent anywhere until you share it yourself.'
    );
    sideCol.appendChild(privacy);

    const actions = document.createElement('div');
    actions.className = 'd-flex flex-wrap gap-2';
    const downloadBtn = document.createElement('button');
    downloadBtn.type = 'button';
    downloadBtn.className = 'btn btn-primary';
    DOMUtils.append(downloadBtn, DOMUtils.createIcon('bi bi-download icon-inline'), ` ${_shT('share.download', 'Download')}`);
    actions.appendChild(downloadBtn);

    const filename = `${_shSlug(model.filename || model.heading)}.png`;
    downloadBtn.addEventListener('click', async () => {
        const blob = await _shCanvasToBlob(canvas);
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    });

    // The system share sheet, where the browser can share a file (mostly phones).
    const probe = typeof File === 'function' ? new File([new Blob()], filename, { type: 'image/png' }) : null;
    if (probe && typeof navigator.canShare === 'function' && navigator.canShare({ files: [probe] })) {
        const shareBtn = document.createElement('button');
        shareBtn.type = 'button';
        shareBtn.className = 'btn btn-outline-primary';
        DOMUtils.append(shareBtn, DOMUtils.createIcon('bi bi-share icon-inline'), ` ${_shT('share.share', 'Share')}`);
        shareBtn.addEventListener('click', async () => {
            const blob = await _shCanvasToBlob(canvas);
            if (!blob) return;
            try {
                await navigator.share({ files: [new File([blob], filename, { type: 'image/png' })], title: model.heading });
            } catch (err) {
                // The user closing the share sheet is not an error.
                if (err && err.name !== 'AbortError') console.error('Share failed:', err);
            }
        });
        actions.appendChild(shareBtn);
    }
    sideCol.appendChild(actions);

    DOMUtils.append(root, previewCol, sideCol);
    bodyEl.appendChild(root);
    redraw();
}

/**
 * Build a small "share" icon button.
 * @param {Function} onClick
 * @param {string} [className]
 * @returns {HTMLButtonElement}
 */
function createShareButton(onClick, className = 'btn btn-sm btn-outline-secondary') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    const label = _shT('share.open', 'Share as an image');
    button.title = label;
    button.setAttribute('aria-label', label);
    button.appendChild(DOMUtils.createIcon('bi bi-share'));
    button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
    });
    return button;
}

// ── Card models ──────────────────────────────────────────────────────────────

/** "2h05" / "45 min" from a number of minutes; '' when unknown. */
function _shFormatMinutes(minutes) {
    const value = Number(minutes);
    if (!Number.isFinite(value) || value <= 0) return '';
    const hours = Math.floor(value / 60);
    const rest = Math.round(value % 60);
    if (hours <= 0) return _shT('share.minutes', '{minutes} min', { minutes: rest });
    return `${hours}h${String(rest).padStart(2, '0')}`;
}

/**
 * Card of one Astrodex picture with its acquisition details.
 * @param {Object} item - Astrodex item
 * @param {Object} picture - one of its pictures
 * @param {Object} labels - { type, constellation, equipment, date } already resolved by the caller
 */
function shareAstrodexPicture(item, picture, labels = {}) {
    const frames = Number(picture.frames) > 0 ? Number(picture.frames) : null;
    const sub = /^\d+$/.test(String(picture.exposition_time ?? '').trim()) ? Number(picture.exposition_time) : null;
    let exposures = '';
    if (frames && sub) exposures = `${frames} x ${sub} s`;
    else if (frames) exposures = String(frames);
    else if (picture.exposition_time) exposures = sub ? `${sub} s` : String(picture.exposition_time);

    openShareCard({
        title: _shT('share.title_picture', 'Share this picture'),
        filename: `astrodex-${item.name}`,
        kicker: _shT('share.kicker_astrodex', 'Astrodex'),
        heading: item.name,
        subheading: [labels.type, labels.constellation].filter(Boolean).join(' - '),
        imageUrl: appUrl(`/api/astrodex/images/${picture.filename}`),
        facts: [
            { id: 'date', label: _shT('share.fact_date', 'Date'), value: labels.date || '' },
            { id: 'equipment', label: _shT('share.fact_equipment', 'Equipment'), value: labels.equipment || '' },
            { id: 'exposures', label: _shT('share.fact_exposures', 'Exposures'), value: exposures },
            {
                id: 'integration',
                label: _shT('share.fact_integration', 'Integration'),
                value: _shFormatMinutes(picture.integration_minutes),
            },
            { id: 'filters', label: _shT('share.fact_filters', 'Filters'), value: picture.combination_id ? '' : picture.filters || '' },
        ],
    });
}

/**
 * Recap card of one Observation Log session.
 * @param {Object} session
 * @param {Object} labels - { date, equipment, imageUrl } already resolved by the caller
 */
function shareObservationSession(session, labels = {}) {
    const entries = session.entries || [];
    const nights = session.nights || [];
    const totalMinutes = entries.reduce((total, entry) => total + (Number(entry.integration_minutes) || 0), 0);
    const average = (key) => {
        const values = nights.map((night) => Number(night[key])).filter((value) => Number.isFinite(value) && value > 0);
        return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
    };
    const sqm = average('sqm');
    const moon = nights
        .map((night) => night.moon_illumination_percent)
        .filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value)));
    const moonAverage = moon.length ? moon.reduce((a, b) => a + Number(b), 0) / moon.length : null;
    const integration = _shFormatMinutes(totalMinutes);

    openShareCard({
        title: _shT('share.title_session', 'Share this session'),
        filename: `session-${labels.date || session.id}`,
        kicker: _shT('share.kicker_session', 'Observing session'),
        heading: labels.date || '',
        subheading: labels.equipment || '',
        imageUrl: labels.imageUrl || '',
        hero: integration ? { value: integration, label: _shT('share.hero_integration', 'total integration') } : null,
        facts: [
            { id: 'targets', label: _shT('share.fact_targets', 'Targets'), value: entries.length ? String(entries.length) : '' },
            { id: 'nights', label: _shT('share.fact_nights', 'Nights'), value: nights.length > 1 ? String(nights.length) : '' },
            { id: 'sqm', label: _shT('share.fact_sqm', 'Sky (SQM)'), value: sqm ? sqm.toFixed(2) : '' },
            {
                id: 'moon',
                label: _shT('share.fact_moon', 'Moon'),
                value: moonAverage !== null ? `${Math.round(moonAverage)}%` : '',
            },
        ],
        list: {
            title: _shT('share.list_targets', 'Targets'),
            items: entries.map((entry) => {
                const minutes = _shFormatMinutes(entry.integration_minutes);
                return minutes ? `${entry.name} - ${minutes}` : String(entry.name || '');
            }),
        },
    });
}

/**
 * "My sky tonight" card: night score, best window, Moon, top targets. Fetches what the
 * dashboard already shows; a part that is not available is simply left out.
 */
async function shareTonight() {
    const lang = typeof i18n?.getCurrentLanguage === 'function' ? i18n.getCurrentLanguage() : 'en';
    const safe = (promise) => promise.catch(() => null);
    const [widget, moonReport, windows, recommended] = await Promise.all([
        safe(fetchJSON('/api/sky-widget')),
        safe(fetchJSON('/api/moon/report')),
        safe(fetchJSON('/api/tonight/best-window?mode=all')),
        safe(fetchJSON(`/api/skytonight/recommendations?limit=3&lang=${encodeURIComponent(lang)}`)),
    ]);

    const score = widget && Number(widget.observation_score) > 0 ? Number(widget.observation_score) : null;
    const window = windows?.modes?.practical?.best_window || windows?.modes?.strict?.best_window || null;
    const timeOf = (value) => (typeof value === 'string' && value.includes(' ') ? value.split(' ')[1] : '');
    const moon = moonReport?.moon || null;
    const phaseKeys = {
        'New Moon': 'moon.new_moon',
        'Waxing Crescent': 'moon.waxing_crescent',
        'First Quarter': 'moon.first_quarter',
        'Waxing Gibbous': 'moon.waxing_gibbous',
        'Full Moon': 'moon.full_moon',
        'Waning Gibbous': 'moon.waning_gibbous',
        'Last Quarter': 'moon.last_quarter',
        'Waning Crescent': 'moon.waning_crescent',
    };
    const phase = moon ? _shT(phaseKeys[moon.phase_name] || '', moon.phase_name || '') : '';
    const today = new Date().toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'long' });

    openShareCard({
        title: _shT('share.title_tonight', 'Share my sky tonight'),
        filename: `sky-tonight-${new Date().toISOString().slice(0, 10)}`,
        kicker: _shT('share.kicker_tonight', 'My sky tonight'),
        heading: today,
        hero: score !== null ? { value: _shNumber(score), unit: '/10', label: _shT('share.hero_score', 'night score') } : null,
        facts: [
            {
                id: 'window',
                label: _shT('share.fact_window', 'Best window'),
                value: window && timeOf(window.start) ? `${timeOf(window.start)} - ${timeOf(window.end)}` : '',
            },
            {
                id: 'duration',
                label: _shT('share.fact_duration', 'Duration'),
                value: window && Number(window.duration_hours) > 0 ? _shFormatMinutes(Number(window.duration_hours) * 60) : '',
            },
            { id: 'phase', label: _shT('share.fact_moon', 'Moon'), value: phase },
            {
                id: 'illumination',
                label: _shT('share.fact_illumination', 'Illumination'),
                value: moon && Number.isFinite(Number(moon.illumination_percent)) ? `${Math.round(Number(moon.illumination_percent))}%` : '',
            },
        ],
        list: {
            title: _shT('share.list_top_targets', 'Top targets'),
            items: (recommended?.targets || []).map((target) =>
                [target.preferred_name, target.object_type].filter(Boolean).join(' - ')
            ),
        },
    });
}

function _shNumber(value) {
    return Number(Number(value).toFixed(1)).toString();
}

/**
 * Card of one upcoming event, as it will happen at the user's location.
 * @param {Object} event - an item of /api/events/upcoming
 * @param {Object} labels - { timing, status } already formatted by the caller
 */
function shareEvent(event, labels = {}) {
    openShareCard({
        title: _shT('share.title_event', 'Share this event'),
        filename: `event-${event.title}`,
        kicker: _shT('share.kicker_event', 'In my sky'),
        heading: event.title || '',
        subheading: labels.status || '',
        facts: [{ id: 'when', label: _shT('share.fact_when', 'When'), value: labels.timing || '' }],
        paragraph: event.description || '',
    });
}
