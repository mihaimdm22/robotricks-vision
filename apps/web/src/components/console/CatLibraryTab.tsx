"use client";

/**
 * Saved cat library — persistent faces from past sightings. Pick a cat that is
 * not currently in view and the robot enters FOLLOW + SEARCH to re-acquire it.
 */

import { useCallback, useEffect, useState } from "react";
import { api, type LibraryCat } from "@/lib/api";
import type { Telemetry } from "@/lib/useTelemetry";
import { ControlTip, SectionHelp, SectionTitle } from "./help";

function formatSeen(ts: number | null | undefined): string {
  if (ts == null || !Number.isFinite(ts)) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function CatLibraryTab({
  telemetry,
  send,
  estopped,
}: {
  telemetry: Telemetry | null;
  send: (obj: Record<string, unknown>) => void;
  estopped: boolean;
}) {
  const [cats, setCats] = useState<LibraryCat[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listCats();
      setCats(res.cats);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load cat library");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const findingId = telemetry?.find_library_id ?? null;
  const inViewIds = new Set((telemetry?.cats ?? []).filter((c) => c.in_view !== false).map((c) => c.id));
  const perception = telemetry?.perception_available !== false;

  async function saveName(id: number) {
    const name = editName.trim();
    if (!name) return;
    await api.renameCat(id, name);
    setEditingId(null);
    await refresh();
  }

  async function remove(id: number) {
    await api.deleteCat(id);
    await refresh();
  }

  function findCat(id: number) {
    send({ type: "find_cat", library_id: id, follow: true });
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <SectionTitle helpId="section.cat_library" className="font-mono text-xs uppercase tracking-[0.18em] text-dim">
          Cat library
        </SectionTitle>
        <button type="button" className="op-btn text-xs" onClick={() => refresh()} disabled={loading}>
          Refresh
        </button>
      </div>

      <p className="mb-3 text-xs text-muted">
        Cats are saved automatically when they appear on camera. Use <span className="text-fg">Find</span> to
        drive and scan for a cat that left the frame.
      </p>

      {findingId != null && (
        <p className="mb-3 rounded-lg border border-orange/40 bg-orange/10 px-3 py-2 text-xs text-orange">
          Searching for {telemetry?.find_library_name ?? `cat #${findingId}`}… robot will rotate and match faces.
        </p>
      )}

      {error && (
        <p className="mb-3 text-xs text-warn">
          {error}
          {error.includes("404") || error.includes("out of date") ? (
            <span className="mt-1 block text-dim">
              Stop and restart <code className="font-mono">catranger serve</code> or{" "}
              <code className="font-mono">make web</code>, then click Refresh.
            </span>
          ) : null}
        </p>
      )}

      {loading && cats.length === 0 && (
        <p className="text-xs text-muted">Loading saved cats…</p>
      )}

      {!loading && cats.length === 0 && !error && (
        <p className="text-xs text-muted">
          No saved cats yet. Connect a camera, select a model, and let cats appear in view — they will be added here.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {cats.map((cat) => {
          const src = cat.thumb_jpeg_b64
            ? `data:image/jpeg;base64,${cat.thumb_jpeg_b64}`
            : null;
          const live =
            cat.last_tracker_id != null && inViewIds.has(cat.last_tracker_id);
          const finding = findingId === cat.id;

          return (
            <div
              key={cat.id}
              className={`flex flex-col overflow-hidden rounded-lg border bg-white/[0.03] ${
                finding ? "border-orange shadow-[0_0_0_1px_var(--color-orange)]" : "border-line"
              }`}
            >
              <div className="relative aspect-square w-full bg-black/40">
                {src ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={src} alt={cat.name} className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full items-center justify-center text-2xl opacity-40">🐱</div>
                )}
                <span className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[0.65rem] text-fg">
                  #{cat.id}
                </span>
                {live && (
                  <span className="absolute right-1 top-1 rounded bg-orange/90 px-1 py-0.5 text-[0.6rem] uppercase text-bg">
                    live
                  </span>
                )}
              </div>

              <div className="flex flex-1 flex-col gap-2 p-2">
                {editingId === cat.id ? (
                  <div className="flex gap-1">
                    <input
                      className="min-w-0 flex-1 rounded border border-line bg-bg px-2 py-1 text-sm"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && saveName(cat.id)}
                    />
                    <button type="button" className="op-btn text-xs" onClick={() => saveName(cat.id)}>
                      Save
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="truncate text-left text-sm font-medium hover:text-orange"
                    onClick={() => {
                      setEditingId(cat.id);
                      setEditName(cat.name);
                    }}
                  >
                    {cat.name}
                  </button>
                )}

                <div className="text-[0.65rem] text-muted">
                  Seen {formatSeen(cat.last_seen_ts)}
                  {cat.last_dist_m != null ? ` · ${Math.round(cat.last_dist_m * 100)} cm` : ""}
                </div>

                <div className="mt-auto flex flex-wrap gap-1">
                  <ControlTip helpId="cat_library.find">
                    <button
                      type="button"
                      className="op-btn flex-1 text-xs text-orange"
                      disabled={estopped || !perception || finding}
                      onClick={() => findCat(cat.id)}
                    >
                      Find
                    </button>
                  </ControlTip>
                  <ControlTip helpId="cat_library.delete">
                    <button
                      type="button"
                      className="op-btn text-xs text-stop"
                      disabled={finding}
                      onClick={() => remove(cat.id)}
                    >
                      Delete
                    </button>
                  </ControlTip>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-4 text-xs text-dim">
        <SectionHelp helpId="section.cat_library" /> Find switches to FOLLOW mode, biases search toward the last
        bearing, and locks on when the face matches.
      </p>
    </div>
  );
}
