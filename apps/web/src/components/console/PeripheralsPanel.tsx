"use client";

/**
 * On-rig peripherals driven by the HC-SR04 reading: ultrasonic ground truth,
 * RGB distance bands, metal-detector buzzer, and LCD mirror — toggled over the
 * same CharBridge single-char link as drive commands.
 */

import type { Telemetry } from "@/lib/useTelemetry";
import { ControlTip, SectionTitle } from "./help";
import type { HelpId } from "@/lib/console-help";

const PERIPH_HELP: Record<string, HelpId> = {
  buzzer_toggle: "periph.buzzer",
  rgb_toggle: "periph.rgb",
  lcd_toggle: "periph.lcd",
  all_on: "periph.all_on",
  all_off: "periph.all_off",
};

const DEFAULT_RANGE_CM = 200;

const ZONE_COLORS: Record<string, string> = {
  red: "#ef4444",
  yellow: "#eab308",
  green: "#22c55e",
  cyan: "#06b6d4",
  blue: "#3b82f6",
};

function zoneColor(zone: string | null | undefined): string {
  if (!zone) return "var(--color-muted)";
  return ZONE_COLORS[zone] ?? "var(--color-muted)";
}

function displayCm(t: Telemetry | null): number | null {
  if (t?.sonar_display_cm != null && t.sonar_display_cm >= 0) return t.sonar_display_cm;
  if (t?.gt_cm != null && t.gt_cm >= 0) return t.gt_cm;
  return null;
}

function formatSonarCm(cm: number | null): string {
  if (cm == null) return "—";
  return `${cm} cm`;
}

function catIdLabel(t: Telemetry | null): string | null {
  const ids = t?.target_ids;
  if (ids != null && ids.length > 0) return ids.slice(0, 4).join("/");
  if (t?.target_id != null) return String(t.target_id);
  return null;
}

function lcdLine1(t: Telemetry | null): string {
  if (t?.sonar_obstacle) return "OBSTACOL! h/j";
  const cat = catIdLabel(t);
  if (cat) return `Cat id:${cat}`;
  if (t?.mode === "MANUAL") return "Manual 0-200cm";
  if (t?.mode === "FOLLOW") return "Follow 0-200cm";
  return "Dist 0-200cm";
}

function lcdLine2(t: Telemetry | null): string {
  const cm = displayCm(t);
  const range = t?.sonar_range_cm ?? DEFAULT_RANGE_CM;
  if (cm == null) return `--- / ${range}cm`;
  return `${cm} cm / ${range}cm`;
}

