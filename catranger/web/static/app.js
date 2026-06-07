// CatRanger control panel. WebSocket for telemetry + low-latency drive intents;
// REST for one-shot mode/estop/model/connection actions. Press-and-hold driving
// (release => stop) matches the server-side watchdog dead-man's switch.
"use strict";

const $ = (id) => document.getElementById(id);
let ws = null;
let mode = "IDLE";
let estopped = false;
const STOP_TEXT = {
  ESTOP: "STOPPED — emergency stop latched. Press ARM / RESET to drive again.",
  WATCHDOG: "STOPPED — lost contact with the browser (dead-man's switch). Hold a control to resume.",
  FIRMWARE_SAFE_STOP: "SAFE STOP — obstacle within the firmware floor. Back away.",
  TARGET_LOST: "FOLLOW — searching, no cat in view.",
  LINK_LOST: "ROBOT LINK LOST — degraded to simulation. Reconnect on the Connections tab.",
  CAMERA_LOST: "CAMERA LOST — no frames. Check the Connections tab.",
};

// ---------------------------------------------------------------- WebSocket
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const t = JSON.parse(ev.data);
    if (t.type === "telemetry") updateUI(t);
  };
  ws.onclose = () => setTimeout(connectWS, 1000); // auto-reconnect
}
function wsSend(obj) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}
async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

// ---------------------------------------------------------------- UI update
function updateUI(t) {
  mode = t.mode;
  estopped = !!t.estop;

  const badge = $("modeBadge");
  badge.textContent = estopped ? "E-STOP" : t.mode;
  badge.className = "mode-badge " + (estopped ? "mode-ESTOP" : "mode-" + t.mode);
  $("resetBtn").classList.toggle("hidden", !estopped);

  // SIMULATION vs LIVE — never let a dummy link masquerade as a real robot
  const sim = $("simBanner");
  if (t.robot_connected) { sim.textContent = "LIVE — REAL ROBOT"; sim.className = "sim-banner live"; }
  else { sim.textContent = "SIMULATION"; sim.className = "sim-banner sim"; }

  // stop-reason banner
  const banner = $("stopBanner");
  if (t.stop_reason && t.stop_reason !== "NONE") {
    banner.textContent = STOP_TEXT[t.stop_reason] || t.stop_reason;
    banner.className = "stop-banner" + (t.stop_reason === "TARGET_LOST" ? " warn" : "");
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");

  // video staleness
  const stale = t.frame_age_ms != null && t.frame_age_ms > (t.video_stale_ms || 1000);
  $("staleOverlay").classList.toggle("hidden", !stale);

  // primary strip
  $("dist").textContent = t.target_dist_m != null ? t.target_dist_m + " m" : "—";
  $("gt").textContent = t.gt_cm != null && t.gt_cm >= 0 ? (t.gt_cm / 100).toFixed(2) + " m" : "—";
  $("target").textContent =
    (t.target_ids && t.target_ids.length)
      ? "id " + t.target_ids.join("/")
      : t.target_id != null
        ? "id " + t.target_id
        : t.n_cats
          ? t.n_cats + " seen"
          : "none";

  // diagnostics
  $("fps").textContent = "FPS " + (t.fps != null ? t.fps : "—");
  pill("camPill", "camera", t.camera_connected, t.camera);
  pill("robotPill", "robot", t.robot_connected, t.robot, true);
  $("modelPill").textContent = "model " + (t.model || "—") + (t.model_status ? " (" + t.model_status + ")" : "");
  $("modelPill").className = "pill " + (t.perception_available ? "ok" : "warn");

  // drive pad enabled only in MANUAL and not e-stopped
  const drivable = mode === "MANUAL" && !estopped;
  $("drivepad").classList.toggle("disabled", !drivable);
  $("driveHint").textContent = estopped
    ? "E-stop latched — press ARM / RESET."
    : drivable ? "Hold a button or W/A/S/D to drive. Release to stop."
    : "Switch to MANUAL to drive.";

  // active mode button
  document.querySelectorAll(".mode-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === t.mode && !estopped));

  chartPush(t);
}
function pill(id, label, ok, detail, robot) {
  const el = $(id);
  el.textContent = `${label} ${detail || (ok ? "on" : "off")}`;
  el.className = "pill " + (ok ? "ok" : (robot ? "warn" : "bad"));
}

// ---------------------------------------------------------------- driving
const speed = () => parseFloat($("speed").value);
let driveTimer = null;
function startDrive(action) {
  if (mode !== "MANUAL" || estopped) return;
  wsSend({ type: "intent", action, value: speed() });
  clearInterval(driveTimer);
  driveTimer = setInterval(() => wsSend({ type: "intent", action, value: speed() }), 120);
}
function stopDrive() {
  clearInterval(driveTimer); driveTimer = null;
  wsSend({ type: "intent", action: "stop", value: 0 });
}
document.querySelectorAll(".dbtn").forEach((b) => {
  const act = b.dataset.act;
  if (act === "stop") { b.onclick = stopDrive; return; }
  b.addEventListener("pointerdown", (e) => { e.preventDefault(); startDrive(act); });
  b.addEventListener("pointerup", stopDrive);
  b.addEventListener("pointerleave", stopDrive);
});
const KEYS = { w: "forward", s: "back", a: "left", d: "right",
  ArrowUp: "forward", ArrowDown: "back", ArrowLeft: "left", ArrowRight: "right" };
const held = new Set();
document.addEventListener("keydown", (e) => {
  const act = KEYS[e.key]; if (!act || held.has(e.key)) return;
  held.add(e.key); startDrive(act);
});
document.addEventListener("keyup", (e) => {
  if (KEYS[e.key]) { held.delete(e.key); stopDrive(); }
});
// keep the watchdog alive while in MANUAL even when idle (so the banner reads
// NONE, not WATCHDOG, when the operator simply isn't pressing anything)
setInterval(() => { if (mode === "MANUAL" && !estopped) wsSend({ type: "heartbeat" }); }, 200);
$("pan").addEventListener("input", (e) => wsSend({ type: "intent", action: "pan", value: parseFloat(e.target.value) }));

// ---------------------------------------------------------------- controls
document.querySelectorAll(".mode-btn").forEach((b) =>
  b.addEventListener("click", () => post("/api/mode", { mode: b.dataset.mode })));
$("estopBtn").addEventListener("click", () => post("/api/estop"));
$("resetBtn").addEventListener("click", () => post("/api/reset"));

// tabs
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector(`.tabpane[data-pane=${tab.dataset.tab}]`).classList.add("active");
    if (tab.dataset.tab === "models") loadModels();
  }));

