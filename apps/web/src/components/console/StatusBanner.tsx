"use client";

/**
 * Single prioritized safety banner. Precedence (highest first):
 *   1. telemetry link lost — we can't trust ANY value, so it outranks all.
 *   2. stop reason (E-stop / watchdog / firmware floor = danger; target/link/
 *      camera lost = warn).
 * Eval-running and observer status are deliberately NOT here — they live as a
 * compact chip (Diagnostics) and a pad badge (DrivePad) so they never crowd out
 * a real safety stop.
 */

import { STOP_REASONS } from "@/lib/stopReasons";
import type { Telemetry, LinkState } from "@/lib/useTelemetry";

const STYLE: Record<string, string> = {
  danger: "bg-stop/20 text-stop border-stop/40",
  warn: "bg-warn/15 text-warn border-warn/40",
};

export function StatusBanner({
  telemetry,
  link,
}: {
  telemetry: Telemetry | null;
  link: LinkState;
}) {
  let text = "";
  let severity: "danger" | "warn" | null = null;

  if (link === "disconnected") {
    text = "TELEMETRY LINK LOST — values may be stale. Reconnecting…";
    severity = "danger";
  } else if (telemetry) {
    const r = STOP_REASONS[telemetry.stop_reason];
    if (r && r.severity !== "ok" && r.text) {
      text = r.text;
      severity = r.severity;
    }
  }

  if (!severity) return null;
  return (
    <div className={`border-b px-4 py-2 text-sm font-medium ${STYLE[severity]}`} role="alert">
      {text}
    </div>
  );
}
