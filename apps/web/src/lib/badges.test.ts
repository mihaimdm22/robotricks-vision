import { describe, expect, it } from "vitest";
import { BadgeDebouncer, badgeStyle, pickBadge } from "./badges";

describe("pickBadge (precedence, <=1 per detection)", () => {
  it("returns null when no known flags are present", () => {
    expect(pickBadge([])).toBeNull();
    expect(pickBadge(["something_unknown"])).toBeNull();
  });

  it("picks the single highest-severity flag", () => {
    // no_distance outranks low_conf even when both fire (no christmas tree).
    expect(pickBadge(["low_conf", "no_distance", "wide_ci"])).toBe("no_distance");
    expect(pickBadge(["low_conf", "wide_ci"])).toBe("wide_ci");
    expect(pickBadge(["low_conf"])).toBe("low_conf");
    expect(pickBadge(["depth_geom_disagree", "low_conf"])).toBe("depth_geom_disagree");
  });
});

describe("badgeStyle", () => {
  it("pairs every badge with text + a glyph (never hue-only)", () => {
    for (const b of ["no_distance", "depth_geom_disagree", "wide_ci", "low_conf"] as const) {
      const s = badgeStyle(b);
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.glyph.length).toBeGreaterThan(0);
      expect(["warn", "stop"]).toContain(s.tone);
    }
  });
});

describe("BadgeDebouncer", () => {
  it("only surfaces a badge after it persists minFrames", () => {
    const d = new BadgeDebouncer(3);
    expect(d.update("t1", "low_conf")).toBeNull(); // frame 1
    expect(d.update("t1", "low_conf")).toBeNull(); // frame 2
    expect(d.update("t1", "low_conf")).toBe("low_conf"); // frame 3 -> stable
    expect(d.update("t1", "low_conf")).toBe("low_conf"); // stays
  });

  it("resets the streak when the badge changes", () => {
    const d = new BadgeDebouncer(2);
    expect(d.update("t1", "low_conf")).toBeNull();
    expect(d.update("t1", "wide_ci")).toBeNull(); // changed -> streak restarts
    expect(d.update("t1", "wide_ci")).toBe("wide_ci");
  });

  it("clears the streak on a null (flag gone) and tracks per-key", () => {
    const d = new BadgeDebouncer(2);
    d.update("t1", "low_conf");
    expect(d.update("t1", null)).toBeNull(); // cleared
    expect(d.update("t1", "low_conf")).toBeNull(); // must build up again
    // a different detection key has its own streak
    expect(d.update("t2", "wide_ci")).toBeNull();
    expect(d.update("t2", "wide_ci")).toBe("wide_ci");
  });

  it("retain() reaps streaks for detections gone this frame (no unbounded growth)", () => {
    const d = new BadgeDebouncer(2);
    d.update("t1", "low_conf");
    d.update("t2", "low_conf");
    d.retain(new Set(["t1"])); // t2 left the frame -> its streak is dropped
    // t2 must rebuild from scratch (proves its streak was reaped, not retained)
    expect(d.update("t2", "low_conf")).toBeNull();
    // t1 was retained -> one more frame stabilizes it
    expect(d.update("t1", "low_conf")).toBe("low_conf");
  });
});
