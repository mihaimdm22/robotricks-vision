"use client";

/**
 * DrivePad — press-and-hold teleop, ported from the vanilla panel with the
 * release-to-stop guarantee made robust under React:
 *  - pointerdown captures the pointer (setPointerCapture) so dragging off the
 *    button still delivers pointerup → stop.
 *  - pointerup / pointercancel / lostpointercapture ALL stop.
 *  - keyboard is bound on `window` (not per-button) and IGNORED while typing in
 *    a form field, and ignores auto-repeat.
 *  - window blur + tab-hide → stop (you can't hold a key you can't see).
 *  - a 120ms intent re-send while pressing + a 200ms MANUAL idle heartbeat keep
 *    the dead-man's switch happy (banner reads NONE, not WATCHDOG, when idle).
 *  - observers (no token) and non-MANUAL/E-stop states show a locked pad.
 */

import { useEffect, useRef, useState } from "react";
import type { Telemetry } from "@/lib/useTelemetry";

const KEYS: Record<string, string> = {
  w: "forward",
  s: "back",
  a: "left",
  d: "right",
  ArrowUp: "forward",
  ArrowDown: "back",
  ArrowLeft: "left",
  ArrowRight: "right",
};

function typingInField(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el as HTMLElement).isContentEditable;
}

export function DrivePad({
  telemetry,
  send,
  onRequestControl,
}: {
  telemetry: Telemetry | null;
  send: (obj: Record<string, unknown>) => void;
  onRequestControl: () => void;
}) {
  const [speed, setSpeed] = useState(0.6);
  const speedRef = useRef(speed);

  const mode = telemetry?.mode;
  const estop = !!telemetry?.estop;
  const isController = !!telemetry?.you_are_controller;
  const drivable = mode === "MANUAL" && !estop && isController;
  const drivableRef = useRef(drivable);

  // Mirror the latest values into refs (read by the long-lived key/pointer
  // handlers) — in effects, never during render.
  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);
  useEffect(() => {
    drivableRef.current = drivable;
  }, [drivable]);

  const driveTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const held = useRef<Set<string>>(new Set());

  function startDrive(action: string) {
    if (!drivableRef.current) return;
    send({ type: "intent", action, value: speedRef.current });
    if (driveTimer.current) clearInterval(driveTimer.current);
    driveTimer.current = setInterval(
      () => send({ type: "intent", action, value: speedRef.current }),
      120,
    );
  }
  function stopDrive() {
    if (driveTimer.current) clearInterval(driveTimer.current);
    driveTimer.current = null;
    send({ type: "intent", action: "stop", value: 0 });
  }

  // MANUAL idle heartbeat (200ms) — keep the watchdog happy while parked.
  useEffect(() => {
    if (!drivable) return;
    const id = setInterval(() => send({ type: "heartbeat" }), 200);
    return () => clearInterval(id);
  }, [drivable, send]);

  // Global keyboard driving + safety stops (blur / tab-hide).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (typingInField() || e.repeat) return;
      const action = KEYS[e.key];
      if (!action || held.current.has(e.key)) return;
      held.current.add(e.key);
      startDrive(action);
    }
    function onKeyUp(e: KeyboardEvent) {
      if (KEYS[e.key]) {
        held.current.delete(e.key);
        stopDrive();
      }
    }
    function panic() {
      held.current.clear();
      stopDrive();
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", panic);
    document.addEventListener("visibilitychange", panic);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", panic);
      document.removeEventListener("visibilitychange", panic);
      if (driveTimer.current) clearInterval(driveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const padBtn = (action: string, label: string, area: string) => (
    <button
      key={action}
      type="button"
      disabled={!drivable}
      style={{ gridArea: area }}
      className="op-btn select-none text-lg disabled:opacity-100"
      onPointerDown={(e) => {
        e.preventDefault();
        (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
        startDrive(action);
      }}
      onPointerUp={stopDrive}
      onPointerCancel={stopDrive}
      onLostPointerCapture={stopDrive}
    >
      {label}
    </button>
  );

  const lockMsg = estop
    ? "E-stop latched — press ARM / RESET."
    : !isController
      ? "Observer — another operator holds control."
      : mode !== "MANUAL"
        ? "Switch to MANUAL to drive."
        : "Hold a button or W/A/S/D to drive. Release to stop.";

  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-sm text-muted">
        {!isController && telemetry && (
          <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs font-mono uppercase tracking-wide text-warn">
            🔒 Observer
          </span>
        )}
        <span>{lockMsg}</span>
      </div>

      <div
        className="relative grid gap-2"
        style={{
          gridTemplateAreas: `". up ." "left mid right" ". down ."`,
          gridTemplateColumns: "1fr 1fr 1fr",
          maxWidth: 260,
        }}
        aria-disabled={!drivable}
      >
        {padBtn("forward", "▲", "up")}
        {padBtn("left", "◀", "left")}
        <button
          type="button"
          disabled={!drivable}
          style={{ gridArea: "mid" }}
          className="op-btn font-bold text-stop"
          onClick={stopDrive}
        >
          STOP
        </button>
        {padBtn("right", "▶", "right")}
        {padBtn("back", "▼", "down")}
        {!drivable && (
          <div className="pointer-events-none absolute inset-0 rounded-xl bg-black/45" />
        )}
      </div>

      {!isController && telemetry && (
        <button type="button" className="op-btn mt-3 w-full" onClick={onRequestControl}>
          Request control
        </button>
      )}

      <label className="mt-4 flex items-center gap-3 text-sm text-muted">
        Speed
        <input
          type="range"
          min={0.1}
          max={1}
          step={0.1}
          value={speed}
          onChange={(e) => setSpeed(parseFloat(e.target.value))}
          className="flex-1 accent-orange-bright"
        />
        <span className="font-mono text-fg">{speed.toFixed(1)}</span>
      </label>
      <label className="mt-2 flex items-center gap-3 text-sm text-muted">
        Pan
        <input
          type="range"
          min={-1}
          max={1}
          step={0.05}
          defaultValue={0}
          disabled={!drivable}
          onChange={(e) =>
            drivable && send({ type: "intent", action: "pan", value: parseFloat(e.target.value) })
          }
          className="flex-1 accent-purple-bright"
        />
      </label>
    </div>
  );
}
