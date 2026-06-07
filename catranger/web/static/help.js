// Operator console help — tooltips + detail modals (mirrors apps/web console-help.ts).
"use strict";

const HELP = {
  "tab.control": {
    title: "Control tab",
    tip: "Drive, pick cats, and toggle on-rig peripherals.",
    detail:
      "Live teleoperation and target selection. Switch MANUAL to drive, FOLLOW to track a cat, or IDLE to park. Peripherals (buzzer, RGB, LCD) work whenever the robot USB link is up — they do not require MANUAL mode or the drive token.",
  },
  "tab.cats": {
    title: "Cats tab",
    tip: "Saved cat faces from past sightings — find cats that left the frame.",
    detail:
      "Cats are saved automatically when detected. Click Find to enter FOLLOW mode: the robot rotates toward the last known bearing and matches the saved face when the cat reappears. Rename a cat by clicking its name.",
  },
  "tab.models": {
    title: "Models tab",
    tip: "Hot-swap the vision detector without restarting the server.",
    detail:
      "Models come from configs/models.yaml and training run history. Selecting a model reloads weights on the backend. Perception must be ready before the cat picker and distance readouts are trustworthy.",
  },
  "tab.connections": {
    title: "Connections tab",
    tip: "Camera, robot link, calibration, and firmware flash.",
    detail:
      "One-time setup: connect your camera (USB index, synthetic, or Tapo RTSP), and connect the robot over USB/BT/BLE. Use sonar calibration to align vision distance with the HC-SR04. Flash firmware only over USB — it disconnects the live link.",
  },
  "tab.cv": {
    title: "CV tab",
    tip: "Offline evaluation and model training (server must be IDLE).",
    detail:
      "Eval runs metrics on recorded video or image folders. Training fine-tunes detectors via prepare/train/autoresearch. Both are CPU/GPU heavy; the server blocks them unless the robot mode is IDLE.",
  },
  "cv.sub.eval": {
    title: "Eval sub-tab",
    tip: "Batch metrics on a dataset — not live webcam.",
    detail:
      "Runs the perception pipeline on a folder of images or a video file. Reports FPS, tracking continuity, distance accuracy (when labels exist), command smoothness, and synthetic re-acquire tests. Requires IDLE mode.",
  },
  "cv.sub.training": {
    title: "Training sub-tab",
    tip: "Prepare datasets, fine-tune, or run autoresearch loops.",
    detail:
      "prepare builds a dataset from Roboflow, Open Images, or manual exports. train fine-tunes YOLO on your data. autoresearch loops keep/reject trials. All jobs require IDLE, ML extras (uv sync --extra ml), and a prepared dataset for train/autoresearch.",
  },
  "mode.idle": { title: "IDLE mode", tip: "Motors off — safe default for config and heavy jobs.", detail: "IDLE stops drive intents and is required before eval or training starts. Peripherals and camera PTZ still work." },
  "mode.manual": { title: "MANUAL mode", tip: "Press-and-hold drive pad — release to stop.", detail: "Only the operator holding the drive token can send motion intents. Hold a direction or W/A/S/D; releasing sends stop." },
  "mode.follow": { title: "FOLLOW mode", tip: "Chassis follows the locked or preferred cat target.", detail: "Requires a loaded model, live camera, and a tracked cat. Pick a cat in the picker or use Auto (largest box)." },
  "safety.estop": { title: "E-STOP", tip: "Immediate hardware stop — always available.", detail: "Latches software motion and alerts the firmware. Sent over REST so it works even if the WebSocket is down. After E-STOP, use ARM / RESET to clear." },
  "safety.reset": { title: "ARM / RESET", tip: "Clear E-STOP latch and re-arm motion.", detail: "Only shown while E-STOP is latched. Confirms it is safe to move again." },
  "drive.forward": { title: "Drive forward", tip: "Hold to drive forward — release to stop." },
  "drive.back": { title: "Drive reverse", tip: "Hold to reverse — release to stop." },
  "drive.left": { title: "Turn left", tip: "Hold to turn left — release to stop." },
  "drive.right": { title: "Turn right", tip: "Hold to turn right — release to stop." },
  "drive.stop": { title: "Stop", tip: "Send an immediate stop intent." },
  "drive.request_control": { title: "Request control", tip: "Ask to become the sole drive operator.", detail: "Only one browser tab holds the drive token at a time. Observers can watch telemetry but cannot drive." },
  "drive.speed": { title: "Drive speed", tip: "Scaler for forward/back and turn intents (0.1–1.0)." },
  "drive.body_yaw": { title: "Body yaw", tip: "Rotate the robot chassis — not the camera PTZ." },
  "cat.select": { title: "Select cat", tip: "Lock tracking onto this cat ID." },
  "cat.follow": { title: "Follow cat", tip: "Lock this cat and switch to FOLLOW mode." },
  "cat.auto": { title: "Auto (largest)", tip: "Clear preferred ID — tracker picks largest box." },
  "cat.auto_follow": { title: "Auto + FOLLOW", tip: "Clear lock and enter FOLLOW on largest cat." },
  "section.cats": { title: "Cats in view", tip: "Detected cats with thumbnails and distance.", detail: "Each card shows a tracker ID, model distance, confidence, and bearing. Select locks the ID; Follow also engages FOLLOW mode." },
  "section.cat_library": { title: "Cat library", tip: "Persistent saved faces — find cats not currently on camera.", detail: "Find drives the robot in FOLLOW mode and locks on when the face matches again." },
  "cat_library.find": { title: "Find saved cat", tip: "Drive and scan to re-acquire this cat by face." },
  "cat_library.delete": { title: "Delete saved cat", tip: "Remove this cat from the library database." },
  "periph.buzzer": { title: "Buzzer toggle", tip: "Enable/disable proximity beeps on the rig." },
  "periph.rgb": { title: "RGB toggle", tip: "Enable/disable distance-colored LED." },
  "periph.lcd": { title: "LCD toggle", tip: "Enable/disable the 16×2 distance display." },
  "periph.all_on": { title: "All peripherals on", tip: "Turn buzzer, RGB, and LCD on together." },
  "periph.all_off": { title: "All peripherals off", tip: "Turn buzzer, RGB, and LCD off together." },
  "section.peripherals": { title: "Rig sensors & peripherals", tip: "Sonar ground truth, RGB bands, buzzer, LCD mirror.", detail: "HC-SR04 provides ground-truth distance (0–200 cm). Toggles need CharBridge firmware on USB @ 9600." },
  "ptz.up": { title: "Tilt up", tip: "Nudge camera tilt up (Tapo only)." },
  "ptz.down": { title: "Tilt down", tip: "Nudge camera tilt down (Tapo only)." },
  "ptz.left": { title: "Pan left", tip: "Nudge camera pan left (Tapo only)." },
  "ptz.right": { title: "Pan right", tip: "Nudge camera pan right (Tapo only)." },
  "ptz.home": { title: "Camera home", tip: "Recall Tapo home preset.", detail: "Pan/tilt moves the camera mount only — not the robot chassis. Requires Tapo C211 RTSP." },
  "section.ptz": { title: "Camera pan/tilt", tip: "Tapo motor control — independent of drive mode.", detail: "Only available when connected via Tapo RTSP. Body yaw on the drive pad rotates the robot, not the camera." },
  "conn.camera_connect": { title: "Connect camera", tip: "Open USB index, synthetic, or RTSP source.", detail: "Synthetic is for UI testing. Tapo RTSP needs a Camera Account (Tapo app → Advanced), not your cloud password." },
  "conn.camera_synthetic": { title: "Use synthetic", tip: "Switch to built-in test pattern — no hardware." },
  "conn.camera_profile": { title: "Camera profile", tip: "Intrinsics and distortion model for distance.", detail: "go2_1080p — default USB/laptop profile. tapo_c211 — Tapo pan/tilt + calibrated intrinsics." },
  "conn.sonar_calibrate": { title: "Calibrate distance", tip: "Scale vision fy using sonar + offset (~5 s).", detail: "Collects paired samples while tracking a target. Connect camera and robot USB; hold 25–180 cm with steady echo." },
  "conn.sonar_preview": { title: "Preview calibration", tip: "Dry run — shows scale without saving YAML." },
  "conn.sonar_offset": { title: "Sensor → camera offset", tip: "Millimeters from HC-SR04 to camera along boresight.", detail: "Default 90 mm. Calibration compares vision distance to sonar + this offset." },
  "conn.robot_scan": { title: "Scan devices", tip: "List serial ports and BLE availability." },
  "conn.robot_connect": { title: "Connect robot", tip: "Open dummy, BT, BLE, or USB CharBridge link." },
  "conn.robot_disconnect": { title: "Disconnect robot", tip: "Close link and fall back to simulation." },
  "conn.robot_flash": { title: "Flash firmware", tip: "Upload cat_ranger.ino over USB (disconnects link).", detail: "Requires arduino-cli on the server. Pick the USB port, then flash — reconnect after upload." },
  "conn.robot_type": { title: "Connection type", tip: "dummy | bt | ble | usb — CharBridge expects USB @ 9600." },
  "models.use": { title: "Use model", tip: "Hot-swap active detector on the server." },
  "eval.run": { title: "Run eval", tip: "Start batch eval — robot must be IDLE." },
  "eval.cancel": { title: "Cancel eval", tip: "Stop the running eval job." },
  "train.run": { title: "Run training", tip: "Start prepare/train/autoresearch — IDLE required." },
  "train.stop": { title: "Stop training", tip: "Cancel the current training job." },
  "train.promote": { title: "Promote run", tip: "Add this run's best.pt to the model registry.", detail: "Promoted weights appear in the Models tab for hot-swap." },
  "telemetry.distance": { title: "Distance", tip: "Vision range to locked target (meters).", detail: "From the active detector + camera intrinsics. Run sonar calibration if marked uncalibrated." },
  "telemetry.ground_truth": { title: "Ground truth", tip: "HC-SR04 sonar distance (meters).", detail: "Ultrasonic reading on the rig — independent of the camera model." },
  "telemetry.target": { title: "Target", tip: "Locked tracker ID(s) or count of cats seen." },
  "telemetry.fps": { title: "FPS", tip: "End-to-end perception frame rate." },
  "telemetry.camera_pill": { title: "Camera status", tip: "Active camera source and connection state." },
  "telemetry.robot_pill": { title: "Robot status", tip: "Bridge type and live vs simulation." },
  "telemetry.model_pill": { title: "Model status", tip: "Active detector and load state." },
};

