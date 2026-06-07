// CatRanger control panel. WebSocket for telemetry + low-latency drive intents;
// REST for one-shot mode/estop/model/connection actions. Press-and-hold driving
// (release => stop) matches the server-side watchdog dead-man's switch.
"use strict";

const $ = (id) => document.getElementById(id);
let ws = null;
let linkState = "connecting";
let mode = "IDLE";
let estopped = false;
let lastT = null;
let bannerReason = null;
let bannerShowTimer = null;
let bannerHideTimer = null;
let nackTimer = null;
const STOP_TEXT = {
  TELEMETRY_LOST: "TELEMETRY LINK LOST — reconnecting… Controls may be stale until the link returns.",
  ESTOP: "STOPPED — emergency stop latched. Press ARM / RESET to drive again.",
  WATCHDOG: "STOPPED — lost contact with the browser (dead-man's switch). Hold a control to resume.",
  FIRMWARE_SAFE_STOP: "SAFE STOP — obstacle within the firmware floor. Back away.",
  TARGET_LOST: "FOLLOW — searching, no cat in view.",
  LINK_LOST: "ROBOT LINK LOST — degraded to simulation. Reconnect on the Connections tab.",
  CAMERA_LOST: "CAMERA LOST — no frames. Check the Connections tab.",
};

// WS-B2 badge debounce (ported from apps/web badges.ts)
const BADGE_PRECEDENCE = ["no_distance", "depth_geom_disagree", "wide_ci", "low_conf"];
const BADGE_RANK = new Map(BADGE_PRECEDENCE.map((b, i) => [b, i]));
const BADGE_STYLE = {
  no_distance: { label: "no range", tone: "stop", glyph: "⊘" },
  depth_geom_disagree: { label: "depth≠geom", tone: "warn", glyph: "≠" },
  wide_ci: { label: "wide CI", tone: "warn", glyph: "↔" },
  low_conf: { label: "low conf", tone: "warn", glyph: "?" },
};
function pickBadge(flags) {
  if (!flags || !flags.length) return null;
  let best = null, bestRank = Infinity;
  for (const f of flags) {
    const r = BADGE_RANK.get(f);
    if (r !== undefined && r < bestRank) { bestRank = r; best = f; }
  }
  return best;
}
class BadgeDebouncer {
  constructor(minFrames = 3) { this.min = minFrames; this.state = new Map(); }
  update(key, badge) {
    if (!badge) { this.state.delete(key); return null; }
    const cur = this.state.get(key);
    const count = cur && cur.badge === badge ? cur.count + 1 : 1;
    this.state.set(key, { badge, count });
    return count >= this.min ? badge : null;
  }
  retain(live) { for (const k of this.state.keys()) if (!live.has(k)) this.state.delete(k); }
}
const badgeDebouncer = new BadgeDebouncer(3);
let overlayFrameId = -1;
const shownBadges = new Map();

