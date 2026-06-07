"use client";

import {
  cloneElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type ReactElement,
} from "react";
import { createPortal } from "react-dom";
import { getHelp, type HelpId } from "@/lib/console-help";

const SHOW_MS = 400;
const HIDE_MS = 100;

type Props = {
  helpId: HelpId;
  children: ReactElement<HTMLAttributes<HTMLElement> & { disabled?: boolean }>;
  className?: string;
  /** Applied to the outer host so grid layouts (drive pad, PTZ) stay aligned. */
  hostStyle?: CSSProperties;
  hostClassName?: string;
  /** Fill the grid cell (drive pad / PTZ only). Default inline-flex — do not use in flex rows. */
  fill?: boolean;
};

/** Short passive tooltip on hover/focus; wraps disabled controls so tips still show. */
export function ControlTip({ helpId, children, className, hostStyle, hostClassName, fill }: Props) {
  const entry = getHelp(helpId);
  const tipId = useId();
  const hostRef = useRef<HTMLSpanElement>(null);
  const showTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [visible, setVisible] = useState(false);
  const [pos, setPos] = useState<CSSProperties>({});

  const clearTimers = () => {
    if (showTimer.current) clearTimeout(showTimer.current);
    if (hideTimer.current) clearTimeout(hideTimer.current);
  };

  const reposition = useCallback(() => {
    const host = hostRef.current;
    if (!host) return;
    const r = host.getBoundingClientRect();
    setPos({
      left: r.left + r.width / 2,
      top: r.top - 8,
    });
  }, []);

  const scheduleShow = () => {
    clearTimers();
    showTimer.current = setTimeout(() => {
      reposition();
      setVisible(true);
    }, SHOW_MS);
  };

  const scheduleHide = () => {
    clearTimers();
    hideTimer.current = setTimeout(() => setVisible(false), HIDE_MS);
  };

  useEffect(() => {
    if (!visible) return;
    reposition();
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [visible, reposition]);

  const disabled = Boolean(children.props.disabled);
  const child = cloneElement(children, {
    ...children.props,
    "aria-describedby": visible ? tipId : undefined,
    onMouseEnter: (e: React.MouseEvent<HTMLElement>) => {
      children.props.onMouseEnter?.(e);
      scheduleShow();
    },
    onMouseLeave: (e: React.MouseEvent<HTMLElement>) => {
      children.props.onMouseLeave?.(e);
      scheduleHide();
    },
    onFocus: (e: React.FocusEvent<HTMLElement>) => {
      children.props.onFocus?.(e);
      scheduleShow();
    },
    onBlur: (e: React.FocusEvent<HTMLElement>) => {
      children.props.onBlur?.(e);
      scheduleHide();
    },
  });

  const fillClass = fill ? "h-full w-full" : "";

  const inner = disabled ? (
    <span className={`inline-flex rounded-[10px] ${fillClass}`} tabIndex={0}>
      {child}
    </span>
  ) : (
    child
  );

  return (
    <>
      <span
        ref={hostRef}
        style={hostStyle}
        className={`help-tip-host inline-flex ${fillClass} ${hostClassName ?? ""} ${className ?? ""}`}
        onMouseEnter={scheduleShow}
        onMouseLeave={scheduleHide}
        onFocus={scheduleShow}
        onBlur={scheduleHide}
      >
        {inner}
      </span>
      {visible &&
        createPortal(
          <span id={tipId} role="tooltip" className="help-tooltip" style={pos}>
            {entry.tip}
          </span>,
          document.body,
        )}
    </>
  );
}
