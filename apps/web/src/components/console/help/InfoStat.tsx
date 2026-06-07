"use client";

import type { HelpId } from "@/lib/console-help";
import { SectionHelp } from "./SectionHelp";

/** Telemetry / readout tile with label help. */
export function InfoStat({
  label,
  helpId,
  value,
  warn,
}: {
  label: string;
  helpId: HelpId;
  value: string;
  warn?: string;
}) {
  return (
    <div className="op-surface telemetry-stat flex flex-col gap-1 px-4 py-3">
      <span className="inline-flex items-center gap-1 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">
        {label}
        <SectionHelp helpId={helpId} />
      </span>
      <span className="font-mono text-2xl tabular-nums text-fg transition-opacity duration-300">
        {value}
        {warn && <span className="ml-1 align-middle text-xs text-warn">{warn}</span>}
      </span>
    </div>
  );
}