export function PeripheralsPanel({
  telemetry,
  send,
  controllable,
}: {
  telemetry: Telemetry | null;
  send: (obj: Record<string, unknown>) => void;
  /** True when CharBridge is live — not tied to MANUAL / drive token. */
  controllable: boolean;
}) {
  const t = telemetry;
  const periph = t?.peripherals;
  const charBridge = periph != null;
  const rangeCm = t?.sonar_range_cm ?? DEFAULT_RANGE_CM;
  const cm = displayCm(t);
  const modelM = t?.target_dist_m;
  const modelCm = modelM != null ? Math.round(modelM * 100) : null;
  const deltaCm =
    cm != null && modelCm != null ? Math.abs(modelCm - cm) : null;

  function toggle(action: string) {
    if (!controllable) return;
    send({ type: "peripheral", action });
  }

  const lockReason = !t?.robot_connected
    ? "Connect the robot (USB @ 9600) to toggle peripherals."
    : !charBridge
      ? "Peripheral toggles need CharBridge firmware on USB."
      : null;

  return (
    <div className="mt-6 border-t border-line pt-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <SectionTitle helpId="section.peripherals" className="font-mono text-xs uppercase tracking-[0.18em] text-dim">
          Rig sensors &amp; peripherals
        </SectionTitle>
        {!charBridge && (
          <span className="text-xs text-muted">CharBridge firmware required</span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {/* Ultrasonic */}
        <div className="op-surface flex flex-col gap-2 px-4 py-3">
          <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">
            HC-SR04 ultrasonic
          </span>
          <div className="flex items-end gap-3">
            <span
              className="font-mono text-3xl tabular-nums"
              style={{ color: zoneColor(t?.sonar_zone) }}
            >
              {formatSonarCm(cm)}
            </span>
            {t?.sonar_obstacle && (
              <span className="mb-1 rounded-full border border-stop px-2 py-0.5 text-xs font-mono text-stop">
                obstacle
              </span>
            )}
          </div>
          {t?.sonar_no_echo && (
            <span className="text-xs text-muted">Sensor out of range (holding last reading)</span>
          )}
          <div className="h-2 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full transition-[width,background-color] duration-500 ease-out"
              style={{
                width:
                  cm != null ? `${Math.min(100, (cm / rangeCm) * 100)}%` : "0%",
                backgroundColor: zoneColor(t?.sonar_zone),
              }}
            />
          </div>
          {deltaCm != null && (
            <span className="text-xs text-muted">
              Model {modelCm} cm · Δ {deltaCm} cm vs sonar
            </span>
          )}
        </div>

        {/* RGB LED */}
        <div className="op-surface flex items-center gap-4 px-4 py-3">
          <div
            className="h-14 w-14 shrink-0 rounded-full border-2 border-white/20 shadow-inner transition-colors duration-500"
            style={{
              backgroundColor:
                periph?.rgb === false
                  ? "#1a1a1a"
                  : zoneColor(t?.sonar_zone),
              boxShadow:
                periph?.rgb !== false && t?.sonar_zone
                  ? `0 0 18px ${zoneColor(t?.sonar_zone)}`
                  : undefined,
            }}
            aria-label="RGB distance indicator"
          />
          <div>
            <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">
              RGB LED
            </span>
            <p className="text-sm text-muted">
              Red ≤40 · yellow ≤80 · green ≤120 · cyan ≤160 · blue farther (2 m)
            </p>
          </div>
        </div>

        {/* Buzzer */}
        <div className="op-surface flex items-center gap-4 px-4 py-3">
          <div
            className={`flex h-12 w-12 items-center justify-center rounded-lg border text-xl transition-colors duration-300 ${
              t?.buzzer_active ? "border-warn bg-warn/25 shadow-[0_0_12px_-2px_var(--color-warn)]" : "border-line bg-white/5"
            }`}
            aria-label="Proximity buzzer"
          >
            🔊
          </div>
          <div>
            <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">
              Speaker (metal-detector)
            </span>
            <p className="text-sm text-muted">
              Faster beeps as obstacle &lt; 180 cm · silent beyond 2 m
            </p>
          </div>
        </div>

        {/* LCD mirror */}
        <div className="op-surface px-4 py-3">
          <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">
            LCD 16×2 mirror
          </span>
          <div
            className="mt-2 rounded border border-line bg-[#0a3d2e] px-3 py-2 font-mono text-sm text-[#33ff99] shadow-inner"
            style={{ fontFamily: "ui-monospace, monospace" }}
          >
            <div className="truncate">{periph?.lcd === false ? "(off)" : lcdLine1(t)}</div>
            <div className="truncate">{periph?.lcd === false ? "" : lcdLine2(t)}</div>
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {(
          [
            ["buzzer_toggle", "Buzzer", periph?.buzzer],
            ["rgb_toggle", "RGB", periph?.rgb],
            ["lcd_toggle", "LCD", periph?.lcd],
          ] as const
        ).map(([action, label, on]) => (
          <ControlTip key={action} helpId={PERIPH_HELP[action]}>
            <button
              type="button"
              className="op-btn text-sm"
              data-active={on !== false}
              disabled={!controllable}
              onClick={() => toggle(action)}
            >
              {label} {on === false ? "off" : "on"}
            </button>
          </ControlTip>
        ))}
        <button
          type="button"
          className="op-btn text-sm"
          disabled={!controllable}
          onClick={() => toggle("all_on")}
        >
          All on
        </button>
        <button
          type="button"
          className="op-btn text-sm"
          disabled={!controllable}
          onClick={() => toggle("all_off")}
        >
          All off
        </button>
      </div>
      {lockReason && (
        <p className="mt-2 text-xs text-muted">{lockReason}</p>
      )}
    </div>
  );
}
