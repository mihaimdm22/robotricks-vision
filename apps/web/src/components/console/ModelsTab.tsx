"use client";

/** Hot-swap the detector. Registry entries mirror overnight run history. */

import { useCallback, useEffect, useState } from "react";
import { api, type ModelInfo } from "@/lib/api";
import { ControlTip } from "./help";

function fmtMetric(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/\.?0+$/, "");
}

function fmtDuration(s: number | null | undefined): string {
  if (s == null) return "—";
  if (s <= 0) return "vendor";
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`;
}

function fmtWhen(ts: string | undefined): string {
  if (!ts) return "—";
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(ts);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts;
}

export function ModelsTab() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [active, setActive] = useState("");
  const [hint, setHint] = useState(
    "Registry models from configs/models.yaml — same shape as Training run history.",
  );
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await api.getModels();
    if (r.ok !== false && Array.isArray(r.models)) {
      setModels(r.models);
      setActive(r.active);
      setHint(
        r.models.length
          ? `Active: ${r.active} (${r.status}). Hot-swap without restart.`
          : "No models in registry — check configs/models.yaml.",
      );
    } else {
      setHint("problem" in r ? r.problem : "Could not load models from the backend.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function select(id: string) {
    setBusy(id);
    const r = await api.selectModel(id);
    if (r.ok) {
      setHint(`Active: ${r.model} (${r.status})${r.warning ? ` — ${r.warning}` : ""}`);
    } else {
      setHint(`Failed: ${r.problem}${r.fix ? ` — ${r.fix}` : ""}`);
    }
    setBusy(null);
    load();
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">{hint}</p>
      <div className="op-surface p-3">
        <h4 className="mb-2 font-display text-sm font-semibold text-orange-bright">
          Model registry
        </h4>
        {models.length === 0 ? (
          <p className="text-xs text-dim">No models loaded.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-dim">
                <th className="py-1 font-normal">when</th>
                <th className="py-1 font-normal">kind</th>
                <th className="py-1 font-normal">model</th>
                <th className="py-1 font-normal">metric</th>
                <th className="py-1 font-normal">dur</th>
                <th className="py-1 font-normal" />
              </tr>
            </thead>
            <tbody>
              {models.map((m) => {
                const isActive = m.id === active;
                return (
                  <tr
                    key={m.id}
                    className="border-t border-line/60 align-top"
                    data-active={isActive}
                  >
                    <td className="py-2 text-muted">{fmtWhen(m.trained_at)}</td>
                    <td className="py-2 font-mono text-muted">{m.run_kind || m.backend}</td>
                    <td className="py-2">
                      <div className="font-medium">{m.name}</div>
                      <div className="text-xs text-dim">
                        {m.backend}
                        {m.dataset ? ` · ${m.dataset}` : ""}
                      </div>
                      {m.summary && (
                        <div className="mt-1 text-xs text-muted">{m.summary}</div>
                      )}
                      {m.notes && (
                        <div className="mt-0.5 text-xs text-dim">{m.notes}</div>
                      )}
                    </td>
                    <td className="py-2 text-right font-mono">
                      {fmtMetric(m.metric ?? null)}
                      {m.metric_key ? (
                        <div className="text-dim text-[0.65rem]">{m.metric_key}</div>
                      ) : null}
                    </td>
                    <td className="py-2 font-mono text-dim">{fmtDuration(m.duration_s)}</td>
                    <td className="py-2 text-right">
                      <ControlTip helpId="models.use">
                        <button
                          type="button"
                          className="op-btn px-2 py-1 text-xs"
                          disabled={isActive || busy === m.id}
                          onClick={() => select(m.id)}
                        >
                          {isActive ? "active" : busy === m.id ? "loading…" : "use"}
                        </button>
                      </ControlTip>
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
