"use client";

/**
 * MJPEG video. Three distinct failure surfaces (the vanilla panel only had one):
 *  - STALE: frames stopped arriving (telemetry frame_age_ms past the threshold).
 *  - UNREACHABLE: the <img> itself failed to load (server down / wrong origin /
 *    CORS) — there is no frame_age_ms signal in that case, so we catch onError.
 * A plain <img> is used (not next/image): MJPEG is a multipart stream, not a
 * static asset.
 *
 * Stale detection uses hysteresis + delayed reload so brief frame gaps don't
 * remount the stream (which causes a visible full-frame flicker).
 */

import { memo, useEffect, useRef, useState } from "react";
import { videoURL } from "@/lib/api";
import type { Telemetry } from "@/lib/useTelemetry";
import { CameraPTZ } from "./CameraPTZ";
import { OverlayCanvas } from "./OverlayCanvas";
import { ControlTip } from "./help";

function VideoPaneInner({ telemetry }: { telemetry: Telemetry | null }) {
  const [reloadKey, setReloadKey] = useState(0);
  const [unreachable, setUnreachable] = useState(false);
  const [showStale, setShowStale] = useState(false);
  const reloadScheduled = useRef(false);

  const frameAge = telemetry?.frame_age_ms;
  const staleMs = telemetry?.video_stale_ms ?? 1000;
  const frameFresh = frameAge == null || frameAge <= staleMs;

  useEffect(() => {
    if (frameFresh) {
      setShowStale(false);
      reloadScheduled.current = false;
      return;
    }
    const showId = setTimeout(() => setShowStale(true), 2500);
    const reloadId = setTimeout(() => {
      if (reloadScheduled.current) return;
      reloadScheduled.current = true;
      setReloadKey((k) => k + 1);
    }, 7000);
    return () => {
      clearTimeout(showId);
      clearTimeout(reloadId);
    };
  }, [frameFresh, frameAge]);

  const live = frameFresh && !unreachable;

  return (
    <div className="flex flex-col gap-2">
      <div className="video-shell relative aspect-video w-full overflow-hidden rounded-xl border border-line bg-black">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          key={reloadKey}
          src={`${videoURL()}?k=${reloadKey}`}
          alt="live robot video"
          className="video-feed absolute inset-0 z-0 h-full w-full object-contain"
          onLoad={() => {
            setUnreachable(false);
            reloadScheduled.current = false;
          }}
          onError={() => setUnreachable(true)}
        />
        <OverlayCanvas telemetry={telemetry} live={live} />
        {unreachable ? (
          <Overlay tone="danger">
            VIDEO FEED UNREACHABLE
            <ControlTip helpId="video.retry">
              <button
                type="button"
                className="op-btn mt-3"
                onClick={() => {
                  reloadScheduled.current = false;
                  setReloadKey((k) => k + 1);
                }}
              >
                Retry
              </button>
            </ControlTip>
          </Overlay>
        ) : (
          showStale && <Overlay tone="warn">VIDEO STALE — waiting for frames</Overlay>
        )}
      </div>
      <CameraPTZ telemetry={telemetry} />
    </div>
  );
}

export const VideoPane = memo(VideoPaneInner);

function Overlay({ tone, children }: { tone: "warn" | "danger"; children: React.ReactNode }) {
  return (
    <div
      className="video-overlay absolute inset-0 z-20 flex flex-col items-center justify-center gap-1 bg-black/70 text-center font-mono text-sm font-semibold uppercase tracking-wide backdrop-blur-[2px]"
      style={{ color: tone === "danger" ? "var(--color-stop)" : "var(--color-warn)" }}
    >
      {children}
    </div>
  );
}