function showNack(problem, fix) {
  const el = $("nackToast");
  el.textContent = `${problem}${fix ? " — " + fix : ""}`;
  el.classList.remove("hidden");
  clearTimeout(nackTimer);
  nackTimer = setTimeout(() => el.classList.add("hidden"), 4000);
}
function setLink(state) {
  linkState = state;
  const el = $("linkBadge");
  if (state === "live") { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  el.textContent = state === "connecting" ? "connecting…" : "link lost";
  el.className = "link-badge " + (state === "connecting" ? "dim" : "warn");
  if (state === "disconnected") {
    bannerReason = "TELEMETRY_LOST";
    const banner = $("stopBanner");
    banner.textContent = STOP_TEXT.TELEMETRY_LOST;
    banner.className = "stop-banner warn";
    banner.classList.remove("hidden");
  }
}
function typingInField() {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

// ---------------------------------------------------------------- WebSocket
function connectWS() {
  setLink("connecting");
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { setLink("live"); wsSend({ type: "claim" }); };
  ws.onmessage = (ev) => {
    const t = JSON.parse(ev.data);
    if (t.type === "telemetry") updateUI(t);
    else if (t.type === "nack") showNack(t.problem || "request rejected", t.fix);
  };
  ws.onclose = () => { setLink("disconnected"); setTimeout(connectWS, 1000); };
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
  try {
    const data = await r.json();
    if (!data.ok && !data.problem) data.problem = data.code || `request failed (HTTP ${r.status})`;
    return data;
  } catch {
    return { ok: false, problem: `bad response from server (HTTP ${r.status})`, fix: "restart catranger serve and retry" };
  }
}
async function patch(path, body) {
  const r = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}
async function del(path) {
  const r = await fetch(path, { method: "DELETE" });
  return r.json();
}

// ---------------------------------------------------------------- UI update
function updateUI(t) {
  lastT = t;
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

  // stop-reason banner (debounced so WATCHDOG doesn't flicker at the 0.5s edge)
  let reason = t.stop_reason && t.stop_reason !== "NONE" ? t.stop_reason : null;
  if (linkState === "disconnected") reason = "TELEMETRY_LOST";
  if (reason !== bannerReason) {
    clearTimeout(bannerShowTimer);
    clearTimeout(bannerHideTimer);
    bannerReason = reason;
    if (reason) {
      bannerHideTimer = setTimeout(() => {
        const banner = $("stopBanner");
        banner.textContent = STOP_TEXT[reason] || reason;
        banner.className = "stop-banner" + (reason === "TARGET_LOST" ? " warn" : "");
        banner.classList.remove("hidden");
      }, 180);
    } else {
      bannerShowTimer = setTimeout(() => $("stopBanner").classList.add("hidden"), 180);
    }
  }

  // video staleness
  const stale = t.frame_age_ms != null && t.frame_age_ms > (t.video_stale_ms || 1000);
  $("staleOverlay").classList.toggle("hidden", !stale);

  // primary strip
  $("dist").textContent = t.target_dist_m != null ? t.target_dist_m + " m" : "—";
  $("distWarn").classList.toggle("hidden", t.camera_calibrated !== false);
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

  $("modelPill").textContent = "model " + (t.model || "—") + (t.model_status ? " (" + t.model_status + ")" : "");
  $("modelPill").className = "pill " + (t.perception_available ? "ok" : "warn");
  $("evalPill").classList.toggle("hidden", !t.eval_running);
  if (t.eval_running) { $("evalPill").textContent = "eval running"; $("evalPill").className = "pill warn"; }
  $("trainPill").classList.toggle("hidden", !t.train_running);
  if (t.train_running) { $("trainPill").textContent = "train running"; $("trainPill").className = "pill warn"; }

  const isController = t.you_are_controller !== false;
  const drivable = mode === "MANUAL" && !estopped && isController && linkState === "live";
  $("drivepad").classList.toggle("disabled", !drivable);
  $("bodyYaw").disabled = !drivable;
  $("observerBadge").classList.toggle("hidden", isController || !t);
  $("requestControlBtn").classList.toggle("hidden", isController || !t);
  $("driveHint").textContent = estopped
    ? "E-stop latched — press ARM / RESET."
    : linkState !== "live"
      ? "Telemetry link lost — reconnecting…"
      : !isController
        ? "Observer — another operator holds control."
        : drivable ? "Hold a button or W/A/S/D to drive. Release to stop."
        : "Switch to MANUAL to drive.";

  // active mode button
  document.querySelectorAll(".mode-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === t.mode && !estopped));

  chartPush(t);
  drawOverlay(t);
  renderCatPicker(t);
  renderPeripherals(t);
  renderPtz(t);
  updateCatsFinding(t);
  drivableRef = mode === "MANUAL" && !estopped && t.you_are_controller !== false && linkState === "live";
}
function pill(id, label, ok, detail, robot) {
  const el = $(id);
  el.textContent = `${label} ${detail || (ok ? "on" : "off")}`;
  el.className = "pill " + (ok ? "ok" : (robot ? "warn" : "bad"));
}

// ---------------------------------------------------------------- driving
const speed = () => parseFloat($("speed").value);
let drivableRef = false;
let driveTimer = null;
function startDrive(action) {
  if (!drivableRef) return;
  wsSend({ type: "intent", action, value: speed() });
  clearInterval(driveTimer);
  driveTimer = setInterval(() => {
    if (!drivableRef) { stopDrive(); return; }
    wsSend({ type: "intent", action, value: speed() });
  }, 120);
}
function stopDrive() {
  clearInterval(driveTimer); driveTimer = null;
  wsSend({ type: "intent", action: "stop", value: 0 });
}
function panicDrive() { held.clear(); stopDrive(); }
document.querySelectorAll(".dbtn").forEach((b) => {
  const act = b.dataset.act;
  if (act === "stop") { b.onclick = stopDrive; return; }
  b.addEventListener("pointerdown", (e) => { e.preventDefault(); b.setPointerCapture?.(e.pointerId); startDrive(act); });
  b.addEventListener("pointerup", stopDrive);
  b.addEventListener("pointercancel", stopDrive);
  b.addEventListener("lostpointercapture", stopDrive);
});
const KEYS = { w: "forward", s: "back", a: "left", d: "right",
  ArrowUp: "forward", ArrowDown: "back", ArrowLeft: "left", ArrowRight: "right" };
const held = new Set();
document.addEventListener("keydown", (e) => {
  if (typingInField() || e.repeat) return;
  const act = KEYS[e.key]; if (!act || held.has(e.key)) return;
  held.add(e.key); startDrive(act);
});
document.addEventListener("keyup", (e) => {
  if (KEYS[e.key]) { held.delete(e.key); stopDrive(); }
});
window.addEventListener("blur", panicDrive);
document.addEventListener("visibilitychange", () => { if (document.hidden) panicDrive(); });
$("speed").addEventListener("input", () => { $("speedVal").textContent = speed().toFixed(1); });
$("bodyYaw").addEventListener("input", (e) => {
  const v = parseFloat(e.target.value);
  $("yawVal").textContent = v.toFixed(2);
  if (drivableRef) wsSend({ type: "intent", action: "pan", value: v });
});
$("requestControlBtn").addEventListener("click", () => wsSend({ type: "request_control" }));
// keep the watchdog alive while in MANUAL even when idle
setInterval(() => {
  if (mode === "MANUAL" && !estopped && lastT?.you_are_controller !== false)
    wsSend({ type: "heartbeat" });
}, 200);

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
    if (tab.dataset.tab === "cats") loadCatLibrary();
    if (tab.dataset.tab === "cv") refreshTrainPanel();
    if (tab.dataset.tab === "connections") initFlashPanel();
  }));
$("openCatsTab").addEventListener("click", () => {
  document.querySelector('.tab[data-tab="cats"]').click();
});

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
    btn.dataset.help = "models.use";
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
  if (window.ConsoleHelp) ConsoleHelp.rescan(ul);
}

