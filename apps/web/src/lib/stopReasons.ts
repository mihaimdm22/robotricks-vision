/**
 * Operator-facing copy for every robot stop reason.
 *
 * Ported verbatim from the vanilla panel's STOP_TEXT so the safety taxonomy
 * survives the migration: the operator must always know WHY the robot stopped
 * and what to do. The `Record<StopReason, ...>` is exhaustive — adding a reason
 * to the server enum without copy here is a TypeScript build error (the design
 * review's "a missing reason must fail CI, not render a raw enum").
 */

export type StopReason =
  | "NONE"
  | "ESTOP"
  | "WATCHDOG"
  | "FIRMWARE_SAFE_STOP"
  | "TARGET_LOST"
  | "LINK_LOST"
  | "CAMERA_LOST";

export type Severity = "ok" | "warn" | "danger";

export const STOP_REASONS: Record<StopReason, { text: string; severity: Severity }> = {
  NONE: { text: "", severity: "ok" },
  ESTOP: {
    text: "STOPPED — emergency stop latched. Press ARM / RESET to drive again.",
    severity: "danger",
  },
  WATCHDOG: {
    text: "STOPPED — lost contact with the browser (dead-man's switch). Hold a control to resume.",
    severity: "danger",
  },
  FIRMWARE_SAFE_STOP: {
    text: "SAFE STOP — obstacle within the firmware floor. Back away.",
    severity: "danger",
  },
  TARGET_LOST: { text: "FOLLOW — searching, no cat in view.", severity: "warn" },
  LINK_LOST: {
    text: "ROBOT LINK LOST — degraded to simulation. Reconnect on the Connections tab.",
    severity: "warn",
  },
  CAMERA_LOST: {
    text: "CAMERA LOST — no frames. Check the Connections tab.",
    severity: "warn",
  },
};