// ---------------------------------------------------------------- models
async function loadModels() {
  const data = await (await fetch("/api/models")).json();
  const ul = $("modelList"); ul.innerHTML = "";
  data.models.forEach((m) => {
    const li = document.createElement("li");
    if (m.id === data.active) li.classList.add("active");
    const when = m.trained_at ? m.trained_at.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2}).*/, "$1-$2-$3 $4:$5") : "";
    const meta = [m.run_kind || m.backend, m.dataset || "", when].filter(Boolean).join(" · ");
    const detail = m.summary || m.notes || "";
    li.innerHTML = `<div><b>${m.name}</b><div class="meta">${meta}</div>${detail ? `<div class="meta">${detail}</div>` : ""}</div>`;
    const btn = document.createElement("button");
    btn.className = "btn"; btn.textContent = m.id === data.active ? "active" : "use";
    btn.disabled = m.id === data.active;
    btn.onclick = async () => {
      btn.textContent = "loading…";
      const r = await post("/api/models/select", { id: m.id });
      $("modelHint").textContent = r.ok
        ? `Active: ${r.model} (${r.status})${r.warning ? " — " + r.warning : ""}`
        : `Failed: ${r.problem || r.code}`;
      loadModels();
    };
    li.appendChild(btn); ul.appendChild(li);
  });
}

// ---------------------------------------------------------------- connections
$("camConnect").addEventListener("click", async () => {
  const r = await post("/api/camera/connect", { spec: $("camSpec").value || "synthetic" });
  msg("camMsg", r.warning ? r.warning : `connected: ${r.label}`, r.warning ? "warn" : "ok");
});
$("camDisconnect").addEventListener("click", async () => {
  await post("/api/camera/disconnect"); msg("camMsg", "using synthetic source", "ok");
});
$("robotConnect").addEventListener("click", async () => {
  const r = await post("/api/robot/connect", {
    connection: $("robotConn").value,
    target: $("robotTarget").value || null,
    baud: parseInt($("robotBaud").value, 10) || 115200,
  });
  msg("robotMsg", r.warning ? r.warning : `bridge: ${r.bridge} (${r.connected ? "live" : "sim"})`,
    r.warning ? "warn" : (r.connected ? "ok" : "warn"));
});
$("robotDisconnect").addEventListener("click", async () => {
  await post("/api/robot/disconnect"); msg("robotMsg", "disconnected (simulation)", "ok");
});
function msg(id, text, cls) { const e = $(id); e.textContent = text; e.className = "conn-msg " + cls; }

// ---------------------------------------------------------------- history chart
// Dependency-free canvas chart: model estimate (orange) + CI band vs HC-SR04
// ground truth (green). Seeds from /api/history, then appends live /ws points.
const chart = { pts: [], max: 2000, lastPush: 0, raf: 0, css: null };

