"use client";

/**
 * Persistent safety header — present on every tab, never scrolls. Carries the
 * controls that must always be reachable: E-STOP (and ARM/RESET when latched).
 * E-STOP is NEVER dimmed by observer/eval/link state — it is the one control
 * exempt from every lockout (design review). It and RESET go over the WS, which
 * the server applies ungated by the drive token.
 */

import Link from "next/link";
import { api } from "@/lib/api";
import type { Telemetry, LinkState } from "@/lib/useTelemetry";

const MODE_COLOR: Record<string, string> = {
  IDLE: "var(--color-dim)",
  MANUAL: "var(--color-manual)",
  FOLLOW: "var(--color-follow)",
};

export function SafetyHeader({
  telemetry,
  link,
}: {
  telemetry: Telemetry | null;
  link: LinkState;
}) {
  const estop = !!telemetry?.estop;
  const mode = telemetry?.mode ?? "IDLE";
  const live = !!telemetry?.robot_connected;

  return (
    <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-bg/95 px-4 py-3 backdrop-blur-sm">
      <Link href="/" className="font-display text-lg font-semibold">
        CatRanger <span className="text-orange-bright">Console</span>
      </Link>

      <span
        className="rounded-md px-2 py-0.5 text-xs font-mono font-semibold uppercase tracking-wide"
        style={{
          background: live ? "color-mix(in oklab, var(--color-ok) 22%, transparent)" : "rgba(255,255,255,0.06)",
          color: live ? "var(--color-ok)" : "var(--color-warn)",
        }}
      >
        {live ? "LIVE — REAL ROBOT" : "SIMULATION"}
      </span>

      <span
        className="rounded-md px-2.5 py-0.5 text-xs font-mono font-bold uppercase tracking-wide text-white"
        style={{ background: estop ? "var(--color-stop)" : MODE_COLOR[mode] }}
      >
        {estop ? "E-STOP" : mode}
      </span>

      {link !== "live" && (
        <span className="rounded-md px-2 py-0.5 text-xs font-mono uppercase tracking-wide text-warn">
          {link === "connecting" ? "connecting…" : "link lost"}
        </span>
      )}

      <div className="flex-1" />

      {/* E-STOP / RESET go over REST, not the WS: fetch() works even while the
          telemetry socket is down (where send() would silently no-op) — the one
          moment you most need the stop to land. */}
      {estop && (
        <button
          type="button"
          className="op-btn"
          style={{ borderColor: "var(--color-ok)" }}
          onClick={() => api.reset()}
        >
          ARM / RESET
        </button>
      )}
      <button type="button" className="op-btn op-estop" onClick={() => api.estop()}>
        ■ E-STOP
      </button>
    </header>
  );
}
