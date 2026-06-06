"use client";

import { useId, useMemo, useState } from "react";
import { liveDistance } from "@/lib/content";

const GAUGE_MIN = 1.2;
const GAUGE_MAX = 2.4;

function pct(v: number) {
  const p = ((v - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)) * 100;
  return Math.max(0, Math.min(100, p));
}

const fmt = (v: number) => v.toFixed(2);

export function LiveDistanceCard() {
  const { meters, lo, hi, truthMeters, closingMps, catName, trackId } = liveDistance;
  const [lead, setLead] = useState(0.5);
  const sliderId = useId();

  const predicted = useMemo(
    () => Math.max(0, meters - closingMps * lead),
    [meters, closingMps, lead],
  );
  const half = (hi - lo) / 2;

  return (
    <div className="glass relative overflow-hidden p-5 sm:p-6">
      {/* header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-truth animate-pulse-soft" />
          <span className="font-mono text-xs uppercase tracking-[0.2em] text-muted">
            Live distance
          </span>
        </div>
        <span className="font-mono text-xs text-dim">
          track #{trackId} · {catName}
        </span>
      </div>

      {/* primary readout */}
      <div className="mt-4 flex items-end justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-5xl font-semibold tabular-nums tracking-tight text-fg">
              {fmt(meters)}
            </span>
            <span className="font-mono text-lg text-muted">m</span>
          </div>
          <div className="mt-1 font-mono text-xs text-orange-bright">
            ± {fmt(half)} m&nbsp;
            <span className="text-dim">95% CI</span>
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-sm text-truth">{fmt(truthMeters)} m</div>
          <div className="font-mono text-[11px] uppercase tracking-wide text-dim">
            HC-SR04 truth
          </div>
        </div>
      </div>

      {/* gauge */}
      <div className="mt-5">
        <div className="relative h-12">
          {/* baseline */}
          <div className="absolute inset-x-0 top-6 h-px bg-line" />
          {/* CI band */}
          <div
            className="absolute top-[18px] h-3 rounded-full bg-orange/25"
            style={{ left: `${pct(lo)}%`, width: `${pct(hi) - pct(lo)}%` }}
          />
          {/* trajectory between now and predicted */}
          <div
            className="absolute top-6 h-0.5 -translate-y-1/2 rounded-full"
            style={{
              left: `${Math.min(pct(predicted), pct(meters))}%`,
              width: `${Math.abs(pct(meters) - pct(predicted))}%`,
              background:
                "linear-gradient(90deg, var(--color-orange), var(--color-purple-bright))",
            }}
          />
          {/* truth tick */}
          <div
            className="absolute top-3 h-6 w-px bg-truth"
            style={{ left: `${pct(truthMeters)}%` }}
          />
          {/* current marker */}
          <Marker left={pct(meters)} label="now" color="var(--color-orange-bright)" />
          {/* predicted marker */}
          <Marker
            left={pct(predicted)}
            label={`+${lead.toFixed(1)}s`}
            color="var(--color-purple-bright)"
          />
        </div>
        <div className="flex justify-between font-mono text-[10px] text-dim">
          <span>{GAUGE_MIN.toFixed(1)} m</span>
          <span>{GAUGE_MAX.toFixed(1)} m</span>
        </div>
      </div>

      {/* predicted callout + slider */}
      <div className="mt-4 rounded-2xl border border-line bg-white/[0.02] p-4">
        <div className="flex items-center justify-between">
          <label
            htmlFor={sliderId}
            className="font-mono text-xs uppercase tracking-[0.15em] text-muted"
          >
            Shutter lead
          </label>
          <span className="font-mono text-sm text-purple-bright">
            where it will be:{" "}
            <span className="text-fg">{fmt(predicted)} m</span>
          </span>
        </div>
        <input
          id={sliderId}
          type="range"
          min={0}
          max={1}
          step={0.1}
          value={lead}
          onChange={(e) => setLead(Number(e.target.value))}
          aria-valuetext={`${lead.toFixed(1)} seconds ahead`}
          className="mt-3 h-2 w-full cursor-pointer appearance-none rounded-full bg-white/10 accent-orange"
        />
        <div className="mt-1 flex justify-between font-mono text-[10px] text-dim">
          <span>now</span>
          <span>+1.0 s</span>
        </div>
      </div>
    </div>
  );
}

function Marker({
  left,
  label,
  color,
}: {
  left: number;
  label: string;
  color: string;
}) {
  return (
    <div
      className="absolute top-6 -translate-x-1/2 -translate-y-1/2"
      style={{ left: `${left}%` }}
    >
      <div
        className="size-3.5 rounded-full border-2 border-bg"
        style={{ background: color, boxShadow: `0 0 12px ${color}` }}
      />
      <span
        className="absolute left-1/2 top-4 -translate-x-1/2 whitespace-nowrap font-mono text-[10px]"
        style={{ color }}
      >
        {label}
      </span>
    </div>
  );
}