// ---------------------------------------------------------------- connections
$("camConnect").addEventListener("click", async () => {
  const spec = $("camSpec").value || "synthetic";
  const profile = /^rtsp:\/\//i.test(spec.trim()) ? "tapo_c211" : $("camProfile").value;
  if (/^rtsp:\/\//i.test(spec.trim())) $("camProfile").value = "tapo_c211";
  const r = await post("/api/camera/connect", { spec, camera: profile });
  const tone = r.warning || (r.ok && !r.calibrated) ? "warn" : "ok";
  const text = r.warning || (r.ok
    ? `connected: ${r.label}${r.calibrated ? "" : " — uncalibrated; distance approximate"} (${r.camera_profile || profile})`
    : r.problem || r.code);
  msg("camMsg", text, r.ok ? tone : "warn");
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

$("sonarCal").addEventListener("click", () => runSonarCal(false));
$("sonarPreview").addEventListener("click", () => runSonarCal(true));
async function runSonarCal(dryRun) {
  const spec = ($("camSpec").value || "").trim();
  const profile = /^rtsp:\/\//i.test(spec) ? "tapo_c211" : $("camProfile").value;
  msg("sonarMsg", dryRun ? "previewing… (~5 s)" : "calibrating… (~5 s)", "ok");
  const r = await post("/api/calibrate/sonar", {
    camera: profile,
    baseline_m: (parseFloat($("sonarBaseline").value) || 90) / 1000,
    dry_run: dryRun,
  });
  if (r.ok) {
    const bits = [
      dryRun ? "preview" : "saved",
      r.scale != null ? `scale ${r.scale.toFixed(3)}` : null,
      r.old_fy != null && r.new_fy != null ? `fy ${r.old_fy} → ${r.new_fy}` : null,
    ].filter(Boolean);
    msg("sonarMsg", bits.join(" · "), r.warning ? "warn" : "ok");
  } else msg("sonarMsg", r.problem || r.code, "warn");
}

$("robotDiscover").addEventListener("click", () => discoverPorts(false));
$("flashDiscover").addEventListener("click", () => discoverPorts(true));

async function discoverPorts(focusFlash) {
  const hintEl = focusFlash ? $("flashHint") : $("discoverHint");
  hintEl.textContent = "scanning…";
  const r = await (await fetch("/api/robot/discover")).json();
  const ul = $("portList"); ul.innerHTML = "";
  if (r.ok) {
    hintEl.textContent = r.hint || `${r.serial.length} port(s)`;
    populatePortSelects(r.serial || []);
    r.serial.forEach((p) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.className = "btn ghost";
      b.textContent = p.label || p.target;
      b.onclick = () => pickPort(p.target, focusFlash);
      li.appendChild(b); ul.appendChild(li);
    });
    if (focusFlash) updateFlashUi();
  } else hintEl.textContent = r.problem || "discover failed";
}

function pickPort(target, focusFlash) {
  $("robotTarget").value = target;
  $("robotConn").value = "usb";
  const sel = $("flashPort");
  if (sel) {
    let opt = [...sel.options].find((o) => o.value === target);
    if (!opt) {
      opt = document.createElement("option");
      opt.value = target;
      opt.textContent = target;
      sel.appendChild(opt);
    }
    sel.value = target;
  }
  updateFlashUi();
  if (focusFlash) msg("flashMsg", `selected ${target}`, "ok");
}

function scorePort(p) {
  const t = (p.target || "").toLowerCase();
  const l = (p.label || "").toLowerCase();
  let s = 0;
  if (t.includes("usbserial") || t.includes("usbmodem") || t.includes("wchusb")) s += 10;
  if (t.includes("arduino")) s += 8;
  if (t.startsWith("/dev/cu.")) s += 5;
  if (l.includes("usb") || l.includes("serial") || l.includes("arduino")) s += 3;
  if (t.includes("bluetooth") || t.includes("debug-console")) s -= 20;
  return s;
}

function populatePortSelects(ports) {
  const sel = $("flashPort");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = '<option value="">— pick USB Arduino port —</option>';
  ports.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.target;
    opt.textContent = `${p.label || p.target} (${p.target})`;
    sel.appendChild(opt);
  });
  const best = [...ports].sort((a, b) => scorePort(b) - scorePort(a))[0];
  if (prev && ports.some((p) => p.target === prev)) sel.value = prev;
  else if (best && scorePort(best) > 0) sel.value = best.target;
}

function selectedFlashPort() {
  const fromFlash = ($("flashPort")?.value || "").trim();
  if (fromFlash) return fromFlash;
  return ($("robotTarget").value || "").trim() || null;
}

