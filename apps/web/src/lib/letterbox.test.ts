import { describe, expect, it } from "vitest";
import { contentRect, denormBox } from "./letterbox";

describe("contentRect (object-contain)", () => {
  it("fills the element with no bars when aspects match", () => {
    // 1600x900 element, 16:9 frame -> no letterboxing.
    expect(contentRect(1600, 900, 1920, 1080)).toEqual({ x: 0, y: 0, w: 1600, h: 900 });
  });

  it("adds vertical (pillarbox) bars for a taller frame in a wider element", () => {
    // 4:3 frame in a 200x100 element -> height-limited, centered horizontally.
    // scale = min(200/400, 100/300) = min(0.5, 0.333) = 0.333 -> 133.33 x 100
    const r = contentRect(200, 100, 400, 300);
    expect(r.h).toBeCloseTo(100, 5);
    expect(r.w).toBeCloseTo(133.333, 2);
    expect(r.y).toBeCloseTo(0, 5);
    expect(r.x).toBeCloseTo((200 - 133.333) / 2, 2);
  });

  it("adds horizontal (letterbox) bars for a wider frame in a taller element", () => {
    // 2:1 frame in a 100x100 element -> width-limited, centered vertically.
    const r = contentRect(100, 100, 200, 100);
    expect(r.w).toBeCloseTo(100, 5);
    expect(r.h).toBeCloseTo(50, 5);
    expect(r.x).toBeCloseTo(0, 5);
    expect(r.y).toBeCloseTo(25, 5);
  });

  it("falls back to the full element for degenerate inputs", () => {
    expect(contentRect(640, 360, 0, 0)).toEqual({ x: 0, y: 0, w: 640, h: 360 });
    expect(contentRect(0, 0, 1920, 1080)).toEqual({ x: 0, y: 0, w: 0, h: 0 });
  });
});

describe("denormBox", () => {
  it("maps a normalized box into the content rect (offset + scale)", () => {
    const rect = { x: 10, y: 5, w: 200, h: 100 };
    // central half-box [0.25,0.25]-[0.75,0.75]
    expect(denormBox([0.25, 0.25, 0.75, 0.75], rect)).toEqual({
      x: 10 + 50,
      y: 5 + 25,
      w: 100,
      h: 50,
    });
  });

  it("maps the full box to the whole rect", () => {
    const rect = { x: 30, y: 8, w: 133.33, h: 100 };
    expect(denormBox([0, 0, 1, 1], rect)).toEqual({ x: 30, y: 8, w: 133.33, h: 100 });
  });

  it("respects letterbox offset so overlays track the displayed video, not the element", () => {
    // pillarboxed rect from the contentRect test; a box at the frame's left edge must
    // land at the rect's x offset, NOT at element x=0 (the drift bug B1 guards against).
    const rect = contentRect(200, 100, 400, 300);
    const b = denormBox([0, 0, 0.5, 1], rect);
    expect(b.x).toBeCloseTo(rect.x, 5);
    expect(b.x).toBeGreaterThan(0);
  });
});
