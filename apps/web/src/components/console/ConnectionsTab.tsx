"use client";

/** Camera (wireless) + robot (BT/USB/BLE) connections, with M5 device
 * auto-discovery feeding a pick-list instead of requiring a typed target. */

import { useEffect, useRef, useState } from "react";
import {
  api,
  apiBase,
  buildDefaultBase,
  setApiBase,
  clearApiBase,
  type CameraProfile,
} from "@/lib/api";
import { ControlTip, SectionHelp, SectionTitle } from "./help";

type Msg = { text: string; tone: "ok" | "warn" } | null;

export function ConnectionsTab() {
  const [baseInput, setBaseInput] = useState(() => apiBase());

  // setApiBase/clearApiBase notify the store; Console re-reads and remounts this
  // subtree (and the WS/MJPEG) against the new origin — no callback needed (R6).
  function saveBase() {
    setApiBase(baseInput);
  }
  function resetBase() {
    clearApiBase();
    setBaseInput(buildDefaultBase);
  }

  const [camSpec, setCamSpec] = useState("");
  const [camProfile, setCamProfile] = useState<CameraProfile>("go2_1080p");
  const [camMsg, setCamMsg] = useState<Msg>(null);
  const [sonarBaselineMm, setSonarBaselineMm] = useState(90);
  const [sonarCalMsg, setSonarCalMsg] = useState<Msg>(null);
  const [sonarCalBusy, setSonarCalBusy] = useState(false);

  const [conn, setConn] = useState("dummy");
  const [target, setTarget] = useState("");
  const [baud, setBaud] = useState(9600);
  const [robotMsg, setRobotMsg] = useState<Msg>(null);
  const [ports, setPorts] = useState<{ target: string; label: string }[]>([]);
  const [discoverHint, setDiscoverHint] = useState<string | null>(null);
  const [flashReady, setFlashReady] = useState<boolean | null>(null);
  const [flashHint, setFlashHint] = useState<string | null>(null);
  const [flashMsg, setFlashMsg] = useState<Msg>(null);
  const [flashBusy, setFlashBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function refreshFlashReadiness() {
    const r = await api.flashReadiness();
    setFlashReady(r.ok);
    setFlashHint(
      r.ok ? null : `${r.problem ?? "flash unavailable"}${r.fix ? ` — ${r.fix}` : ""}`,
    );
    return r;
  }

  useEffect(() => {
    void refreshFlashReadiness();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function connectCam() {
    const profile: CameraProfile = looksRtsp ? "tapo_c211" : camProfile;
    if (looksRtsp && camProfile !== "tapo_c211") {
      setCamProfile("tapo_c211");
    }
    const r = await api.connectCamera(camSpec || "synthetic", profile);
    if (r.ok) {
      // Uncalibrated intrinsics (placeholder distances) is a warn condition, not
      // a green ok — surface it WARN-toned so distance is never trusted blindly.
      const uncalibrated = !r.calibrated;
      const text = r.warning
        ? r.warning
        : uncalibrated
          ? `connected: ${r.label} — uncalibrated (${r.camera_profile}); distance is approximate`
          : `connected: ${r.label} (${r.camera_profile})`;
      setCamMsg({ text, tone: r.warning || uncalibrated ? "warn" : "ok" });
    } else {
      setCamMsg({ text: errText(r), tone: "warn" });
    }
  }

  // The Tapo speaks RTSP; suggest (do NOT auto-switch) the matching profile.
  const looksRtsp = /^rtsp:\/\//i.test(camSpec.trim());
  const suggestTapo = looksRtsp && camProfile !== "tapo_c211";

  async function discover() {
    setDiscoverHint("scanning…");
    const r = await api.discover();
    if (r.ok) {
      setPorts(r.serial);
      setDiscoverHint(r.hint ?? `${r.serial.length} port(s)${r.ble_available ? " · BLE available" : ""}`);
      void refreshFlashReadiness();
    } else {
      setDiscoverHint(r.problem);
    }
  }

  async function connectRobot() {
    const r = await api.connectRobot(conn, target || null, baud);
    if (r.ok)
      setRobotMsg({
        text: r.warning ?? `bridge: ${r.bridge} (${r.connected ? "live" : "sim"})`,
        tone: r.warning ? "warn" : r.connected ? "ok" : "warn",
      });
    else setRobotMsg({ text: errText(r), tone: "warn" });
  }

  async function calibrateDistanceWithSonar(dryRun = false) {
    setSonarCalBusy(true);
    setSonarCalMsg({ text: dryRun ? "previewing… (~5 s)" : "calibrating… (~5 s)", tone: "ok" });
    try {
      const profile: CameraProfile = looksRtsp ? "tapo_c211" : camProfile;
      const r = await api.calibrateWithSonar({
        camera: profile,
        baseline_m: sonarBaselineMm / 1000,
        dry_run: dryRun,
      });
      if (r.ok) {
        const bits = [
          dryRun ? "preview" : "saved",
          r.scale != null ? `scale ${r.scale.toFixed(3)}` : null,
          r.old_fy != null && r.new_fy != null ? `fy ${r.old_fy} → ${r.new_fy}` : null,
          r.n_samples != null ? `${r.n_samples} samples` : null,
        ].filter(Boolean);
        setSonarCalMsg({
          text: bits.join(" · "),
          tone: r.warning ? "warn" : "ok",
        });
      } else {
        setSonarCalMsg({ text: errText(r), tone: "warn" });
      }
    } finally {
      setSonarCalBusy(false);
    }
  }

  function stopFlashPoll() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setFlashBusy(false);
  }

  async function pollFlashStatus() {
    const st = await api.flashStatus();
    if (!st.ok) {
      stopFlashPoll();
      setFlashMsg({ text: errText(st), tone: "warn" });
      return;
    }
    if (st.state === "running") {
      setFlashMsg({ text: `flashing… ${st.elapsed_s ?? 0}s`, tone: "ok" });
      return;
    }
    stopFlashPoll();
    if (st.state === "done" && st.result?.ok) {
      setFlashMsg({ text: "firmware uploaded — reconnect the robot", tone: "ok" });
    } else {
      const problem = st.error ?? st.result?.problem ?? "flash failed";
      const fix = st.result?.fix;
      setFlashMsg({
        text: `${problem}${fix ? ` — ${fix}` : ""}`,
        tone: "warn",
      });
    }
  }

  async function flashFirmware() {
    setFlashMsg(null);
    const ready = await refreshFlashReadiness();
    if (!ready.ok) {
      setFlashMsg({
        text: `${ready.problem ?? "flash unavailable"}${ready.fix ? ` — ${ready.fix}` : ""}`,
        tone: "warn",
      });
      return;
    }
    const port = target.trim() || null;
    const r = await api.flashFirmware(port);
    if (!r.ok) {
      setFlashMsg({ text: errText(r), tone: "warn" });
      return;
    }
    setFlashBusy(true);
    setFlashMsg({ text: "compiling and uploading…", tone: "ok" });
    setRobotMsg({ text: "robot disconnected for USB flash", tone: "warn" });
    pollRef.current = setInterval(() => {
      void pollFlashStatus();
    }, 1500);
    void pollFlashStatus();
  }

  // Render the full typed error: problem (cause) — fix. The old code dropped
  // `cause`, which is often the most useful line (R14).
  const errText = (e: { problem: string; cause?: string; fix?: string }) =>
    `${e.problem}${e.cause ? ` (${e.cause})` : ""}${e.fix ? ` — ${e.fix}` : ""}`;

  const msgEl = (m: Msg) =>
    m && (
      <div className="mt-2 text-sm" style={{ color: m.tone === "ok" ? "var(--color-ok)" : "var(--color-warn)" }}>
        {m.text}
      </div>
    );

  const overridden = baseInput.replace(/\/$/, "") !== buildDefaultBase;

  return (
    <div className="flex flex-col gap-5">
      <section className="op-surface p-4">
        <h3 className="mb-2 inline-flex items-center gap-1.5 font-display font-semibold">
          Backend URL
          <SectionHelp helpId="conn.backend_save" />
        </h3>
        <p className="mb-2 text-xs text-dim">
          The control server (<code className="font-mono">catranger serve</code>).
          Saved in this browser and applied without a rebuild — point it at this
          machine&apos;s LAN IP (e.g. <code className="font-mono">http://192.168.1.42:8080</code>)
          for phone access, and add that origin to <code className="font-mono">cors_origins</code>{" "}
          in <code className="font-mono">configs/web.yaml</code>.
        </p>
        <input
          className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm font-mono"
          placeholder={buildDefaultBase}
          value={baseInput}
          onChange={(e) => setBaseInput(e.target.value)}
        />
        <div className="mt-2 flex items-center gap-2">
          <ControlTip helpId="conn.backend_save">
            <button type="button" className="op-btn" onClick={saveBase}>
              Save &amp; reconnect
            </button>
          </ControlTip>
          <ControlTip helpId="conn.backend_reset">
            <button type="button" className="op-btn" onClick={resetBase}>
              Reset to default
            </button>
          </ControlTip>
          <span className="ml-auto text-xs text-dim">
            {overridden ? "override active" : "build default"}
          </span>
        </div>
      </section>

      <section className="op-surface p-4">
        <SectionTitle helpId="conn.camera_connect" className="mb-2 font-display font-semibold">
          Camera (wireless)
        </SectionTitle>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm"
            placeholder="synthetic | 0 | rtsp://user:pass@ip:554/stream1"
            value={camSpec}
            onChange={(e) => setCamSpec(e.target.value)}
          />
          <ControlTip helpId="conn.camera_profile">
            <select
              className="rounded-md border border-line bg-bg px-3 py-2 text-sm"
              value={camProfile}
              onChange={(e) => setCamProfile(e.target.value as CameraProfile)}
              aria-label="Camera profile"
            >
              <option value="go2_1080p">go2_1080p</option>
              <option value="tapo_c211">tapo_c211</option>
            </select>
          </ControlTip>
        </div>
        {suggestTapo && (
          <div className="mt-2 text-xs text-warn">
            RTSP stream detected — use the <code className="font-mono">tapo_c211</code> profile
            for pan/tilt and Tapo distance intrinsics (auto-selected on Connect).
          </div>
        )}
        <p className="mt-2 text-xs text-dim">
          Tapo needs a Camera Account (Tapo app → Advanced → Camera Account), not
          your cloud login.
        </p>
        <div className="mt-2 flex gap-2">
          <ControlTip helpId="conn.camera_connect">
            <button type="button" className="op-btn" onClick={connectCam}>
              Connect
            </button>
          </ControlTip>
          <ControlTip helpId="conn.camera_synthetic">
            <button
              type="button"
              className="op-btn"
              onClick={async () => {
                await api.disconnectCamera();
                setCamMsg({ text: "using synthetic source", tone: "ok" });
              }}
            >
              Use synthetic
            </button>
          </ControlTip>
        </div>
        {msgEl(camMsg)}
      </section>

      <section className="op-surface p-4">
        <SectionTitle helpId="conn.sonar_calibrate" className="mb-2 font-display font-semibold">
          Distance calibration (HC-SR04)
        </SectionTitle>
        <p className="text-xs text-dim">
          Uses live vision distance vs the ultrasonic sensor. The camera sits behind the
          sensor along the boresight — default offset is 90&nbsp;mm (sensor reading + offset
          = camera ground truth).
        </p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="flex items-center gap-2 text-sm">
            <span className="inline-flex items-center gap-1 text-dim whitespace-nowrap">
              Sensor → camera
              <SectionHelp helpId="conn.sonar_offset" />
            </span>
            <input
              type="number"
              min={0}
              max={500}
              className="w-24 rounded-md border border-line bg-bg px-3 py-2 text-sm"
              value={sonarBaselineMm}
              onChange={(e) => setSonarBaselineMm(parseInt(e.target.value, 10) || 0)}
              aria-label="Sensor to camera offset in millimeters"
            />
            <span className="text-dim">mm</span>
          </label>
          <div className="flex flex-wrap gap-2">
            <ControlTip helpId="conn.sonar_calibrate">
              <button
                type="button"
                className="op-btn"
                disabled={sonarCalBusy}
                onClick={() => void calibrateDistanceWithSonar(false)}
              >
                {sonarCalBusy ? "Sampling…" : "Calibrate (~5 s)"}
              </button>
            </ControlTip>
            <ControlTip helpId="conn.sonar_preview">
              <button
                type="button"
                className="op-btn"
                disabled={sonarCalBusy}
                onClick={() => void calibrateDistanceWithSonar(true)}
              >
                Preview
              </button>
            </ControlTip>
          </div>
        </div>
        <p className="mt-2 text-xs text-dim">
          Connect camera + robot USB, track a cat (or flat target), hold 25–180&nbsp;cm from
          the sonar with a steady echo.
        </p>
        {msgEl(sonarCalMsg)}
      </section>

      <section className="op-surface p-4">
        <div className="mb-2 flex items-center justify-between">
          <SectionTitle helpId="conn.robot_connect" className="font-display font-semibold">
            Robot (Bluetooth / USB)
          </SectionTitle>
          <ControlTip helpId="conn.robot_scan">
            <button type="button" className="op-btn" onClick={discover}>
              Scan devices
            </button>
          </ControlTip>
        </div>
        <div className="flex flex-col gap-2">
          <ControlTip helpId="conn.robot_type">
            <select
              className="rounded-md border border-line bg-bg px-3 py-2 text-sm"
              value={conn}
              onChange={(e) => setConn(e.target.value)}
            >
            <option value="dummy">dummy (simulation)</option>
            <option value="bt">bt — HC-05 SPP</option>
            <option value="ble">ble — HM-10</option>
            <option value="usb">usb — serial (char @ 9600)</option>
            </select>
          </ControlTip>
          {ports.length > 0 && (
            <select
              className="rounded-md border border-line bg-bg px-3 py-2 text-sm"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">— pick a discovered port —</option>
              {ports.map((p) => (
                <option key={p.target} value={p.target}>
                  {p.label}
                </option>
              ))}
            </select>
          )}
          <input
            className="rounded-md border border-line bg-bg px-3 py-2 text-sm"
            placeholder="/dev/cu.HC-05... or BLE address"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
          <input
            type="number"
            className="rounded-md border border-line bg-bg px-3 py-2 text-sm"
            value={baud}
            onChange={(e) => setBaud(parseInt(e.target.value, 10) || 9600)}
          />
          <div className="flex flex-wrap gap-2">
            <ControlTip helpId="conn.robot_connect">
              <button type="button" className="op-btn" onClick={connectRobot}>
                Connect
              </button>
            </ControlTip>
            <ControlTip helpId="conn.robot_disconnect">
              <button
                type="button"
                className="op-btn"
                onClick={async () => {
                  await api.disconnectRobot();
                  setRobotMsg({ text: "disconnected (simulation)", tone: "ok" });
                }}
              >
                Disconnect
              </button>
            </ControlTip>
            <ControlTip helpId="conn.robot_flash">
              <button
                type="button"
                className="op-btn"
                disabled={flashBusy}
                onClick={() => void flashFirmware()}
              >
                {flashBusy ? "Flashing…" : "Flash firmware (USB)"}
              </button>
            </ControlTip>
          </div>
        </div>
        {flashHint && flashReady === false && (
          <div className="mt-2 text-xs text-warn">{flashHint}</div>
        )}
        {msgEl(flashMsg)}
        {discoverHint && <div className="mt-2 text-xs text-dim">{discoverHint}</div>}
        {msgEl(robotMsg)}
      </section>
    </div>
  );
}