// ---------------------------------------------------------------- overlay + cats + PTZ + peripherals
function contentRect(elemW, elemH, frameW, frameH) {
  if (elemW <= 0 || elemH <= 0 || frameW <= 0 || frameH <= 0)
    return { x: 0, y: 0, w: Math.max(0, elemW), h: Math.max(0, elemH) };
  const scale = Math.min(elemW / frameW, elemH / frameH);
  const w = frameW * scale, h = frameH * scale;
  return { x: (elemW - w) / 2, y: (elemH - h) / 2, w, h };
}
function denormBox(xyxy, rect) {
  const [x1, y1, x2, y2] = xyxy;
  return { x: rect.x + x1 * rect.w, y: rect.y + y1 * rect.h, w: (x2 - x1) * rect.w, h: (y2 - y1) * rect.h };
}
function drawOverlay(t) {
  const cv = $("overlay");
  const wrap = cv?.parentElement;
  if (!cv || !wrap) return;
  const o = t.overlay;
  const ctx = cv.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cw = wrap.clientWidth - 16, ch = wrap.clientHeight - 16;
  if (cw <= 0 || ch <= 0) return;
  cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cw, ch);
  const stale = t.frame_age_ms != null && t.frame_age_ms > (t.video_stale_ms || 1000);
  ctx.globalAlpha = stale ? 0.35 : 1;
  if (!o || !o.dets || !o.dets.length) return;

  if (o.frame_id !== overlayFrameId) {
    overlayFrameId = o.frame_id;
    const next = new Map();
    const liveKeys = new Set();
    o.dets.forEach((d, i) => {
      const key = d.track_id != null ? `t${d.track_id}` : `i${i}`;
      liveKeys.add(key);
      const b = badgeDebouncer.update(key, pickBadge(d.flags));
      if (b) next.set(key, b);
    });
    badgeDebouncer.retain(liveKeys);
    shownBadges.clear();
    next.forEach((v, k) => shownBadges.set(k, v));
  }

  const rect = contentRect(cw, ch, o.frame_w || 1920, o.frame_h || 1080);
  const accent = "#22c55e", dim = "rgba(255,255,255,0.55)", warn = "#f59e0b", stop = "#ef4444";
  ctx.font = "600 13px ui-monospace, monospace";
  ctx.textBaseline = "bottom";
  for (const d of o.dets) if (!d.is_target) drawDet(ctx, d, rect, dim, false);
  for (const d of o.dets) if (d.is_target) drawDet(ctx, d, rect, accent, true);
  o.dets.forEach((d, i) => {
    const badge = shownBadges.get(d.track_id != null ? `t${d.track_id}` : `i${i}`);
    if (badge) drawBadge(ctx, d, rect, badge, warn, stop);
  });
}
function drawDet(ctx, d, rect, color, isTarget) {
  const b = denormBox(d.xyxy_norm, rect);
  ctx.strokeStyle = color;
  ctx.lineWidth = isTarget ? 3 : 1.5;
  ctx.strokeRect(b.x, b.y, b.w, b.h);
  const label = overlayLabel(d, isTarget);
  if (!label) return;
  const padX = 4, th = 17, tw = ctx.measureText(label).width + padX * 2;
  const lx = b.x, ly = b.y > th ? b.y : b.y + b.h + th;
  ctx.fillStyle = "rgba(0,0,0,0.66)";
  ctx.fillRect(lx, ly - th, tw, th);
  ctx.fillStyle = color;
  ctx.fillText(label, lx + padX, ly - 3);
}
function overlayLabel(d, isTarget) {
  const ids = isTarget && d.known_track_ids?.length ? d.known_track_ids : d.track_id != null ? [d.track_id] : [];
  const id = ids.length ? `#${ids.join("/")}` : "·";
  if (!isTarget) return id;
  const parts = [id];
  if (d.dist_m != null) {
    const ci = d.dist_lo != null && d.dist_hi != null ? ` ±${((d.dist_hi - d.dist_lo) / 2).toFixed(2)}` : "";
    parts.push(`${d.dist_m.toFixed(2)}m${ci}`);
  }
  if (d.bearing_deg != null) parts.push(`${d.bearing_deg >= 0 ? "+" : ""}${d.bearing_deg.toFixed(0)}°`);
  return parts.join("  ");
}
function drawBadge(ctx, d, rect, badge, warn, stop) {
  const st = BADGE_STYLE[badge];
  const text = `${st.glyph} ${st.label}`;
  const b = denormBox(d.xyxy_norm, rect);
  ctx.font = "600 11px ui-monospace, monospace";
  ctx.textBaseline = "middle";
  const padX = 4, h = 16, w = ctx.measureText(text).width + padX * 2;
  const x = b.x, y = b.y + b.h - h;
  ctx.fillStyle = st.tone === "stop" ? stop : warn;
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#000";
  ctx.fillText(text, x + padX, y + h / 2 + 0.5);
}

function mergeCatCards(t) {
  const byId = new Map();
  for (const cat of t.cats || []) byId.set(cat.id, { ...cat });
  const locked = t.target_id ?? null;
  const preferred = t.preferred_target_id ?? null;
  const ensure = (id, partial) => {
    if (byId.has(id)) return;
    byId.set(id, {
      id, conf: partial?.conf ?? 0, dist_m: partial?.dist_m ?? null,
      bearing_deg: partial?.bearing_deg ?? 0, is_locked: locked === id,
      is_preferred: preferred === id, thumb_jpeg_b64: partial?.thumb_jpeg_b64 ?? null,
      in_view: partial?.in_view,
    });
  };
  for (const det of t.overlay?.dets || []) {
    if (det.track_id == null || byId.has(det.track_id)) continue;
    ensure(det.track_id, {
      conf: det.conf, dist_m: det.dist_m, bearing_deg: det.bearing_deg,
      is_locked: det.is_target || locked === det.track_id, is_preferred: preferred === det.track_id,
    });
  }
  for (const id of t.target_ids || []) ensure(id);
  if (t.target_id != null) ensure(t.target_id);
  return [...byId.values()].sort((a, b) => b.conf - a.conf);
}

