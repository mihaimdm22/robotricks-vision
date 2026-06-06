"use client";

/**
 * M3 Eval tab. Start a background eval run, poll status, render the report.
 * Metric CARDS come from the structured metrics JSON; the full report.md is
 * shown verbatim in a <pre> (our own trusted output — no markdown dependency).
 * Distance MAE/MAPE only appears when ground-truth labels were supplied, so the
 * happy path over the provided unlabeled set shows FPS / tracking / smoothness.
 */

import { useCallback, useEffect, useState } from "react";
import { api, type EvalMetrics, type EvalStatus } from "@/lib/api";

const SECTION_TITLES: Record<string, string> = {
  fps: "Throughput (FPS)",
  tracking: "Track continuity",
  distance: "Distance accuracy (How Far)",
  smoothness: "Command smoothness",
  reacquire: "Synthetic-occlusion re-acquire",
};

function fmt(v: number | boolean | null): string {
  if (v === null) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Number.isNaN(v)) return "n/a";
  return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/\.?0+$/, "");
}

export function EvalTab() {
  const [source, setSource] = useState("data/raw/how_far");
  const [approach, setApproach] = useState("A");
  const [maxFrames, setMaxFrames] = useState(0);
  const [useDepth, setUseDepth] = useState(false);

  const [status, setStatus] = useState<EvalStatus | null>(null);
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [err, setErr] = useState<{ problem: string; fix?: string } | null>(null);

  const running = status?.state === "running";

  const refresh = useCallback(async () => {
    const s = await api.evalStatus();
    if (s.ok) setStatus(s);
  }, []);

  useEffect(() => {
    // fetch-on-mount: setState happens after the await, not synchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  // Poll while running; fetch the report when it finishes.
  useEffect(() => {
    if (!running) return;
    const id = setInterval(async () => {
      const s = await api.evalStatus();
      if (!s.ok) return;
      setStatus(s);
      if (s.state === "done") {
        const r = await api.evalReport();
        if (r.ok) {
          setMetrics(r.metrics);
          setMarkdown(r.markdown);
        }
      }
    }, 1000);
    return () => clearInterval(id);
  }, [running]);

  async function run() {
    setErr(null);
    setMetrics(null);
    setMarkdown("");
    const r = await api.evalRun({
      source,
      approach,
      classes: null,
      max_frames: maxFrames,
      use_depth: useDepth,
    });
    if (!r.ok) {
      setErr({ problem: r.problem, fix: r.fix });
      return;
    }
    refresh();
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="op-surface flex flex-col gap-3 p-4">
        <label className="text-sm text-muted">
          Source (image dir / video — not a webcam)
          <input
            className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-sm"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
        </label>
        <div className="flex flex-wrap gap-3 text-sm text-muted">
          <label>
            Approach
            <select
              className="ml-2 rounded-md border border-line bg-bg px-2 py-1"
              value={approach}
              onChange={(e) => setApproach(e.target.value)}
            >
              <option value="A">A — YOLO11</option>
              <option value="B">B — RT-DETR</option>
            </select>
          </label>
          <label>
            Max frames (0 = all)
            <input
              type="number"
              className="ml-2 w-24 rounded-md border border-line bg-bg px-2 py-1"
              value={maxFrames}
              onChange={(e) => setMaxFrames(parseInt(e.target.value, 10) || 0)}
            />
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={useDepth} onChange={(e) => setUseDepth(e.target.checked)} />
            depth net (slower on CPU)
          </label>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="op-btn" onClick={run} disabled={running}>
            {running ? "Running…" : "Run eval"}
          </button>
          {running && (
            <button type="button" className="op-btn" onClick={() => api.evalCancel()}>
              Cancel
            </button>
          )}
          <span className="text-xs text-dim">
            {status ? `state: ${status.state}` : ""}
            {running && status?.done ? ` · ${status.done}${status.total ? `/${status.total}` : ""} frames` : ""}
          </span>
        </div>
        <p className="text-xs text-dim">
          Eval is CPU/GPU-heavy — the server refuses it unless the robot is IDLE.
        </p>
      </div>

      {err && (
        <div className="op-surface border-stop/40 p-3 text-sm text-stop">
          {err.problem}
          {err.fix && <div className="mt-1 text-warn">→ {err.fix}</div>}
        </div>
      )}
      {status?.state === "error" && status.error && (
        <div className="op-surface border-stop/40 p-3 text-sm text-stop">eval failed: {status.error}</div>
      )}

      {metrics && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {Object.entries(metrics).map(([section, vals]) => (
            <div key={section} className="op-surface p-3">
              <h4 className="mb-2 font-display text-sm font-semibold text-orange-bright">
                {SECTION_TITLES[section] ?? section}
              </h4>
              <table className="w-full text-sm">
                <tbody>
                  {Object.entries(vals).map(([k, v]) => (
                    <tr key={k} className="border-t border-line/60">
                      <td className="py-1 text-muted">{k}</td>
                      <td className="py-1 text-right font-mono">{fmt(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {markdown && (
        <details className="op-surface p-3">
          <summary className="cursor-pointer text-sm text-muted">Full report.md</summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted">{markdown}</pre>
        </details>
      )}
    </div>
  );
}
