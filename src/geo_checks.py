"""Reusable checks for geospatial analysis.

Rule: never compute areas, distances or buffers in a geographic CRS (degrees).
"""

from __future__ import annotations

import geopandas as gpd


def check_crs(gdf: gpd.GeoDataFrame, name: str = "layer") -> dict:
    """Describe the CRS of a layer and flag problems before any measurement."""
    if gdf.crs is None:
        raise ValueError(f"{name}: the layer has no CRS. Assign the correct one before continuing.")
    crs = gdf.crs
    return {
        "layer": name,
        "crs": crs.to_string(),
        "is_geographic": crs.is_geographic,
        "units": crs.axis_info[0].unit_name if crs.axis_info else "unknown",
        "features": len(gdf),
        "empty_geometries": int(gdf.geometry.is_empty.sum()),
        "missing_geometries": int(gdf.geometry.isna().sum()),
        "invalid_geometries": int((~gdf.geometry.is_valid).sum()),
    }


def to_metric(gdf: gpd.GeoDataFrame, crs: str | int | None = None) -> gpd.GeoDataFrame:
    """Reproject to a metric CRS.

    If no CRS is given, the local UTM zone is estimated. For study areas that
    cross several UTM zones, pass an equal-area CRS explicitly (for example a
    national equal-area projection, or EPSG:6933 for global work).
    """
    if gdf.crs is None:
        raise ValueError("The layer has no CRS.")
    target = crs if crs is not None else gdf.estimate_utm_crs()
    return gdf.to_crs(target)


def area_ha(gdf: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Area in hectares. Refuses to work in a geographic CRS."""
    if gdf.crs is None or gdf.crs.is_geographic:
        raise ValueError("Area requested in a geographic CRS. Reproject with to_metric() first.")
    return gdf.geometry.area / 10_000