function renderCatPicker(t) {
  const root = $("catPicker");
  const hint = $("catPickerHint");
  const cats = mergeCatCards(t);
  const preferred = t.preferred_target_id ?? null;
  const locked = t.target_id ?? null;
  $("catPickerStatus").textContent = preferred != null ? `following id ${preferred}`
    : locked != null ? `locked id ${locked}` : "auto (largest)";
  if (!cats.length) {
    root.innerHTML = "";
    hint.classList.remove("hidden");
    return;
  }
  hint.classList.add("hidden");
  root.innerHTML = "";
  const perception = t.perception_available !== false;
  cats.forEach((c) => {
    const card = document.createElement("div");
    const active = preferred === c.id || (preferred == null && (c.is_locked || locked === c.id));
    card.className = "cat-card" + (active ? " active" : "") + (c.in_view === false ? " dim" : "");
    const img = document.createElement("img");
    img.alt = `cat ${c.id}`;
    img.src = c.thumb_jpeg_b64 ? `data:image/jpeg;base64,${c.thumb_jpeg_b64}` : "";
    const meta = document.createElement("div");
    meta.className = "meta";
    const dist = c.dist_m != null ? `${Math.round(c.dist_m * 100)} cm` : "—";
    meta.textContent = `#${c.id} · ${dist} · conf ${(c.conf * 100).toFixed(0)}%`;
    const sel = document.createElement("button");
    sel.type = "button"; sel.className = "cat-action"; sel.textContent = "Select";
    sel.dataset.help = "cat.select";
    sel.disabled = !!t.estop || !perception;
    sel.onclick = (e) => { e.stopPropagation(); wsSend({ type: "select_target", id: c.id, follow: false }); };
    const fol = document.createElement("button");
    fol.type = "button"; fol.className = "cat-action follow"; fol.textContent = "Follow";
    fol.dataset.help = "cat.follow";
    fol.disabled = !!t.estop || !perception;
    fol.onclick = (e) => { e.stopPropagation(); wsSend({ type: "select_target", id: c.id, follow: true }); };
    card.append(img, meta, sel, fol);
    root.appendChild(card);
  });
  const row = document.createElement("div");
  row.className = "cat-auto-row";
  const auto = document.createElement("button");
  auto.className = "btn ghost"; auto.textContent = "Auto (largest)";
  auto.dataset.help = "cat.auto";
  auto.disabled = !!t.estop || !perception || preferred == null;
  auto.onclick = () => wsSend({ type: "select_target", id: "auto", follow: false });
  const autoF = document.createElement("button");
  autoF.className = "btn ghost"; autoF.textContent = "Auto + FOLLOW";
  autoF.dataset.help = "cat.auto_follow";
  autoF.disabled = !!t.estop || !perception || preferred == null;
  autoF.onclick = () => wsSend({ type: "select_target", id: "auto", follow: true });
  row.append(auto, autoF);
  root.appendChild(row);
  if (window.ConsoleHelp) ConsoleHelp.rescan(root);
}

function renderPeripherals(t) {
  const cm = t.sonar_display_cm != null && t.sonar_display_cm >= 0 ? t.sonar_display_cm
    : t.gt_cm != null && t.gt_cm >= 0 ? t.gt_cm : null;
  const range = t.sonar_range_cm ?? 200;
  const zoneColors = { red: "#ef4444", yellow: "#eab308", green: "#22c55e", cyan: "#06b6d4", blue: "#3b82f6" };
  const zoneColor = zoneColors[t.sonar_zone] || "var(--muted)";
  $("sonarReadout").textContent = cm != null ? `${cm} cm` : "—";
  $("sonarReadout").style.color = zoneColor;
  $("sonarObstacle").classList.toggle("hidden", !t.sonar_obstacle);
  $("sonarNoEcho").classList.toggle("hidden", !t.sonar_no_echo);
  const fill = $("sonarZoneFill");
  fill.style.width = cm != null ? `${Math.min(100, (cm / range) * 100)}%` : "0%";
  fill.style.backgroundColor = zoneColor;
  const modelCm = t.target_dist_m != null ? Math.round(t.target_dist_m * 100) : null;
  const delta = cm != null && modelCm != null ? Math.abs(modelCm - cm) : null;
  $("sonarDelta").textContent = delta != null ? `Model ${modelCm} cm · Δ ${delta} cm vs sonar` : "";
  const orb = $("rgbOrb");
  const p = t.peripherals;
  const rgbOn = p?.rgb !== false;
  orb.style.backgroundColor = !rgbOn ? "#1a1a1a" : zoneColor;
  orb.style.boxShadow = rgbOn && t.sonar_zone ? `0 0 18px ${zoneColor}` : "";
  $("buzzerState").textContent = t.buzzer_active ? "active" : (p?.buzzer ? "on" : "off");
  const catIds = t.target_ids?.length ? t.target_ids.slice(0, 4).join("/") : t.target_id != null ? String(t.target_id) : null;
  $("lcdLine1").textContent = t.sonar_obstacle ? "OBSTACOL! h/j"
    : catIds ? `Cat id:${catIds}` : t.mode === "MANUAL" ? "Manual 0-200cm" : t.mode === "FOLLOW" ? "Follow 0-200cm" : "Dist 0-200cm";
  $("lcdLine2").textContent = cm != null ? `${cm} cm / ${range}cm` : `--- / ${range}cm`;
  const live = t.robot_connected && p;
  $("periphHint").textContent = live ? "CharBridge linked — toggles mirror firmware state."
    : !t.robot_connected ? "Connect the robot (USB @ 9600) to toggle peripherals."
    : "Connect CharBridge firmware to toggle on-rig feedback.";
  document.querySelectorAll(".btn.periph").forEach((b) => {
    b.disabled = !live;
    const act = b.dataset.periph;
    b.classList.toggle("active", !!(p && (
      (act === "buzzer_toggle" && p.buzzer) ||
      (act === "rgb_toggle" && p.rgb) ||
      (act === "lcd_toggle" && p.lcd)
    )));
    b.onclick = () => wsSend({ type: "peripheral", action: act });
  });
}

