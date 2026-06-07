"use client";

/**
 * Primary glanceable strip (distance / ground truth / target) + diagnostics row.
 * When the socket is fully down we soften values — no strike-through (that flickers
 * on every reconnect attempt and reads as broken UI).
 */

import type { Telemetry, LinkState } from "@/lib/useTelemetry";
import { InfoStat, SectionHelp } from "./help";

function Pill({
  label,
  tone,
  helpId,
}: {
  label: string;
  tone: "ok" | "warn" | "bad";
  helpId?: "telemetry.camera_pill" | "telemetry.robot_pill" | "telemetry.model_pill";
}) {
  const color =
    tone === "ok" ? "var(--color-ok)" : tone === "warn" ? "var(--color-warn)" : "var(--color-stop)";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-mono transition-colors duration-300"
      style={{ borderColor: color, color }}
    >
      {label}
      {helpId && <SectionHelp helpId={helpId} className="!h-4 !w-4 text-[0.55rem]" />}
    </span>
  );
}

export function TelemetryStrip({
  telemetry,
  link,
}: {
  telemetry: Telemetry | null;
  link: LinkState;
}) {
  const t = telemetry;
  const offline = link === "disconnected";
  const uncal = t?.target_dist_m != null && t.camera_calibrated === false;
  const dist = t?.target_dist_m != null ? `${t.target_dist_m} m` : "—";
  const sonarCm =
    t?.sonar_display_cm != null && t.sonar_display_cm >= 0
      ? t.sonar_display_cm
      : t?.gt_cm != null && t.gt_cm >= 0
        ? t.gt_cm
        : null;
  const gt = sonarCm != null ? `${(sonarCm / 100).toFixed(2)} m` : "—";
  const targetIds =
    t?.target_ids && t.target_ids.length > 0
      ? t.target_ids
      : t?.target_id != null
        ? [t.target_id]
        : [];
  const target =
    targetIds.length > 0
      ? `id ${targetIds.join("/")}`
      : t?.n_cats
        ? `${t.n_cats} seen`
        : "none";

  return (
    <div
      className={`telemetry-strip transition-opacity duration-500 ${offline ? "opacity-55" : "opacity-100"}`}
      aria-live="polite"
    >
      {offline && (
        <p className="mb-2 text-xs font-mono text-warn">Link reconnecting — values may be stale</p>
      )}
      <div className="grid grid-cols-3 gap-2">
        <InfoStat label="Distance" helpId="telemetry.distance" value={dist} warn={uncal ? "~ uncalibrated" : undefined} />
        <InfoStat label="Ground truth" helpId="telemetry.ground_truth" value={gt} />
        <InfoStat label="Target" helpId="telemetry.target" value={target} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1 font-mono tabular-nums text-muted">
          FPS {t?.fps != null ? t.fps : "—"}
          <SectionHelp helpId="telemetry.fps" className="!h-4 !w-4 text-[0.55rem]" />
        </span>
        <Pill label={`camera ${t?.camera ?? "—"}`} tone={t?.camera_connected ? "ok" : "bad"} helpId="telemetry.camera_pill" />
        <Pill label={`robot ${t?.robot ?? "—"}`} tone={t?.robot_connected ? "ok" : "warn"} helpId="telemetry.robot_pill" />
        <Pill
          label={`model ${t?.model ?? "—"}${t?.model_status ? ` (${t.model_status})` : ""}`}
          tone={t?.perception_available ? "ok" : "warn"}
          helpId="telemetry.model_pill"
        />
        {t?.eval_running && <Pill label="eval running — FPS may drop" tone="warn" />}
        {t?.train_running && <Pill label="training running — FPS may drop" tone="warn" />}
      </div>
    </div>
  );
}
