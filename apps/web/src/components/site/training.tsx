import { Icon } from "@/components/icons";
import { GlassCard, SectionHeading } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { trainingIntro, trainingPillars, trainPipeline, trainingStack } from "@/lib/content";

export function Training() {
  return (
    <section id="training" className="relative px-4 py-24 sm:px-6 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow={trainingIntro.eyebrow}
          title={
            <>
              Fine-tuned only when it <span className="text-gradient">earns its keep</span>.
            </>
          }
          intro={trainingIntro.intro}
        />

        {/* ---- training policy, three pillars ---- */}
        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {trainingPillars.map((p, i) => (
            <Reveal key={p.title} delay={i * 0.08}>
              <GlassCard className="h-full p-6">
                <span className="relative inline-flex size-11 items-center justify-center rounded-2xl border border-line bg-white/[0.03]">
                  <span className="absolute inset-0 rounded-2xl bg-gradient-to-br from-orange/15 to-purple/15" />
                  <Icon name={p.icon} className="relative size-5 text-orange-bright" />
                </span>
                <span className="mt-5 block font-mono text-[11px] uppercase tracking-[0.18em] text-dim">
                  {p.tag}
                </span>
                <h3 className="mt-2 text-lg font-semibold">{p.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{p.body}</p>
              </GlassCard>
            </Reveal>
          ))}
        </div>

        {/* ---- the fine-tune loop ---- */}
        <Reveal className="mt-6">
          <GlassCard className="p-5 sm:p-7">
            <p className="font-mono text-xs uppercase tracking-[0.25em] text-orange-bright">
              The fine-tune loop
            </p>
            <ol className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-6 lg:gap-2">
              {trainPipeline.map((s, i) => (
                <li
                  key={s.label}
                  className="relative flex flex-col gap-2 rounded-2xl border border-line bg-white/[0.02] p-4"
                >
                  <div className="flex items-center justify-between">
                    <span className="relative inline-flex size-9 items-center justify-center rounded-xl border border-line bg-white/[0.03]">
                      <Icon name={s.icon} className="size-5 text-orange-bright" />
                    </span>
                    <span className="font-mono text-[11px] text-white/15">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                  </div>
                  <h3 className="text-sm font-semibold">{s.label}</h3>
                  <p className="text-xs leading-relaxed text-muted">{s.note}</p>
                  {i < trainPipeline.length - 1 && (
                    <span className="absolute -right-2.5 top-1/2 hidden size-5 -translate-y-1/2 items-center justify-center text-purple-bright lg:flex">
                      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                        <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </GlassCard>
        </Reveal>

        {/* ---- pluggable models + datasets ---- */}
        <Reveal className="mt-6">
          <GlassCard className="p-6 sm:p-8">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.25em] text-orange-bright">
                {trainingStack.eyebrow}
              </p>
              <h3 className="mt-2 text-2xl font-semibold sm:text-3xl">{trainingStack.title}</h3>
            </div>
            <div className="mt-7 grid gap-4 md:grid-cols-3">
              <div className="rounded-2xl border border-line bg-white/[0.02] p-5">
                <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-dim">
                  {trainingStack.models.label}
                </span>
                <ul className="mt-3 space-y-2">
                  {trainingStack.models.items.map((m) => (
                    <li key={m} className="flex items-center gap-2 text-sm text-muted">
                      <span className="size-1.5 shrink-0 rounded-full bg-orange-bright" />
                      {m}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-2xl border border-line bg-white/[0.02] p-5">
                <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-dim">
                  {trainingStack.datasets.label}
                </span>
                <ul className="mt-3 space-y-2">
                  {trainingStack.datasets.items.map((d) => (
                    <li key={d} className="flex items-center gap-2 text-sm text-muted">
                      <span className="size-1.5 shrink-0 rounded-full bg-purple-bright" />
                      {d}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-2xl border border-line bg-white/[0.02] p-5">
                <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-dim">
                  {trainingStack.loop.label}
                </span>
                <p className="mt-3 text-sm leading-relaxed text-muted">{trainingStack.loop.body}</p>
              </div>
            </div>
          </GlassCard>
        </Reveal>
      </div>
    </section>
  );
}
