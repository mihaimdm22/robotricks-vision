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
  $("target").textContent = t.target_id != null ? "id " + t.target_id : (t.n_cats ? t.n_cats + " seen" : "none");

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
    li.innerHTML = `<div><b>${m.name}</b><div class="meta">${m.backend} · ${m.dataset || ""}</div></div>`;
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

connectWS();
