// Decodor de PNG pentru teste: citește pixelii unei imagini RGBA pe 8 biți, fără intercalare (forma în care Chrome scrie capturile și iconițele), ca testele să poată verifica ce desenează o iconiță.
// Primește: octeții fișierului PNG (Buffer). Dă înapoi: { width, height, pixel(x, y) } cu pixel = [r, g, b, a].
// Ce NU face: nu înțelege alte tipuri de culoare, alte adâncimi sau imagini intercalate (le refuză cu un mesaj), nu verifică sumele CRC și nu scrie PNG-uri.
import assert from 'node:assert/strict';
import zlib from 'node:zlib';

// Antetul unui PNG: 8 octeți de semnătură, apoi bucățile (chunks) { lungime(4), tip(4), date, CRC(4) }.
const SIGNATURE_BYTES = 8;
const CHUNK_OVERHEAD_BYTES = 12;
const BYTES_PER_PIXEL = 4;

/** Valoarea prezisă de filtrul Paeth pentru un octet, din cel din stânga, cel de deasupra și cel din colțul stânga-sus. */
function paethPredictor(left, up, upLeft) {
  const estimate = left + up - upLeft;
  const distanceLeft = Math.abs(estimate - left);
  const distanceUp = Math.abs(estimate - up);
  const distanceUpLeft = Math.abs(estimate - upLeft);
  if (distanceLeft <= distanceUp && distanceLeft <= distanceUpLeft) return left;
  return distanceUp <= distanceUpLeft ? up : upLeft;
}

/** Decodifică un PNG RGBA pe 8 biți, fără intercalare: { width, height, pixel(x, y) } cu pixel = [r, g, b, a]; refuză orice altă formă. */
export function decodePng(bytes) {
  let offset = SIGNATURE_BYTES;
  let width = 0;
  let height = 0;
  const compressed = [];
  while (offset < bytes.length) {
    const length = bytes.readUInt32BE(offset);
    const type = bytes.toString('latin1', offset + 4, offset + 8);
    const data = bytes.subarray(offset + 8, offset + 8 + length);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      assert.deepEqual([data[8], data[9], data[12]], [8, 6, 0], 'doar RGBA pe 8 biți, fără intercalare');
    } else if (type === 'IDAT') {
      compressed.push(data);
    }
    offset += CHUNK_OVERHEAD_BYTES + length;
  }
  const raw = zlib.inflateSync(Buffer.concat(compressed));
  const stride = width * BYTES_PER_PIXEL;
  const pixels = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)];
    assert.ok(filter <= 4, `filtru PNG necunoscut: ${filter}`);
    for (let x = 0; x < stride; x += 1) {
      const left = x >= BYTES_PER_PIXEL ? pixels[y * stride + x - BYTES_PER_PIXEL] : 0;
      const up = y > 0 ? pixels[(y - 1) * stride + x] : 0;
      const upLeft = x >= BYTES_PER_PIXEL && y > 0 ? pixels[(y - 1) * stride + x - BYTES_PER_PIXEL] : 0;
      let predicted = 0;
      if (filter === 1) predicted = left;
      else if (filter === 2) predicted = up;
      else if (filter === 3) predicted = (left + up) >> 1;
      else if (filter === 4) predicted = paethPredictor(left, up, upLeft);
      pixels[y * stride + x] = (raw[y * (stride + 1) + 1 + x] + predicted) & 255;
    }
  }
  return {
    width,
    height,
    pixel: (x, y) => [...pixels.subarray(y * stride + x * BYTES_PER_PIXEL, y * stride + (x + 1) * BYTES_PER_PIXEL)],
  };
}
