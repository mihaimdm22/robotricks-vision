"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { getHelp, type HelpId } from "@/lib/console-help";
import { HelpModal } from "./HelpModal";

type HelpContextValue = {
  openHelp: (id: HelpId) => void;
  closeHelp: () => void;
};

const HelpContext = createContext<HelpContextValue | null>(null);

export function HelpProvider({ children }: { children: ReactNode }) {
  const [openId, setOpenId] = useState<HelpId | null>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  const openHelp = useCallback((id: HelpId) => setOpenId(id), []);
  const closeHelp = useCallback(() => setOpenId(null), []);

  useEffect(() => {
    if (!openId) return;
    closeBtnRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") closeHelp();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [openId, closeHelp]);

  const entry = openId ? getHelp(openId) : null;

  return (
    <HelpContext.Provider value={{ openHelp, closeHelp }}>
      {children}
      {entry && openId && (
        <HelpModal
          title={entry.title}
          body={entry.detail ?? entry.tip}
          closeRef={closeBtnRef}
          onClose={closeHelp}
        />
      )}
    </HelpContext.Provider>
  );
}

export function useHelpModal(): HelpContextValue {
  const ctx = useContext(HelpContext);
  if (!ctx) throw new Error("useHelpModal must be used within HelpProvider");
  return ctx;
}
