"use client";

import { useEffect, type RefObject } from "react";
import { createPortal } from "react-dom";

export function HelpModal({
  title,
  body,
  onClose,
  closeRef,
}: {
  title: string;
  body: string;
  onClose: () => void;
  closeRef: RefObject<HTMLButtonElement | null>;
}) {
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  return createPortal(
    <div className="help-modal-root" role="presentation">
      <button type="button" className="help-modal-backdrop" aria-label="Close help" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="help-modal-title"
        className="help-modal-panel op-surface"
      >
        <header className="help-modal-header">
          <h2 id="help-modal-title" className="font-display text-lg font-semibold">
            {title}
          </h2>
          <button ref={closeRef} type="button" className="op-btn help-modal-close" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="help-modal-body text-sm text-muted">{body}</div>
      </div>
    </div>,
    document.body,
  );
}
