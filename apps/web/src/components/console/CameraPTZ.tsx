"use client";

/**
 * Camera pan/tilt (PTZ) — its OWN device, distinct from the chassis "Body yaw".
 * NOT drive-token-gated and not mode-gated: it works in any mode, by anyone, via
 * REST to /api/camera/ptz. Only the Tapo C211 has a motor, so the cluster is
 * disabled-with-reason for any other camera profile.
 *
 * Each tap nudges by a small signed step (the camera self-stops; there's no
 * dead-man hold here, unlike the chassis DrivePad).
 */

import type { Telemetry } from "@/lib/useTelemetry";
import { api } from "@/lib/api";

const STEP = 0.25;

export function CameraPTZ({ telemetry }: { telemetry: Telemetry | null }) {
  const enabled = telemetry?.camera_profile === "tapo_c211";
  const reason = !telemetry
    ? "no telemetry"
    : !enabled
      ? "pan/tilt needs the tapo_c211 camera profile"
      : null;

  const nudge = (pan: number, tilt: number) => {
    if (enabled) api.ptz(pan, tilt);
  };

  const btn = (label: string, pan: number, tilt: number, area: string) => (
    <button
      key={area}
      type="button"
      disabled={!enabled}
      style={{ gridArea: area }}
      className="op-btn"
      onClick={() => nudge(pan, tilt)}
    >
      {label}
    </button>
  );

  return (
    <div className="op-surface flex flex-col gap-2 p-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">
          Camera pan/tilt
        </span>
        {reason && <span className="text-xs text-warn">{reason}</span>}
      </div>
      <div className="flex items-center gap-3">
        <div
          className="grid gap-1.5"
          style={{
            gridTemplateAreas: `". up ." "left mid right" ". down ."`,
            gridTemplateColumns: "2.5rem 2.5rem 2.5rem",
          }}
        >
          {btn("▲", 0, STEP, "up")}
          {btn("◀", -STEP, 0, "left")}
          <button
            type="button"
            disabled={!enabled}
            style={{ gridArea: "mid" }}
            className="op-btn"
            onClick={() => enabled && api.ptzPreset("home")}
            title="Recall home preset"
          >
            ⌂
          </button>
          {btn("▶", STEP, 0, "right")}
          {btn("▼", 0, -STEP, "down")}
        </div>
        <span className="text-xs text-dim">
          Independent of drive mode — moves the camera, not the robot.
        </span>
      </div>
    </div>
  );
}
