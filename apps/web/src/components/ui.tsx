/**
 * Shared visual primitives for the landing page — and the seed of the
 * app-wide design system reused by the dashboard/admin.
 */
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { Icon, type IconName } from "@/components/icons";

function cx(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ----------------------------- GlassCard ----------------------------- */
export function GlassCard({
  className,
  children,
  ...rest
}: ComponentProps<"div">) {
  return (
    <div className={cx("glass", className)} {...rest}>
      {children}
    </div>
  );
}

/* ------------------------------- Chip -------------------------------- */
export function BadgeChip({
  children,
  dot = true,
  className,
}: {
  children: ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span className={cx("chip", className)}>
      {dot && (
        <span className="size-1.5 rounded-full bg-orange-bright animate-pulse-soft" />
      )}
      {children}
    </span>
  );
}

/* --------------------------- Gradient button -------------------------- */
type BtnProps = {
  children: ReactNode;
  href: string;
  className?: string;
};

export function GradientButton({ children, href, className }: BtnProps) {
  return (
    <Link
      href={href}
      className={cx(
        "btn-drive inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-sm font-medium tracking-wide",
        className,
      )}
    >
      {children}
    </Link>
  );
}

export function OutlinePill({ children, href, className }: BtnProps) {
  return (
    <Link
      href={href}
      className={cx(
        "pill-outline inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-sm font-medium tracking-wide text-fg",
        className,
      )}
    >
      {children}
    </Link>
  );
}

/* ----------------------------- IconBadge ----------------------------- */
export function IconBadge({ name }: { name: IconName }) {
  return (
    <span className="relative inline-flex size-12 items-center justify-center rounded-2xl border border-line bg-white/[0.03]">
      <span className="absolute inset-0 rounded-2xl bg-gradient-to-br from-orange/15 to-purple/15" />
      <Icon name={name} className="relative size-6 text-orange-bright" />
    </span>
  );
}

/* --------------------------- Section header -------------------------- */
export function SectionHeading({
  eyebrow,
  title,
  intro,
}: {
  eyebrow: string;
  title: ReactNode;
  intro?: string;
}) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="font-mono text-xs uppercase tracking-[0.25em] text-orange-bright">
        {eyebrow}
      </p>
      <h2 className="mt-4 text-balance text-4xl font-semibold sm:text-5xl">
        {title}
      </h2>
      {intro && (
        <p className="mt-4 text-pretty text-base leading-relaxed text-muted">
          {intro}
        </p>
      )}
    </div>
  );
}
