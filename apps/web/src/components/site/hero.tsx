import { GradientButton, OutlinePill, BadgeChip } from "@/components/ui";
import { hero } from "@/lib/content";
import { AnnotatedFrame } from "./annotated-frame";
import { LiveDistanceCard } from "./live-distance";

export function Hero() {
  return (
    <section id="top" className="relative px-4 pt-32 sm:px-6 sm:pt-36 lg:pt-40">
      <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-[1.05fr_1fr] lg:gap-10">
        {/* ---- left: message ---- */}
        <div className="text-center lg:pt-12 lg:text-left">
          <span className="chip">
            <span className="size-1.5 rounded-full bg-orange-bright" />
            {hero.eyebrow}
          </span>

          <h1 className="mt-6">
            <span className="block text-outline text-3xl font-semibold uppercase tracking-[0.06em] sm:text-4xl">
              {hero.headingTop}
            </span>
            <span className="relative mt-1 inline-block">
              <span className="text-gradient text-7xl font-bold uppercase tracking-tight sm:text-8xl">
                {hero.headingAccent}
              </span>
              <Swoosh />
            </span>
          </h1>

          <p className="mx-auto mt-6 max-w-xl text-pretty text-base leading-relaxed text-muted lg:mx-0">
            {hero.body}
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-3 lg:justify-start">
            <GradientButton href={hero.primary.href}>
              {hero.primary.label}
              <ArrowRight />
            </GradientButton>
            <OutlinePill href={hero.secondary.href}>
              <Play />
              {hero.secondary.label}
            </OutlinePill>
          </div>

          <div className="mt-6 flex flex-wrap justify-center gap-2 lg:justify-start">
            {hero.chips.map((c) => (
              <BadgeChip key={c}>{c}</BadgeChip>
            ))}
          </div>

          <dl className="mt-10 grid max-w-md grid-cols-3 gap-4 lg:max-w-none">
            {hero.stats.map((s) => (
              <div key={s.label} className="text-center lg:text-left">
                <dt className="sr-only">{s.label}</dt>
                <dd className="font-display text-2xl font-semibold text-fg sm:text-3xl">
                  {s.value}
                </dd>
                <p className="mt-0.5 text-xs text-dim">{s.label}</p>
              </div>
            ))}
          </dl>
        </div>

        {/* ---- right: live visual ---- */}
        <div id="live" className="relative scroll-mt-28">
          <div className="relative">
            <div className="glass animate-float overflow-hidden p-2.5 glow-purple">
              <AnnotatedFrame />
            </div>

            {/* floating decorative chips (desktop) */}
            <div className="absolute -left-6 top-10 hidden animate-float-slow lg:block">
              <BadgeChip>±1 cm ground truth</BadgeChip>
            </div>
            <div className="absolute -right-5 top-28 hidden animate-float lg:block">
              <BadgeChip>fused depth</BadgeChip>
            </div>
            <div className="absolute -bottom-4 left-12 hidden animate-float-slow lg:block">
              <BadgeChip>predicted +0.5s</BadgeChip>
            </div>
          </div>

          <div className="mt-5">
            <LiveDistanceCard />
          </div>
        </div>
      </div>
    </section>
  );
}

function Swoosh() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 320 60"
      className="absolute -bottom-3 left-0 h-8 w-[112%]"
      fill="none"
    >
      <defs>
        <linearGradient id="swoosh" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="var(--color-orange)" />
          <stop offset="1" stopColor="var(--color-purple-bright)" />
        </linearGradient>
      </defs>
      <path
        d="M4 44 C 90 56 210 50 286 18"
        stroke="url(#swoosh)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray="3 9"
        style={{ animation: "dash 1.4s linear infinite" }}
      />
      <path d="M278 8 L300 14 L282 28 Z" fill="var(--color-purple-bright)" />
    </svg>
  );
}

function ArrowRight() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Play() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden>
      <path d="M8 5.5v13l11-6.5z" />
    </svg>
  );
}
