"use client";

import { getHelp, type HelpId } from "@/lib/console-help";
import { useHelpModal } from "./HelpProvider";
import { ControlTip } from "./ControlTip";

/** Info (i) control — opens the detail modal when long copy exists. */
export function SectionHelp({ helpId, className }: { helpId: HelpId; className?: string }) {
  const { openHelp } = useHelpModal();
  const entry = getHelp(helpId);
  const hasDetail = Boolean(entry.detail);

  if (!hasDetail) {
    return (
      <ControlTip helpId={helpId}>
        <button
          type="button"
          className={`help-info-btn ${className ?? ""}`}
          aria-label={`Help: ${entry.title}`}
        >
          i
        </button>
      </ControlTip>
    );
  }

  return (
    <ControlTip helpId={helpId}>
      <button
        type="button"
        className={`help-info-btn ${className ?? ""}`}
        aria-label={`More about ${entry.title}`}
        onClick={(e) => {
          e.stopPropagation();
          openHelp(helpId);
        }}
      >
        i
      </button>
    </ControlTip>
  );
}

/** Section title row with optional modal help. */
export function SectionTitle({
  helpId,
  children,
  className,
}: {
  helpId?: HelpId;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className ?? ""}`}>
      {children}
      {helpId && <SectionHelp helpId={helpId} />}
    </span>
  );
}
