"use client";

import { useEffect, useRef } from "react";
import { contentRect } from "@/lib/letterbox";
import { concatBytes, drainJpegs, type ByteBuffer } from "@/lib/mjpeg";

type Props = {
  src: string;
  onFrame?: () => void;
  onError?: () => void;
};

/**
 * Paint MJPEG via fetch + canvas instead of <img src="multipart/...">.
 * Same letterboxing as object-contain so OverlayCanvas stays aligned.
 */
export function MjpegCanvas({ src, onFrame, onError }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const onFrameRef = useRef(onFrame);
  const onErrorRef = useRef(onError);
  onFrameRef.current = onFrame;
  onErrorRef.current = onError;

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    const ac = new AbortController();
    let buffer: ByteBuffer = new Uint8Array(0);
    let painting = false;
    let pending: ByteBuffer[] = [];
    let disposed = false;

    const paint = async (jpeg: ByteBuffer) => {
      if (disposed) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      try {
        const blob = new Blob([jpeg], { type: "image/jpeg" });
        const bitmap = await createImageBitmap(blob);
        if (disposed) {
          bitmap.close();
          return;
        }
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
        ctx.fillStyle = "#000";
        ctx.fillRect(0, 0, cw, ch);
        const rect = contentRect(cw, ch, bitmap.width, bitmap.height);
        ctx.drawImage(bitmap, rect.x, rect.y, rect.w, rect.h);
        bitmap.close();
        onFrameRef.current?.();
      } catch {
        onErrorRef.current?.();
      }
    };

    const pump = async () => {
      if (painting || pending.length === 0 || disposed) return;
      painting = true;
      while (pending.length > 0 && !disposed) {
        const jpeg = pending.shift();
        if (jpeg) await paint(jpeg);
      }
      painting = false;
    };

    (async () => {
      try {
        const res = await fetch(src, { cache: "no-store", signal: ac.signal });
        if (!res.ok || !res.body) throw new Error(`video ${res.status}`);
        const reader = res.body.getReader();
        while (!disposed) {
          const { done, value } = await reader.read();
          if (done) break;
          if (!value?.length) continue;
          buffer = concatBytes(buffer, new Uint8Array(value));
          const { frames, rest } = drainJpegs(buffer);
          buffer = rest;
          if (frames.length) {
            pending.push(...frames);
            void pump();
          }
        }
        if (!disposed) onErrorRef.current?.();
      } catch {
        if (!disposed) onErrorRef.current?.();
      }
    })();

    const ro = new ResizeObserver(() => {
      if (pending.length === 0) return;
      void pump();
    });
    ro.observe(parent);

    return () => {
      disposed = true;
      ac.abort();
      ro.disconnect();
    };
  }, [src]);

  return (
    <canvas
      ref={canvasRef}
      className="video-feed absolute inset-0 z-0 h-full w-full"
      aria-label="live robot video"
    />
  );
}
