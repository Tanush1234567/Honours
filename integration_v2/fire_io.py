"""Native landscape conversion, grid-aligned arrival parsing and fireline export."""
from pathlib import Path
from math import floor as math_floor, ceil as math_ceil
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import shapes
from rasterio.shutil import copy as raster_copy
from rasterio.crs import CRS
from shapely.geometry import shape, box, Polygon
from shapely.ops import unary_union, polygonize
from .grid_utils import load_landscape_georef, save_grid


def export_landscape(source, destination, options=None):
    """Create a native LCP from a proper FlamMap multiband landscape, without resampling.

    GDAL's default vertical units match the bundled LANDFIRE bands: elevation m,
    slope degrees, aspect azimuth degrees, cover %, height/base height m*10,
    bulk density kg/m3*100. Override options for other source conventions.
    """
    source, destination = Path(source), Path(destination)
    load_landscape_georef(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # CreateCopy may cache statistics in the source's .aux.xml even when it was
    # opened read-only. Disable PAM to keep the user's source input unchanged.
    with rasterio.Env(GDAL_PAM_ENABLED="NO"), rasterio.open(source) as src:
        if src.count not in (5, 7, 8, 10) or any(d != "int16" for d in src.dtypes):
            raise ValueError("Native FARSITE needs a 5/7/8/10-band int16 FlamMap landscape, not a map image")
        if src.driver == "LCP":
            # Avoid reinterpreting the units of an existing LCP.
            import shutil
            shutil.copy2(source, destination)
        else:
            raster_copy(src, destination, driver="LCP", **(options or {}))
        # LCP does not embed a CRS. Always write the companion projection.
        destination.with_suffix(".prj").write_text(src.crs.to_wkt(version="WKT1_ESRI"), encoding="utf-8")
    target_ref = load_landscape_georef(destination)
    source_ref = load_landscape_georef(source)
    if not same_grid(source_ref, target_ref):
        raise ValueError("LCP export changed landscape georeferencing")
    return destination


def same_grid(left, right):
    return (left["rows"] == right["rows"] and left["cols"] == right["cols"]
            and CRS.from_user_input(left["crs"]) == CRS.from_user_input(right["crs"])
            and left["transform"].almost_equals(right["transform"], precision=1e-6))


def validate_native_fuels(path, ignition_grid=None):
    with rasterio.open(path) as src:
        if src.count < 5:
            raise ValueError("FARSITE requires terrain, fuel model and canopy-cover bands")
        fuel = src.read(4)
        burnable = ((fuel >= 1) & (fuel <= 13)) | ((fuel >= 101) & (fuel <= 204))
        if not burnable.any():
            raise ValueError("Landscape fuel-model band 4 has no burnable cells (bundled static_v3 data are all -9999). "
                             "Supply a complete FlamMap landscape or run --native-demo; geometry alone cannot drive FARSITE")
        if ignition_grid is not None and not np.any(burnable & (ignition_grid == 1)):
            raise ValueError("Initial ignition does not overlap any burnable fuel-model cells")


def read_arrival(path, georef, world):
    """Read elapsed minutes, never ROS. Reject mismatched grids rather than guessing.

    Native ASCII grids lack a CRS; the known staged landscape supplies it ONLY
    after verifying shape and affine transform. NoData/negative values are unreached.
    """
    with rasterio.open(path) as src:
        if src.shape != world.grid.shape or not src.transform.almost_equals(georef["transform"], precision=1e-6):
            raise ValueError("Arrival raster shape/transform differs from the optimisation grid")
        if src.crs is not None and src.crs != CRS.from_user_input(georef["crs"]):
            raise ValueError("Arrival raster CRS differs from the staged landscape")
        data = src.read(1, masked=True).astype(float)
        arrival = data.filled(np.inf)
    arrival[~np.isfinite(arrival) | (arrival < 0)] = np.inf
    arrival[world.grid == 1] = 0.0
    arrival[world.grid == 2] = np.inf
    return arrival


def save_arrival(arrival, path, georef):
    arrival = np.asarray(arrival, dtype="float64")
    values = np.where(np.isfinite(arrival), arrival, -9999.)
    with rasterio.open(path, "w", driver="GTiff", height=georef["rows"], width=georef["cols"],
                       count=1, dtype="float64", crs=georef["crs"], transform=georef["transform"],
                       nodata=-9999, compress="deflate") as dst:
        dst.write(values, 1)


def mask_polygons(mask, georef):
    return [shape(geom) for geom, val in shapes(mask.astype("uint8"), mask=mask,
                                              transform=georef["transform"], connectivity=4) if val == 1]


def write_fire_layers(world, directory, georef):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    save_grid(world.grid, directory / "grid.tif", georef)
    layers = {}
    for label, code in (("ignition", 1), ("barriers", 2)):
        polygons = mask_polygons(world.grid == code, georef)
        if label == "ignition" and world.fire_geometry is not None:
            geometry = world.fire_geometry
            polygons = ([geometry] if geometry.geom_type == "Polygon" else
                        [g for g in getattr(geometry, "geoms", []) if g.geom_type == "Polygon"])
        if polygons:
            path = directory / f"{label}.shp"
            gpd.GeoDataFrame({"state": [code] * len(polygons)}, geometry=polygons,
                             crs=georef["crs"]).to_file(path, driver="ESRI Shapefile")
            layers[label] = path
        if label == "ignition":
            line = unary_union(polygons).boundary if polygons else None
            gpd.GeoDataFrame({"step": [world.step] if line is not None else []},
                             geometry=[line] if line is not None else [], crs=georef["crs"]).to_file(
                                 directory / "fireline.gpkg", layer="active_fireline", driver="GPKG")
    return layers


def grid_from_geometry(geometry, georef, threshold):
    """Exact polygon/cell area test, retaining the static_v3 >=50% convention."""
    grid = np.zeros((georef["rows"], georef["cols"]), dtype="int8")
    if geometry.is_empty:
        return grid
    tr = georef["transform"]
    minx, miny, maxx, maxy = geometry.bounds
    c0, c1 = max(0, math_floor((minx-tr.c)/tr.a)), min(georef["cols"], math_ceil((maxx-tr.c)/tr.a))
    r0, r1 = max(0, math_floor((tr.f-maxy)/-tr.e)), min(georef["rows"], math_ceil((tr.f-miny)/-tr.e))
    for r in range(r0, r1):
        for c in range(c0, c1):
            x, y = tr @ (c, r)
            if geometry.intersection(box(x, y+tr.e, x+tr.a, y)).area / (tr.a * -tr.e) + 1e-12 >= threshold:
                grid[r, c] = 1
    return grid


def read_perimeter_forecast(path, world, georef, settings):
    """Preserve the true continuous perimeter and derive timed area-threshold cells.

    Keeping the subcell perimeter prevents slow fires from restarting their
    progress at every raster-cell boundary on each rolling window.
    """
    frame = gpd.read_file(path)
    if frame.empty:
        raise ValueError("FARSITE returned no timed perimeters")
    if frame.crs is None:
        frame = frame.set_crs(georef["crs"])
    elif CRS.from_user_input(frame.crs) != CRS.from_user_input(georef["crs"]):
        raise ValueError("FARSITE perimeter CRS differs from the landscape")
    field = next((c for c in frame.columns if c.lower().startswith("elapsed_m")), None)
    if field is None:
        raise ValueError("FARSITE perimeters need the Elapsed_Minutes/Elapsed_Mi field in minutes")
    times = np.asarray(frame[field], dtype=float)
    if not np.isfinite(times).all() or (times < 0).any():
        raise ValueError("Invalid FARSITE perimeter elapsed times")
    tr = georef["transform"]
    extent = box(tr.c, tr.f+tr.e*georef["rows"], tr.c+tr.a*georef["cols"], tr.f)
    barriers = unary_union(mask_polygons(world.grid == 2, georef))
    initial = world.fire_geometry if world.fire_geometry is not None else unary_union(mask_polygons(world.grid == 1, georef))
    perimeters, arrival = {}, np.full(world.grid.shape, np.inf)
    arrival[world.grid == 1] = 0
    for t in range(1, settings.horizon_steps + 1):
        mask = np.isclose(times, t*settings.step_minutes, rtol=0, atol=1e-6)
        if not mask.any():
            raise ValueError(f"FARSITE did not save a perimeter at elapsed minute {t*settings.step_minutes:g}; "
                             "use an internal timestep dividing the optimisation timestep")
        polygons = []
        for geom in frame.loc[mask].geometry:
            if geom is None or geom.is_empty:
                continue
            if geom.geom_type in ("Polygon", "MultiPolygon"):
                polygons.append(geom)
            elif geom.geom_type == "LineString" and geom.is_ring:
                polygons.append(Polygon(geom))
            elif geom.geom_type == "MultiLineString":
                polygons.extend(polygonize(geom.geoms))
            else:
                raise ValueError("Native perimeter must contain polygons or closed fireline rings")
        geometry = unary_union([initial, *polygons]).intersection(extent).difference(barriers)
        if not geometry.is_valid:
            raise ValueError("Native FARSITE perimeter is invalid")
        perimeters[t] = geometry
        covered = grid_from_geometry(geometry, georef, settings.ignition_area_fraction) == 1
        arrival[(world.grid != 2) & covered & np.isinf(arrival)] = t*settings.step_minutes
    return arrival, perimeters
