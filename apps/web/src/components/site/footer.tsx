import Link from "next/link";
import { Gear } from "@/components/icons";
import { footer } from "@/lib/content";

export function Footer() {
  return (
    <footer className="relative border-t border-line px-4 py-14 sm:px-6">
      <div className="mx-auto grid max-w-6xl gap-10 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <Link href="#top" className="flex items-center gap-2.5">
            <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-orange to-purple text-white">
              <Gear className="size-5" />
            </span>
            <span className="font-display text-lg font-semibold">
              Cat<span className="text-gradient">Ranger</span>
            </span>
          </Link>
          <p className="mt-4 max-w-xs font-mono text-xs uppercase tracking-[0.18em] text-dim">
            {footer.tagline}
          </p>
        </div>

        {footer.columns.map((col) => (
          <div key={col.title}>
            <h3 className="font-mono text-xs uppercase tracking-[0.18em] text-muted">
              {col.title}
            </h3>
            <ul className="mt-4 space-y-2.5">
              {col.links.map((l) => (
                <li key={l}>
                  <Link
                    href="#"
                    className="text-sm text-dim transition-colors hover:text-fg"
                  >
                    {l}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="mx-auto mt-12 flex max-w-6xl flex-col items-center justify-between gap-3 border-t border-line pt-6 text-center text-xs text-dim sm:flex-row sm:text-left">
        <p>© 2026 CatRanger · Monsson hack-a-ton entry.</p>
        <p className="font-mono">Built on pretrained perception + camera geometry.</p>
      </div>
    </footer>
  );
}
