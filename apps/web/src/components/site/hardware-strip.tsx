import { Icon } from "@/components/icons";
import { GlassCard, SectionHeading } from "@/components/ui";
import { Reveal } from "@/components/reveal";
import { hardware } from "@/lib/content";

export function HardwareStrip() {
  return (
    <section id="hardware" className="relative px-4 py-24 sm:px-6 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="Hardware"
          title={
            <>
              Fully wireless. One laptop <span className="text-gradient">brain</span>.
            </>
          }
          intro="The laptop talks to the camera over Wi-Fi and the robot over Bluetooth — no gateway. Connect it all from the admin view in a few clicks."
        />

        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {hardware.map((h, i) => (
            <Reveal key={h.name} delay={i * 0.08}>
              <GlassCard className="flex h-full items-start gap-4 p-6">
                <span className="relative inline-flex size-12 shrink-0 items-center justify-center rounded-2xl border border-line bg-white/[0.03]">
                  <span className="absolute inset-0 rounded-2xl bg-gradient-to-br from-orange/15 to-purple/15" />
                  <Icon name={h.icon} className="relative size-6 text-purple-bright" />
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-semibold">{h.name}</h3>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-dim">
                      {h.role}
                    </span>
                  </div>
                  <p className="mt-0.5 font-mono text-xs text-orange-bright">{h.link}</p>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{h.detail}</p>
                </div>
              </GlassCard>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
