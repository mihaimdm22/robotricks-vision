"use client";

/**
 * Primary glanceable strip (distance / ground truth / target) + a small
 * diagnostics row (FPS, camera/robot/model pills, eval-running chip).
 * When the telemetry link is not live, the whole strip is dimmed + struck so a
 * frozen last-known value is never mistaken for a fresh reading.
 */

import type { Telemetry, LinkState } from "@/lib/useTelemetry";

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="op-surface flex flex-col gap-1 px-4 py-3">
      <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">{k}</span>
      <span className="font-mono text-2xl text-fg">{v}</span>
    </div>
  );
}

function Pill({ label, tone }: { label: string; tone: "ok" | "warn" | "bad" }) {
  const color =
    tone === "ok" ? "var(--color-ok)" : tone === "warn" ? "var(--color-warn)" : "var(--color-stop)";
  return (
    <span
      className="rounded-full border px-2.5 py-0.5 text-xs font-mono"
      style={{ borderColor: color, color }}
    >
      {label}
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
  const dist = t?.target_dist_m != null ? `${t.target_dist_m} m` : "—";
  const gt = t?.gt_cm != null && t.gt_cm >= 0 ? `${(t.gt_cm / 100).toFixed(2)} m` : "—";
  const target =
    t?.target_id != null ? `id ${t.target_id}` : t?.n_cats ? `${t.n_cats} seen` : "none";

  return (
    <div
      className={link === "live" ? "" : "pointer-events-none select-none opacity-40 line-through"}
      aria-live="polite"
    >
      <div className="grid grid-cols-3 gap-2">
        <Stat k="Distance" v={dist} />
        <Stat k="Ground truth" v={gt} />
        <Stat k="Target" v={target} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono text-muted">FPS {t?.fps != null ? t.fps : "—"}</span>
        <Pill label={`camera ${t?.camera ?? "—"}`} tone={t?.camera_connected ? "ok" : "bad"} />
        <Pill label={`robot ${t?.robot ?? "—"}`} tone={t?.robot_connected ? "ok" : "warn"} />
        <Pill
          label={`model ${t?.model ?? "—"}${t?.model_status ? ` (${t.model_status})` : ""}`}
          tone={t?.perception_available ? "ok" : "warn"}
        />
        {t?.eval_running && <Pill label="eval running — FPS may drop" tone="warn" />}
      </div>
    </div>
  );
}
