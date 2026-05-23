/**
 * constraint_help.js
 * Dynamic canvas-based visual guides for SkyTonight constraint settings.
 * Diagrams are theme-aware and redraw whenever an input changes.
 */

(function () {
    'use strict';

    // ── Theme-aware colors ────────────────────────────────────────────────────
    function _themeColors() {
        const rs = getComputedStyle(document.documentElement);
        const theme = (document.documentElement.getAttribute('data-theme') || '').toLowerCase();
        const isDark = theme === 'dark' || theme === 'red';
        const cssVar = (name, fallback) => { const v = rs.getPropertyValue(name); return v ? v.trim() : fallback; };
        return {
            isDark,
            text:            cssVar('--text-color',  isDark ? '#e5e7eb' : '#1f2937'),
            muted:           cssVar('--text-grey',   isDark ? '#d1d5db' : '#6b7280'),
            sky:             isDark ? '#05091a' : '#1a2d6e',
            skyMid:          isDark ? '#0d1a3a' : '#2d4a9e',
            ground:          isDark ? '#2d1f0e' : '#7c5230',
            gridLine:        isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.10)',
            observable:      'rgba(34,197,94,0.22)',
            observableLine:  'rgba(34,197,94,0.9)',
            blocked:         'rgba(239,68,68,0.15)',
            blockedLine:     'rgba(220,60,60,0.85)',
            accent:          cssVar('--accent-1', isDark ? '#8b5cf6' : '#6366f1'),
            surface:         isDark ? 'rgba(15,23,42,0.55)' : 'rgba(255,255,255,0.55)',
            moonColor:       '#fbbf24',
            starOk:          'rgba(34,197,94,0.9)',
            starBlocked:     'rgba(239,68,68,0.9)',
        };
    }

    // ── Canvas setup (handles devicePixelRatio) ───────────────────────────────
    function _setup(canvas) {
        const dpr = window.devicePixelRatio || 1;
        const w   = canvas.offsetWidth  || 280;
        const h   = canvas.offsetHeight || 120;
        canvas.width  = w * dpr;
        canvas.height = h * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        return { ctx, w, h };
    }

    // ── Readable text on dark sky backgrounds (dark halo) ─────────────────────
    function _skyText(ctx, text, x, y) {
        ctx.shadowColor = 'rgba(0,0,0,0.85)';
        ctx.shadowBlur  = 4;
        ctx.fillText(text, x, y);
        ctx.shadowBlur  = 0;
        ctx.shadowColor = 'transparent';
    }

    // ── Diagram 1: Altitude min / max ─────────────────────────────────────────
    function drawAltitude(canvas) {
        const altMin = parseFloat(document.getElementById('altitude-min')?.value) || 25;
        const altMax = parseFloat(document.getElementById('altitude-max')?.value) || 90;
        const c = _themeColors();
        const { ctx, w, h } = _setup(canvas);
        ctx.clearRect(0, 0, w, h);

        const ML = 36, MR = 8, MT = 12, MB = 22;
        const pw = w - ML - MR, ph = h - MT - MB;
        const altToY = a => MT + ph * (1 - Math.min(90, Math.max(0, a)) / 90);

        // Sky gradient
        const grad = ctx.createLinearGradient(ML, MT, ML, MT + ph);
        grad.addColorStop(0,   c.sky);
        grad.addColorStop(0.7, c.skyMid);
        grad.addColorStop(1,   c.isDark ? '#1a1205' : '#8B6A30');
        ctx.fillStyle = grad;
        ctx.fillRect(ML, MT, pw, ph);

        // Ground strip
        ctx.fillStyle = c.ground;
        ctx.fillRect(ML, MT + ph * 0.94, pw, ph * 0.06);

        // Observable zone
        const yMin = altToY(altMin), yMax = altToY(altMax);
        ctx.fillStyle = c.observable;
        ctx.fillRect(ML, yMax, pw, yMin - yMax);

        // Reference grid at 30° and 60°
        ctx.setLineDash([3, 3]);
        ctx.lineWidth = 0.7;
        [30, 60].forEach(a => {
            const y = altToY(a);
            ctx.strokeStyle = c.gridLine;
            ctx.beginPath(); ctx.moveTo(ML, y); ctx.lineTo(ML + pw, y); ctx.stroke();
            ctx.fillStyle = c.muted; ctx.font = '10px system-ui'; ctx.textAlign = 'right';
            _skyText(ctx, `${a}°`, ML - 3, y + 4);
        });
        ctx.setLineDash([]);

        // min line (red)
        ctx.strokeStyle = c.blockedLine; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(ML, yMin); ctx.lineTo(ML + pw, yMin); ctx.stroke();
        // max line (green)
        ctx.strokeStyle = c.observableLine;
        ctx.beginPath(); ctx.moveTo(ML, yMax); ctx.lineTo(ML + pw, yMax); ctx.stroke();

        // Axis extremes
        ctx.fillStyle = c.muted; ctx.font = '10px system-ui'; ctx.textAlign = 'right';
        _skyText(ctx, '90°', ML - 3, MT + 8);
        _skyText(ctx, '0°',  ML - 3, MT + ph);

        // Value labels on the constraint lines
        ctx.font = 'bold 11px system-ui'; ctx.textAlign = 'left';
        ctx.fillStyle = c.blockedLine;    _skyText(ctx, `min ${altMin}°`, ML + 4, yMin - 4);
        ctx.fillStyle = c.observableLine; _skyText(ctx, `max ${altMax}°`, ML + 4, yMax + 13);

        // ✓ in the observable band
        if (yMin - yMax > 18) {
            ctx.fillStyle = 'rgba(255,255,255,0.90)'; ctx.font = '13px system-ui'; ctx.textAlign = 'center';
            ctx.fillText('✓', ML + pw / 2, (yMin + yMax) / 2 + 5);
        }

        // Axes
        ctx.strokeStyle = c.gridLine; ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.moveTo(ML, MT); ctx.lineTo(ML, MT + ph); ctx.lineTo(ML + pw, MT + ph); ctx.stroke();

        ctx.fillStyle = c.muted; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
        ctx.fillText('↑ altitude above horizon', ML + pw / 2, h - 4);
    }

    // ── Diagram 2: Airmass ────────────────────────────────────────────────────
    function drawAirmass(canvas) {
        const airmass = Math.max(1, parseFloat(document.getElementById('airmass')?.value) || 2.0);
        const c = _themeColors();
        const { ctx, w, h } = _setup(canvas);
        ctx.clearRect(0, 0, w, h);

        const groundY = h - 26;
        const cx      = w / 2;
        const skyR    = Math.min(w / 2 - 18, groundY - 12);
        const altCutRad = Math.asin(Math.min(1, 1 / airmass)); // altitude in radians

        // Sky dome gradient
        const domeGrad = ctx.createRadialGradient(cx, groundY, skyR * 0.05, cx, groundY, skyR);
        domeGrad.addColorStop(0, c.skyMid);
        domeGrad.addColorStop(1, c.sky);
        ctx.beginPath();
        ctx.arc(cx, groundY, skyR, Math.PI, 0);
        ctx.closePath();
        ctx.fillStyle = domeGrad;
        ctx.fill();

        // Blocked zone below cutoff — clip to dome
        ctx.save();
        ctx.beginPath(); ctx.arc(cx, groundY, skyR, Math.PI, 0); ctx.closePath(); ctx.clip();
        const yLine = groundY - skyR * Math.sin(altCutRad);
        ctx.fillStyle = c.blocked;
        ctx.fillRect(cx - skyR, yLine, skyR * 2, groundY - yLine + 4);
        ctx.restore();

        // Reference altitude rings at 30° and 60°
        ctx.setLineDash([2, 3]); ctx.lineWidth = 0.7;
        [30, 60].forEach(deg => {
            const a = deg * Math.PI / 180;
            const yl  = groundY - skyR * Math.sin(a);
            const xl  = cx - skyR * Math.cos(a);
            const xr  = cx + skyR * Math.cos(a);
            ctx.strokeStyle = c.gridLine;
            ctx.beginPath(); ctx.moveTo(xl, yl); ctx.lineTo(xr, yl); ctx.stroke();
            ctx.fillStyle = c.muted; ctx.font = '10px system-ui'; ctx.textAlign = 'right';
            _skyText(ctx, `${deg}°`, xl - 2, yl + 4);
        });
        ctx.setLineDash([]);

        // Cutoff chord line
        const xLeft  = cx - skyR * Math.cos(altCutRad);
        const xRight = cx + skyR * Math.cos(altCutRad);
        ctx.strokeStyle = c.blockedLine; ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 3]);
        ctx.beginPath(); ctx.moveTo(xLeft, yLine); ctx.lineTo(xRight, yLine); ctx.stroke();
        ctx.setLineDash([]);

        // Zenith dashed line
        ctx.strokeStyle = c.gridLine; ctx.lineWidth = 0.7; ctx.setLineDash([2, 3]);
        ctx.beginPath(); ctx.moveTo(cx, groundY - skyR - 2); ctx.lineTo(cx, groundY); ctx.stroke();
        ctx.setLineDash([]);

        // Ground line
        ctx.strokeStyle = c.ground; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(cx - skyR - 6, groundY); ctx.lineTo(cx + skyR + 6, groundY); ctx.stroke();

        // Observer dot
        ctx.fillStyle = c.accent;
        ctx.beginPath(); ctx.arc(cx, groundY, 4, 0, 2 * Math.PI); ctx.fill();

        // Cutoff altitude label
        const altDeg = Math.round(altCutRad * 180 / Math.PI);
        ctx.fillStyle = c.blockedLine; ctx.font = 'bold 11px system-ui'; ctx.textAlign = 'center';
        if (yLine > 14) _skyText(ctx, `cutoff ≈ ${altDeg}°`, cx, yLine - 6);

        // Zenith label
        ctx.fillStyle = c.muted; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
        _skyText(ctx, '90°', cx, groundY - skyR - 4);

        // Bottom info (outside dome, on card bg)
        ctx.fillStyle = c.muted; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
        ctx.fillText(`Airmass ${airmass.toFixed(1)}  →  min altitude ≈ ${altDeg}°`, cx, h - 6);
    }

    // ── Diagram 3: Size min / max (log-scale ruler) ───────────────────────────
    function drawSize(canvas) {
        const sizeMin = parseFloat(document.getElementById('size-min')?.value) || 3;
        const sizeMax = parseFloat(document.getElementById('size-max')?.value) || 150;
        const c = _themeColors();
        const { ctx, w, h } = _setup(canvas);
        ctx.clearRect(0, 0, w, h);

        const ML = 8, MR = 8;
        const pw    = w - ML - MR;
        const rulerY = h / 2 + 8;
        const barH  = 16;

        const LOG_MIN = Math.log10(0.3), LOG_MAX = Math.log10(350);
        const toX = v => ML + pw * (Math.log10(Math.max(0.3, v)) - LOG_MIN) / (LOG_MAX - LOG_MIN);

        // Background track
        ctx.fillStyle = c.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)';
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(ML, rulerY - barH / 2, pw, barH, 3);
        else ctx.rect(ML, rulerY - barH / 2, pw, barH);
        ctx.fill();

        // Observable zone between min and max
        const xMin = toX(sizeMin), xMax = toX(sizeMax);
        ctx.fillStyle = c.observable;
        ctx.fillRect(xMin, rulerY - barH / 2, Math.max(0, xMax - xMin), barH);

        // Min / max lines
        ctx.lineWidth = 2;
        ctx.strokeStyle = c.blockedLine;
        ctx.beginPath(); ctx.moveTo(xMin, rulerY - barH / 2 - 4); ctx.lineTo(xMin, rulerY + barH / 2 + 4); ctx.stroke();
        ctx.strokeStyle = c.observableLine;
        ctx.beginPath(); ctx.moveTo(xMax, rulerY - barH / 2 - 4); ctx.lineTo(xMax, rulerY + barH / 2 + 4); ctx.stroke();

        // Reference objects
        const refs = [
            { size: 0.6,  label: "NGC\n6826" },
            { size: 7,    label: "M1" },
            { size: 30,   label: "☽" },
            { size: 65,   label: "M42" },
            { size: 185,  label: "M31" },
        ];
        refs.forEach(({ size, label }) => {
            const x = toX(size);
            if (x < ML + 2 || x > w - MR - 2) return;
            ctx.strokeStyle = c.muted; ctx.lineWidth = 0.8;
            ctx.beginPath(); ctx.moveTo(x, rulerY - barH / 2 - 2); ctx.lineTo(x, rulerY - barH / 2 - 10); ctx.stroke();
            ctx.fillStyle = c.muted; ctx.font = '9px system-ui'; ctx.textAlign = 'center';
            const lines = label.split('\n');
            lines.forEach((l, i) => ctx.fillText(l, x, rulerY - barH / 2 - 14 - (lines.length - 1 - i) * 10));
        });

        // Scale ticks at bottom
        [0.5, 1, 3, 10, 30, 100, 300].forEach(v => {
            const x = toX(v);
            if (x < ML || x > w - MR) return;
            ctx.strokeStyle = c.gridLine; ctx.lineWidth = 0.7;
            ctx.beginPath(); ctx.moveTo(x, rulerY + barH / 2); ctx.lineTo(x, rulerY + barH / 2 + 6); ctx.stroke();
            ctx.fillStyle = c.muted; ctx.font = '9px system-ui'; ctx.textAlign = 'center';
            ctx.fillText(`${v}'`, x, rulerY + barH / 2 + 16);
        });

        // Min / max value labels (second row, below tick labels)
        ctx.font = 'bold 10px system-ui';
        ctx.fillStyle = c.blockedLine;
        ctx.textAlign = xMin < ML + pw * 0.35 ? 'left' : 'right';
        ctx.fillText(`min ${sizeMin}'`, xMin + (xMin < ML + pw * 0.35 ? 3 : -3), rulerY + barH / 2 + 28);
        ctx.fillStyle = c.observableLine;
        ctx.textAlign = xMax > ML + pw * 0.65 ? 'right' : 'left';
        ctx.fillText(`max ${sizeMax}'`, xMax + (xMax > ML + pw * 0.65 ? -3 : 3), rulerY + barH / 2 + 28);

        // Caption
        ctx.fillStyle = c.muted; ctx.font = '9px system-ui'; ctx.textAlign = 'center';
        ctx.fillText('← angular size in arcminutes (log scale)', w / 2, h - 2);
    }

    // ── Diagram 4: Moon separation ────────────────────────────────────────────
    function drawMoon(canvas) {
        const moonSep  = parseFloat(document.getElementById('moon-sep')?.value) || 40;
        const useIllum = document.getElementById('moon-illumination')?.checked ?? true;
        const c = _themeColors();
        const { ctx, w, h } = _setup(canvas);
        ctx.clearRect(0, 0, w, h);

        // Night sky background (whole canvas)
        const bg = ctx.createLinearGradient(0, 0, 0, h);
        bg.addColorStop(0, c.sky); bg.addColorStop(1, c.skyMid);
        ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

        const moonX = w * 0.26, moonY = h * 0.40, moonR = 13;
        const targetX = w * 0.74, targetY = h * 0.38;

        // Exclusion zone around moon (visual, not to exact scale)
        const zonePx = Math.min(moonX - moonR - 6, (targetX - moonX) * 0.78);
        const dist   = Math.hypot(targetX - moonX, targetY - moonY);
        const inside = dist < zonePx;

        ctx.fillStyle = c.blocked;
        ctx.beginPath(); ctx.arc(moonX, moonY, zonePx, 0, 2 * Math.PI); ctx.fill();
        ctx.strokeStyle = c.blockedLine; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.arc(moonX, moonY, zonePx, 0, 2 * Math.PI); ctx.stroke();
        ctx.setLineDash([]);

        // Dashed line from moon to target
        ctx.strokeStyle = c.isDark ? 'rgba(251,191,36,0.5)' : 'rgba(180,130,0,0.6)';
        ctx.lineWidth = 0.8; ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(moonX, moonY); ctx.lineTo(targetX, targetY); ctx.stroke();
        ctx.setLineDash([]);

        // Moon
        const moonGrad = ctx.createRadialGradient(moonX - 3, moonY - 3, 1, moonX, moonY, moonR);
        moonGrad.addColorStop(0, '#fffde7');
        moonGrad.addColorStop(1, c.moonColor);
        ctx.fillStyle = moonGrad;
        ctx.beginPath(); ctx.arc(moonX, moonY, moonR, 0, 2 * Math.PI); ctx.fill();
        ctx.strokeStyle = '#d97706'; ctx.lineWidth = 0.5; ctx.stroke();

        // Target star (green = ok, red = blocked)
        ctx.fillStyle = inside ? c.starBlocked : c.starOk;
        ctx.beginPath(); ctx.arc(targetX, targetY, 5, 0, 2 * Math.PI); ctx.fill();
        // Four-point star sparkle
        ctx.strokeStyle = inside ? c.starBlocked : c.starOk; ctx.lineWidth = 1;
        for (let i = 0; i < 4; i++) {
            const a = i * Math.PI / 2;
            ctx.beginPath();
            ctx.moveTo(targetX + Math.cos(a) * 6, targetY + Math.sin(a) * 6);
            ctx.lineTo(targetX + Math.cos(a) * 9, targetY + Math.sin(a) * 9);
            ctx.stroke();
        }

        // Status label on target
        ctx.fillStyle = inside ? c.starBlocked : c.starOk;
        ctx.font = '10px system-ui'; ctx.textAlign = 'center';
        ctx.fillText(inside ? '✗ blocked' : '✓ allowed', targetX, targetY + 20);

        // Separation label (between moon and edge of exclusion zone)
        const midX = (moonX + targetX) / 2, midY = Math.min(moonY, targetY) - 8;
        ctx.fillStyle = 'rgba(255,255,255,0.90)'; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
        ctx.fillText(`${moonSep}° min`, midX, midY);

        // Bottom mode info
        ctx.font = '10px system-ui'; ctx.textAlign = 'center';
        ctx.fillStyle = 'rgba(255,255,255,0.90)';
        if (useIllum) {
            ctx.fillText('Dynamic mode: illumination% × 100 = min°', w / 2, h - 16);
            ctx.fillStyle = 'rgba(255,255,255,0.70)';
            ctx.fillText('(e.g. 60% moon  →  60° minimum)', w / 2, h - 4);
        } else {
            ctx.fillText(`Fixed: ${moonSep}° minimum separation from moon`, w / 2, h - 8);
        }
    }

    // ── Diagram 5: Observable time threshold ─────────────────────────────────
    function drawTime(canvas) {
        const threshold = Math.min(1, Math.max(0, parseFloat(document.getElementById('time-threshold')?.value) || 0.4));
        const c = _themeColors();
        const { ctx, w, h } = _setup(canvas);
        ctx.clearRect(0, 0, w, h);

        const ML = 10, MR = 10;
        const pw    = w - ML - MR;
        const barH  = 34;
        const barY  = (h - barH) / 2 - 12;
        const xThr  = ML + pw * threshold;

        // Night bar
        const nightGrad = ctx.createLinearGradient(ML, 0, ML + pw, 0);
        nightGrad.addColorStop(0,   c.sky);
        nightGrad.addColorStop(0.5, c.skyMid);
        nightGrad.addColorStop(1,   c.sky);
        ctx.fillStyle = nightGrad;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(ML, barY, pw, barH, 4);
        else ctx.rect(ML, barY, pw, barH);
        ctx.fill();

        // Fail zone (left of threshold)
        if (xThr > ML + 2) {
            ctx.fillStyle = c.blocked;
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(ML, barY, xThr - ML, barH, [4, 0, 0, 4]);
            else ctx.rect(ML, barY, xThr - ML, barH);
            ctx.fill();
        }

        // Pass zone (right of threshold)
        if (xThr < ML + pw - 2) {
            ctx.fillStyle = c.observable;
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(xThr, barY, ML + pw - xThr, barH, [0, 4, 4, 0]);
            else ctx.rect(xThr, barY, ML + pw - xThr, barH);
            ctx.fill();
        }

        // Threshold line
        ctx.strokeStyle = c.observableLine; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(xThr, barY - 5); ctx.lineTo(xThr, barY + barH + 5); ctx.stroke();

        // Zone text labels (inside the night bar — sky background)
        ctx.font = '11px system-ui'; ctx.textAlign = 'center';
        if (xThr - ML > 40) {
            ctx.fillStyle = c.blockedLine;
            _skyText(ctx, '✗ filtered', ML + (xThr - ML) / 2, barY + barH / 2 + 4);
        }
        if (ML + pw - xThr > 40) {
            ctx.fillStyle = c.observableLine;
            _skyText(ctx, '✓ shown', xThr + (ML + pw - xThr) / 2, barY + barH / 2 + 4);
        }

        // Threshold percentage label (above bar, on card bg)
        ctx.fillStyle = c.text; ctx.font = 'bold 12px system-ui'; ctx.textAlign = 'center';
        ctx.fillText(`${Math.round(threshold * 100)}%`, xThr, barY - 9);

        // Timeline axis labels (below bar, on card bg)
        ctx.fillStyle = c.muted; ctx.font = '10px system-ui';
        ctx.textAlign = 'left';  ctx.fillText('night start', ML, barY + barH + 16);
        ctx.textAlign = 'right'; ctx.fillText('night end',   ML + pw, barY + barH + 16);
        ctx.textAlign = 'center';
        ctx.fillText('← fraction of night target is above constraints', w / 2, barY + barH + 28);
    }

    // ── Draw all ──────────────────────────────────────────────────────────────
    function _drawAll() {
        const map = {
            'guide-altitude': drawAltitude,
            'guide-airmass':  drawAirmass,
            'guide-size':     drawSize,
            'guide-moon':     drawMoon,
            'guide-time':     drawTime,
        };
        for (const [id, fn] of Object.entries(map)) {
            const el = document.getElementById(id);
            if (el && el.offsetParent !== null) fn(el); // only draw if visible
        }
    }

    // ── Public init ───────────────────────────────────────────────────────────
    function initConstraintHelp() {
        // Redraw on input change
        ['altitude-min', 'altitude-max', 'airmass', 'size-min', 'size-max',
         'moon-sep', 'time-threshold', 'moon-illumination']
            .forEach(id => {
                const el = document.getElementById(id);
                if (el) { el.addEventListener('input', _drawAll); el.addEventListener('change', _drawAll); }
            });

        // Initial draw when the collapse is first opened
        document.getElementById('constraint-guides')?.addEventListener('shown.bs.collapse', _drawAll);

        // Redraw after window resize
        let _resizeTimer = null;
        window.addEventListener('resize', () => {
            clearTimeout(_resizeTimer);
            _resizeTimer = setTimeout(_drawAll, 120);
        });

        // Redraw on theme switch
        new MutationObserver(_drawAll).observe(document.documentElement, {
            attributes: true, attributeFilter: ['data-theme', 'data-bs-theme'],
        });
    }

    window.initConstraintHelp = initConstraintHelp;
    window._drawConstraintGuides = _drawAll; // expose for manual trigger
})();
