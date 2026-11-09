"""Recreate this synthetic, multi-cell native FARSITE input scenario."""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

HERE = Path(__file__).resolve().parent


def main():
    rows = cols = 12
    cell_m = 30
    transform = from_origin(500000, 4500360, cell_m, cell_m)
    crs = "EPSG:32633"
    bands = np.zeros((5, rows, cols), dtype="int16")
    bands[0] = 100  # Elevation (m); other terrain and canopy bands stay zero.
    bands[3] = 1    # Standard short-grass fuel model, throughout the landscape.
    with rasterio.open(HERE / "landscape.tif", "w", driver="GTiff",
                       height=rows, width=cols, count=5, dtype="int16",
                       crs=crs, transform=transform) as dst:
        dst.write(bands)
        for index, label in enumerate(("elevation_m", "slope_degrees", "aspect_degrees",
                                       "fuel_model", "canopy_cover_pct"), start=1):
            dst.set_band_description(index, label)
    # Exactly nine complete cells: rows 7..9, columns 2..4, zero based.
    west, north = transform * (2, 7)
    east, south = transform * (5, 10)
    gpd.GeoDataFrame({"id": [1]}, geometry=[box(west, south, east, north)], crs=crs).to_file(
        HERE / "ignition.shp", driver="ESRI Shapefile", index=False)
    manifest = {
        "synthetic": True, "rows": rows, "cols": cols, "cell_size_m": cell_m,
        "extent_m": [cols * cell_m, rows * cell_m], "crs": crs,
        "fuel_model": 1, "initial_burning_cells": 9,
        "ignition_rows_inclusive": [7, 9], "ignition_cols_inclusive": [2, 4],
        "airfield": [11, 0], "water_cells": [[11, 11]],
        "num_tankers": 1, "num_scoopers": 1,
    }
    (HERE / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Created 12 x 12 landscape and nine-cell ignition in {HERE}")


if __name__ == "__main__":
    main()
