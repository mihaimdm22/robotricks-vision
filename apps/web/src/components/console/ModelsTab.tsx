"use client";

/** Hot-swap the detector. The baseline is always available. */

import { useCallback, useEffect, useState } from "react";
import { api, type ModelInfo } from "@/lib/api";

export function ModelsTab() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [active, setActive] = useState("");
  const [hint, setHint] = useState("Hot-swap the detector. The baseline is always available.");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await api.getModels();
    if (r.ok) {
      setModels(r.models);
      setActive(r.active);
    } else {
      setHint(r.problem);
    }
  }, []);

  useEffect(() => {
    // fetch-on-mount: setState happens after the await, not synchronously.
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
    <div>
      <p className="mb-3 text-sm text-muted">{hint}</p>
      <ul className="flex flex-col gap-2">
        {models.map((m) => (
          <li
            key={m.id}
            className="op-surface flex items-center justify-between px-3 py-2"
            data-active={m.id === active}
          >
            <div>
              <b>{m.name}</b>
              <div className="text-xs text-dim">
                {m.backend}
                {m.dataset ? ` · ${m.dataset}` : ""}
              </div>
            </div>
            <button
              type="button"
              className="op-btn"
              disabled={m.id === active || busy === m.id}
              onClick={() => select(m.id)}
            >
              {m.id === active ? "active" : busy === m.id ? "loading…" : "use"}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