const SHOW_MS = 400;
const HIDE_MS = 100;

let tooltipEl = null;
let modalRoot = null;
let showTimer = null;
let hideTimer = null;
let activeHost = null;

function getHelp(id) {
  return HELP[id] || { title: id, tip: "" };
}

function clearTimers() {
  if (showTimer) clearTimeout(showTimer);
  if (hideTimer) clearTimeout(hideTimer);
  showTimer = hideTimer = null;
}

function hideTooltip() {
  clearTimers();
  if (tooltipEl) tooltipEl.classList.add("hidden");
  activeHost = null;
}

function positionTooltip(host) {
  if (!tooltipEl || !host) return;
  const r = host.getBoundingClientRect();
  tooltipEl.style.left = `${r.left + r.width / 2}px`;
  tooltipEl.style.top = `${r.top - 8}px`;
}

function showTooltip(host, text) {
  if (!tooltipEl || !text) return;
  activeHost = host;
  tooltipEl.textContent = text;
  positionTooltip(host);
  tooltipEl.classList.remove("hidden");
}

function scheduleShow(host, text) {
  clearTimers();
  showTimer = setTimeout(() => showTooltip(host, text), SHOW_MS);
}

function scheduleHide() {
  clearTimers();
  hideTimer = setTimeout(hideTooltip, HIDE_MS);
}

