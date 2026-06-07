import { Icon } from "@/components/icons";
import { GlassCard, SectionHeading } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { metrics, metricsIntro } from "@/lib/content";

export function Metrics() {
  return (
    <section id="metrics" className="relative px-4 py-24 sm:px-6 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow={metricsIntro.eyebrow}
          title={
            <>
              We only keep what{" "}
              <span className="text-gradient">moves the number</span>.
            </>
          }
          intro={metricsIntro.intro}
        />

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {metrics.map((m, i) => (
            <Reveal key={m.value} delay={i * 0.07}>
              <GlassCard className="h-full p-6">
                <span className="relative inline-flex size-11 items-center justify-center rounded-2xl border border-line bg-white/[0.03]">
                  <span className="absolute inset-0 rounded-2xl bg-gradient-to-br from-orange/15 to-purple/15" />
                  <Icon name={m.icon} className="relative size-5 text-orange-bright" />
                </span>
                <p className="mt-5 font-display text-xl font-semibold">{m.value}</p>
                <p className="mt-0.5 font-mono text-[11px] uppercase tracking-[0.14em] text-dim">
                  {m.label}
                </p>
                <p className="mt-3 text-sm leading-relaxed text-muted">{m.body}</p>
              </GlassCard>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
