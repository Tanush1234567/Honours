from pathlib import Path
import numpy as np
import pytest
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin, Affine
from shapely.geometry import box
from integration.static_v3.grid_utils import load_landscape_georef, grid_from_ignition_shp, save_grid
from integration.static_v3.config import LANDSCAPE_TIF, IGNITION_SHP


def test_bundled_inputs_and_roundtrip(tmp_path):
    georef = load_landscape_georef(LANDSCAPE_TIF)
    assert (georef["rows"], georef["cols"], georef["cell_size_x"]) == (82, 230, 30)
    grid = grid_from_ignition_shp(IGNITION_SHP, georef)
    assert np.sum(grid == 1) == 960
    path = tmp_path / "grid.tif"
    save_grid(grid, path, georef)
    with rasterio.open(path) as src:
        assert src.crs.to_wkt() == georef["crs"] and src.transform == georef["transform"]
        np.testing.assert_array_equal(src.read(1), grid)


@pytest.mark.parametrize("crs,tr,message", [
    ("EPSG:4326", from_origin(0, 1, .01, .01), "projected"),
    ("EPSG:2263", from_origin(0, 100, 30, 30), "metres"),
    ("EPSG:32633", Affine(30, 1, 0, 0, -30, 100), "north-up"),
])
def test_incompatible_raster_rejected(tmp_path, crs, tr, message):
    path = tmp_path / "bad.tif"
    with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=1,
                       dtype="uint8", transform=tr, crs=crs) as dst:
        dst.write(np.zeros((2, 2), dtype=np.uint8), 1)
    with pytest.raises(ValueError, match=message):
        load_landscape_georef(path)


def test_exact_half_cell_ignition(tmp_path):
    path = tmp_path / "ignition.shp"
    gpd.GeoDataFrame(geometry=[box(0, 0, 15, 30)], crs="EPSG:32633").to_file(path)
    georef = {"rows": 1, "cols": 1, "transform": from_origin(0, 30, 30, 30),
              "crs": rasterio.crs.CRS.from_epsg(32633), "cell_size_x": 30, "cell_size_y": 30}
    assert grid_from_ignition_shp(path, georef)[0, 0] == 1
    path.with_suffix(".prj").unlink()
    with pytest.raises(ValueError, match="Missing shapefile"):
        grid_from_ignition_shp(path, georef)
