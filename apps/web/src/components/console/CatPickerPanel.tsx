"use client";

/**
 * Live cat picker — tracker ids with crop thumbnails. Tap a cat to lock follow
 * onto it; "Auto" clears the lock (largest box wins).
 */

import { useEffect, useMemo, useState } from "react";
import type { CatCard, Telemetry } from "@/lib/useTelemetry";
import { ControlTip, SectionTitle } from "./help";

export type { CatCard };

/** Merge server catalog with overlay/telemetry ids so Follow buttons stay available. */
function mergeCatCards(telemetry: Telemetry | null): CatCard[] {
  const byId = new Map<number, CatCard>();
  for (const cat of telemetry?.cats ?? []) {
    byId.set(cat.id, cat);
  }

  const locked = telemetry?.target_id ?? null;
  const preferred = telemetry?.preferred_target_id ?? null;

  const ensure = (id: number, partial?: Partial<CatCard>) => {
    if (byId.has(id)) return;
    byId.set(id, {
      id,
      conf: partial?.conf ?? 0,
      dist_m: partial?.dist_m ?? null,
      bearing_deg: partial?.bearing_deg ?? 0,
      is_locked: locked === id,
      is_preferred: preferred === id,
      thumb_jpeg_b64: partial?.thumb_jpeg_b64 ?? null,
    });
  };

  for (const det of telemetry?.overlay?.dets ?? []) {
    if (det.track_id == null) continue;
    if (byId.has(det.track_id)) continue;
    ensure(det.track_id, {
      conf: det.conf,
      dist_m: det.dist_m,
      bearing_deg: det.bearing_deg,
      is_locked: det.is_target || locked === det.track_id,
      is_preferred: preferred === det.track_id,
    });
  }

  for (const id of telemetry?.target_ids ?? []) {
    ensure(id);
  }
  if (telemetry?.target_id != null) {
    ensure(telemetry.target_id);
  }

  return [...byId.values()].sort((a, b) => b.conf - a.conf);
}

const CAT_PAGE_SIZE = 6;

