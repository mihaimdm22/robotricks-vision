"use client";

/**
 * CV tab — the perception/training surface. A sub-toggle switches between the
 * existing Eval view (unchanged) and the new Training view. Kept as a thin
 * wrapper so each sub-view stays a self-contained component.
 */

import { useState } from "react";
import { EvalTab } from "./EvalTab";
import { TrainingTab } from "./TrainingTab";

type Sub = "eval" | "training";
const SUBS: { id: Sub; label: string }[] = [
  { id: "eval", label: "Eval" },
  { id: "training", label: "Training" },
];

export function CVTab() {
  const [sub, setSub] = useState<Sub>("eval");
  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        {SUBS.map((s) => (
          <button
            key={s.id}
            type="button"
            className="op-btn flex-1"
            data-active={sub === s.id}
            onClick={() => setSub(s.id)}
          >
            {s.label}
          </button>
        ))}
      </div>
      {sub === "eval" ? <EvalTab /> : <TrainingTab />}
    </div>
  );
}
