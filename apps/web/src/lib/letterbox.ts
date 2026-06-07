/**
 * Letterbox geometry for the canvas overlay (WS-B1).
 *
 * The MJPEG <img> uses `object-contain`, so the displayed video is centered inside the
 * element with letterbox bars when the frame aspect differs from the element's. A canvas
 * laid `inset-0` covers the WHOLE element (bars included), so normalized box coords must
 * be mapped into the *content rect*, not the element — otherwise every overlay drifts
 * from the burned-in boxes (the #1 thing the design review said would look broken).
 *
 * Pure functions (no DOM) so the alignment math is independently reasoned about/tested.
 */

export type Rect = { x: number; y: number; w: number; h: number };

/**
 * The displayed content rectangle of an `object-contain` element: the frame
 * (`frameW`×`frameH`) scaled to fit inside the element (`elemW`×`elemH`), centered, with
 * letterbox bars as needed. Falls back to the full element for degenerate inputs.
 */
export function contentRect(elemW: number, elemH: number, frameW: number, frameH: number): Rect {
  if (elemW <= 0 || elemH <= 0 || frameW <= 0 || frameH <= 0) {
    return { x: 0, y: 0, w: Math.max(0, elemW), h: Math.max(0, elemH) };
  }
  const scale = Math.min(elemW / frameW, elemH / frameH);
  const w = frameW * scale;
  const h = frameH * scale;
  return { x: (elemW - w) / 2, y: (elemH - h) / 2, w, h };
}

/** Map a normalized [0,1] `xyxy` box into pixel coords within a content rect. */
export function denormBox(xyxyNorm: [number, number, number, number], rect: Rect): Rect {
  const [x1, y1, x2, y2] = xyxyNorm;
  return {
    x: rect.x + x1 * rect.w,
    y: rect.y + y1 * rect.h,
    w: (x2 - x1) * rect.w,
    h: (y2 - y1) * rect.h,
  };
}
