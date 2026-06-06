import { Icon } from "@/components/icons";
import { GlassCard, SectionHeading } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { capabilities } from "@/lib/content";

export function Capabilities() {
  return (
    <section id="features" className="relative px-4 py-24 sm:px-6 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="Core capabilities"
          title={
            <>
              Three things, done <span className="text-gradient">honestly</span>.
            </>
          }
          intro="No magic numbers. Every distance carries its uncertainty, every prediction shows its lead time, and every robot move has a hard safety stop."
        />

        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {capabilities.map((c, i) => (
            <Reveal key={c.title} delay={i * 0.08}>
              <GlassCard className="group h-full p-6 transition-transform duration-300 hover:-translate-y-1">
                <div className="flex items-center justify-between">
                  <span className="relative inline-flex size-12 items-center justify-center rounded-2xl border border-line bg-white/[0.03]">
                    <span className="absolute inset-0 rounded-2xl bg-gradient-to-br from-orange/20 to-purple/20 opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                    <Icon name={c.icon} className="relative size-6 text-orange-bright" />
                  </span>
                  <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-dim">
                    {c.tag}
                  </span>
                </div>
                <h3 className="mt-5 text-xl font-semibold">{c.title}</h3>
                <p className="mt-2.5 text-sm leading-relaxed text-muted">{c.body}</p>
              </GlassCard>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
