import Link from "next/link";
import { Icon } from "@/components/icons";
import { GlassCard, SectionHeading } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { docs, docsIntro } from "@/lib/content";

export function Docs() {
  return (
    <section id="docs" className="relative px-4 py-24 sm:px-6 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow={docsIntro.eyebrow}
          title={
            <>
              Go <span className="text-gradient">deeper</span>.
            </>
          }
          intro={docsIntro.intro}
        />

        <div className="mt-14 grid gap-5 sm:grid-cols-2">
          {docs.map((d, i) => (
            <Reveal key={d.title} delay={i * 0.07}>
              <Link href={d.href} target="_blank" rel="noreferrer" className="group block h-full">
                <GlassCard className="flex h-full items-start gap-4 p-6 transition-transform duration-300 group-hover:-translate-y-1">
                  <span className="relative inline-flex size-12 shrink-0 items-center justify-center rounded-2xl border border-line bg-white/[0.03]">
                    <span className="absolute inset-0 rounded-2xl bg-gradient-to-br from-orange/15 to-purple/15" />
                    <Icon name={d.icon} className="relative size-6 text-orange-bright" />
                  </span>
                  <div>
                    <h3 className="text-lg font-semibold">{d.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-muted">{d.body}</p>
                    <span className="mt-3 inline-flex items-center gap-1.5 font-mono text-xs text-orange-bright">
                      {d.cta}
                      <svg viewBox="0 0 24 24" className="size-3.5 transition-transform group-hover:translate-x-0.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                        <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </span>
                  </div>
                </GlassCard>
              </Link>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
