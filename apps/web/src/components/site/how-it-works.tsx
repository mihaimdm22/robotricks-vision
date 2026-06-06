import { Icon } from "@/components/icons";
import { GlassCard, SectionHeading } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { steps } from "@/lib/content";

export function HowItWorks() {
  return (
    <section id="how" className="relative px-4 py-24 sm:px-6 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="How it works"
          title={
            <>
              One frame, four <span className="text-gradient">stages</span>.
            </>
          }
          intro="Pretrained perception plus classical camera geometry — no training required to run. The same pipeline drives the overlay, the JSON, and the robot."
        />

        <ol className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((s, i) => (
            <Reveal key={s.n} delay={i * 0.07}>
              <GlassCard className="relative h-full p-6">
                <div className="flex items-center justify-between">
                  <Icon name={s.icon} className="size-6 text-orange-bright" />
                  <span className="font-mono text-2xl font-semibold text-white/10">
                    {s.n}
                  </span>
                </div>
                <h3 className="mt-5 text-lg font-semibold">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
                {i < steps.length - 1 && (
                  <span className="absolute -right-3 top-1/2 hidden size-6 -translate-y-1/2 items-center justify-center text-purple-bright lg:flex">
                    <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                      <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                )}
              </GlassCard>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}
