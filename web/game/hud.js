// Canvas HUD widgets: per-player score/time panels, the track-progress bar, small
// tags, and the end-of-run cards. Layout only — callers pass in the numbers.
import { DISPLAY_FONT, UI_FONT } from "./scenery.js";

export const PANEL_W = 264;

function _rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }

function _text(ctx, s, x, y, font, color, align, outline) {
  ctx.font = font;
  ctx.textAlign = align || "left";
  if (outline) {
    ctx.lineJoin = "round"; ctx.lineWidth = outline; ctx.strokeStyle = "rgba(0,0,0,0.55)";
    ctx.strokeText(s, x, y);
  }
  ctx.fillStyle = color;
  ctx.fillText(s, x, y);
}

// o: { label, color, score, time, lines: [string], dead, finished }
export function drawPlayerPanel(ctx, x, y, o) {
  const lines = o.lines || [];
  const h = lines.length ? 87 + lines.length * 19 : 80;   // ~16px below the last baseline
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.3)"; ctx.shadowBlur = 12; ctx.shadowOffsetY = 3;
  ctx.fillStyle = "rgba(14,20,34,0.74)";
  _rr(ctx, x, y, PANEL_W, h, 14); ctx.fill();
  ctx.restore();
  ctx.save();
  ctx.fillStyle = o.color;
  _rr(ctx, x, y, 6, h, [14, 0, 0, 14]); ctx.fill();
  ctx.textBaseline = "alphabetic";
  const tag = o.finished ? "  ✓ FINISHED" : (o.dead ? "  ✕ CRASHED" : "");
  _text(ctx, o.label.toUpperCase() + tag, x + 20, y + 24, `800 13px ${UI_FONT}`,
        o.finished ? "#7dffa6" : (o.dead ? "#ff8a80" : o.color));
  _text(ctx, String(o.score), x + 20, y + 64, `38px ${DISPLAY_FONT}`, "#fff");
  const sw = ctx.measureText(String(o.score)).width;
  _text(ctx, "score", x + 26 + sw, y + 63, `700 13px ${UI_FONT}`, "#9fb0c6");
  // timer, right side
  _text(ctx, o.time, x + PANEL_W - 16, y + 64, `26px ${DISPLAY_FONT}`, o.finished ? "#7dffa6" : "#ffe9a8", "right");
  _text(ctx, "⏱", x + PANEL_W - 16, y + 25, `14px ${UI_FONT}`, "#9fb0c6", "right");
  for (let i = 0; i < lines.length; i++) {
    _text(ctx, lines[i], x + 20, y + 88 + i * 19, `700 13px ${UI_FONT}`, "#c9d4e2");
  }
  ctx.restore();
  return y + h;
}

