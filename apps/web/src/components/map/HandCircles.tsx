"use client";

import type { Map as MlMap } from "maplibre-gl";
import { useEffect, useMemo, useState } from "react";
import { cellToBoundary } from "h3-js";
import { centre } from "@/lib/hex";
import { circlePaths } from "@/lib/marks";

const STAGGER_MS = 120;

/**
 * Gold, wobbly marker circles around the analyst-reviewed top picks, drawn on an SVG over
 * the map. Shapes are generated once per cell (fixed seed) at a reference size and then only
 * translated/scaled as the map moves, so they never "re-wobble".
 */
export function HandCircles({ map, cells }: { map: MlMap; cells: string[] }) {
  const [, force] = useState(0);

  useEffect(() => {
    const update = () => force((n) => n + 1);
    map.on("move", update);
    map.on("resize", update);
    return () => {
      map.off("move", update);
      map.off("resize", update);
    };
  }, [map]);

  const { refZoom, shapes } = useMemo(() => {
    // Size the circle from a real hexagon on screen at this zoom: centre → corner × 1.4.
    const zoomAtBuild = map.getZoom();
    let r = 30;
    if (cells[0]) {
      const a = map.project(centre(cells[0]));
      const [lng, lat] = cellToBoundary(cells[0], true)[0];
      const b = map.project([lng, lat]);
      r = Math.max(16, Math.hypot(a.x - b.x, a.y - b.y) * 1.4);
    }
    return {
      refZoom: zoomAtBuild,
      shapes: cells.map((h3) => ({ h3, paths: circlePaths(h3, 0, 0, r * 2.3, r * 2.0) })),
    };
  }, [cells, map]);

  const scale = Math.pow(2, map.getZoom() - refZoom);
  const canvas = map.getCanvas();
  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0"
      width={canvas.clientWidth}
      height={canvas.clientHeight}
    >
      {shapes.map(({ h3, paths }, i) => {
        const p = map.project(centre(h3));
        return (
          <g key={h3} transform={`translate(${p.x},${p.y}) scale(${Math.max(0.5, Math.min(scale, 3))})`}>
            {paths.map((d, j) => (
              <path
                key={j}
                d={d}
                pathLength={1}
                vectorEffect="non-scaling-stroke"
                className="hand-stroke"
                style={{ animationDelay: `${i * STAGGER_MS + j * 60}ms` }}
              />
            ))}
          </g>
        );
      })}
    </svg>
  );
}
