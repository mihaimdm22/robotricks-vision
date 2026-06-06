/**
 * Fixed, decorative ambient canvas: layered orange/purple/magenta radial
 * glows + a masked engineering grid. Purely visual, hidden from a11y tree.
 */
export function BackgroundField() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      {/* base wash */}
      <div className="absolute inset-0 bg-bg" />
      {/* drive-orange glow, top-left */}
      <div
        className="absolute -left-40 -top-48 size-[42rem] rounded-full blur-[120px] opacity-50"
        style={{
          background:
            "radial-gradient(circle, var(--color-orange) 0%, transparent 62%)",
        }}
      />
      {/* motion-purple glow, right */}
      <div
        className="absolute -right-52 top-24 size-[46rem] rounded-full blur-[130px] opacity-45"
        style={{
          background:
            "radial-gradient(circle, var(--color-purple) 0%, transparent 62%)",
        }}
      />
      {/* magenta floor */}
      <div
        className="absolute -bottom-64 left-1/3 size-[40rem] -translate-x-1/2 rounded-full blur-[140px] opacity-30"
        style={{
          background:
            "radial-gradient(circle, var(--color-magenta) 0%, transparent 65%)",
        }}
      />
      {/* engineering grid */}
      <div className="grid-field absolute inset-0" />
      {/* vignette */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 90% 60% at 50% 0%, transparent 40%, rgba(0,0,0,0.55) 100%)",
        }}
      />
    </div>
  );
}
