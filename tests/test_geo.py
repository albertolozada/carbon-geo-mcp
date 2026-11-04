"""Tests with geometries whose answers are known in advance."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box

from carbon_geo_mcp import geo

UTM = "EPSG:32720"
X0, Y0 = 600_000, 7_620_000


def _save(gdf: gpd.GeoDataFrame, path, crs="EPSG:4326"):
    gdf.to_crs(crs).to_file(path, driver="GPKG")
    return str(path)


@pytest.fixture
def squares(tmp_path):
    """Two 1 km x 1 km squares (100 ha each) overlapping by 10 ha, saved in degrees."""
    a = box(X0, Y0, X0 + 1000, Y0 + 1000)
    b = box(X0 + 900, Y0, X0 + 1900, Y0 + 1000)
    gdf = gpd.GeoDataFrame({"stratum": ["A", "B"]}, geometry=[a, b], crs=UTM)
    return _save(gdf, tmp_path / "squares.gpkg")


def test_layer_info_flags_geographic_crs(squares):
    info = geo.layer_info(squares)
    assert info["is_geographic"] is True
    assert info["features"] == 2
    assert any("Geographic CRS" in w for w in info["warnings"])


def test_area_is_measured_in_equal_area_and_dissolved(squares):
    res = geo.area_by_stratum(squares, "stratum")
    areas = {s["stratum"]: s["area_ha"] for s in res["strata"]}
    # UTM area is 100 ha; equal-area differs only by the UTM scale factor (< 0.2 %)
    assert areas["A"] == pytest.approx(100, rel=2e-3)
    assert res["total_area_ha"] == pytest.approx(190, rel=2e-3)
    assert res["overlap_between_strata_ha"] == pytest.approx(10, rel=2e-2)
    assert "laea" in res["crs_used"]


def test_requested_geographic_crs_is_refused(squares):
    with pytest.raises(geo.GeoCheckError, match="geographic"):
        geo.area_by_stratum(squares, crs="EPSG:4326")


def test_declared_area_comparison(squares):
    res = geo.compare_declared_area(squares, {"total": 190, "A": 120, "Z": 5}, "stratum", tolerance_pct=1)
    rows = {r["item"]: r for r in res["comparison"]}
    assert rows["total"]["status"] == "within tolerance"
    assert rows["A"]["status"] == "outside tolerance"
    assert rows["Z"]["status"] == "not found in the layer"


def test_overlap_and_explicit_zero(tmp_path, squares):
    far = gpd.GeoDataFrame({"n": ["far"]}, geometry=[box(X0 + 5000, Y0, X0 + 6000, Y0 + 1000)], crs=UTM)
    near = gpd.GeoDataFrame({"n": ["near"]}, geometry=[box(X0 + 1400, Y0, X0 + 2400, Y0 + 1000)], crs=UTM)
    res0 = geo.check_overlap(squares, _save(far, tmp_path / "far.gpkg"))
    assert res0["overlap"] is False and res0["overlap_ha"] == 0
    res = geo.check_overlap(squares, _save(near, tmp_path / "near.gpkg"), "stratum", "n")
    assert res["overlap_ha"] == pytest.approx(50, rel=2e-3)
    assert res["overlapping_pairs"][0]["id_a"] == "B"


def test_plots_in_strata(tmp_path, squares):
    pts = gpd.GeoDataFrame(
        {
            "pid": ["in_a", "wrong", "out", "edge", "dup"],
            "stratum": ["A", "A", "A", "A", "A"],
        },
        geometry=[
            Point(X0 + 200, Y0 + 500),
            Point(X0 + 1500, Y0 + 500),   # falls in B
            Point(X0 - 250, Y0 + 500),    # 250 m outside
            Point(X0 + 500, Y0 + 10),     # 10 m from the edge
            Point(X0 + 200, Y0 + 500),    # same place as in_a
        ],
        crs=UTM,
    )
    res = geo.plots_in_strata(_save(pts, tmp_path / "plots.gpkg"), squares, "stratum", "stratum", "pid", 30)
    assert res["plots_outside"] == 1
    assert res["outside"][0]["distance_to_strata_m"] == pytest.approx(250, abs=1)
    assert [m["plot"] for m in res["stratum_mismatches"]] == ["wrong"]
    assert [p["plot"] for p in res["plots_near_boundary"]] == ["edge"]
    assert set(res["duplicate_coordinates"]) == {"in_a", "dup"}


def test_forest_loss_projected_raster(tmp_path):
    """10 x 10 pixels of 30 m; 4 pixels lost in year 21 inside the AOI = 0.36 ha."""
    data = np.zeros((10, 10), dtype="uint8")
    data[2:4, 2:4] = 21
    data[8, 8] = 22  # outside the AOI below
    tif = tmp_path / "loss.tif"
    with rasterio.open(tif, "w", driver="GTiff", height=10, width=10, count=1, dtype="uint8",
                       crs=UTM, transform=from_origin(X0, Y0 + 300, 30, 30)) as dst:
        dst.write(data, 1)
    aoi = gpd.GeoDataFrame(geometry=[box(X0, Y0 + 120, X0 + 180, Y0 + 300)], crs=UTM)
    res = geo.forest_loss_in_area(_save(aoi, tmp_path / "aoi.gpkg", UTM), str(tif))
    assert res["loss_by_year"] == [{"year": 2021, "pixels": 4, "loss_ha": 0.36}]
    assert res["raster_coverage_pct"] == pytest.approx(100, abs=0.01)


def test_forest_loss_reports_partial_coverage(tmp_path):
    data = np.zeros((10, 10), dtype="uint8")
    tif = tmp_path / "loss.tif"
    with rasterio.open(tif, "w", driver="GTiff", height=10, width=10, count=1, dtype="uint8",
                       crs=UTM, transform=from_origin(X0, Y0 + 300, 30, 30)) as dst:
        dst.write(data, 1)
    aoi = gpd.GeoDataFrame(geometry=[box(X0 + 150, Y0, X0 + 450, Y0 + 300)], crs=UTM)  # half outside
    res = geo.forest_loss_in_area(_save(aoi, tmp_path / "aoi.gpkg", UTM), str(tif))
    assert res["raster_coverage_pct"] == pytest.approx(50, abs=0.5)
    assert any("covers only" in w for w in res["warnings"])
    assert any("No loss pixels" in w for w in res["warnings"])


def test_geodesic_pixel_area():
    """A 0.00025 degree pixel at the equator is about 27.8 m x 27.6 m."""
    area = geo._pixel_area_m2(from_origin(0, 0.00025, 0.00025, 0.00025), geo.CRS.from_epsg(4326), np.array([0]), 1)
    assert area[0, 0] == pytest.approx(27.83 * 27.64, rel=5e-3)


def test_completeness_counts_blank_text(tmp_path):
    gdf = gpd.GeoDataFrame({"owner": ["x", "", None]}, geometry=[Point(0, 0)] * 3, crs="EPSG:4326")
    res = geo.data_completeness(_save(gdf, tmp_path / "c.gpkg"))
    assert res["fields"][0]["missing"] == 2


def test_missing_file_and_allowed_roots(tmp_path, monkeypatch, squares):
    with pytest.raises(geo.GeoCheckError, match="not found"):
        geo.layer_info(str(tmp_path / "nope.gpkg"))
    monkeypatch.setenv(geo.ROOTS_ENV, str(tmp_path / "other"))
    with pytest.raises(geo.GeoCheckError, match="outside the folders"):
        geo.layer_info(squares)
