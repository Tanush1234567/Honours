from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
from types import SimpleNamespace
import numpy as np
import geopandas as gpd
import pytest
import rasterio
from rasterio.transform import from_origin
from integration_v2.fire_engine import FarsiteEngine, NativeSettings, write_native_input
from integration_v2.fire_io import export_landscape, read_arrival, write_fire_layers, save_arrival
from integration_v2.scenario import World
from integration_v2.wind import Wind
from test_dynamic import example


ROOT = Path(__file__).resolve().parents[1]


def test_landscape_export_preserves_all_static_pixels_and_crs(tmp_path):
    original = ROOT / "inputs" / "landscape.tif"
    converted = export_landscape(original, tmp_path / "matching.lcp")
    with rasterio.open(original) as src, rasterio.open(converted) as dst:
        assert src.crs == dst.crs
        assert src.transform == dst.transform
        assert src.count == dst.count == 8
        assert np.array_equal(src.read(), dst.read())


def test_arrival_nodata_zero_and_extinguished_mask(tmp_path):
    world, ref, _ = example()
    world.grid[1, 1] = 2
    values = np.full(world.grid.shape, np.inf)
    values[2, 2], values[2, 3], values[1, 1] = 0, 1.25, 0
    path = tmp_path / "arrival.tif"
    save_arrival(values, path, ref)
    actual = read_arrival(path, ref, world)
    assert actual[2, 2] == 0
    assert actual[2, 3] == 1.25
    assert np.isinf(actual[1, 1]) and np.isinf(actual[0, 0])


def test_arrival_misalignment_is_rejected(tmp_path):
    world, ref, _ = example()
    shifted = dict(ref, transform=from_origin(1, 150, 30, 30))
    path = tmp_path / "shifted.tif"
    save_arrival(np.zeros_like(world.grid), path, shifted)
    with pytest.raises(ValueError, match="shape/transform"):
        read_arrival(path, ref, world)


def test_shapefile_roundtrip_and_permanent_barriers(tmp_path):
    world, ref, _ = example()
    world.grid[2, 3] = 2
    layers = write_fire_layers(world, tmp_path, ref)
    assert set(layers) == {"ignition", "barriers"}
    fire, barrier = gpd.read_file(layers["ignition"]), gpd.read_file(layers["barriers"])
    assert fire.geometry.area.sum() == 900
    assert barrier.geometry.area.sum() == 900
    assert fire.geometry.union_all().intersection(barrier.geometry.union_all()).area == 0
    assert fire.crs == barrier.crs
    assert (tmp_path / "fireline.gpkg").is_file()


def test_native_input_dates_wind_conversion_and_barrier_fill(tmp_path):
    start = datetime(2020, 7, 20, 23, 58)
    path = tmp_path / "weather.input"
    write_native_input(path, start, start + timedelta(minutes=5), NativeSettings(Path("unused")), Wind(16.09344, 270), 42)
    text = path.read_text()
    assert "FARSITE_START_TIME: 07 20 2358" in text
    assert "FARSITE_END_TIME: 07 21 0003" in text
    assert "10.00000000 270.00000000" in text  # mph, meteorological from
    assert "FARSITE_FILL_BARRIERS: 1" in text
    assert "RAWS_UNITS: English" in text


def test_gui_executable_is_rejected():
    with pytest.raises(ValueError, match="GUI"):
        NativeSettings(Path(r"C:\Workspace\FlamMap6\FlamMap6.exe")).validate()


def adapter_fixture(tmp_path):
    world, ref, cfg = example()
    # Test the adapter boundary without pretending this is a native simulation.
    exe = tmp_path / "TestFARSITE.exe"
    exe.write_bytes(b"test fixture; subprocess is patched")
    engine = FarsiteEngine.__new__(FarsiteEngine)
    engine.native = NativeSettings(exe)
    engine.georef = ref
    engine.landscape = tmp_path / "fixture.lcp"
    engine.landscape.write_bytes(b"test fixture")
    engine.landscape.with_suffix(".prj").write_text(ref["crs"].to_wkt())
    return engine, world, ref, cfg