export function CatPickerPanel({
  telemetry,
  send,
  estopped,
  onOpenLibrary,
}: {
  telemetry: Telemetry | null;
  send: (obj: Record<string, unknown>) => void;
  estopped: boolean;
  onOpenLibrary?: () => void;
}) {
  const cats = useMemo(() => mergeCatCards(telemetry), [telemetry]);
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(cats.length / CAT_PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageCats = cats.slice(
    safePage * CAT_PAGE_SIZE,
    safePage * CAT_PAGE_SIZE + CAT_PAGE_SIZE,
  );

  useEffect(() => {
    setPage((p) => Math.min(p, Math.max(0, pageCount - 1)));
  }, [pageCount]);

  const preferred = telemetry?.preferred_target_id ?? null;
  const locked = telemetry?.target_id ?? null;
  const perception = telemetry?.perception_available !== false;
  const modelReady = telemetry?.model_status === "ready";

  function pick(id: number | "auto", follow: boolean) {
    send({
      type: "select_target",
      id: id === "auto" ? "auto" : id,
      follow,
    });
  }

  return (
    <div className="mt-6 border-t border-line pt-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle helpId="section.cats" className="font-mono text-xs uppercase tracking-[0.18em] text-dim">
          Cats in view
        </SectionTitle>
        <div className="flex flex-wrap items-center gap-2">
          {onOpenLibrary && (
            <button
              type="button"
              className="text-xs text-orange underline-offset-2 hover:underline"
              onClick={onOpenLibrary}
            >
              Saved cats →
            </button>
          )}
          <span className="text-xs text-muted">
            {preferred != null ? `following id ${preferred}` : locked != null ? `locked id ${locked}` : "auto (largest)"}
          </span>
        </div>
      </div>

      {!modelReady && (
        <p className="mb-2 text-xs text-muted">
          Select a model in the Models tab and connect a camera to detect cats.
        </p>
      )}

      {modelReady && cats.length === 0 && (
        <p className="mb-2 text-xs text-muted">
          {telemetry?.target_ids && telemetry.target_ids.length > 0
            ? `Tracker sees id ${telemetry.target_ids.join("/")} — refreshing picker…`
            : telemetry?.target_id != null
              ? `Tracker sees id ${telemetry.target_id} — refreshing picker…`
              : "No cats detected — point the camera at a cat."}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {pageCats.map((cat) => (
          <CatButton
            key={cat.id}
            cat={cat}
            active={preferred === cat.id || (preferred == null && cat.is_locked)}
            disabled={estopped || !perception}
            onSelect={() => pick(cat.id, false)}
            onFollow={() => pick(cat.id, true)}
          />
        ))}
      </div>

      {cats.length > CAT_PAGE_SIZE && (
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            className="op-btn px-2 py-1 text-xs"
            disabled={safePage <= 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            ← Prev
          </button>
          <span className="font-mono text-xs tabular-nums text-muted">
            {safePage * CAT_PAGE_SIZE + 1}–
            {Math.min(cats.length, (safePage + 1) * CAT_PAGE_SIZE)} of {cats.length} · page{" "}
            {safePage + 1}/{pageCount}
          </span>
          <button
            type="button"
            className="op-btn px-2 py-1 text-xs"
            disabled={safePage >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          >
            Next →
          </button>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <ControlTip helpId="cat.auto">
          <button
            type="button"
            className="op-btn text-sm"
            disabled={estopped || !perception || preferred == null}
            onClick={() => pick("auto", false)}
          >
            Auto (largest)
          </button>
        </ControlTip>
        <ControlTip helpId="cat.auto_follow">
          <button
            type="button"
            className="op-btn text-sm"
            disabled={estopped || !perception || preferred == null}
            onClick={() => pick("auto", true)}
          >
            Auto + FOLLOW
          </button>
        </ControlTip>
      </div>
      <p className="mt-2 text-xs text-dim">
        Click a cat to lock tracking. Use <span className="text-fg">Follow</span> on a card
        or switch to FOLLOW mode to drive toward the selected cat. Cats stay listed after they
        leave the frame (marked “out of view”). Saved faces live in the <span className="text-fg">Cats</span> tab.
      </p>
    </div>
  );
}

function CatButton({
  cat,
  active,
  disabled,
  onSelect,
  onFollow,
}: {
  cat: CatCard;
  active: boolean;
  disabled: boolean;
  onSelect: () => void;
  onFollow: () => void;
}) {
  const src = cat.thumb_jpeg_b64
    ? `data:image/jpeg;base64,${cat.thumb_jpeg_b64}`
    : null;
  const dist =
    cat.dist_m != null ? `${Math.round(cat.dist_m * 100)} cm` : "—";

  return (
    <div
      className={`flex min-w-[7.5rem] flex-col overflow-hidden rounded-lg border bg-white/[0.03] ${
        active ? "border-orange shadow-[0_0_0_1px_var(--color-orange)]" : "border-line"
      } ${cat.in_view === false ? "opacity-70" : ""}`}
    >
      <ControlTip helpId="cat.select" className="w-full">
        <button
          type="button"
          className="flex flex-col items-stretch text-left disabled:opacity-50"
          disabled={disabled}
          onClick={onSelect}
          aria-pressed={active}
        >
        <div className="relative aspect-square w-full bg-black/40">
          {src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={src}
              alt={`Cat ${cat.id}`}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-2xl opacity-40">🐱</div>
          )}
          <span className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 font-mono text-xs text-fg">
            #{cat.id}
          </span>
          {cat.is_locked && (
            <span className="absolute right-1 top-1 rounded bg-orange/90 px-1 py-0.5 text-[0.6rem] uppercase tracking-wide text-bg">
              lock
            </span>
          )}
          {cat.in_view === false && (
            <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 py-0.5 text-[0.6rem] uppercase text-muted">
              out of view
            </span>
          )}
        </div>
        <div className="px-2 py-1.5">
          <div className="font-mono text-sm tabular-nums">{dist}</div>
          <div className="text-[0.65rem] text-muted">
            conf {cat.conf.toFixed(2)} · {cat.bearing_deg.toFixed(0)}°
          </div>
        </div>
      </button>
      </ControlTip>
      <ControlTip helpId="cat.follow" className="w-full">
        <button
          type="button"
          className="border-t border-line py-1 text-xs text-orange hover:bg-white/5 disabled:opacity-40"
          disabled={disabled}
          onClick={onFollow}
        >
          Follow
        </button>
      </ControlTip>
    </div>
  );
}