const PTZ_STEP = 0.25;
function renderPtz(t) {
  const enabled = !!t.ptz_available;
  $("ptzHint").textContent = enabled ? "" : "Tapo RTSP required for pan/tilt";
  document.querySelectorAll(".btn.ptz").forEach((b) => { b.disabled = !enabled; });
}
document.querySelectorAll(".btn.ptz").forEach((b) => {
  b.addEventListener("click", () => {
    if (!lastT?.ptz_available) return;
    const k = b.dataset.ptz;
    if (k === "home") post("/api/camera/ptz/preset", { name: "home" });
    else if (k === "up") post("/api/camera/ptz", { pan: 0, tilt: PTZ_STEP });
    else if (k === "down") post("/api/camera/ptz", { pan: 0, tilt: -PTZ_STEP });
    else if (k === "left") post("/api/camera/ptz", { pan: -PTZ_STEP, tilt: 0 });
    else if (k === "right") post("/api/camera/ptz", { pan: PTZ_STEP, tilt: 0 });
  });
});

async function loadCatLibrary() {
  msg("catsMsg", "loading…", "ok");
  const r = await (await fetch("/api/cats?limit=200")).json();
  if (!r.ok) { msg("catsMsg", r.problem || "failed to load cats", "warn"); return; }
  msg("catsMsg", `${r.cats.length} saved cat(s)`, "ok");
  const ul = $("catLibrary"); ul.innerHTML = "";
  r.cats.forEach((c) => {
    const li = document.createElement("li");
    const img = document.createElement("img");
    img.src = c.thumb_jpeg_b64 ? `data:image/jpeg;base64,${c.thumb_jpeg_b64}` : "";
    img.alt = c.name || `cat ${c.id}`;
    const body = document.createElement("div");
    body.innerHTML = `<b>${c.name || "Cat #" + c.id}</b><div class="meta">#${c.id} · ${c.sighting_count || 0} sightings</div>`;
    if (lastT?.overlay?.dets?.some((d) => d.track_id === c.id || d.known_track_ids?.includes(c.id)))
      body.innerHTML += `<span class="live-tag">Live</span>`;
    const actions = document.createElement("div");
    actions.className = "actions";
    const find = document.createElement("button");
    find.className = "btn"; find.textContent = "Find";
    find.dataset.help = "cat_library.find";
    find.onclick = () => wsSend({ type: "find_cat", library_id: c.id, follow: true });
    const ren = document.createElement("button");
    ren.className = "btn ghost"; ren.textContent = "Rename";
    ren.onclick = async () => {
      const name = prompt("Cat name", c.name || "");
      if (!name) return;
      await patch(`/api/cats/${c.id}`, { name });
      loadCatLibrary();
    };
    const delb = document.createElement("button");
    delb.className = "btn ghost"; delb.textContent = "Delete";
    delb.dataset.help = "cat_library.delete";
    delb.onclick = async () => { if (confirm("Delete this cat?")) { await del(`/api/cats/${c.id}`); loadCatLibrary(); } };
    actions.append(find, ren, delb);
    li.append(img, body, actions);
    ul.appendChild(li);
  });
  if (window.ConsoleHelp) ConsoleHelp.rescan(ul);
}
$("catsRefresh").addEventListener("click", loadCatLibrary);
function updateCatsFinding(t) {
  const el = $("catsFinding");
  if (t.find_library_id != null) {
    el.textContent = `Searching for ${t.find_library_name || "cat #" + t.find_library_id}…`;
    el.className = "conn-msg ok"; el.classList.remove("hidden");
  } else el.classList.add("hidden");
}

// ---------------------------------------------------------------- CV tab
document.querySelectorAll(".cv-sub").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".cv-sub").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("cvEval").classList.toggle("hidden", b.dataset.cv !== "eval");
    $("cvTrain").classList.toggle("hidden", b.dataset.cv !== "train");
    if (b.dataset.cv === "train") refreshTrainPanel();
  }));

const EVAL_SECTIONS = {
  fps: "Throughput (FPS)", tracking: "Track continuity", distance: "Distance accuracy",
  smoothness: "Command smoothness", reacquire: "Synthetic-occlusion re-acquire",
};
function fmtMetric(v) {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Number.isNaN(v)) return "n/a";
  return Number.isInteger(v) ? String(v) : Number(v).toFixed(4).replace(/\.?0+$/, "");
}
$("evalRun").addEventListener("click", async () => {
  $("evalMetrics").classList.add("hidden");
  $("evalReportWrap").classList.add("hidden");
  const r = await post("/api/eval/run", {
    source: $("evalSource").value || "data/raw/how_far",
    approach: $("evalApproach").value,
    classes: null,
    max_frames: parseInt($("evalMaxFrames").value, 10) || 0,
    use_depth: $("evalUseDepth").checked,
  });
  msg("evalStatus", r.ok ? `eval ${r.state}` : (r.problem || r.code), r.ok ? "ok" : "warn");
  if (r.ok) pollEval();
});
$("evalCancel").addEventListener("click", async () => {
  await post("/api/eval/cancel"); msg("evalStatus", "cancel requested", "ok");
});
async function pollEval() {
  const s = await (await fetch("/api/eval/status")).json();
  if (!s.ok) return;
  const prog = s.state === "running" && s.done != null
    ? ` · ${s.done}${s.total ? `/${s.total}` : ""} frames` : "";
  $("evalProgress").textContent = s.state + prog;
  msg("evalStatus", `eval ${s.state}${prog}`, s.state === "error" ? "warn" : "ok");
  if (s.state === "running") setTimeout(pollEval, 1000);
  else if (s.state === "done") loadEvalReport();
  else if (s.state === "error" && s.error) msg("evalStatus", `eval failed: ${s.error}`, "warn");
}
async function loadEvalReport() {
  const r = await (await fetch("/api/eval/report")).json();
  if (!r.ok) return;
  const grid = $("evalMetrics");
  grid.innerHTML = "";
  if (r.metrics) {
    Object.entries(r.metrics).forEach(([section, vals]) => {
      const card = document.createElement("div");
      card.className = "metric-card";
      card.innerHTML = `<h4>${EVAL_SECTIONS[section] || section}</h4>`;
      const table = document.createElement("table");
      Object.entries(vals).forEach(([k, v]) => {
        table.innerHTML += `<tr><td>${k}</td><td>${fmtMetric(v)}</td></tr>`;
      });
      card.appendChild(table);
      grid.appendChild(card);
    });
    grid.classList.remove("hidden");
  }
  if (r.markdown) {
    $("evalReport").textContent = r.markdown;
    $("evalReportWrap").classList.remove("hidden");
  }
}

