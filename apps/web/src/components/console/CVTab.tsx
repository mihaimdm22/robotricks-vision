"use client";

/**
 * CV tab — the perception/training surface. A sub-toggle switches between the
 * existing Eval view (unchanged) and the new Training view. Kept as a thin
 * wrapper so each sub-view stays a self-contained component.
 */

import { useState } from "react";
import { EvalTab } from "./EvalTab";
import { TrainingTab } from "./TrainingTab";
import { ControlTip } from "./help";
import type { HelpId } from "@/lib/console-help";

type Sub = "eval" | "training";
const SUBS: { id: Sub; label: string; helpId: HelpId }[] = [
  { id: "eval", label: "Eval", helpId: "cv.sub.eval" },
  { id: "training", label: "Training", helpId: "cv.sub.training" },
];

export function CVTab() {
  const [sub, setSub] = useState<Sub>("eval");
  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        {SUBS.map((s) => (
          <ControlTip key={s.id} helpId={s.helpId}>
            <button
              type="button"
              className="op-btn flex-1"
              data-active={sub === s.id}
              onClick={() => setSub(s.id)}
            >
              {s.label}
            </button>
          </ControlTip>
        ))}
      </div>
      {sub === "eval" ? <EvalTab /> : <TrainingTab />}
    </div>
  );
}
