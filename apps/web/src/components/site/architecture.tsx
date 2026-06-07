import { Icon } from "@/components/icons";
import { GlassCard, SectionHeading } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { approaches, fusion, pipeline } from "@/lib/content";

export function Architecture() {
  return (
    <section id="architecture" className="relative px-4 py-24 sm:px-6 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="Architecture"
          title={
            <>
              One pipeline, <span className="text-gradient">end to end</span>.
            </>
          }
          intro="Pretrained perception plus classical camera geometry. The same chain produces the overlay, the JSON report, and the robot commands — no training required to run."
        />

        {/* ---- pipeline flow ---- */}
        <Reveal className="mt-14">
          <GlassCard className="p-5 sm:p-7">
            <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6 lg:gap-2">
              {pipeline.map((s, i) => (
                <li key={s.label} className="relative flex flex-col gap-2 rounded-2xl border border-line bg-white/[0.02] p-4">
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
                  {i < pipeline.length - 1 && (
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

        {/* ---- two interchangeable approaches ---- */}
        <div className="mt-12">
          <p className="text-center font-mono text-xs uppercase tracking-[0.25em] text-orange-bright">
            Two interchangeable approaches
          </p>
          <div className="mt-6 grid gap-5 md:grid-cols-2">
            {approaches.map((a, i) => (
              <Reveal key={a.tag} delay={i * 0.08}>
                <GlassCard className="h-full p-6">
                  <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-dim">
                    {a.tag}
                  </span>
                  <dl className="mt-4 space-y-3 text-sm">
                    <div className="flex items-baseline justify-between gap-4">
                      <dt className="text-dim">Detector</dt>
                      <dd className="text-right font-medium">{a.detector}</dd>
                    </div>
                    <div className="flex items-baseline justify-between gap-4 border-t border-line pt-3">
                      <dt className="text-dim">Tracker</dt>
                      <dd className="text-right font-medium">{a.tracker}</dd>
                    </div>
                    <div className="border-t border-line pt-3">
                      <dt className="text-dim">Pick when</dt>
                      <dd className="mt-1 leading-relaxed text-muted">{a.pickWhen}</dd>
                    </div>
                  </dl>
                </GlassCard>
              </Reveal>
            ))}
          </div>
        </div>

        {/* ---- distance fusion ---- */}
        <Reveal className="mt-12">
          <GlassCard className="p-6 sm:p-8">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="font-mono text-xs uppercase tracking-[0.25em] text-orange-bright">
                  {fusion.eyebrow}
                </p>
                <h3 className="mt-2 text-2xl font-semibold sm:text-3xl">{fusion.title}</h3>
              </div>
            </div>
            <div className="mt-7 grid gap-4 md:grid-cols-3">
              {[fusion.geometry, fusion.depth, fusion.fused].map((f) => (
                <div key={f.label} className="rounded-2xl border border-line bg-white/[0.02] p-5">
                  <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-dim">
                    {f.label}
                  </span>
                  <p className="mt-3 rounded-lg bg-black/30 px-3 py-2 font-mono text-xs text-orange-bright">
                    {f.formula}
                  </p>
                  <p className="mt-3 text-sm leading-relaxed text-muted">{f.body}</p>
                </div>
              ))}
            </div>
          </GlassCard>
        </Reveal>
      </div>
    </section>
  );
}
