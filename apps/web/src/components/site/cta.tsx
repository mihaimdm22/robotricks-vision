import { GradientButton, OutlinePill } from "@/components/ui";
import { Reveal } from "@/components/reveal";

export function CallToAction() {
  return (
    <section className="relative px-4 py-12 sm:px-6 sm:py-20">
      <Reveal className="mx-auto max-w-5xl">
        <div className="glass relative overflow-hidden px-6 py-14 text-center sm:px-12 sm:py-20">
          {/* internal glow */}
          <div
            aria-hidden
            className="absolute inset-0 opacity-70"
            style={{
              background:
                "radial-gradient(60% 80% at 50% 0%, color-mix(in oklab, var(--color-orange) 28%, transparent), transparent 70%)",
            }}
          />
          <div className="relative">
            <h2 className="mx-auto max-w-2xl text-balance text-4xl font-semibold sm:text-5xl">
              Point a camera. Know the{" "}
              <span className="text-gradient">distance</span>.
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-pretty text-base text-muted">
              Open the console, connect your camera and robot, and start a session.
              The pretrained baseline runs out of the box — no training, no calibration
              to get a first reading.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <GradientButton href="/console">Open Console</GradientButton>
              <OutlinePill href="#how">See the pipeline</OutlinePill>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
