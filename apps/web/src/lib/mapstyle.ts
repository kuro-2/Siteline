/**
 * Restyle OpenFreeMap's Positron to the design tokens: muted land, river-blue water,
 * minimal labels, no POIs. Applied after the style loads, so we keep their tiles and
 * attribution but not their look.
 */
import type { Map as MlMap } from "maplibre-gl";

export interface Palette {
  land: string;
  water: string;
  park: string;
  road: string;
  roadMajor: string;
  building: string;
  label: string;
  labelHalo: string;
  boundary: string;
}

export function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  const dark = css.getPropertyValue("color-scheme").trim() === "dark";
  return {
    land: v("--mist"),
    water: mix(v("--river"), v("--mist"), dark ? 0.55 : 0.6),
    park: dark ? "#16221f" : "#e4ece5",
    road: dark ? "#1f2c30" : "#ffffff",
    roadMajor: dark ? "#2b3a3f" : "#f6f8f6",
    building: dark ? "#1a2629" : "#e3e8e4",
    label: v("--ink-soft"),
    labelHalo: v("--mist"),
    boundary: v("--rule"),
  };
}

export function restyle(map: MlMap, p: Palette): void {
  const style = map.getStyle();
  for (const layer of style.layers ?? []) {
    const id = layer.id;
    try {
      if (layer.type === "background") {
        map.setPaintProperty(id, "background-color", p.land);
      } else if (layer.type === "fill") {
        if (/water/.test(id)) map.setPaintProperty(id, "fill-color", p.water);
        else if (/park|wood|grass|landcover|forest/.test(id)) map.setPaintProperty(id, "fill-color", p.park);
        else if (/building/.test(id)) map.setPaintProperty(id, "fill-color", p.building);
        else map.setPaintProperty(id, "fill-color", p.land);
      } else if (layer.type === "line") {
        if (/water|river|stream/.test(id)) map.setPaintProperty(id, "line-color", p.water);
        else if (/boundary|admin/.test(id)) map.setPaintProperty(id, "line-color", p.boundary);
        else if (/motorway|trunk|primary/.test(id)) map.setPaintProperty(id, "line-color", p.roadMajor);
        else map.setPaintProperty(id, "line-color", p.road);
      } else if (layer.type === "symbol") {
        // Minimal labels: keep place and road names, drop POIs and house numbers.
        if (/poi|housenumber|aerodrome|airport|transit|rail/.test(id)) {
          map.setLayoutProperty(id, "visibility", "none");
          continue;
        }
        // Sentence case everywhere: no all-caps place labels.
        map.setLayoutProperty(id, "text-transform", "none");
        map.setPaintProperty(id, "text-color", p.label);
        map.setPaintProperty(id, "text-halo-color", p.labelHalo);
        map.setPaintProperty(id, "text-halo-width", 1.2);
      }
    } catch {
      // Some layers don't support a property (e.g. pattern fills); leave them be.
    }
  }
}

/** A small canvas pattern of diagonal lines for low-confidence hexes. */
export function hatchImage(color: string, size = 8): ImageData {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const ctx = c.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  ctx.moveTo(0, size);
  ctx.lineTo(size, 0);
  ctx.moveTo(-size / 2, size / 2);
  ctx.lineTo(size / 2, -size / 2);
  ctx.moveTo(size / 2, size * 1.5);
  ctx.lineTo(size * 1.5, size / 2);
  ctx.stroke();
  return ctx.getImageData(0, 0, size, size);
}

/** Mix two #rrggbb colours: weight = share of `a`. */
export function mix(a: string, b: string, weight: number): string {
  const pa = parseHex(a);
  const pb = parseHex(b);
  if (!pa || !pb) return a;
  const c = pa.map((x, i) => Math.round(x * weight + (pb[i] ?? 0) * (1 - weight)));
  return `#${c.map((x) => x.toString(16).padStart(2, "0")).join("")}`;
}

function parseHex(h: string): number[] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(h.trim());
  if (!m || !m[1]) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
