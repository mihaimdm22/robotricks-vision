"use client";

/**
 * MJPEG video. Three distinct failure surfaces (the vanilla panel only had one):
 *  - STALE: frames stopped arriving (telemetry frame_age_ms past the threshold).
 *  - UNREACHABLE: the <img> itself failed to load (server down / wrong origin /
 *    CORS) — there is no frame_age_ms signal in that case, so we catch onError.
 * A plain <img> is used (not next/image): MJPEG is a multipart stream, not a
 * static asset.
 */

import { useEffect, useState } from "react";
import { videoURL } from "@/lib/api";
import type { Telemetry } from "@/lib/useTelemetry";

export function VideoPane({ telemetry }: { telemetry: Telemetry | null }) {
  const [reloadKey, setReloadKey] = useState(0);
  const [unreachable, setUnreachable] = useState(false);

  const stale =
    telemetry?.frame_age_ms != null &&
    telemetry.frame_age_ms > (telemetry.video_stale_ms || 1000);

  // Auto re-fetch the stream once when it goes stale (an MJPEG <img> won't
  // reconnect on its own).
  useEffect(() => {
    if (stale) {
      const id = setTimeout(() => setReloadKey((k) => k + 1), 1500);
      return () => clearTimeout(id);
    }
  }, [stale]);

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl border border-line bg-black">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        key={reloadKey}
        src={`${videoURL()}?k=${reloadKey}`}
        alt="live robot video"
        className="h-full w-full object-contain"
        onLoad={() => setUnreachable(false)}
        onError={() => setUnreachable(true)}
      />
      {unreachable ? (
        <Overlay tone="danger">
          VIDEO FEED UNREACHABLE
          <button type="button" className="op-btn mt-3" onClick={() => setReloadKey((k) => k + 1)}>
            Retry
          </button>
        </Overlay>
      ) : (
        stale && <Overlay tone="warn">VIDEO STALE — no fresh frames</Overlay>
      )}
    </div>
  );
}

function Overlay({ tone, children }: { tone: "warn" | "danger"; children: React.ReactNode }) {
  return (
    <div
      className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/65 text-center font-mono text-sm font-semibold uppercase tracking-wide"
      style={{ color: tone === "danger" ? "var(--color-stop)" : "var(--color-warn)" }}
    >
      {children}
    </div>
  );
}