let trainReadiness = null;
let trainHistory = [];
let confirmPromoteDir = null;
function refreshTrainKindUi() {
  const kind = $("trainKind").value;
  $("trainEpochsWrap").classList.toggle("hidden", kind !== "train");
  $("trainSourceWrap").classList.toggle("hidden", kind !== "prepare");
  updateTrainBlockReason();
}
$("trainKind").addEventListener("change", refreshTrainKindUi);
$("trainDevice").addEventListener("change", updateTrainBlockReason);
async function refreshTrainPanel() {
  refreshTrainKindUi();
  const r = await (await fetch("/api/train/readiness")).json();
  if (r.ok) trainReadiness = r;
  renderTrainReadiness();
  const h = await (await fetch("/api/train/history")).json();
  if (h.ok) { trainHistory = h.runs || []; renderTrainHistory(); }
  const s = await (await fetch("/api/train/status")).json();
  if (s.ok && s.state === "running") pollTrain();
  updateTrainBlockReason();
}
function renderTrainReadiness() {
  const el = $("trainReadiness");
  if (!trainReadiness) { el.textContent = "checking readiness…"; return; }
  const mk = (ok) => ok ? "ok" : "x";
  el.innerHTML = `<span class="k">readiness</span>
    ml-extra <b class="${trainReadiness.ml_available ? "ok" : "bad"}">${mk(trainReadiness.ml_available)}</b>
    dataset <b class="${trainReadiness.dataset_ready ? "ok" : "bad"}">${mk(trainReadiness.dataset_ready)}</b>
    device <b>${$("trainDevice").value}</b>
    IDLE <b class="${trainReadiness.idle ? "ok" : "bad"}">${mk(trainReadiness.idle)}</b>`;
}
function updateTrainBlockReason() {
  const kind = $("trainKind").value;
  const needsMl = kind === "train" || kind === "autoresearch";
  const needsDataset = kind === "train" || kind === "autoresearch";
  let reason = null;
  if (!trainReadiness) reason = "checking readiness…";
  else if (trainReadiness.running) reason = "a run is already in progress";
  else if (trainReadiness.eval_running) reason = "an eval is running — wait for it to finish";
  else if (!trainReadiness.idle) reason = "set IDLE to train";
  else if (needsMl && !trainReadiness.ml_available) reason = "ML extras missing — run `uv sync --extra ml`";
  else if (needsDataset && !trainReadiness.dataset_ready) reason = "no dataset — run prepare first";
  $("trainBlockReason").textContent = reason || "";
  $("trainRun").disabled = !!reason;
}
$("trainRun").addEventListener("click", async () => {
  const body = { kind: $("trainKind").value };
  const dev = $("trainDevice").value;
  if (dev !== "auto") body.device = dev;
  if (body.kind === "train") body.epochs = parseInt($("trainEpochs").value, 10) || 0;
  if (body.kind === "prepare") body.source = $("trainSource").value;
  const r = await post("/api/train/run", body);
  msg("trainStatus", r.ok ? `train ${r.state}` : (r.problem || r.code), r.ok ? "ok" : "warn");
  if (r.ok) pollTrain();
  else refreshTrainPanel();
});
$("trainCancel").addEventListener("click", async () => {
  await post("/api/train/cancel"); msg("trainStatus", "stop requested", "ok");
});
async function pollTrain() {
  const s = await (await fetch("/api/train/status")).json();
  if (!s.ok) return;
  let line = `train ${s.state}`;
  if (s.epoch != null) line += ` epoch ${s.epoch}/${s.total_epochs || "?"}`;
  if (s.elapsed_s != null) line += ` · ${Math.round(s.elapsed_s)}s`;
  msg("trainStatus", line, s.state === "error" ? "warn" : "ok");
  const log = $("trainLog");
  if (s.log_tail) { log.textContent = s.log_tail; log.classList.remove("hidden"); }
  if (s.state === "running") setTimeout(pollTrain, 1500);
  else refreshTrainPanel();
}
function renderTrainHistory() {
  const wrap = $("trainHistoryWrap");
  const ul = $("trainHistory");
  if (!trainHistory.length) { wrap.classList.add("hidden"); return; }
  wrap.classList.remove("hidden");
  ul.innerHTML = "";
  trainHistory.forEach((run) => {
    const li = document.createElement("li");
    const when = run.trained_at ? run.trained_at.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2}).*/, "$1-$2-$3 $4:$5") : run.dir;
    li.innerHTML = `<div><b>${run.kind || "train"}</b><div class="meta">${when} · ${run.metric != null ? fmtMetric(run.metric) : "—"}</div></div>`;
    const btn = document.createElement("button");
    btn.className = "btn ghost";
    btn.dataset.help = "train.promote";
    btn.textContent = confirmPromoteDir === run.dir ? "Confirm promote?" : "Promote";
    btn.onclick = async () => {
      if (confirmPromoteDir !== run.dir) { confirmPromoteDir = run.dir; renderTrainHistory(); return; }
      confirmPromoteDir = null;
      const r = await post("/api/train/promote", { run_dir: run.dir });
      msg("trainPromoteMsg", r.ok ? `promoted ${r.model_id}` : (r.problem || r.code), r.ok ? "ok" : "warn");
      refreshTrainPanel();
      loadModels();
    };
    li.appendChild(btn);
    ul.appendChild(li);
  });
  if (window.ConsoleHelp) ConsoleHelp.rescan(ul);
}

