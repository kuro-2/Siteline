"""WorldPop constrained population raster → population per H3 cell."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import h3
import numpy as np
import rasterio
from rasterio.windows import from_bounds


def population_by_cell(
    raster_path: Path, cells: set[str], resolution: int
) -> tuple[dict[str, float], int]:
    """Sum raster pixels whose centre falls in each cell. Returns (sums, pixels_used)."""
    if not cells:
        return {}, 0
    lats, lngs = [], []
    for c in cells:
        for lat, lng in h3.cell_to_boundary(c):
            lats.append(lat)
            lngs.append(lng)
    west, east, south, north = min(lngs), max(lngs), min(lats), max(lats)

    with rasterio.open(raster_path) as src:
        if src.crs is not None and src.crs.to_epsg() not in (4326, None):
            raise ValueError(f"Expected a WGS84 (EPSG:4326) raster, got {src.crs}.")
        window = from_bounds(west, south, east, north, transform=src.transform)
        window = window.round_offsets().round_lengths()
        data = src.read(1, window=window, masked=True)
        transform = src.window_transform(window)

    sums: dict[str, float] = defaultdict(float)
    used = 0
    rows, cols = np.nonzero(~np.ma.getmaskarray(data))
    for r, c in zip(rows.tolist(), cols.tolist(), strict=True):
        v = float(data[r, c])
        if not np.isfinite(v) or v <= 0:
            continue
        x, y = transform * (c + 0.5, r + 0.5)
        cell = h3.latlng_to_cell(y, x, resolution)
        if cell in cells:
            sums[cell] += v
            used += 1
    return {c: round(sums.get(c, 0.0), 1) for c in cells}, used
