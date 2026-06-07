/**
 * Incremental MJPEG byte-stream parser. Finds complete JPEG SOI..EOI segments in a
 * buffer so we can paint frames on a <canvas> when <img multipart/x-mixed-replace>
 * fails to repaint (Chromium + Next.js proxy edge cases).
 */

const SOI = 0xd8;
const EOI = 0xd9;

/** Bytes buffer used while parsing MJPEG streams. */
export type ByteBuffer = Uint8Array<ArrayBuffer>;

/** Append `chunk` to `prev` (returns a new Uint8Array). */
export function concatBytes(prev: ByteBuffer, chunk: Uint8Array): ByteBuffer {
  if (prev.length === 0) return new Uint8Array(chunk);
  const out = new Uint8Array(prev.length + chunk.length);
  out.set(prev, 0);
  out.set(chunk, prev.length);
  return out;
}

/**
 * Pull zero or more complete JPEGs from the front of `buffer`.
 * Returns extracted frames and the unconsumed tail (may include a partial JPEG).
 */
export function drainJpegs(buffer: ByteBuffer): { frames: ByteBuffer[]; rest: ByteBuffer } {
  const frames: ByteBuffer[] = [];
  let i = 0;

  while (i < buffer.length) {
    if (i + 1 >= buffer.length) break;
    if (buffer[i] !== 0xff || buffer[i + 1] !== SOI) {
      i += 1;
      continue;
    }
    let end = -1;
    for (let j = i + 2; j + 1 < buffer.length; j++) {
      if (buffer[j] === 0xff && buffer[j + 1] === EOI) {
        end = j + 2;
        break;
      }
    }
    if (end === -1) break;
    frames.push(new Uint8Array(buffer.subarray(i, end)));
    i = end;
  }

  return { frames, rest: i > 0 ? new Uint8Array(buffer.subarray(i)) : buffer };
}
