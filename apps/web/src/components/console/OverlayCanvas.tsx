"use client";

/**
 * WS-B1/B2 hybrid overlay: the crisp, vector layer drawn on a <canvas> over the MJPEG
 * <img>.
 *
 * Bounding boxes stay burned into the JPEG server-side (perfect pixel alignment, cheap);
 * this layer adds what JPEG compression blurs and what the operator needs sharp — the
 * locked-target ring, the distance/ID/bearing labels (B1), and at most one debounced
 * failure badge per detection (B2) — from the WS-B0 overlay JSON on the telemetry socket.
 * Coords map into the object-contain content rect so they track the burned boxes
 * regardless of aspect; the canvas dims when the link isn't live so a stale overlay is
 * never presented as fresh truth.
 */

import { useEffect, useRef } from "react";
import { type Badge, BadgeDebouncer, badgeStyle, pickBadge } from "@/lib/badges";
import { contentRect, denormBox, type Rect } from "@/lib/letterbox";
import type { OverlayDet, Telemetry } from "@/lib/useTelemetry";

/** Stable per-detection key: track id when present, else frame index (so multiple
 *  untracked detections never collide on one debounce streak / badge). */
function detKey(d: OverlayDet, index: number): string {
  return d.track_id != null ? `t${d.track_id}` : `i${index}`;
}

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function OverlayCanvas({ telemetry, live }: { telemetry: Telemetry | null; live: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const debouncer = useRef(new BadgeDebouncer(3));
  const lastFrame = useRef(-1);
  const shownBadges = useRef(new Map<string, Badge>());
  const overlay = telemetry?.overlay ?? null;

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    const draw = () => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const cw = parent.clientWidth;
      const ch = parent.clientHeight;
      const bw = Math.round(cw * dpr);
      const bh = Math.round(ch * dpr);
      if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = bw;
        canvas.height = bh;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);
      if (!overlay || overlay.dets.length === 0) return;

      // Advance badge debounce ONCE per new frame; cache so a resize redraw doesn't
      // double-count the same frame. Key by track id, or by index for untracked dets so
      // multiple null-id detections don't collide on one streak/badge.
      if (overlay.frame_id !== lastFrame.current) {
        lastFrame.current = overlay.frame_id;
        const next = new Map<string, Badge>();
        const liveKeys = new Set<string>();
        overlay.dets.forEach((d, i) => {
          const key = detKey(d, i);
          liveKeys.add(key);
          const b = debouncer.current.update(key, pickBadge(d.flags));
          if (b) next.set(key, b);
        });
        debouncer.current.retain(liveKeys); // reap streaks for detections gone this frame
        shownBadges.current = next;
      }

      const colors = {
        accent: cssVar("--color-ok", "#22c55e"),
        dim: "rgba(255,255,255,0.55)",
        warn: cssVar("--color-warn", "#f59e0b"),
        stop: cssVar("--color-stop", "#ef4444"),
      };
      ctx.globalAlpha = live ? 1 : 0.35; // stale frame underneath -> dim, don't lie

      const rect = contentRect(cw, ch, overlay.frame_w, overlay.frame_h);
      // Rings + labels: non-targets first so the locked target sits on top.
      ctx.font = "600 13px ui-monospace, monospace";
      ctx.textBaseline = "bottom";
      for (const d of overlay.dets) if (!d.is_target) drawDet(ctx, d, rect, colors.dim, false);
      for (const d of overlay.dets) if (d.is_target) drawDet(ctx, d, rect, colors.accent, true);
      // Then the (debounced) failure badges on top.
      overlay.dets.forEach((d, i) => {
        const b = shownBadges.current.get(detKey(d, i));
        if (b) drawBadge(ctx, d, rect, b, colors.warn, colors.stop);
      });
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(parent);
    return () => ro.disconnect();
  }, [overlay, live]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 z-10 h-full w-full"
    />
  );
}

function drawDet(
  ctx: CanvasRenderingContext2D,
  d: OverlayDet,
  rect: Rect,
  color: string,
  isTarget: boolean,
): void {
  const b = denormBox(d.xyxy_norm, rect);
  ctx.strokeStyle = color;
  ctx.lineWidth = isTarget ? 3 : 1.5;
  // Draw all boxes on canvas so overlays stay aligned when MJPEG repaints stall.
  ctx.strokeRect(b.x, b.y, b.w, b.h);

  const label = labelFor(d, isTarget);
  if (!label) return;
  const padX = 4;
  const tw = ctx.measureText(label).width + padX * 2;
  const th = 17;
  const lx = b.x;
  const ly = b.y > th ? b.y : b.y + b.h + th; // flip below the box if it'd clip off-top
  ctx.fillStyle = "rgba(0,0,0,0.66)";
  ctx.fillRect(lx, ly - th, tw, th);
  ctx.fillStyle = color;
  ctx.fillText(label, lx + padX, ly - 3);
}

function drawBadge(
  ctx: CanvasRenderingContext2D,
  d: OverlayDet,
  rect: Rect,
  badge: Badge,
  warn: string,
  stop: string,
): void {
  const b = denormBox(d.xyxy_norm, rect);
  const { label, tone, glyph } = badgeStyle(badge);
  const text = `${glyph} ${label}`;
  ctx.font = "600 11px ui-monospace, monospace";
  ctx.textBaseline = "middle";
  const padX = 4;
  const h = 16;
  const w = ctx.measureText(text).width + padX * 2;
  const x = b.x;
  const y = b.y + b.h - h; // bottom-left of the box, clear of the top label
  ctx.fillStyle = tone === "stop" ? stop : warn;
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#000";
  ctx.fillText(text, x + padX, y + h / 2 + 0.5);
}

function labelFor(d: OverlayDet, isTarget: boolean): string {
  const ids =
    isTarget && d.known_track_ids && d.known_track_ids.length > 0
      ? d.known_track_ids
      : d.track_id != null
        ? [d.track_id]
        : [];
  const id = ids.length ? `#${ids.join("/")}` : "·";
  if (!isTarget) return id; // keep non-targets quiet (hierarchy: the target is the story)
  const parts = [id];
  if (d.dist_m != null) {
    const ci =
      d.dist_lo != null && d.dist_hi != null ? ` ±${((d.dist_hi - d.dist_lo) / 2).toFixed(2)}` : "";
    parts.push(`${d.dist_m.toFixed(2)}m${ci}`);
  }
  parts.push(`${d.bearing_deg >= 0 ? "+" : ""}${d.bearing_deg.toFixed(0)}°`);
  return parts.join("  ");
}