function chartColors() {
  if (chart.css) return chart.css;
  const s = getComputedStyle(document.documentElement);
  const g = (n, f) => (s.getPropertyValue(n).trim() || f);
  chart.css = {
    est: g("--orange-bright", "#ff8a3d"),
    band: g("--orange", "#ff6b1a"),
    gt: g("--truth", "#34d399"),
    line: "rgba(255,255,255,0.10)",
    dim: g("--dim", "#6f6881"),
    mono: g("--font-mono", "monospace"),
  };
  return chart.css;
}
function hexA(hex, a) {
  const h = (hex || "").replace("#", "");
  if (h.length < 6) return `rgba(255,107,26,${a})`;
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
}
function chartScheduleDraw() {
  if (chart.raf) return;
  chart.raf = requestAnimationFrame(() => { chart.raf = 0; chartDraw(); });
}
function chartPush(t) {
  const est = t.target_dist_m;
  if (est == null) return;
  const now = Date.now() / 1000;
  if (now - chart.lastPush < 0.2) return; // ~5 Hz live cap
  chart.lastPush = now;
  const gt = (t.gt_cm != null && t.gt_cm >= 0) ? t.gt_cm / 100 : null;
  chart.pts.push({ t: now, est, lo: t.target_dist_lo ?? null, hi: t.target_dist_hi ?? null, gt });
  if (chart.pts.length > chart.max) chart.pts.splice(0, chart.pts.length - chart.max);
  chartScheduleDraw();
}
async function chartSeed() {
  try {
    const data = await (await fetch("/api/history?limit=1500")).json();
    chart.pts = (data.samples || []).map((s) => ({
      t: s.ts, est: s.est_m, lo: s.lo, hi: s.hi,
      gt: (s.gt_cm != null && s.gt_cm >= 0) ? s.gt_cm / 100 : null,
    }));
    chartScheduleDraw();
  } catch (e) { /* no history yet — chart fills as samples arrive */ }
}
function chartDraw() {
  const cv = $("distChart");
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (W === 0 || H === 0) return;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const c = chartColors();
  const x0 = 36, x1 = W - 10, y0 = 10, y1 = H - 16;
  const pts = chart.pts;

  ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x0, y1); ctx.lineTo(x1, y1); ctx.stroke();

  if (pts.length < 1) {
    ctx.fillStyle = c.dim; ctx.font = `11px ${c.mono}`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("waiting for distance data…", (x0 + x1) / 2, (y0 + y1) / 2);
    return;
  }

  let tMin = pts[0].t, tMax = pts[pts.length - 1].t;
  if (tMax - tMin < 1) tMax = tMin + 1;
  let vMin = Infinity, vMax = -Infinity;
  for (const p of pts) for (const v of [p.est, p.lo, p.hi, p.gt])
    if (v != null && isFinite(v)) { if (v < vMin) vMin = v; if (v > vMax) vMax = v; }
  if (!isFinite(vMin)) { vMin = 0; vMax = 1; }
  if (vMax - vMin < 0.2) vMax = vMin + 0.2;
  const padV = (vMax - vMin) * 0.1;
  vMin = Math.max(0, vMin - padV); vMax = vMax + padV;

  const sx = (t) => x0 + (x1 - x0) * (t - tMin) / (tMax - tMin);
  const sy = (v) => y1 - (y1 - y0) * (v - vMin) / (vMax - vMin);

  ctx.fillStyle = c.dim; ctx.font = `10px ${c.mono}`; ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let i = 0; i <= 2; i++) {
    const v = vMin + (vMax - vMin) * i / 2, y = sy(v);
    ctx.strokeStyle = c.line; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
    ctx.fillText(v.toFixed(1) + "m", x0 - 6, y);
  }

  const band = pts.filter((p) => p.lo != null && p.hi != null);
  if (band.length > 1) {
    ctx.beginPath();
    band.forEach((p, i) => { const X = sx(p.t), Y = sy(p.hi); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    for (let i = band.length - 1; i >= 0; i--) ctx.lineTo(sx(band[i].t), sy(band[i].lo));
    ctx.closePath(); ctx.fillStyle = hexA(c.band, 0.16); ctx.fill();
  }

  const line = (key, color, width, dash) => {
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash || []);
    ctx.beginPath(); let pen = false;
    for (const p of pts) {
      const v = p[key];
      if (v == null || !isFinite(v)) { pen = false; continue; }
      const X = sx(p.t), Y = sy(v);
      pen ? ctx.lineTo(X, Y) : (ctx.moveTo(X, Y), pen = true);
    }
    ctx.stroke(); ctx.setLineDash([]);
  };
  line("gt", c.gt, 1.5, [4, 4]);
  line("est", c.est, 2);

  const last = pts[pts.length - 1];
  if (last.est != null) { ctx.fillStyle = c.est; ctx.beginPath(); ctx.arc(sx(last.t), sy(last.est), 3, 0, Math.PI * 2); ctx.fill(); }
}
window.addEventListener("resize", chartScheduleDraw);
chartSeed();

connectWS();
