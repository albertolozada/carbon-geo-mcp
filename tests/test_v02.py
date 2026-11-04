"""Tests for the v0.2 tools: plan_crs, create_map and check_raster_availability."""

from __future__ import annotations

import os
from pathlib import Path

import anyio
import geopandas as gpd
import pytest
from mcp import Client
from shapely.geometry import box, mapping

from carbon_geo_mcp import geo, maps, stac
from carbon_geo_mcp.server import mcp

UTM = "EPSG:32720"
X0, Y0 = 600_000, 7_620_000
SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


def _save(gdf, path, crs="EPSG:4326"):
    gdf.to_crs(crs).to_file(path, driver="GPKG")
    return str(path)


@pytest.fixture
def square(tmp_path):
    gdf = gpd.GeoDataFrame({"stratum": ["A"]}, geometry=[box(X0, Y0, X0 + 1000, Y0 + 1000)], crs=UTM)
    return _save(gdf, tmp_path / "square.gpkg")


# ---------------------------------------------------------------- plan_crs

def test_plan_crs_proposes_equal_area_and_utm(square):
    res = geo.plan_crs([square])
    assert res["layers"][0]["utm_zones"] == [20]
    assert "laea" in res["proposal"]["areas"]["crs"]
    assert res["proposal"]["distances"]["crs"] == "EPSG:32720"
    # About 1 degree east of the central meridian at 21.5 S: UTM shrinks areas by about 0.05 %
    assert res["proposal"]["utm_area_distortion_at_edge_pct"] == pytest.approx(-0.05, abs=0.02)


def test_plan_crs_detects_projected_values_labelled_as_degrees(tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[box(X0, Y0, X0 + 1000, Y0 + 1000)], crs=UTM)
    bad = gdf.set_crs("EPSG:4326", allow_override=True)
    bad.to_file(tmp_path / "bad.gpkg", driver="GPKG")
    res = geo.plan_crs([str(tmp_path / "bad.gpkg")])
    assert res["layers"][0]["coordinate_problems"]
    assert res["proposal"] is None


def test_plan_crs_flags_mixed_crs_and_zones(tmp_path, square):
    far = gpd.GeoDataFrame(geometry=[box(-57.5, -21.6, -57.4, -21.5)], crs="EPSG:4326")  # UTM zone 21
    res = geo.plan_crs([square, _save(far, tmp_path / "far.gpkg", "EPSG:32721")])
    text = " ".join(res["warnings"])
    assert "different CRS" in text
    assert "UTM zones" in text


# ---------------------------------------------------------------- create_map

def test_create_map_returns_png(square):
    png, summary = maps.create_map([{"path": square, "category_field": "stratum"}], "Test")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert summary["crs_used"] == "EPSG:32720"


def test_create_map_through_mcp_returns_image_and_text(square):
    async def go():
        async with Client(mcp) as client:
            return await client.call_tool("create_map", {"layers": [{"path": square, "label": "square"}]})

    res = anyio.run(go)
    assert not res.is_error
    assert [c.type for c in res.content] == ["image", "text"]


def test_create_map_rejects_unknown_field(square):
    with pytest.raises(geo.GeoCheckError, match="not found"):
        maps.create_map([{"path": square, "category_field": "nope"}])


# ---------------------------------------------------------------- STAC summary (offline)

def _item(i, date, geom, cloud):
    return {"id": f"S2_{i}", "geometry": mapping(geom), "properties": {"datetime": f"{date}T14:00:00Z", "eo:cloud_cover": cloud}}


def test_summarize_items_coverage_and_cloud():
    aoi = gpd.GeoDataFrame(geometry=[box(-62.0, -21.5, -61.9, -21.4)], crs="EPSG:4326")
    west, east = box(-62.1, -21.6, -61.95, -21.3), box(-61.95, -21.6, -61.8, -21.3)
    full = box(-62.1, -21.6, -61.8, -21.3)
    items = [
        _item(1, "2024-01-05", west, 5), _item(2, "2024-01-05", east, 10),  # two tiles, full coverage
        _item(3, "2024-01-10", west, 2),                                       # half coverage
        _item(4, "2024-02-14", full, 60),                                      # cloudy
    ]
    res = stac.summarize_items(aoi, items, max_cloud_pct=20)
    by_date = {d["date"]: d for d in res["dates"]}
    assert by_date["2024-01-05"]["aoi_coverage_pct"] == pytest.approx(100, abs=0.1)
    assert by_date["2024-01-10"]["aoi_coverage_pct"] == pytest.approx(50, abs=1)
    assert res["usable_dates"] == ["2024-01-05"]
    assert res["dates_per_month"] == {"2024-01": 2, "2024-02": 1}
    assert res["best_dates"][0]["date"] == "2024-01-05"


def test_summarize_items_empty():
    aoi = gpd.GeoDataFrame(geometry=[box(-62.0, -21.5, -61.9, -21.4)], crs="EPSG:4326")
    res = stac.summarize_items(aoi, [], max_cloud_pct=20)
    assert res["scenes_found"] == 0 and res["usable_dates"] == []


# ---------------------------------------------------------------- STAC live (CI only)

@pytest.mark.skipif(os.environ.get("CARBON_GEO_MCP_NETWORK_TESTS") != "1", reason="network tests disabled")
def test_live_earth_search():
    res = stac.check_raster_availability(
        str(SAMPLE / "project_strata.gpkg"), "2024-01-01", "2024-03-31", max_cloud_pct=30
    )
    assert res["scenes_found"] > 0
    assert res["sent_to_catalog"]["bbox_wgs84"][0] < -61.9
