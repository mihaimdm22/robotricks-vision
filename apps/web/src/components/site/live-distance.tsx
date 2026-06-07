"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "motion/react";
import { liveDistance } from "@/lib/content";

const GAUGE_MIN = 1.2;
const GAUGE_MAX = 2.4;
const EASE = [0.2, 0.8, 0.2, 1] as const;

function pct(v: number) {
  const p = ((v - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)) * 100;
  return Math.max(0, Math.min(100, p));
}

const fmt = (v: number) => v.toFixed(2);

/** A number that counts up to `to` once `run` flips true (instant if reduced). */
function CountUp({
  to,
  run,
  reduced,
  decimals = 2,
  delay = 0,
  duration = 1,
}: {
  to: number;
  run: boolean;
  reduced: boolean | null;
  decimals?: number;
  delay?: number;
  duration?: number;
}) {
  const mv = useMotionValue(reduced ? to : 0);
  const text = useTransform(mv, (v) => v.toFixed(decimals));
  useEffect(() => {
    if (reduced) {
      mv.set(to);
      return;
    }
    if (!run) return;
    const controls = animate(mv, to, { duration, delay, ease: EASE });
    return () => controls.stop();
  }, [mv, to, run, reduced, delay, duration]);
  return <motion.span>{text}</motion.span>;
}

export function LiveDistanceCard() {
  const { meters, lo, hi, truthMeters, closingMps, catName, trackId } = liveDistance;
  const reduced = useReducedMotion();
  const sliderId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const sliderRef = useRef<HTMLInputElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const [touched, setTouched] = useState(false);

  const half = (hi - lo) / 2;
  const nowPct = pct(meters);

  // Single source of truth for the shutter lead. Driven by an auto-demo sweep
  // until the user grabs the slider; everything below derives from it without a
  // per-frame React re-render.
  const lead = useMotionValue(0.5);
  const predictedM = useTransform(lead, (l) => Math.max(0, meters - closingMps * l));
  const predictedPctMV = useTransform(predictedM, (m) => pct(m));
  const predictedText = useTransform(predictedM, fmt);
  const leadLabel = useTransform(lead, (l) => `+${l.toFixed(1)}s`);
  const predLeft = useTransform(predictedPctMV, (p) => `${p}%`);
  const trajLeft = useTransform(predictedPctMV, (p) => `${Math.min(p, nowPct)}%`);
  const trajWidth = useTransform(predictedPctMV, (p) => `${Math.abs(nowPct - p)}%`);

  // auto-demo sweep: 0.5 → 1 → 0 → 0.5 (full range, no jump), pauses on touch
  useEffect(() => {
    if (reduced || touched || !inView) return;
    const controls = animate(lead, [0.5, 1, 0, 0.5], {
      duration: 8,
      ease: "easeInOut",
      repeat: Infinity,
      delay: 1.2,
    });
    return () => controls.stop();
  }, [lead, reduced, touched, inView]);

  // keep the native slider thumb in sync with the sweep (imperative, no re-render)
  useEffect(() => {
    const unsub = lead.on("change", (v) => {
      if (sliderRef.current && !touched) sliderRef.current.value = String(v);
    });
    return unsub;
  }, [lead, touched]);

  const onSlide = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!touched) setTouched(true);
    lead.set(Number(e.target.value));
  };

  return (
    <motion.div
      ref={ref}
      className="glass relative overflow-hidden p-5 sm:p-6"
      initial={reduced ? false : { opacity: 0, y: 18 }}
      animate={inView || reduced ? { opacity: 1, y: 0 } : undefined}
      transition={reduced ? { duration: 0 } : { duration: 0.6, ease: EASE }}
    >
      {/* header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-dim" />
          <span className="font-mono text-xs uppercase tracking-[0.2em] text-muted">
            Example readout
          </span>
        </div>
        <span className="font-mono text-xs text-dim">
          sample · track #{trackId} · {catName}
        </span>
      </div>

      {/* primary readout */}
      <div className="mt-4 flex items-end justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-5xl font-semibold tabular-nums tracking-tight text-fg">
              <CountUp to={meters} run={inView} reduced={reduced} />
            </span>
            <span className="font-mono text-lg text-muted">m</span>
          </div>
          <div className="mt-1 font-mono text-xs text-orange-bright">
            ± <CountUp to={half} run={inView} reduced={reduced} delay={0.15} /> m&nbsp;
            <span className="text-dim">95% CI</span>
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-sm text-truth">
            <CountUp to={truthMeters} run={inView} reduced={reduced} delay={0.25} /> m
          </div>
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
          {/* CI band (draws in) */}
          <motion.div
            className="absolute top-[18px] h-3 rounded-full bg-orange/25"
            style={{ left: `${pct(lo)}%` }}
            initial={reduced ? false : { width: 0, opacity: 0 }}
            animate={
              inView || reduced ? { width: `${pct(hi) - pct(lo)}%`, opacity: 1 } : undefined
            }
            transition={reduced ? { duration: 0 } : { duration: 0.7, delay: 0.4, ease: EASE }}
          />
          {/* trajectory between now and predicted */}
          <motion.div
            className="absolute top-6 h-0.5 -translate-y-1/2 rounded-full"
            style={{
              left: trajLeft,
              width: trajWidth,
              background:
                "linear-gradient(90deg, var(--color-orange), var(--color-purple-bright))",
            }}
          />
          {/* truth tick */}
          <div className="absolute top-3 h-6 w-px bg-truth" style={{ left: `${pct(truthMeters)}%` }} />
          {/* current marker (pulsing = "live") */}
          <StaticMarker left={nowPct} label="now" color="var(--color-orange-bright)" pulse={!reduced} />
          {/* predicted marker (rides the sweep) */}
          <motion.div
            className="absolute top-6 -translate-x-1/2 -translate-y-1/2"
            style={{ left: predLeft }}
          >
            <div
              className="size-3.5 rounded-full border-2 border-bg"
              style={{
                background: "var(--color-purple-bright)",
                boxShadow: "0 0 12px var(--color-purple-bright)",
              }}
            />
            <motion.span
              className="absolute left-1/2 top-4 -translate-x-1/2 whitespace-nowrap font-mono text-[10px] text-purple-bright"
            >
              {leadLabel}
            </motion.span>
          </motion.div>
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
            where it will be: <motion.span className="text-fg">{predictedText}</motion.span>
            <span className="text-fg"> m</span>
          </span>
        </div>
        <input
          id={sliderId}
          ref={sliderRef}
          type="range"
          min={0}
          max={1}
          step={0.1}
          defaultValue={0.5}
          onChange={onSlide}
          aria-label="Shutter lead, seconds ahead"
          className="mt-3 h-2 w-full cursor-pointer appearance-none rounded-full bg-white/10 accent-orange"
        />
        <div className="mt-1 flex justify-between font-mono text-[10px] text-dim">
          <span>now</span>
          <span>+1.0 s</span>
        </div>
      </div>
    </motion.div>
  );
}

function StaticMarker({
  left,
  label,
  color,
  pulse,
}: {
  left: number;
  label: string;
  color: string;
  pulse?: boolean;
}) {
  return (
    <div className="absolute top-6 -translate-x-1/2 -translate-y-1/2" style={{ left: `${left}%` }}>
      {pulse && (
        <span
          className="absolute left-1/2 top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full animate-pulse-soft"
          style={{ background: color, opacity: 0.5, filter: "blur(2px)" }}
        />
      )}
      <div
        className="relative size-3.5 rounded-full border-2 border-bg"
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
