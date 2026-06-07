import { describe, expect, it } from "vitest";
import { concatBytes, drainJpegs } from "./mjpeg";

describe("drainJpegs", () => {
  it("extracts a complete JPEG and discards trailing non-image bytes", () => {
    const prefix = new TextEncoder().encode("garbage");
    const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0x00, 0x01, 0xff, 0xd9]);
    const suffix = new TextEncoder().encode("tail");
    const buf = concatBytes(concatBytes(prefix, jpeg), suffix);
    const { frames, rest } = drainJpegs(buf);
    expect(frames).toHaveLength(1);
    expect(Array.from(frames[0])).toEqual(Array.from(jpeg));
    expect(rest.length).toBeLessThanOrEqual(1);
  });

  it("waits for EOI before emitting a frame", () => {
    const partial = new Uint8Array([0xff, 0xd8, 0xff, 0x00]);
    const { frames, rest } = drainJpegs(partial);
    expect(frames).toHaveLength(0);
    expect(rest).toEqual(partial);
  });
});
