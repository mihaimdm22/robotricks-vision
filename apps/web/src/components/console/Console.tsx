"use client";

/**
 * The control console: persistent safety header + status banner, a video/
 * telemetry column, and a tabbed panel (Control / Models / Connections / CV).
 * All robot I/O goes through the one telemetry WebSocket; one-shot config
 * actions (model/camera/robot) use REST. Mode + drive require the drive token;
 * E-stop never does.
 */

import { useEffect, useState, useSyncExternalStore } from "react";
import { useTelemetry } from "@/lib/useTelemetry";
import { apiBase, buildDefaultBase, subscribeApiBase } from "@/lib/api";
import { SafetyHeader } from "./SafetyHeader";
import { StatusBanner } from "./StatusBanner";
import { VideoPane } from "./VideoPane";
import { TelemetryStrip } from "./TelemetryStrip";
import { DrivePad } from "./DrivePad";
import { PeripheralsPanel } from "./PeripheralsPanel";
import { CatPickerPanel } from "./CatPickerPanel";
import { CatLibraryTab } from "./CatLibraryTab";
import { ModelsTab } from "./ModelsTab";
import { ConnectionsTab } from "./ConnectionsTab";
import { CVTab } from "./CVTab";
import { ControlTip, HelpProvider } from "./help";
import type { HelpId } from "@/lib/console-help";

type Tab = "control" | "cats" | "models" | "connections" | "cv";
const TABS: { id: Tab; label: string; helpId: HelpId }[] = [
  { id: "control", label: "Control", helpId: "tab.control" },
  { id: "cats", label: "Cats", helpId: "tab.cats" },
  { id: "models", label: "Models", helpId: "tab.models" },
  { id: "connections", label: "Connections", helpId: "tab.connections" },
  { id: "cv", label: "CV", helpId: "tab.cv" },
];

const MODES = ["IDLE", "MANUAL", "FOLLOW"] as const;

const MODE_HELP: Record<(typeof MODES)[number], HelpId> = {
  IDLE: "mode.idle",
  MANUAL: "mode.manual",
  FOLLOW: "mode.follow",
};

export function Console() {
  // The effective backend URL doubles as a remount key: when the operator saves a
  // new Backend URL (Connections tab), the store notifies, this re-reads, the key
  // changes, and ConsoleBody — with its telemetry WebSocket and MJPEG <img> —
  // remounts against the new origin (R6).
  //
  // useSyncExternalStore is the sanctioned pattern for a localStorage-backed value:
  // the server snapshot (buildDefaultBase) matches the SSR HTML (no hydration
  // mismatch on VideoPane's <img src>), then it adopts the client snapshot.
  const base = useSyncExternalStore(
    subscribeApiBase,
    () => apiBase(),
    () => buildDefaultBase,
  );
  return <ConsoleBody key={base} />;
}

function ConsoleBody() {
  const { telemetry, link, nack, clearNack, send } = useTelemetry();
  const [tab, setTab] = useState<Tab>("control");

  // Never received a frame and the link is down → almost certainly no reachable
  // backend (vs a mid-session blip, where telemetry exists but is stale). Show the
  // honest "runs locally" affordance instead of leaving the operator on the
  // safety banner's misleading "reconnecting…" (R3).
  const noBackend = !telemetry && link === "disconnected";

  // Auto-dismiss a nack toast after a few seconds.
  useEffect(() => {
    if (!nack) return;
    const id = setTimeout(clearNack, 4000);
    return () => clearTimeout(id);
  }, [nack, clearNack]);

  const mode = telemetry?.mode ?? "IDLE";
  const estopped = !!telemetry?.estop;

  return (
    <HelpProvider>
    <div className="min-h-screen bg-bg text-fg console-page">
      <SafetyHeader telemetry={telemetry} link={link} />
      <StatusBanner telemetry={telemetry} link={link} />

      {noBackend && (
        <div
          className="border-b border-line bg-white/[0.03] px-4 py-2 text-sm text-muted"
          role="status"
        >
          No backend connected — this console runs locally. Start{" "}
          <code className="font-mono text-fg">catranger serve</code>, or set a{" "}
          <button
            type="button"
            className="underline underline-offset-2 hover:text-fg"
            onClick={() => setTab("connections")}
          >
            Backend URL
          </button>{" "}
          (Connections tab). See the README.
        </div>
      )}

      {nack && (
        <div className="border-b border-warn/40 bg-warn/15 px-4 py-2 text-sm text-warn" role="status">
          {nack.problem}
          {nack.fix ? ` — ${nack.fix}` : ""}
        </div>
      )}

      <main className="mx-auto grid max-w-7xl gap-5 p-4 lg:grid-cols-[1.4fr_1fr]">
        <section className="flex flex-col gap-3">
          <VideoPane telemetry={telemetry} />
          <TelemetryStrip telemetry={telemetry} link={link} />
        </section>

        <section className="op-surface flex flex-col p-4">
          <nav className="mb-4 flex flex-wrap gap-1 border-b border-line">
            {TABS.map((t) => (
              <ControlTip key={t.id} helpId={t.helpId}>
                <button
                  type="button"
                  className="op-btn shrink-0 rounded-b-none border-b-0 px-2 text-xs sm:px-3 sm:text-sm"
                  data-active={tab === t.id}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              </ControlTip>
            ))}
          </nav>

          {tab === "control" && (
            <div>
              <div className="mb-4 flex gap-2">
                {MODES.map((m) => (
                  <ControlTip key={m} helpId={MODE_HELP[m]}>
                    <button
                      type="button"
                      className="op-btn flex-1"
                      data-active={mode === m && !estopped}
                      onClick={() => send({ type: "mode", mode: m })}
                    >
                      {m}
                    </button>
                  </ControlTip>
                ))}
              </div>
              <DrivePad
                telemetry={telemetry}
                send={send}
                onRequestControl={() => send({ type: "request_control" })}
              />
              <PeripheralsPanel
                telemetry={telemetry}
                send={send}
                controllable={
                  !!telemetry?.robot_connected && telemetry?.peripherals != null
                }
              />
              <CatPickerPanel
                telemetry={telemetry}
                send={send}
                estopped={estopped}
                onOpenLibrary={() => setTab("cats")}
              />
            </div>
          )}
          {tab === "cats" && (
            <CatLibraryTab telemetry={telemetry} send={send} estopped={estopped} />
          )}
          {tab === "models" && <ModelsTab />}
          {tab === "connections" && <ConnectionsTab />}
          {tab === "cv" && <CVTab />}
        </section>
      </main>
    </div>
    </HelpProvider>
  );
}