// ---------------------------------------------------------------- firmware flash
let flashPoll = null;
let flashBusy = false;
let flashReady = false;

function errText(e) {
  if (!e) return "unknown error";
  return `${e.problem || e.code || "error"}${e.cause ? ` (${e.cause})` : ""}${e.fix ? ` — ${e.fix}` : ""}`;
}

async function refreshFlashReadiness() {
  try {
    const r = await (await fetch("/api/robot/flash/readiness")).json();
    flashReady = !!r.ok;
    $("flashHint").textContent = r.ok
      ? (r.arduino_cli ? `ready · ${r.arduino_cli}` : "ready")
      : errText(r);
    updateFlashUi();
    return r;
  } catch (exc) {
    flashReady = false;
    $("flashHint").textContent = `flash readiness check failed — ${exc.message || exc}`;
    updateFlashUi();
    return { ok: false };
  }
}

function updateFlashUi() {
  const btn = $("flashFirmware");
  if (!btn) return;
  const port = selectedFlashPort();
  btn.disabled = flashBusy || !flashReady || !port;
  btn.textContent = flashBusy ? "Flashing…" : "Flash firmware (USB)";
}

function showFlashLog(text) {
  const el = $("flashLog");
  if (!text) { el.classList.add("hidden"); el.textContent = ""; return; }
  el.textContent = text;
  el.classList.remove("hidden");
}

async function pollFlashStatus() {
  let st;
  try {
    st = await (await fetch("/api/robot/flash/status")).json();
  } catch (exc) {
    clearInterval(flashPoll); flashPoll = null; flashBusy = false;
    msg("flashMsg", `status poll failed — ${exc.message || exc}`, "warn");
    updateFlashUi();
    return;
  }
  if (!st.ok) {
    clearInterval(flashPoll); flashPoll = null; flashBusy = false;
    msg("flashMsg", errText(st), "warn");
    updateFlashUi();
    return;
  }
  if (st.state === "running") {
    msg("flashMsg", `flashing… ${st.elapsed_s ?? 0}s (${st.port || "auto port"})`, "ok");
    return;
  }
  clearInterval(flashPoll); flashPoll = null; flashBusy = false;
  const result = st.result || {};
  if (st.state === "done" && result.ok !== false) {
    msg("flashMsg", "firmware uploaded — reconnect the robot on the port above", "ok");
    showFlashLog(result.log || "");
  } else {
    msg("flashMsg", errText({ problem: st.error || result.problem, cause: result.code, fix: result.fix }), "warn");
    showFlashLog(result.log || st.error || "");
  }
  updateFlashUi();
  refreshFlashReadiness();
}

async function startFlash() {
  msg("flashMsg", "", "ok");
  showFlashLog("");
  const ready = await refreshFlashReadiness();
  if (!ready.ok) { msg("flashMsg", $("flashHint").textContent, "warn"); return; }
  const port = selectedFlashPort();
  if (!port) {
    msg("flashMsg", "pick a USB port first — Scan USB ports, then choose your Arduino from the list", "warn");
    return;
  }
  if (port.includes("Bluetooth") || port.includes("debug-console")) {
    msg("flashMsg", "that port is not an Arduino USB device — pick usbserial/usbmodem", "warn");
    return;
  }
  flashBusy = true;
  updateFlashUi();
  try {
    const r = await post("/api/robot/flash", { port });
    if (!r.ok) {
      flashBusy = false;
      updateFlashUi();
      msg("flashMsg", errText(r), "warn");
      return;
    }
    $("robotTarget").value = port;
    msg("flashMsg", "compiling and uploading… (can take 1–3 min on first run)", "ok");
    msg("robotMsg", "robot disconnected for USB flash", "warn");
    clearInterval(flashPoll);
    flashPoll = setInterval(pollFlashStatus, 1500);
    pollFlashStatus();
  } catch (exc) {
    flashBusy = false;
    updateFlashUi();
    msg("flashMsg", `flash request failed — ${exc.message || exc}`, "warn");
  }
}

function initFlashPanel() {
  refreshFlashReadiness();
  if ($("flashPort") && !selectedFlashPort()) discoverPorts(true);
}

const flashBtn = $("flashFirmware");
if (flashBtn) {
  flashBtn.addEventListener("click", () => { void startFlash(); });
  $("flashPort")?.addEventListener("change", updateFlashUi);
  refreshFlashReadiness();
}

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

if (window.ConsoleHelp) ConsoleHelp.init();
connectWS();