function bindTooltip(el, helpId) {
  const entry = getHelp(helpId);
  if (!entry.tip) return;
  el.dataset.helpBound = helpId;
  const onShow = () => scheduleShow(el, entry.tip);
  const onHide = () => scheduleHide();
  el.addEventListener("mouseenter", onShow);
  el.addEventListener("mouseleave", onHide);
  el.addEventListener("focus", onShow);
  el.addEventListener("blur", onHide);
}

function openModal(helpId) {
  const entry = getHelp(helpId);
  if (!modalRoot) return;
  modalRoot.querySelector(".help-modal-title").textContent = entry.title;
  modalRoot.querySelector(".help-modal-body").textContent = entry.detail || entry.tip;
  modalRoot.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  modalRoot.querySelector(".help-modal-close").focus();
}

function closeModal() {
  if (!modalRoot) return;
  modalRoot.classList.add("hidden");
  document.body.style.overflow = "";
}

function ensureChrome() {
  if (!tooltipEl) {
    tooltipEl = document.createElement("span");
    tooltipEl.className = "help-tooltip hidden";
    tooltipEl.setAttribute("role", "tooltip");
    document.body.appendChild(tooltipEl);
    window.addEventListener("scroll", () => activeHost && positionTooltip(activeHost), true);
    window.addEventListener("resize", () => activeHost && positionTooltip(activeHost));
  }
  if (!modalRoot) {
    modalRoot = document.createElement("div");
    modalRoot.className = "help-modal-root hidden";
    modalRoot.innerHTML =
      '<button type="button" class="help-modal-backdrop" aria-label="Close help"></button>' +
      '<div class="help-modal-panel" role="dialog" aria-modal="true">' +
      '<header class="help-modal-header">' +
      '<h2 class="help-modal-title"></h2>' +
      '<button type="button" class="btn ghost help-modal-close">Close</button>' +
      "</header>" +
      '<div class="help-modal-body"></div>' +
      "</div>";
    document.body.appendChild(modalRoot);
    modalRoot.querySelector(".help-modal-backdrop").addEventListener("click", closeModal);
    modalRoot.querySelector(".help-modal-close").addEventListener("click", closeModal);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modalRoot && !modalRoot.classList.contains("hidden")) closeModal();
    });
  }
}

function injectSectionHelp(el) {
  const id = el.dataset.helpSection;
  if (!id || el.dataset.helpSectionDone) return;
  const entry = getHelp(id);
  el.dataset.helpSectionDone = "1";
  el.classList.add("section-title-row");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "help-info-btn";
  btn.textContent = "i";
  btn.setAttribute("aria-label", entry.detail ? `More about ${entry.title}` : `Help: ${entry.title}`);
  bindTooltip(btn, id);
  if (entry.detail) {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openModal(id);
    });
  }
  el.appendChild(btn);
}

function bindElement(el) {
  const id = el.dataset.help;
  if (!id || el.dataset.helpBound) return;
  bindTooltip(el, id);
}

function rescan(root) {
  ensureChrome();
  const scope = root || document;
  scope.querySelectorAll("[data-help-section]").forEach(injectSectionHelp);
  scope.querySelectorAll("[data-help]").forEach(bindElement);
}

function init() {
  ensureChrome();
  rescan(document);
}

window.ConsoleHelp = { init, rescan, bind: bindElement, open: openModal, HELP };
