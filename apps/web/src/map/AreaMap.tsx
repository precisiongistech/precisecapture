/**
 * A MapLibre map for drawing or showing one polygon (project extent, assigned area).
 * Drawing: click to add vertices, double-click (or "Finish") to close. "Clear" removes it.
 * Upload: GeoJSON or KML files are parsed client-side and the first polygon is used.
 */
import type { Feature, FeatureCollection, Geometry } from "geojson";
import maplibregl, { type Map as MlMap } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui";

export type Polygon = { type: "Polygon"; coordinates: number[][][] };
export type MultiPolygon = { type: "MultiPolygon"; coordinates: number[][][][] };
export type AreaGeometry = Polygon | MultiPolygon;

const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

const GHANA_CENTER: [number, number] = [-1.2, 7.9];

export function AreaMap({
  value,
  onChange,
  readOnly = false,
  height = 360,
}: {
  value: AreaGeometry | null;
  onChange?: (geom: Polygon | null) => void;
  readOnly?: boolean;
  height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const [drawing, setDrawing] = useState(false);
  const pointsRef = useRef<number[][]>([]);
  const [, force] = useState(0);

  useEffect(() => {
    if (!el.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: el.current,
      style: STYLE,
      center: GHANA_CENTER,
      zoom: 6,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("load", () => {
      map.addSource("area", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "area-fill",
        type: "fill",
        source: "area",
        paint: { "fill-color": "#1f9d55", "fill-opacity": 0.2 },
      });
      map.addLayer({
        id: "area-line",
        type: "line",
        source: "area",
        paint: { "line-color": "#136236", "line-width": 2 },
      });
      map.addSource("draft", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "draft-line",
        type: "line",
        source: "draft",
        paint: { "line-color": "#d97706", "line-width": 2, "line-dasharray": [2, 1] },
      });
      map.addLayer({
        id: "draft-pts",
        type: "circle",
        source: "draft",
        paint: { "circle-radius": 4, "circle-color": "#d97706" },
        filter: ["==", "$type", "Point"],
      });
      render(map, value);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map && map.isStyleLoaded()) render(map, value);
  }, [value]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !drawing) return;
    const onClick = (e: maplibregl.MapMouseEvent) => {
      pointsRef.current = [...pointsRef.current, [e.lngLat.lng, e.lngLat.lat]];
      renderDraft(map, pointsRef.current);
      force((n) => n + 1);
    };
    const onDbl = (e: maplibregl.MapMouseEvent) => {
      e.preventDefault();
      finish();
    };
    map.on("click", onClick);
    map.on("dblclick", onDbl);
    map.getCanvas().style.cursor = "crosshair";
    return () => {
      map.off("click", onClick);
      map.off("dblclick", onDbl);
      map.getCanvas().style.cursor = "";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawing]);

  function finish() {
    const pts = pointsRef.current;
    const map = mapRef.current;
    if (pts.length >= 3 && onChange) {
      onChange({ type: "Polygon", coordinates: [[...pts, pts[0]!]] });
    }
    pointsRef.current = [];
    if (map) renderDraft(map, []);
    setDrawing(false);
  }

  async function onFile(file: File) {
    const text = await file.text();
    const geom = file.name.toLowerCase().endsWith(".kml")
      ? polygonFromKml(text)
      : polygonFromGeoJson(text);
    if (!geom) {
      alert("No polygon found in the file");
      return;
    }
    onChange?.(geom);
    const map = mapRef.current;
    if (map) fitTo(map, geom);
  }

  return (
    <div className="space-y-2">
      <div
        ref={el}
        style={{ height }}
        className="w-full overflow-hidden rounded-md border border-neutral-300"
      />
      {!readOnly && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {!drawing ? (
            <Button type="button" variant="secondary" size="sm" onClick={() => setDrawing(true)}>
              {value ? "Redraw area" : "Draw area"}
            </Button>
          ) : (
            <>
              <span className="text-neutral-600">
                Click to add corners ({pointsRef.current.length}); double-click or Finish to close.
              </span>
              <Button
                type="button"
                size="sm"
                onClick={finish}
                disabled={pointsRef.current.length < 3}
              >
                Finish
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  pointsRef.current = [];
                  setDrawing(false);
                  if (mapRef.current) renderDraft(mapRef.current, []);
                }}
              >
                Cancel
              </Button>
            </>
          )}
          <label className="cursor-pointer rounded-md border border-neutral-300 bg-white px-2.5 py-1 hover:bg-neutral-100">
            Upload GeoJSON / KML
            <input
              type="file"
              accept=".geojson,.json,.kml"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && void onFile(e.target.files[0])}
            />
          </label>
          {value && (
            <Button type="button" variant="ghost" size="sm" onClick={() => onChange?.(null)}>
              Clear
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function render(map: MlMap, geom: AreaGeometry | null) {
  const src = map.getSource("area") as maplibregl.GeoJSONSource | undefined;
  if (!src) return;
  src.setData({
    type: "FeatureCollection",
    features: geom ? [{ type: "Feature", geometry: geom, properties: {} }] : [],
  });
  if (geom) fitTo(map, geom);
}

function renderDraft(map: MlMap, pts: number[][]) {
  const src = map.getSource("draft") as maplibregl.GeoJSONSource | undefined;
  if (!src) return;
  const features: Feature[] = pts.map((p) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: p },
    properties: {},
  }));
  if (pts.length >= 2)
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: pts },
      properties: {},
    });
  src.setData({ type: "FeatureCollection", features });
}

function fitTo(map: MlMap, geom: AreaGeometry) {
  const coords = geom.type === "Polygon" ? geom.coordinates.flat() : geom.coordinates.flat(2);
  const lons = coords.map((c) => c[0]!);
  const lats = coords.map((c) => c[1]!);
  map.fitBounds([Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)], {
    padding: 30,
    duration: 300,
    maxZoom: 14,
  });
}

export function polygonFromGeoJson(text: string): Polygon | null {
  try {
    const data = JSON.parse(text) as FeatureCollection | Feature | Geometry;
    const geoms: Geometry[] = [];
    if (data.type === "FeatureCollection")
      data.features.forEach((f: Feature) => {
        if (f.geometry) geoms.push(f.geometry);
      });
    else if (data.type === "Feature") {
      if (data.geometry) geoms.push(data.geometry);
    } else geoms.push(data as Geometry);
    for (const g of geoms) {
      if (g.type === "Polygon") return g as Polygon;
      if (g.type === "MultiPolygon" && g.coordinates[0])
        return { type: "Polygon", coordinates: g.coordinates[0] };
    }
  } catch {
    return null;
  }
  return null;
}

export function polygonFromKml(text: string): Polygon | null {
  const doc = new DOMParser().parseFromString(text, "application/xml");
  const ring = doc.querySelector("Polygon outerBoundaryIs coordinates, Polygon coordinates");
  if (!ring?.textContent) return null;
  const pts = ring.textContent
    .trim()
    .split(/\s+/)
    .map((tuple) => tuple.split(",").slice(0, 2).map(Number))
    .filter((c) => c.length === 2 && c.every((n) => Number.isFinite(n)));
  if (pts.length < 4) return null;
  return { type: "Polygon", coordinates: [pts] };
}