// markers: [{ frac, color }]; best: frac or null. Track + finish cap centered at cx.
export function drawProgressBar(ctx, cx, y, w, markers, best) {
  const CAP = 9;                       // checkered cap sits just past the track end
  const x = cx - (w + CAP) / 2;
  ctx.save();
  ctx.fillStyle = "rgba(14,20,34,0.6)";
  _rr(ctx, x - 12, y - 12, w + CAP + 24, 24, 12); ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.18)";
  _rr(ctx, x, y - 3, w, 6, 3); ctx.fill();
  const lead = markers.length ? markers[0] : null;
  if (lead) {
    ctx.fillStyle = lead.color;
    _rr(ctx, x, y - 3, Math.max(6, w * lead.frac), 6, 3); ctx.fill();
  }
  if (best != null && best > 0) {
    const bx = x + w * Math.min(1, best);
    ctx.fillStyle = "#ffc933";
    ctx.fillRect(bx - 1.5, y - 9, 3, 18);
  }
  // checkered finish
  for (let r = 0; r < 3; r++) for (let c = 0; c < 2; c++) {
    ctx.fillStyle = (r + c) % 2 ? "#111" : "#fff";
    ctx.fillRect(x + w + 1 + c * 4, y - 6 + r * 4, 4, 4);
  }
  for (let i = markers.length - 1; i >= 0; i--) {
    const m = markers[i];
    const mx = x + w * Math.min(1, Math.max(0, m.frac));
    ctx.fillStyle = "#fff";
    ctx.beginPath(); ctx.arc(mx, y, 7, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = m.color;
    ctx.beginPath(); ctx.arc(mx, y, 5, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
}

export function drawTag(ctx, x, y, s, bg, fg) {
  ctx.save();
  ctx.font = `800 12px ${UI_FONT}`;
  const w = ctx.measureText(s).width + 20;
  ctx.fillStyle = bg;
  _rr(ctx, x, y, w, 22, 11); ctx.fill();
  ctx.fillStyle = fg || "#fff";
  ctx.textAlign = "left";
  ctx.fillText(s, x + 10, y + 15);
  ctx.restore();
}

// Readout line for the center column (altimeter / speed / cheat modes).
export function drawReadout(ctx, s, cx, y, color, size) {
  ctx.save();
  _text(ctx, s, cx, y, `800 ${size || 20}px ${UI_FONT}`, color, "center", 4);
  ctx.restore();
}

// o: { title, color, subtitle, rows: [[label, value, badge?]], hint, alpha, width }
export function drawEndCard(ctx, cx, cy, o) {
  const w = o.width || 520;
  const rows = o.rows || [];
  const h = 118 + rows.length * 34 + (o.subtitle ? 26 : 0) + (o.hint ? 44 : 0);
  const x = cx - w / 2, y = cy - h / 2;
  ctx.save();
  ctx.globalAlpha = o.alpha == null ? 1 : o.alpha;
  ctx.shadowColor = "rgba(0,0,0,0.45)"; ctx.shadowBlur = 30; ctx.shadowOffsetY = 8;
  ctx.fillStyle = "rgba(14,20,34,0.92)";
  _rr(ctx, x, y + (1 - (o.alpha ?? 1)) * 20, w, h, 22); ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.translate(0, (1 - (o.alpha ?? 1)) * 20);
  ctx.fillStyle = o.color;
  _rr(ctx, x, y, w, 8, [22, 22, 0, 0]); ctx.fill();
  let yy = y + 66;
  _text(ctx, o.title, cx, yy, `44px ${DISPLAY_FONT}`, o.color, "center");
  if (o.subtitle) { yy += 28; _text(ctx, o.subtitle, cx, yy, `700 15px ${UI_FONT}`, "#b8c4d6", "center"); }
  yy += 24;
  for (const [label, value, badge] of rows) {
    yy += 34;
    ctx.fillStyle = "rgba(255,255,255,0.06)";
    _rr(ctx, x + 28, yy - 24, w - 56, 30, 8); ctx.fill();
    _text(ctx, label, x + 42, yy - 3, `700 15px ${UI_FONT}`, "#c9d4e2");
    // value: a string, or [[text, color], ...] segments (e.g. a red cheated part).
    const segs = Array.isArray(value) ? value : [[value, "#fff"]];
    ctx.font = `22px ${DISPLAY_FONT}`;
    const vw = segs.reduce((a, [t]) => a + ctx.measureText(t).width, 0);
    let vx = x + w - 42 - vw;
    for (const [t, c] of segs) {
      _text(ctx, t, vx, yy - 2, `22px ${DISPLAY_FONT}`, c, "left");
      vx += ctx.measureText(t).width;
    }
    if (badge) {
      // badge: a string (gold) or { text, bg, fg }.
      const b = typeof badge === "string" ? { text: badge, bg: "#ffc933", fg: "#4a3200" } : badge;
      ctx.font = `800 11px ${UI_FONT}`;
      const bw = ctx.measureText(b.text).width + 14;
      const bx = x + w - 42 - vw - 10 - bw;
      ctx.fillStyle = b.bg;
      _rr(ctx, bx, yy - 20, bw, 19, 9); ctx.fill();
      _text(ctx, b.text, bx + bw / 2, yy - 6, `800 11px ${UI_FONT}`, b.fg, "center");
    }
  }
  if (o.hint) {
    yy += 44;
    _drawKeyHint(ctx, cx, yy - 6, o.hint);
  }
  ctx.restore();
  return { x, y, w, h };
}

// "R Restart · T New map" with key-cap boxes; hint = [[key, label], ...].
function _drawKeyHint(ctx, cx, y, hint) {
  ctx.font = `800 14px ${UI_FONT}`;
  const parts = hint.map(([k, l]) => ({ k, l, kw: ctx.measureText(k).width + 16, lw: ctx.measureText(l).width }));
  const gap = 26;
  const total = parts.reduce((a, p) => a + p.kw + 8 + p.lw, 0) + gap * (parts.length - 1);
  let x = cx - total / 2;
  for (const p of parts) {
    ctx.fillStyle = "rgba(255,255,255,0.14)";
    _rr(ctx, x, y - 17, p.kw, 24, 6); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.textAlign = "left";
    ctx.fillText(p.k, x + 8, y);
    x += p.kw + 8;
    ctx.fillStyle = "#b8c4d6";
    ctx.fillText(p.l, x, y);
    x += p.lw + gap;
  }
}
