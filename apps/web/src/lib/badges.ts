/**
 * WS-B2 failure-badge arbitration.
 *
 * The WS-B0 overlay JSON carries per-detection `flags`; a failure cascade can raise
 * several at once. To avoid a "christmas tree" at the moment the operator most needs one
 * clear signal (design review #4), show AT MOST ONE badge per detection — the
 * highest-severity — and only after it persists a few frames (debounce, kills
 * single-frame blips). Global/safety states (estop, stop_reason, model_error) stay in the
 * StatusBanner, never duplicated as per-box badges.
 *
 * Color is paired with a glyph + text (design #5) so meaning never depends on hue alone.
 * Pure logic here; the canvas just renders what these decide.
 */

// Highest severity first. These are exactly the per-detection flags catranger/web/overlay.py
// emits — no_distance (can't range it) is worst, low_conf is mildest.
export const BADGE_PRECEDENCE = [
  "no_distance",
  "depth_geom_disagree",
  "wide_ci",
  "low_conf",
] as const;

export type Badge = (typeof BADGE_PRECEDENCE)[number];

const RANK = new Map<string, number>(BADGE_PRECEDENCE.map((b, i) => [b, i]));

/** The single highest-severity badge among a detection's flags, or null. */
export function pickBadge(flags: readonly string[]): Badge | null {
  let best: Badge | null = null;
  let bestRank = Number.POSITIVE_INFINITY;
  for (const f of flags) {
    const r = RANK.get(f);
    if (r !== undefined && r < bestRank) {
      bestRank = r;
      best = f as Badge;
    }
  }
  return best;
}

export type BadgeStyle = { label: string; tone: "warn" | "stop"; glyph: string };

const STYLE: Record<Badge, BadgeStyle> = {
  no_distance: { label: "no range", tone: "stop", glyph: "⊘" },
  depth_geom_disagree: { label: "depth≠geom", tone: "warn", glyph: "≠" },
  wide_ci: { label: "wide CI", tone: "warn", glyph: "↔" },
  low_conf: { label: "low conf", tone: "warn", glyph: "?" },
};

/** Render hints for a badge: a CSS-var tone ("warn"/"stop"), a glyph, and short text. */
export function badgeStyle(b: Badge): BadgeStyle {
  return STYLE[b];
}

/**
 * Per-detection debounce: a badge is only surfaced after it persists `minFrames`
 * consecutive frames for that detection key, so a one-frame flicker never flashes.
 * Changing badge or clearing resets the streak. The caller supplies a stable key per
 * detection (e.g. `t<track_id>`, or `i<index>` for untracked dets so they don't collide).
 * Stateful but pure (no DOM) — the canvas holds one in a ref and calls `retain` each frame
 * so streaks for vanished detections don't accumulate.
 */
export class BadgeDebouncer {
  private state = new Map<string, { badge: Badge; count: number }>();

  constructor(private readonly minFrames: number = 3) {}

  /** Feed this frame's chosen badge for a detection key; returns the badge to SHOW, or null. */
  update(key: string, badge: Badge | null): Badge | null {
    if (badge === null) {
      this.state.delete(key);
      return null;
    }
    const cur = this.state.get(key);
    const count = cur && cur.badge === badge ? cur.count + 1 : 1;
    this.state.set(key, { badge, count });
    return count >= this.minFrames ? badge : null;
  }

  /** Drop streaks for keys absent this frame, so the map can't grow unbounded as tracks
   *  come and go. Call once per frame with the live detection keys. */
  retain(liveKeys: Set<string>): void {
    for (const k of this.state.keys()) if (!liveKeys.has(k)) this.state.delete(k);
  }
}
