"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Gear } from "@/components/icons";
import { GradientButton } from "@/components/ui";
import { nav } from "@/lib/content";

export function Nav() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className="fixed inset-x-0 top-0 z-50 px-4 pt-3 sm:px-6">
      <nav
        className={`mx-auto flex max-w-6xl items-center justify-between rounded-2xl px-4 py-3 transition-colors duration-300 sm:px-5 ${
          scrolled ? "glass" : "border border-transparent"
        }`}
      >
        <Link href="#top" className="group flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-orange to-purple text-white">
            <Gear className="size-5 animate-spin-slow" />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">
            Cat<span className="text-gradient">Ranger</span>
          </span>
        </Link>

        <div className="hidden items-center gap-7 lg:flex">
          {nav.links.map((l) => (
            <Link
              key={l.label}
              href={l.href}
              className="text-sm text-muted transition-colors hover:text-fg"
            >
              {l.label}
            </Link>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="hidden sm:inline-flex">
            <GradientButton href={nav.cta.href} className="px-5 py-2.5">
              {nav.cta.label}
            </GradientButton>
          </span>
          <button
            type="button"
            aria-label="Toggle menu"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="flex size-10 items-center justify-center rounded-xl border border-line text-fg lg:hidden"
          >
            <span className="relative block h-3 w-4">
              <span
                className={`absolute left-0 top-0 h-0.5 w-4 bg-current transition-transform ${
                  open ? "translate-y-[5px] rotate-45" : ""
                }`}
              />
              <span
                className={`absolute bottom-0 left-0 h-0.5 w-4 bg-current transition-transform ${
                  open ? "-translate-y-[5px] -rotate-45" : ""
                }`}
              />
            </span>
          </button>
        </div>
      </nav>

      {open && (
        <div className="glass mx-auto mt-2 max-w-6xl space-y-1 p-3 lg:hidden">
          {nav.links.map((l) => (
            <Link
              key={l.label}
              href={l.href}
              onClick={() => setOpen(false)}
              className="block rounded-xl px-4 py-3 text-sm text-muted hover:bg-white/5 hover:text-fg"
            >
              {l.label}
            </Link>
          ))}
          <GradientButton href={nav.cta.href} className="mt-1 w-full">
            {nav.cta.label}
          </GradientButton>
        </div>
      )}
    </header>
  );
}