def test_native_command_protocol_and_space_safe_staging(tmp_path, monkeypatch):
    engine, world, ref, cfg = adapter_fixture(tmp_path)
    folder = tmp_path / "path with spaces" / "native"
    def fake_run(command, **kw):
        assert command == [str(engine.native.executable.resolve()), "command.txt"]
        directory = kw["cwd"]
        assert directory == folder.resolve()
        assert (directory / "command.txt").read_text().strip().split() == [
            "landscape.lcp", "weather.input", "ignition.shp", "0", "fire", "1"]
        values = np.full(world.grid.shape, -9999.)
        values[2, 2], values[2, 3] = 0, 1.5
        with rasterio.open(directory / "fire_ArrivalTime.asc", "w", driver="AAIGrid", height=5,
                           width=5, count=1, dtype="float64", transform=ref["transform"], nodata=-9999) as dst:
            dst.write(values, 1)
        from shapely.geometry import box
        origin, expanded = box(60, 60, 90, 90), box(60, 60, 120, 90)
        gpd.GeoDataFrame({"Elapsed_Mi": [1., 2., 3., 4.]}, geometry=[origin, expanded, expanded, expanded],
                         crs=ref["crs"]).to_file(directory / "fire_Perimeters.shp")
        return SimpleNamespace(returncode=0, stdout="test fixture", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    values = engine.forecast(world, ref, cfg, Wind(10, 225), folder)
    assert values[2, 3] == 2.0  # Exact area coverage, rather than the diagnostic centre arrival.
    assert (folder / "stdout.log").read_text() == "test fixture"


def test_native_zero_exit_without_output_is_an_error(tmp_path, monkeypatch):
    engine, world, ref, cfg = adapter_fixture(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="failed internally", stderr=""))
    with pytest.raises(FileNotFoundError, match="did not produce"):
        engine.forecast(world, ref, cfg, Wind(10, 0), tmp_path / "native")


def test_native_timeout_is_reported_with_logs(tmp_path, monkeypatch):
    engine, world, ref, cfg = adapter_fixture(tmp_path)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1, output=b"still running")
    monkeypatch.setattr(subprocess, "run", timeout)
    folder = tmp_path / "native"
    with pytest.raises(RuntimeError, match="timed out"):
        engine.forecast(world, ref, cfg, Wind(10, 0), folder)
    assert (folder / "stdout.log").read_text() == "still running"


def test_static_landscape_missing_fuel_is_reported():
    from integration_v2.fire_io import validate_native_fuels
    with pytest.raises(ValueError, match="no burnable cells"):
        validate_native_fuels(ROOT / "inputs" / "landscape.tif")


def test_perimeter_preserves_subcell_growth_and_area_rule(tmp_path):
    from shapely.geometry import box
    from integration_v2.fire_io import read_perimeter_forecast
    world, ref, cfg = example()
    # At t=1 only 1/3 of the adjacent cell is covered; at t=2 exactly 1/2.
    geoms = [box(60, 60, 100, 90), box(60, 60, 105, 90), box(60, 60, 110, 90), box(60, 60, 115, 90)]
    path = tmp_path / "perimeters.shp"
    gpd.GeoDataFrame({"Elapsed_Mi": [1., 2., 3., 4.]}, geometry=geoms, crs=ref["crs"]).to_file(path)
    arrival, perimeters = read_perimeter_forecast(path, world, ref, cfg)
    assert arrival[2, 3] == 2
    assert perimeters[1].bounds[2] == 100
    assert perimeters[2].bounds[2] == 105


def test_dll_worker_can_load_installed_farsite():
    import os, sys
    path = Path(r"C:\Workspace\FlamMap6\farsite.dll")
    if os.name != "nt" or not path.is_file():
        pytest.skip("Installed FlamMap Windows DLL is not available")
    result = subprocess.run([sys.executable, str(ROOT / "native_worker.py"), "--dll", str(path), "--probe"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_installed_native_fire_grows_and_preserves_continuous_front(tmp_path):
    import os
    from shapely.geometry import box
    dll = Path(r"C:\Workspace\FlamMap6\farsite.dll")
    if os.name != "nt" or not dll.is_file():
        pytest.skip("Installed FlamMap Windows DLL is not available")
    world, ref, cfg = example(num_tankers=0)
    world.fire_geometry = box(63, 63, 87, 87)
    source = tmp_path / "synthetic.tif"
    data = np.zeros((5, 5, 5), dtype="int16")
    data[0], data[3] = 100, 1
    with rasterio.open(source, "w", driver="GTiff", height=5, width=5, count=5,
                       dtype="int16", crs=ref["crs"], transform=ref["transform"]) as dst:
        dst.write(data)
    engine = FarsiteEngine(source, ref, NativeSettings(dll_path=dll), tmp_path)
    arrival = engine.forecast(world, ref, cfg, Wind(10, 225), tmp_path / "first")
    assert engine.perimeters[2].area > world.fire_geometry.area
    carried_grid = world.grid.copy()
    carried_grid[(arrival > 0) & (arrival <= 2)] = 1
    after = World(carried_grid, world.delivered_l.copy(), {}, 2)
    engine.advance(world, after, ref, cfg, arrival, 2)
    previous_area = after.fire_geometry.area
    engine.forecast(after, ref, cfg, Wind(10, 225), tmp_path / "second")
    staged = gpd.read_file(tmp_path / "second" / "ignition.shp").geometry.area.sum()
    assert staged == pytest.approx(previous_area)
    assert engine.perimeters[2].area > previous_area
