"use client";

/**
 * Training tab (under the CV sub-toggle, beside Eval). Fine-tune a pretrained
 * detector via the single-file harness: a readiness strip, a launch panel that
 * disables Run with an inline reason when the system can't safely train, a live
 * log tail + coarse progress while running, a run-history table, and per-row
 * promote-to-Models. Heavy jobs are server-gated to IDLE — we NEVER auto-switch
 * the robot to IDLE for the operator; we explain why Run is blocked instead.
 *
 * Cancel is a NEUTRAL op-btn (never red, never near E-stop): a cancelled run is
 * a benign "stopped", not a safety stop.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type TrainKind,
  type TrainReadiness,
  type TrainStatus,
  type TrainHistoryRun,
} from "@/lib/api";
import { ControlTip } from "./help";

const KINDS: { id: TrainKind; label: string }[] = [
  { id: "prepare", label: "prepare — build dataset" },
  { id: "train", label: "train — fine-tune" },
  { id: "autoresearch", label: "autoresearch — keep/reject loop" },
];
const DEVICES = ["auto", "cuda", "mps", "cpu"];
// Must match catranger.train.prepare's --source choices exactly (argparse rejects
// anything else). A free-text path here would fail the run with exit code 2.
type PrepareSource = "roboflow" | "openimages" | "manual";
const PREPARE_SOURCES: PrepareSource[] = ["roboflow", "openimages", "manual"];

function fmtMetric(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/\.?0+$/, "");
}
function fmtDuration(s: number | null): string {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`;
}
function fmtWhen(ts: string): string {
  // history stamps are "YYYYMMDD-HHMMSS-<suffix>", not epoch seconds.
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(ts);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts;
}

function Marker({ ok }: { ok: boolean }) {
  return (
    <span className="font-mono" style={{ color: ok ? "var(--color-ok)" : "var(--color-stop)" }}>
      {ok ? "ok" : "x"}
    </span>
  );
}

export function TrainingTab() {
  const [readiness, setReadiness] = useState<TrainReadiness | null>(null);
  const [kind, setKind] = useState<TrainKind>("train");
  const [epochs, setEpochs] = useState(0);
  const [device, setDevice] = useState("auto");
  const [source, setSource] = useState<PrepareSource>("manual");

  const [status, setStatus] = useState<TrainStatus | null>(null);
  const [history, setHistory] = useState<TrainHistoryRun[]>([]);
  const [err, setErr] = useState<{ problem: string; fix?: string } | null>(null);

  // Promote: confirm-then-act, keyed by run dir, with a per-run result message.
  const [confirmDir, setConfirmDir] = useState<string | null>(null);
  const [promoteMsg, setPromoteMsg] = useState<{ text: string; tone: "ok" | "warn" } | null>(null);

  const logRef = useRef<HTMLPreElement | null>(null);
  const running = status?.state === "running";

  const refreshReadiness = useCallback(async () => {
    const r = await api.trainReadiness();
    if (r.ok) setReadiness(r);
  }, []);
  const refreshStatus = useCallback(async () => {
    const s = await api.trainStatus();
    if (s.ok) setStatus(s);
  }, []);
  const refreshHistory = useCallback(async () => {
    const h = await api.trainHistory();
    if (h.ok) setHistory(h.runs);
  }, []);

  useEffect(() => {
    // fetch-on-mount: setState happens after the await, not synchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshReadiness();
    refreshStatus();
    refreshHistory();
  }, [refreshReadiness, refreshStatus, refreshHistory]);

  // Poll status every 1s while running; refresh readiness + history when it ends.
  useEffect(() => {
    if (!running) return;
    const id = setInterval(async () => {
      const s = await api.trainStatus();
      if (!s.ok) return;
      setStatus(s);
      if (s.state !== "running") {
        refreshReadiness();
        refreshHistory();
      }
    }, 1000);
    return () => clearInterval(id);
  }, [running, refreshReadiness, refreshHistory]);

  // Auto-scroll the log tail to the bottom as it grows.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [status?.log_tail]);

  // Why Run is disabled — the first matching reason, inline (never silent).
  const needsMl = kind === "train" || kind === "autoresearch";
  const needsDataset = kind === "train" || kind === "autoresearch";
  const blockReason: string | null = !readiness
    ? "checking readiness…"
    : running || readiness.running
      ? "a run is already in progress"
      : readiness.eval_running
        ? "an eval is running — wait for it to finish"
        : !readiness.idle
          ? "set IDLE to train" // NEVER auto-switched for the operator
          : needsMl && !readiness.ml_available
            ? "ML extras missing — run `uv sync --extra ml`"
            : needsDataset && !readiness.dataset_ready
              ? "no dataset — run prepare first"
              : null;
  const canRun = blockReason === null;

  async function run() {
    setErr(null);
    const body: Parameters<typeof api.trainRun>[0] = { kind };
    if (device !== "auto") body.device = device;
    if (kind === "train") body.epochs = epochs;
    if (kind === "prepare") body.source = source;
    const r = await api.trainRun(body);
    if (!r.ok) {
      setErr({ problem: r.problem, fix: r.fix });
      return;
    }
    refreshStatus();
    refreshReadiness();
  }

  async function promote(dir: string) {
    setPromoteMsg(null);
    // send the run dir, not a weights path — the backend resolves
    // runs/history/<dir>/best.pt (the archived weights).
    const r = await api.trainPromote({ run_dir: dir });
    if (r.ok) {
      setPromoteMsg({
        text: `promoted ${r.model_id} — now selectable in the Models tab`,
        tone: "ok",
      });
    } else {
      setPromoteMsg({ text: `${r.problem}${r.fix ? ` — ${r.fix}` : ""}`, tone: "warn" });
    }
    setConfirmDir(null);
    refreshHistory();
  }

  return (
    <div className="flex flex-col gap-4">
      {/* (a) readiness strip */}
      <div className="op-surface flex flex-wrap items-center gap-x-5 gap-y-1 p-3 text-sm">
        <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-dim">
          readiness
        </span>
        <span className="text-muted">
          ml-extra <Marker ok={!!readiness?.ml_available} />
        </span>
        <span className="text-muted">
          dataset <Marker ok={!!readiness?.dataset_ready} />
        </span>
        <span className="text-muted">
          device <span className="font-mono text-fg">{device}</span>
        </span>
        <span className="text-muted">
          IDLE <Marker ok={!!readiness?.idle} />
        </span>
      </div>

      {/* Blocking / advisory state cards (each visually distinct) */}
      {readiness && needsMl && !readiness.ml_available && (
        <div className="op-surface border-warn/40 p-3 text-sm text-warn">
          ML extras are not installed — fine-tuning is unavailable.
          <div className="mt-1 font-mono text-xs">uv sync --extra ml</div>
        </div>
      )}
      {readiness && needsDataset && readiness.ml_available && !readiness.dataset_ready && (
        <div className="op-surface border-warn/40 p-3 text-sm text-warn">
          No dataset is prepared. Run the <b>prepare</b> kind first to build one
          (prepare is allowed even without a dataset).
        </div>
      )}
      {readiness && device === "cpu" && (
        <div className="text-xs text-dim">
          No GPU selected — training on CPU is slow but works.
        </div>
      )}

      {/* (b) launch panel */}
      <div className="op-surface flex flex-col gap-3 p-4">
        <label className="text-sm text-muted">
          Kind
          <select
            className="ml-2 rounded-md border border-line bg-bg px-2 py-1"
            value={kind}
            onChange={(e) => setKind(e.target.value as TrainKind)}
            disabled={running}
          >
            {KINDS.map((k) => (
              <option key={k.id} value={k.id}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap gap-3 text-sm text-muted">
          <label>
            Device
            <select
              className="ml-2 rounded-md border border-line bg-bg px-2 py-1"
              value={device}
              onChange={(e) => setDevice(e.target.value)}
              disabled={running}
            >
              {DEVICES.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          {kind === "train" && (
            <label>
              Epochs (0 = config default)
              <input
                type="number"
                className="ml-2 w-24 rounded-md border border-line bg-bg px-2 py-1"
                value={epochs}
                onChange={(e) => setEpochs(parseInt(e.target.value, 10) || 0)}
                disabled={running}
              />
            </label>
          )}
        </div>
        {kind === "prepare" && (
          <label className="text-sm text-muted">
            Source (dataset acquisition strategy)
            <select
              className="ml-2 rounded-md border border-line bg-bg px-2 py-1"
              value={source}
              onChange={(e) => setSource(e.target.value as PrepareSource)}
              disabled={running}
            >
              {PREPARE_SOURCES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="flex items-center gap-3">
          <ControlTip helpId="train.run">
            <button type="button" className="op-btn" onClick={run} disabled={!canRun}>
              {running ? "Running…" : "Run"}
            </button>
          </ControlTip>
          {running && (
            <ControlTip helpId="train.stop">
              <button type="button" className="op-btn" onClick={() => api.trainCancel()}>
                Stop
              </button>
            </ControlTip>
          )}
          {!canRun && !running && blockReason && (
            <span className="text-xs text-warn">{blockReason}</span>
          )}
        </div>
        <p className="text-xs text-dim">
          Training is heavy — the server refuses it unless the robot is IDLE. The
          pretrained baseline is the safety net; fine-tuning is a stretch on top.
        </p>
      </div>

      {err && (
        <div className="op-surface border-stop/40 p-3 text-sm text-stop">
          {err.problem}
          {err.fix && <div className="mt-1 text-warn">→ {err.fix}</div>}
        </div>
      )}

      {/* (c) running progress + live log tail */}
      {status && (running || status.state !== "idle") && (
        <div className="op-surface flex flex-col gap-2 p-3">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="font-mono text-muted">
              state: <span className="text-fg">{status.state}</span>
              {status.kind ? ` · ${status.kind}` : ""}
            </span>
            {status.total_epochs != null && status.total_epochs > 0 && (
              <span className="font-mono text-muted">
                epoch {status.epoch ?? 0}/{status.total_epochs}
              </span>
            )}
            {status.elapsed_s != null && (
              <span className="font-mono text-dim">{fmtDuration(status.elapsed_s)}</span>
            )}
          </div>
          {status.state === "error" && status.error && (
            <div className="op-surface border-stop/40 p-3 text-sm text-stop">
              training failed: {status.error}
            </div>
          )}
          {status.state === "cancelled" && (
            <div className="op-surface border-warn/40 p-3 text-sm text-warn">
              stopped — a partial run directory may exist.
            </div>
          )}
          {status.state === "done" && (
            <div className="op-surface border-ok/40 p-3 text-sm" style={{ color: "var(--color-ok)" }}>
              done{status.summary ? ` — ${status.summary}` : ""}
            </div>
          )}
          {status.log_tail && (
            <pre
              ref={logRef}
              className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-bg p-2 text-xs text-muted"
            >
              {status.log_tail}
            </pre>
          )}
        </div>
      )}

      {/* promote result */}
      {promoteMsg && (
        <div
          className="op-surface p-3 text-sm"
          style={{
            color: promoteMsg.tone === "ok" ? "var(--color-ok)" : "var(--color-warn)",
            borderColor:
              promoteMsg.tone === "ok"
                ? "color-mix(in oklab, var(--color-ok) 40%, transparent)"
                : "color-mix(in oklab, var(--color-warn) 40%, transparent)",
          }}
        >
          {promoteMsg.text}
        </div>
      )}

      {/* (d) run history + (e) per-row promote */}
      <div className="op-surface p-3">
        <h4 className="mb-2 font-display text-sm font-semibold text-orange-bright">Run history</h4>
        {history.length === 0 ? (
          <p className="text-xs text-dim">No runs yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-dim">
                <th className="py-1 font-normal">when</th>
                <th className="py-1 font-normal">kind</th>
                <th className="py-1 font-normal">status</th>
                <th className="py-1 font-normal">metric</th>
                <th className="py-1 font-normal">dur</th>
                <th className="py-1 font-normal" />
              </tr>
            </thead>
            <tbody>
              {history.map((r) => {
                // history archives use ok/fail/cancelled, NOT done/error.
                const finished = r.status === "ok";
                const confirming = confirmDir === r.dir;
                return (
                  <tr key={r.dir} className="border-t border-line/60">
                    <td className="py-1 text-muted">{fmtWhen(r.ts)}</td>
                    <td className="py-1 font-mono text-muted">{r.kind}</td>
                    <td
                      className="py-1 font-mono"
                      style={{
                        color:
                          r.status === "ok"
                            ? "var(--color-ok)"
                            : r.status === "fail"
                              ? "var(--color-stop)"
                              : r.status === "cancelled"
                                ? "var(--color-warn)"
                                : "var(--color-muted)",
                      }}
                    >
                      {r.status}
                    </td>
                    <td className="py-1 text-right font-mono">
                      {fmtMetric(r.metric)}
                      {r.metric_key ? <span className="text-dim"> {r.metric_key}</span> : ""}
                    </td>
                    <td className="py-1 font-mono text-dim">{fmtDuration(r.duration_s)}</td>
                    <td className="py-1 text-right">
                      {finished &&
                        (confirming ? (
                          <span className="inline-flex gap-1">
                            <ControlTip helpId="train.confirm">
                              <button
                                type="button"
                                className="op-btn px-2 py-1 text-xs"
                                onClick={() => promote(r.dir)}
                              >
                                Confirm
                              </button>
                            </ControlTip>
                            <ControlTip helpId="train.promote_cancel">
                              <button
                                type="button"
                                className="op-btn px-2 py-1 text-xs"
                                onClick={() => setConfirmDir(null)}
                              >
                                Cancel
                              </button>
                            </ControlTip>
                          </span>
                        ) : (
                          <ControlTip helpId="train.promote">
                            <button
                              type="button"
                              className="op-btn px-2 py-1 text-xs"
                              onClick={() => setConfirmDir(r.dir)}
                            >
                              Promote
                            </button>
                          </ControlTip>
                        ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
