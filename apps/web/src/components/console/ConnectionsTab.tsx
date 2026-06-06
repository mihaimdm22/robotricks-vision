"use client";

/** Camera (wireless) + robot (BT/USB/BLE) connections, with M5 device
 * auto-discovery feeding a pick-list instead of requiring a typed target. */

import { useState } from "react";
import { api } from "@/lib/api";

type Msg = { text: string; tone: "ok" | "warn" } | null;

export function ConnectionsTab() {
  const [camSpec, setCamSpec] = useState("");
  const [camMsg, setCamMsg] = useState<Msg>(null);

  const [conn, setConn] = useState("dummy");
  const [target, setTarget] = useState("");
  const [baud, setBaud] = useState(115200);
  const [robotMsg, setRobotMsg] = useState<Msg>(null);
  const [ports, setPorts] = useState<{ target: string; label: string }[]>([]);
  const [discoverHint, setDiscoverHint] = useState<string | null>(null);

  async function connectCam() {
    const r = await api.connectCamera(camSpec || "synthetic");
    if (r.ok) setCamMsg({ text: r.warning ?? `connected: ${r.label}`, tone: r.warning ? "warn" : "ok" });
    else setCamMsg({ text: `${r.problem}${r.fix ? ` — ${r.fix}` : ""}`, tone: "warn" });
  }

  async function discover() {
    setDiscoverHint("scanning…");
    const r = await api.discover();
    if (r.ok) {
      setPorts(r.serial);
      setDiscoverHint(r.hint ?? `${r.serial.length} port(s)${r.ble_available ? " · BLE available" : ""}`);
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
    else setRobotMsg({ text: `${r.problem}${r.fix ? ` — ${r.fix}` : ""}`, tone: "warn" });
  }

  const msgEl = (m: Msg) =>
    m && (
      <div className="mt-2 text-sm" style={{ color: m.tone === "ok" ? "var(--color-ok)" : "var(--color-warn)" }}>
        {m.text}
      </div>
    );

  return (
    <div className="flex flex-col gap-5">
      <section className="op-surface p-4">
        <h3 className="mb-2 font-display font-semibold">Camera (wireless)</h3>
        <input
          className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm"
          placeholder="synthetic | 0 | rtsp://user:pass@ip:554/stream1"
          value={camSpec}
          onChange={(e) => setCamSpec(e.target.value)}
        />
        <div className="mt-2 flex gap-2">
          <button type="button" className="op-btn" onClick={connectCam}>
            Connect
          </button>
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
        </div>
        {msgEl(camMsg)}
      </section>

      <section className="op-surface p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-display font-semibold">Robot (Bluetooth / USB)</h3>
          <button type="button" className="op-btn" onClick={discover}>
            Scan devices
          </button>
        </div>
        <div className="flex flex-col gap-2">
          <select
            className="rounded-md border border-line bg-bg px-3 py-2 text-sm"
            value={conn}
            onChange={(e) => setConn(e.target.value)}
          >
            <option value="dummy">dummy (simulation)</option>
            <option value="bt">bt — HC-05 SPP</option>
            <option value="ble">ble — HM-10</option>
            <option value="usb">usb — serial</option>
          </select>
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
            onChange={(e) => setBaud(parseInt(e.target.value, 10) || 115200)}
          />
          <div className="flex gap-2">
            <button type="button" className="op-btn" onClick={connectRobot}>
              Connect
            </button>
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
          </div>
        </div>
        {discoverHint && <div className="mt-2 text-xs text-dim">{discoverHint}</div>}
        {msgEl(robotMsg)}
      </section>
    </div>
  );
}
