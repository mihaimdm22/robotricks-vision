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
import { ControlTip, SectionTitle } from "./help";
import type { HelpId } from "@/lib/console-help";

const STEP = 0.25;

const PTZ_HELP: Record<string, HelpId> = {
  up: "ptz.up",
  down: "ptz.down",
  left: "ptz.left",
  right: "ptz.right",
  home: "ptz.home",
};

export function CameraPTZ({ telemetry }: { telemetry: Telemetry | null }) {
  const enabled = Boolean(telemetry?.ptz_available);
  const reason = !telemetry
    ? "no telemetry"
    : !enabled
      ? "pan/tilt needs a Tapo RTSP URL (with Camera Account credentials)"
      : null;

  const nudge = (pan: number, tilt: number) => {
    if (enabled) api.ptz(pan, tilt);
  };

  const btn = (label: string, pan: number, tilt: number, area: string, helpKey: string) => (
    <ControlTip key={area} helpId={PTZ_HELP[helpKey]} hostStyle={{ gridArea: area }} fill>
      <button
        type="button"
        disabled={!enabled}
        className="op-btn h-full w-full"
        onClick={() => nudge(pan, tilt)}
      >
        {label}
      </button>
    </ControlTip>
  );

  return (
    <div className="op-surface flex flex-col gap-2 p-3">
      <div className="flex items-center justify-between">
        <SectionTitle helpId="section.ptz" className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">
          Camera pan/tilt
        </SectionTitle>
        {reason && <span className="text-xs text-warn">{reason}</span>}
      </div>
      <div className="flex items-center gap-3">
        <div
          className="grid gap-1.5"
          style={{
            gridTemplateAreas: `". up ." "left mid right" ". down ."`,
            gridTemplateColumns: "repeat(3, 2.75rem)",
            gridTemplateRows: "repeat(3, 2.75rem)",
          }}
        >
          {btn("▲", 0, STEP, "up", "up")}
          {btn("◀", -STEP, 0, "left", "left")}
          <ControlTip helpId="ptz.home" hostStyle={{ gridArea: "mid" }} fill>
            <button
              type="button"
              disabled={!enabled}
              className="op-btn h-full w-full"
              onClick={() => enabled && api.ptzPreset("home")}
            >
              ⌂
            </button>
          </ControlTip>
          {btn("▶", STEP, 0, "right", "right")}
          {btn("▼", 0, -STEP, "down", "down")}
        </div>
        <span className="text-xs text-dim">
          Independent of drive mode — moves the camera, not the robot.
        </span>
      </div>
    </div>
  );
}
