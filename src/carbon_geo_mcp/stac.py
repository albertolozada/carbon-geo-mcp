"""Check satellite imagery availability over an area before downloading anything.

Only the bounding box of the area (in WGS84) and the dates are sent to the STAC
catalog. Coverage of the real geometry is computed locally.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import shape

from .geo import WGS84, GeoCheckError, _ha, clean, equal_area_crs, read_layer

DEFAULT_STAC = "https://earth-search.aws.element84.com/v1"


def summarize_items(
    aoi_wgs84: gpd.GeoDataFrame,
    features: list[dict[str, Any]],
    max_cloud_pct: float | None = None,
    cloud_property: str = "eo:cloud_cover",
    full_coverage_pct: float = 99.0,
) -> dict[str, Any]:
    """Summarise STAC items (GeoJSON features) against an area of interest."""
    ea = equal_area_crs(aoi_wgs84)
    aoi = aoi_wgs84.to_crs(ea).geometry.union_all()
    aoi_area = aoi.area

    by_date: dict[str, dict[str, Any]] = {}
    clouds = []
    for f in features:
        props = f.get("properties", {})
        date = str(props.get("datetime", ""))[:10]
        cloud = props.get(cloud_property)
        if cloud is not None:
            clouds.append(float(cloud))
        d = by_date.setdefault(date, {"geoms": [], "clouds": [], "ids": []})
        d["geoms"].append(shape(f["geometry"]))
        d["clouds"].append(None if cloud is None else float(cloud))
        d["ids"].append(f.get("id"))

    dates = []
    for date, d in sorted(by_date.items()):
        footprint = gpd.GeoSeries(d["geoms"], crs=WGS84).to_crs(ea).union_all()
        cov = footprint.intersection(aoi).area / aoi_area * 100 if aoi_area else 0.0
        known = [c for c in d["clouds"] if c is not None]
        worst = max(known) if known else None
        dates.append({
            "date": date,
            "scenes": len(d["ids"]),
            "aoi_coverage_pct": round(cov, 1),
            "max_scene_cloud_pct": None if worst is None else round(worst, 1),
            "scene_ids": d["ids"],
        })

    def usable(row: dict[str, Any]) -> bool:
        if row["aoi_coverage_pct"] < full_coverage_pct:
            return False
        if max_cloud_pct is None:
            return True
        return row["max_scene_cloud_pct"] is not None and row["max_scene_cloud_pct"] <= max_cloud_pct

    good = [r for r in dates if usable(r)]
    months = Counter(r["date"][:7] for r in dates)
    best = sorted(
        (r for r in dates if r["aoi_coverage_pct"] >= full_coverage_pct and r["max_scene_cloud_pct"] is not None),
        key=lambda r: r["max_scene_cloud_pct"],
    )[:10]
    return {
        "aoi_area_ha": _ha(aoi_area),
        "scenes_found": len(features),
        "acquisition_dates": len(dates),
        "dates_per_month": dict(sorted(months.items())),
        "scene_cloud_pct": {
            "min": round(min(clouds), 1) if clouds else None,
            "median": round(sorted(clouds)[len(clouds) // 2], 1) if clouds else None,
            "max": round(max(clouds), 1) if clouds else None,
        },
        "full_coverage_threshold_pct": full_coverage_pct,
        "max_cloud_pct": max_cloud_pct,
        "usable_dates": [r["date"] for r in good],
        "usable_dates_count": len(good),
        "best_dates": [{k: r[k] for k in ("date", "aoi_coverage_pct", "max_scene_cloud_pct", "scenes")} for r in best],
        "dates": [{k: r[k] for k in ("date", "scenes", "aoi_coverage_pct", "max_scene_cloud_pct")} for r in dates[:200]],
        "dates_truncated": len(dates) > 200,
    }


def check_raster_availability(
    aoi_path: str,
    start_date: str,
    end_date: str,
    collection: str = "sentinel-2-l2a",
    max_cloud_pct: float | None = 20.0,
    stac_url: str = DEFAULT_STAC,
    aoi_layer: str | None = None,
    max_items: int = 500,
) -> dict[str, Any]:
    try:
        from pystac_client import Client
    except ImportError as exc:  # pragma: no cover
        raise GeoCheckError("pystac-client is not installed.") from exc

    aoi, quality = clean(read_layer(aoi_path, aoi_layer))
    if aoi.empty:
        raise GeoCheckError("The area of interest has no usable polygons.")
    aoi_wgs = aoi.to_crs(WGS84)
    bbox = [round(float(v), 6) for v in aoi_wgs.total_bounds]
    try:
        catalog = Client.open(stac_url)
        search = catalog.search(collections=[collection], bbox=bbox, datetime=f"{start_date}/{end_date}", max_items=max_items)
        features = [item.to_dict() for item in search.items()]
    except Exception as exc:  # noqa: BLE001
        raise GeoCheckError(f"The STAC search failed ({stac_url}, collection '{collection}'): {exc}") from exc

    summary = summarize_items(aoi_wgs, features, max_cloud_pct)
    warnings = []
    if not features:
        warnings.append("No scenes found for this area, collection and period (0 scenes, not an error).")
    if len(features) >= max_items:
        warnings.append(f"The search stopped at max_items={max_items}; there may be more scenes.")
    return {
        "aoi_file": Path(aoi_path).name,
        "stac_url": stac_url,
        "collection": collection,
        "period": f"{start_date}/{end_date}",
        "sent_to_catalog": {"bbox_wgs84": bbox, "datetime": f"{start_date}/{end_date}"},
        **summary,
        "cloud_note": "Cloud cover is the scene-level value reported by the catalog, not cloud cover over the area itself.",
        "geometry_quality": quality,
        "warnings": warnings,
    }
