/**
 * Hand-drawn marker shapes (rough.js), docs/06 §4: stroke --muga, width 2.5,
 * roughness 1.2, bowing 1.5, fixed seed per item so the shape is stable between renders.
 */
import rough from "roughjs";
import { seedFrom } from "./hex";

const generator = rough.generator();
const OPTIONS = { roughness: 1.2, bowing: 1.5, strokeWidth: 2.5 };

export function circlePaths(key: string, cx: number, cy: number, w: number, h: number): string[] {
  const d = generator.ellipse(cx, cy, w, h, { ...OPTIONS, seed: seedFrom(key) });
  return generator.toPaths(d).map((p) => p.d);
}

export function underlinePaths(key: string, width: number, y: number): string[] {
  const d = generator.line(2, y, width - 2, y + 1.5, { ...OPTIONS, roughness: 1.4, seed: seedFrom(key) });
  return generator.toPaths(d).map((p) => p.d);
}
