"use client";

import type { Geometry } from "geojson";

import type { GeoJSONSource, Map as MlMap, MapLayerMouseEvent } from "maplibre-gl";
import { Crosshair, Minus, Plus } from "@phosphor-icons/react/dist/ssr";
import { useCallback, useEffect, useRef, useState } from "react";
import type { MapCell } from "@/lib/api";
import { MAP_STYLE_URL } from "@/lib/config";
import { cellsToGeoJSON, centre } from "@/lib/hex";
import { t } from "@/lib/i18n";
import { hatchImage, readPalette, restyle } from "@/lib/mapstyle";
import { HandCircles } from "./HandCircles";

export interface AreaMapProps {
  label: string;
  boundary: Geometry | null;
  bbox: number[] | null;
  cells: MapCell[];
  circled: string[]; // h3 of reviewed top picks
  selected?: string | null;
  onSelect?: (h3: string) => void;
  onMapClick?: (lngLat: [number, number]) => void;
  pin?: [number, number] | null;
  showControls?: boolean;
  interactive?: boolean;
  padding?: { top: number; right: number; bottom: number; left: number };
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function stepColors(): string[] {
  return [1, 2, 3, 4, 5].map((i) => cssVar(`--opp-${i}`));
}

export function AreaMap(props: AreaMapProps) {
  const {
    label, boundary, bbox, cells, circled, selected, onSelect, onMapClick, pin,
    showControls = true, interactive = true, padding,
  } = props;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const [map, setMap] = useState<MlMap | null>(null);
  const handlers = useRef({ onSelect, onMapClick });
  useEffect(() => {
    handlers.current = { onSelect, onMapClick };
  }, [onSelect, onMapClick]);

  // ------------------------------------------------------------------ create once
  useEffect(() => {
    let cancelled = false;
    let instance: MlMap | null = null;
    (async () => {
      const { Map: MapCtor, setWorkerUrl } = await import("maplibre-gl");
      setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      if (cancelled || !container.current) return;
      const created = new MapCtor({
        container: container.current,
        style: MAP_STYLE_URL,
        bounds: bbox ? [bbox[0], bbox[1], bbox[2], bbox[3]] : undefined,
        center: bbox ? undefined : [91.7362, 26.1445],
        zoom: bbox ? undefined : 12,
        fitBoundsOptions: { padding: typeof padding === "object" ? padding : 32 },
        attributionControl: { compact: true },
        interactive,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        maxZoom: 17,
        minZoom: 10,
      });
      instance = created;
      created.touchZoomRotate.disableRotation();
      created.on("error", (e) => console.error("map error:", e.error?.message ?? e));
      created.on("load", () => {
        try {
          onLoad();
        } catch (err) {
          console.error("map setup failed:", err);
        }
      });
      const onLoad = () => {
        if (!instance) return;
        restyle(instance, readPalette());
        const pal = readPalette();
        instance.addImage("hatch", hatchImage(cssVar("--ink-soft")), { pixelRatio: 2 });
        const colors = stepColors();
        instance.addSource("hexes", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        instance.addSource("boundary", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        instance.addSource("pin", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        instance.addLayer({
          id: "hex-fill",
          type: "fill",
          source: "hexes",
          filter: [">", ["get", "step"], 0],
          paint: {
            "fill-color": ["match", ["get", "step"], 1, colors[0], 2, colors[1], 3, colors[2], 4, colors[3], colors[4]],
            "fill-opacity": ["case", ["get", "lowConfidence"], 0.6, 0.88],
          },
        });
        instance.addLayer({
          id: "hex-hatch",
          type: "fill",
          source: "hexes",
          filter: ["all", [">", ["get", "step"], 0], ["get", "lowConfidence"]],
          paint: { "fill-pattern": "hatch", "fill-opacity": 0.55 },
        });
        instance.addLayer({
          id: "hex-line",
          type: "line",
          source: "hexes",
          paint: { "line-color": cssVar("--rule"), "line-width": 0.8 },
        });
        instance.addLayer({
          id: "boundary-line",
          type: "line",
          source: "boundary",
          paint: { "line-color": cssVar("--ink-soft"), "line-width": 1.5, "line-dasharray": [3, 2] },
        });
        instance.addLayer({
          id: "hex-selected",
          type: "line",
          source: "hexes",
          filter: ["==", ["get", "h3"], ""],
          paint: { "line-color": cssVar("--ink"), "line-width": 3 },
        });
        instance.addLayer({
          id: "pin",
          type: "circle",
          source: "pin",
          paint: {
            "circle-radius": 8,
            "circle-color": cssVar("--tea"),
            "circle-stroke-color": pal.labelHalo,
            "circle-stroke-width": 3,
          },
        });
        instance.on("click", "hex-fill", (e: MapLayerMouseEvent) => {
          const h3 = e.features?.[0]?.properties?.h3 as string | undefined;
          if (h3 && handlers.current.onSelect) handlers.current.onSelect(h3);
        });
        instance.on("click", (e) => handlers.current.onMapClick?.([e.lngLat.lng, e.lngLat.lat]));
        instance.on("mouseenter", "hex-fill", () => {
          if (instance && handlers.current.onSelect) instance.getCanvas().style.cursor = "pointer";
        });
        instance.on("mouseleave", "hex-fill", () => {
          if (instance) instance.getCanvas().style.cursor = "";
        });
        mapRef.current = instance;
        setMap(instance);
      };
    })();
    return () => {
      cancelled = true;
      instance?.remove();
      mapRef.current = null;
      setMap(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the map is created once
  }, []);

  // ------------------------------------------------------------------ data updates
  useEffect(() => {
    if (!map) return;
    (map.getSource("hexes") as GeoJSONSource | undefined)?.setData(cellsToGeoJSON(cells));
  }, [map, cells]);

  // Fit to the area once its bounds arrive (they usually load after the map is created).
  const bboxKey = bbox?.join(",") ?? "";
  useEffect(() => {
    if (!map || !bbox || bbox.length < 4) return;
    const mobile = window.innerWidth < 1024;
    map.fitBounds([bbox[0], bbox[1], bbox[2], bbox[3]] as [number, number, number, number], {
      padding: padding ?? { top: 24, left: 24, right: 24, bottom: mobile ? window.innerHeight * 0.17 : 24 },
      duration: 0,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refit only when the area changes
  }, [map, bboxKey]);

  useEffect(() => {
    if (!map || !boundary) return;
    (map.getSource("boundary") as GeoJSONSource | undefined)?.setData({
      type: "Feature",
      properties: {},
      geometry: boundary,
    });
  }, [map, boundary]);

  useEffect(() => {
    if (!map) return;
    map.setFilter("hex-selected", ["==", ["get", "h3"], selected ?? ""]);
    if (selected) {
      // Centre the block in the part of the map the sheet doesn't cover.
      const mobile = window.innerWidth < 1024;
      map.flyTo({
        center: centre(selected),
        padding: { top: 0, left: 0, right: 0, bottom: mobile ? window.innerHeight * 0.45 : 0 },
        duration: reduceMotion() ? 0 : 700,
      });
    }
  }, [map, selected]);

  useEffect(() => {
    if (!map) return;
    (map.getSource("pin") as GeoJSONSource | undefined)?.setData(
      pin
        ? { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: pin } }
        : { type: "FeatureCollection", features: [] },
    );
  }, [map, pin]);

  // Re-apply colours when the system theme flips.
  useEffect(() => {
    if (!map) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      restyle(map, readPalette());
      const colors = stepColors();
      map.setPaintProperty("hex-fill", "fill-color", [
        "match", ["get", "step"], 1, colors[0], 2, colors[1], 3, colors[2], 4, colors[3], colors[4],
      ]);
      map.setPaintProperty("hex-line", "line-color", cssVar("--rule"));
      map.setPaintProperty("hex-selected", "line-color", cssVar("--ink"));
    };
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [map]);

  const zoom = useCallback((d: number) => mapRef.current?.zoomTo((mapRef.current?.getZoom() ?? 13) + d), []);
  const locate = useCallback(() => {
    navigator.geolocation?.getCurrentPosition((pos) => {
      mapRef.current?.flyTo({
        center: [pos.coords.longitude, pos.coords.latitude],
        zoom: 15,
        duration: reduceMotion() ? 0 : 700,
      });
    });
  }, []);

  return (
    <div className="relative h-full w-full">
      <div ref={container} className="h-full w-full" role="region" aria-label={label} />
      {!map && (
        <p className="absolute inset-x-0 top-1/3 text-center text-ink-soft" aria-live="polite">
          {t("common.loading")}
        </p>
      )}
      {map && <HandCircles map={map} cells={circled} />}
      {showControls && (
        <div className="absolute left-3 top-3 flex flex-col gap-2 lg:left-4 lg:top-4">
          <button type="button" className="map-control" onClick={() => zoom(1)} aria-label={t("common.zoom_in")}>
            <Plus size={20} />
          </button>
          <button type="button" className="map-control" onClick={() => zoom(-1)} aria-label={t("common.zoom_out")}>
            <Minus size={20} />
          </button>
          <button type="button" className="map-control" onClick={locate} aria-label={t("common.my_location")}>
            <Crosshair size={20} />
          </button>
        </div>
      )}
    </div>
  );
}

function reduceMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
