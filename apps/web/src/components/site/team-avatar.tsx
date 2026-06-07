"use client";

import Image from "next/image";
import { useState } from "react";

/**
 * Renders a member headshot from /public/team/<slug>.jpg. Until that file
 * exists (or if it fails to load) it falls back to a branded initials disc,
 * so the section looks finished before real photos are dropped in.
 */
export function TeamAvatar({
  slug,
  name,
  initials,
  hasPhoto,
}: {
  slug: string;
  name: string;
  initials: string;
  /** Set at build time when public/team/<slug>.jpg exists. */
  hasPhoto: boolean;
}) {
  const [failed, setFailed] = useState(false);

  return (
    <span className="relative inline-flex size-20 items-center justify-center overflow-hidden rounded-2xl border border-line bg-white/[0.03]">
      <span
        aria-hidden
        className="absolute inset-0 bg-gradient-to-br from-orange/25 to-purple/25"
      />
      {!hasPhoto || failed ? (
        <span className="relative font-display text-xl font-semibold text-fg">
          {initials}
        </span>
      ) : (
        <Image
          src={`/team/${slug}.jpg`}
          alt={name}
          fill
          sizes="80px"
          onError={() => setFailed(true)}
          className="object-cover"
        />
      )}
    </span>
  );
}
