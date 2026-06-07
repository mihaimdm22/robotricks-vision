/**
 * Central help copy for the operator console.
 * `tip` — short label for hover/focus tooltips (≤ ~120 chars).
 * `detail` — longer explanation shown in the help modal.
 */

export type HelpEntry = {
  title: string;
  tip: string;
  detail?: string;
};

export const HELP = {
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
    tip: "Backend URL, camera, robot link, calibration, and firmware flash.",
    detail:
      "One-time setup: point the browser at catranger serve, connect your camera (USB index, synthetic, or Tapo RTSP), and connect the robot over USB/BT/BLE. Use sonar calibration to align vision distance with the HC-SR04. Flash firmware only over USB — it disconnects the live link.",
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
  "mode.idle": {
    title: "IDLE mode",
    tip: "Motors off — safe default for config and heavy jobs.",
    detail:
      "IDLE stops drive intents and is required before eval or training starts. Peripherals and camera PTZ still work. Use IDLE when you are not actively driving or following.",
  },
  "mode.manual": {
    title: "MANUAL mode",
    tip: "Press-and-hold drive pad — release to stop.",
    detail:
      "Only the operator holding the drive token can send motion intents. Hold a direction or W/A/S/D; releasing sends stop. A 200 ms heartbeat keeps the watchdog happy while parked in MANUAL.",
  },
  "mode.follow": {
    title: "FOLLOW mode",
    tip: "Chassis follows the locked or preferred cat target.",
    detail:
      "Requires a loaded model, live camera, and a tracked cat. Pick a cat in the picker or use Auto (largest box). FOLLOW uses vision bearing and distance — calibrate the camera for reliable range.",
  },
  "safety.estop": {
    title: "E-STOP",
    tip: "Immediate hardware stop — always available.",
    detail:
      "Latches software motion and alerts the firmware. Sent over REST so it works even if the telemetry WebSocket is down. Does not require the drive token. After E-STOP, use ARM / RESET to clear and resume.",
  },
  "safety.reset": {
    title: "ARM / RESET",
    tip: "Clear E-STOP latch and re-arm motion.",
    detail:
      "Only shown while E-STOP is latched. Confirms it is safe to move again. You may still need to switch back to MANUAL or FOLLOW after reset.",
  },
  "drive.forward": {
    title: "Drive forward",
    tip: "Hold to drive forward — release to stop.",
  },
  "drive.back": {
    title: "Drive reverse",
    tip: "Hold to reverse — release to stop.",
  },
  "drive.left": {
    title: "Turn left",
    tip: "Hold to turn left — release to stop.",
  },
  "drive.right": {
    title: "Turn right",
    tip: "Hold to turn right — release to stop.",
  },
  "drive.stop": {
    title: "Stop",
    tip: "Send an immediate stop intent.",
  },
  "drive.request_control": {
    title: "Request control",
    tip: "Ask to become the sole drive operator.",
    detail:
      "Only one browser tab holds the drive token at a time. Observers can watch telemetry but cannot drive. Requesting control transfers the token if the server allows it.",
  },
  "drive.speed": {
    title: "Drive speed",
    tip: "Scaler for forward/back and turn intents (0.1–1.0).",
  },
  "drive.body_yaw": {
    title: "Body yaw",
    tip: "Rotate the robot chassis — not the camera PTZ.",
  },
  "cat.select": {
    title: "Select cat",
    tip: "Lock tracking onto this cat ID.",
  },
  "cat.follow": {
    title: "Follow cat",
    tip: "Lock this cat and switch to FOLLOW mode.",
  },
  "cat.auto": {
    title: "Auto (largest)",
    tip: "Clear preferred ID — tracker picks largest box.",
  },
  "cat.auto_follow": {
    title: "Auto + FOLLOW",
    tip: "Clear lock and enter FOLLOW on largest cat.",
  },
  "section.cats": {
    title: "Cats in view",
    tip: "Detected cats with thumbnails and distance.",
    detail:
      "Each card shows a tracker ID, model distance, confidence, and bearing. Select locks the ID for tracking; Follow also engages FOLLOW mode. Cats remain listed when they leave the frame (out of view). Auto returns to largest-detection wins.",
  },
  "section.cat_library": {
    title: "Cat library",
    tip: "Persistent saved faces — find cats not currently on camera.",
    detail:
      "Thumbnails are captured while cats are visible and stored in outputs/cat_library.sqlite3. Find drives the robot in FOLLOW mode, biases search toward the last bearing, and locks on when the face matches again.",
  },
  "cat_library.find": {
    title: "Find saved cat",
    tip: "Drive and scan to re-acquire this cat by face.",
  },
  "cat_library.delete": {
    title: "Delete saved cat",
    tip: "Remove this cat from the library database.",
  },
  "periph.buzzer": {
    title: "Buzzer toggle",
    tip: "Enable/disable proximity beeps on the rig.",
  },
  "periph.rgb": {
    title: "RGB toggle",
    tip: "Enable/disable distance-colored LED.",
  },
  "periph.lcd": {
    title: "LCD toggle",
    tip: "Enable/disable the 16×2 distance display.",
  },
  "periph.all_on": {
    title: "All peripherals on",
    tip: "Turn buzzer, RGB, and LCD on together.",
  },
  "periph.all_off": {
    title: "All peripherals off",
    tip: "Turn buzzer, RGB, and LCD off together.",
  },
  "section.peripherals": {
    title: "Rig sensors & peripherals",
    tip: "Sonar ground truth, RGB bands, buzzer, LCD mirror.",
    detail:
      "HC-SR04 provides ground-truth distance (0–200 cm). RGB color follows distance bands. Buzzer beeps faster below ~180 cm. LCD mirrors the same state. Toggles need CharBridge firmware on USB @ 9600 — not MANUAL mode.",
  },
  "ptz.up": { title: "Tilt up", tip: "Nudge camera tilt up (Tapo only)." },
  "ptz.down": { title: "Tilt down", tip: "Nudge camera tilt down (Tapo only)." },
  "ptz.left": { title: "Pan left", tip: "Nudge camera pan left (Tapo only)." },
  "ptz.right": { title: "Pan right", tip: "Nudge camera pan right (Tapo only)." },
  "ptz.home": {
    title: "Camera home",
    tip: "Recall Tapo home preset.",
    detail: "Pan/tilt moves the camera mount only — not the robot chassis. Requires Tapo C211 RTSP with Camera Account credentials.",
  },
  "section.ptz": {
    title: "Camera pan/tilt",
    tip: "Tapo motor control — independent of drive mode.",
    detail:
      "Only available when connected via Tapo RTSP (tapo_c211 profile). Works in any robot mode and without the drive token. Body yaw on the drive pad rotates the robot, not the camera.",
  },
  "video.retry": {
    title: "Retry video",
    tip: "Reload the MJPEG stream after a load failure.",
  },
  "conn.backend_save": {
    title: "Save backend URL",
    tip: "Apply URL and reconnect WebSocket + video.",
    detail:
      "Stored in this browser. Use your machine LAN IP for phone access and add that origin to cors_origins in configs/web.yaml.",
  },
  "conn.backend_reset": {
    title: "Reset backend URL",
    tip: "Restore the build-time default API origin.",
  },
  "conn.camera_connect": {
    title: "Connect camera",
    tip: "Open USB index, synthetic, or RTSP source.",
    detail:
      "Synthetic is for UI testing. USB index 0 is the default webcam. Tapo RTSP needs a Camera Account (Tapo app → Advanced), not your cloud password. RTSP auto-selects tapo_c211 on connect.",
  },
  "conn.camera_synthetic": {
    title: "Use synthetic",
    tip: "Switch to built-in test pattern — no hardware.",
  },
  "conn.camera_profile": {
    title: "Camera profile",
    tip: "Intrinsics and distortion model for distance.",
    detail:
      "go2_1080p — default USB/laptop profile. tapo_c211 — Tapo pan/tilt + calibrated intrinsics. Wrong profile makes distance approximate until sonar calibration.",
  },
  "conn.sonar_calibrate": {
    title: "Calibrate distance",
    tip: "Scale vision fy using sonar + offset (~5 s).",
    detail:
      "Collects paired samples while tracking a target. Ground truth = sonar reading + sensor-to-camera offset (default 90 mm). Connect camera and robot USB; hold 25–180 cm with steady echo.",
  },
  "conn.sonar_preview": {
    title: "Preview calibration",
    tip: "Dry run — shows scale without saving YAML.",
  },
  "conn.sonar_offset": {
    title: "Sensor → camera offset",
    tip: "Millimeters from HC-SR04 to camera along boresight.",
    detail:
      "The ultrasonic sensor is the ground-truth reference. The camera sits behind it along the aim direction — default 90 mm. Calibration compares vision distance to sonar + this offset.",
  },
  "conn.robot_scan": {
    title: "Scan devices",
    tip: "List serial ports and BLE availability.",
  },
  "conn.robot_connect": {
    title: "Connect robot",
    tip: "Open dummy, BT, BLE, or USB CharBridge link.",
  },
  "conn.robot_disconnect": {
    title: "Disconnect robot",
    tip: "Close link and fall back to simulation.",
  },
  "conn.robot_flash": {
    title: "Flash firmware",
    tip: "Upload cat_ranger.ino over USB (disconnects link).",
    detail:
      "Requires arduino-cli on the server. Picks the selected port or auto-detects. The runtime USB connection drops during flash — reconnect after upload.",
  },
  "conn.robot_type": {
    title: "Connection type",
    tip: "dummy | bt | ble | usb — CharBridge expects USB @ 9600.",
  },
  "models.use": {
    title: "Use model",
    tip: "Hot-swap active detector on the server.",
  },
  "eval.run": {
    title: "Run eval",
    tip: "Start batch eval — robot must be IDLE.",
  },
  "eval.cancel": {
    title: "Cancel eval",
    tip: "Stop the running eval job.",
  },
  "train.run": {
    title: "Run training",
    tip: "Start prepare/train/autoresearch — IDLE required.",
  },
  "train.stop": {
    title: "Stop training",
    tip: "Cancel the current training job.",
  },
  "train.promote": {
    title: "Promote run",
    tip: "Add this run's best.pt to the model registry.",
    detail:
      "Two-step confirm. Promoted weights appear in the Models tab for hot-swap. Does not auto-select — pick Use after promote.",
  },
  "train.confirm": {
    title: "Confirm promote",
    tip: "Permanently register this run in models.yaml.",
  },
  "train.promote_cancel": {
    title: "Cancel promote",
    tip: "Dismiss promote confirmation.",
  },
  "telemetry.distance": {
    title: "Distance",
    tip: "Vision range to locked target (meters).",
    detail:
      "From the active detector + camera intrinsics. Shows ~ uncalibrated when intrinsics are placeholders — run sonar calibration or use a calibrated profile.",
  },
  "telemetry.ground_truth": {
    title: "Ground truth",
    tip: "HC-SR04 sonar distance (meters).",
    detail:
      "Ultrasonic reading on the rig — independent of the camera model. Used for calibration and peripheral bands (0–200 cm).",
  },
  "telemetry.target": {
    title: "Target",
    tip: "Locked tracker ID(s) or count of cats seen.",
  },
  "telemetry.fps": {
    title: "FPS",
    tip: "End-to-end perception frame rate.",
  },
  "telemetry.camera_pill": {
    title: "Camera status",
    tip: "Active camera source and connection state.",
  },
  "telemetry.robot_pill": {
    title: "Robot status",
    tip: "Bridge type and live vs simulation.",
  },
  "telemetry.model_pill": {
    title: "Model status",
    tip: "Active detector and load state.",
  },
} as const satisfies Record<string, HelpEntry>;

export type HelpId = keyof typeof HELP;

export function getHelp(id: HelpId): HelpEntry {
  return HELP[id];
}
