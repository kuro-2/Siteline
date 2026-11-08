import { cellToBoundary, cellToLatLng } from "h3-js";
import type { MapCell } from "./api";
import { opportunityStep, type Confidence } from "./format";

export interface HexProps {
  h3: string;
  score: number | null;
  step: number; // 0 = no data, 1–5 = opportunity
  confidence: Confidence;
  lowConfidence: boolean; // hatched + 60% opacity
  recommended: boolean;
}

export interface HexFeature {
  type: "Feature";
  id: number;
  properties: HexProps;
  geometry: { type: "Polygon"; coordinates: number[][][] };
}

export interface HexCollection {
  type: "FeatureCollection";
  features: HexFeature[];
}

export function hexPolygon(h3: string): number[][][] {
  const ring = cellToBoundary(h3, true); // [lng, lat], closed ring
  return [ring];
}

export function cellsToGeoJSON(cells: MapCell[]): HexCollection {
  return {
    type: "FeatureCollection",
    features: cells.map(([h3, score, confidence, recommended], i) => ({
      type: "Feature",
      id: i,
      properties: {
        h3,
        score,
        step: opportunityStep(score),
        confidence,
        lowConfidence: confidence === "early_signal" || confidence === "not_enough_data",
        recommended,
      },
      geometry: { type: "Polygon", coordinates: hexPolygon(h3) },
    })),
  };
}

export function centre(h3: string): [number, number] {
  const [lat, lng] = cellToLatLng(h3);
  return [lng, lat];
}

/** Cells sorted for the list view: scored first (high → low), then the rest. */
export function rankCells(cells: MapCell[]): MapCell[] {
  return [...cells].sort((a, b) => {
    if (a[1] === null && b[1] === null) return a[0].localeCompare(b[0]);
    if (a[1] === null) return 1;
    if (b[1] === null) return -1;
    return b[1] - a[1] || a[0].localeCompare(b[0]);
  });
}

/** Short, human-friendly id for a block (last 5 chars of the H3 index, without trailing f's). */
export function shortId(h3: string): string {
  return h3.replace(/f+$/, "").slice(-5).toUpperCase();
}

/** Deterministic integer seed from a string (for rough.js marks). */
export function seedFrom(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h) % 2147483647 || 1;
}
