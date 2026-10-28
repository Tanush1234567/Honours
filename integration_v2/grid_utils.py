"""GIS boundaries: metre-based north-up grids and exact ignition area fractions."""
from pathlib import Path
import numpy as np
import rasterio
import geopandas as gpd
from shapely.geometry import box
from shapely.ops import unary_union


def load_landscape_georef(path):
    with rasterio.open(path) as src:
        if src.crs is None or not src.crs.is_projected:
            raise ValueError("Landscape must have a projected CRS")
        _, factor = src.crs.linear_units_factor
        if abs(factor - 1.0) > 1e-9:
            raise ValueError("Landscape coordinates must be in metres")
        tr = src.transform
        if tr.a <= 0 or tr.e >= 0 or abs(tr.b) > 1e-12 or abs(tr.d) > 1e-12:
            raise ValueError("Use a north-up, unrotated landscape raster")
        return {"rows": src.height, "cols": src.width, "transform": tr,
                "crs": src.crs.to_wkt(), "cell_size_x": tr.a, "cell_size_y": -tr.e}


def grid_from_ignition_shp(path, georef, threshold=0.5):
    path = Path(path)
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        if not path.with_suffix(suffix).is_file():
            raise ValueError(f"Missing shapefile component: {path.with_suffix(suffix)}")
    gdf = gpd.read_file(path)
    if gdf.empty or gdf.crs is None:
        raise ValueError("Ignition must contain polygons and a CRS")
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any() or not gdf.geometry.is_valid.all():
        raise ValueError("Ignition contains missing, empty, or invalid geometry")
    if not gdf.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Ignition must be polygon geometry, not points or lines")
    if not 0 < threshold <= 1:
        raise ValueError("Ignition threshold must be in (0,1]")
    polygon = unary_union(gdf.to_crs(georef["crs"]).geometry)
    tr, rows, cols = georef["transform"], georef["rows"], georef["cols"]
    extent = box(tr.c, tr.f + tr.e * rows, tr.c + tr.a * cols, tr.f)
    if polygon.intersection(extent).area == 0:
        raise ValueError("Ignition does not overlap the landscape after reprojection")
    minx, miny, maxx, maxy = polygon.bounds
    c0 = max(0, int(np.floor((minx - tr.c) / tr.a)))
    c1 = min(cols, int(np.ceil((maxx - tr.c) / tr.a)))
    r0 = max(0, int(np.floor((tr.f - maxy) / -tr.e)))
    r1 = min(rows, int(np.ceil((tr.f - miny) / -tr.e)))
    grid = np.zeros((rows, cols), dtype=np.int8)
    cell_area = tr.a * -tr.e
    for r in range(r0, r1):
        for c in range(c0, c1):
            x, y = tr * (c, r)
            fraction = polygon.intersection(box(x, y + tr.e, x + tr.a, y)).area / cell_area
            if fraction + 1e-12 >= threshold:
                grid[r, c] = 1
    if not np.any(grid == 1):
        raise ValueError("No cells meet the ignition area threshold; check resolution/geometry")
    return grid


def save_grid(grid, path, georef):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=georef["rows"],
                       width=georef["cols"], count=1, dtype="uint8",
                       crs=georef["crs"], transform=georef["transform"], compress="deflate") as dst:
        dst.write(np.asarray(grid, dtype=np.uint8), 1)


def fire_stats(grid):
    return {"unburned": int(np.sum(grid == 0)), "burning": int(np.sum(grid == 1)),
            "extinguished": int(np.sum(grid == 2)), "total": int(grid.size)}
