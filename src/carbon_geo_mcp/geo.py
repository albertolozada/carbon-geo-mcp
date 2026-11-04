"""Core geospatial checks used by the MCP tools.

Every function here is plain Python (GeoPandas, Shapely, PyProj, Rasterio) so it
can be tested and reused without MCP. The rules behind them:

* Never measure in a geographic CRS. Areas use a local equal-area projection
  (Lambert Azimuthal Equal Area centred on the data) unless the caller passes a
  CRS; distances use the local UTM zone.
* Every result says which CRS was used and how many features were missing,
  empty or invalid.
* Overlapping polygons are dissolved before measuring, so the same ground is
  never counted twice.
* "Nothing found" is reported explicitly, never as silence.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS, Geod
from shapely import make_valid
from shapely.geometry import box

ROOTS_ENV = "CARBON_GEO_MCP_ROOTS"
M2_PER_HA = 10_000
WGS84 = "EPSG:4326"


class GeoCheckError(Exception):
    """An anticipated problem with the input (missing file, no CRS, wrong field...)."""


# --------------------------------------------------------------------------- #
# Paths and reading
# --------------------------------------------------------------------------- #

def allowed_roots() -> list[Path]:
    """Folders the server may read, from CARBON_GEO_MCP_ROOTS (os.pathsep separated)."""
    raw = os.environ.get(ROOTS_ENV, "").strip()
    if not raw:
        return []
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]


def resolve_path(path: str) -> Path:
    """Resolve a user path and enforce the allowed roots, if configured."""
    p = Path(path).expanduser().resolve()
    roots = allowed_roots()
    if roots and not any(p == r or r in p.parents for r in roots):
        raise GeoCheckError(
            f"'{p}' is outside the folders this server may read ({ROOTS_ENV}). "
            "Move the file into an allowed folder or update the configuration."
        )
    if not p.exists():
        raise GeoCheckError(f"File not found: '{p}'.")
    return p


def read_layer(path: str, layer: str | None = None) -> gpd.GeoDataFrame:
    p = resolve_path(path)
    try:
        gdf = gpd.read_file(p, layer=layer) if layer else gpd.read_file(p)
    except Exception as exc:  # noqa: BLE001 - re-raised with a readable message
        raise GeoCheckError(f"Could not read '{p.name}': {exc}") from exc
    if gdf.crs is None:
        raise GeoCheckError(
            f"'{p.name}' has no CRS. Assign the correct CRS in the source file before any measurement."
        )
    return gdf


# --------------------------------------------------------------------------- #
# CRS helpers
# --------------------------------------------------------------------------- #

def crs_summary(crs: CRS) -> dict[str, Any]:
    epsg = crs.to_epsg()
    return {
        "crs": f"EPSG:{epsg}" if epsg else crs.to_string(),
        "name": crs.name,
        "is_geographic": bool(crs.is_geographic),
        "units": crs.axis_info[0].unit_name if crs.axis_info else "unknown",
    }


def equal_area_crs(gdf: gpd.GeoDataFrame) -> CRS:
    """Lambert Azimuthal Equal Area centred on the layer: equal-area anywhere on Earth."""
    minx, miny, maxx, maxy = gdf.to_crs(WGS84).total_bounds
    lon0, lat0 = (minx + maxx) / 2, (miny + maxy) / 2
    return CRS.from_proj4(
        f"+proj=laea +lat_0={lat0:.4f} +lon_0={lon0:.4f} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )


def distance_crs(gdf: gpd.GeoDataFrame) -> CRS:
    """Local UTM zone, suitable for distances at project scale."""
    return CRS.from_user_input(gdf.to_crs(WGS84).estimate_utm_crs())


def target_crs(gdf: gpd.GeoDataFrame, crs: str | None, purpose: str) -> tuple[CRS, str]:
    """Pick the measurement CRS and explain the choice."""
    if crs:
        target = CRS.from_user_input(crs)
        if target.is_geographic:
            raise GeoCheckError(
                f"The requested CRS {crs} is geographic (degrees). Use a projected, metric CRS for {purpose}."
            )
        return target, "requested by the user"
    if purpose == "area":
        return equal_area_crs(gdf), "local Lambert Azimuthal Equal Area centred on the data (equal-area)"
    return distance_crs(gdf), "local UTM zone estimated from the data"


# --------------------------------------------------------------------------- #
# Geometry quality
# --------------------------------------------------------------------------- #

def geometry_quality(gdf: gpd.GeoDataFrame) -> dict[str, int]:
    geom = gdf.geometry
    missing = geom.isna()
    empty = geom.is_empty & ~missing
    present = ~missing & ~empty
    invalid = present & ~geom.is_valid
    return {
        "features": int(len(gdf)),
        "missing_geometries": int(missing.sum()),
        "empty_geometries": int(empty.sum()),
        "invalid_geometries": int(invalid.sum()),
    }


def clean(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    """Drop missing/empty geometries and repair invalid ones. Returns the report."""
    quality = geometry_quality(gdf)
    out = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    bad = ~out.geometry.is_valid
    if bad.any():
        out.loc[bad, out.geometry.name] = make_valid(out.loc[bad].geometry.values)
    quality["repaired_geometries"] = int(bad.sum())
    quality["used_features"] = int(len(out))
    return out, quality


def _ha(value_m2: float) -> float:
    return round(float(value_m2) / M2_PER_HA, 2)


def _require_field(gdf: gpd.GeoDataFrame, field: str, label: str) -> None:
    if field not in gdf.columns:
        fields = ", ".join(c for c in gdf.columns if c != gdf.geometry.name)
        raise GeoCheckError(f"Field '{field}' not found in {label}. Available fields: {fields}.")


# --------------------------------------------------------------------------- #
# 1. Layer information
# --------------------------------------------------------------------------- #

def layer_info(path: str, layer: str | None = None) -> dict[str, Any]:
    gdf = read_layer(path, layer)
    fields = []
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        nulls = int(gdf[col].isna().sum())
        fields.append({"field": col, "dtype": str(gdf[col].dtype), "nulls": nulls})
    bounds_native = [round(float(v), 6) for v in gdf.total_bounds]
    bounds_wgs84 = [round(float(v), 6) for v in gdf.to_crs(WGS84).total_bounds]
    warnings = []
    if gdf.crs.is_geographic:
        warnings.append(
            "Geographic CRS (degrees): areas, distances and buffers must not be computed in this CRS."
        )
    return {
        "file": Path(path).name,
        **crs_summary(gdf.crs),
        **geometry_quality(gdf),
        "geometry_types": sorted(str(t) for t in gdf.geom_type.dropna().unique()),
        "bounds_native": bounds_native,
        "bounds_wgs84": bounds_wgs84,
        "fields": fields[:50],
        "fields_truncated": len(fields) > 50,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# 2. Area by stratum
# --------------------------------------------------------------------------- #

def area_by_stratum(
    path: str,
    stratum_field: str | None = None,
    layer: str | None = None,
    crs: str | None = None,
) -> dict[str, Any]:
    raw = read_layer(path, layer)
    source_crs = crs_summary(raw.crs)["crs"]
    gdf, quality = clean(raw)
    if gdf.empty:
        raise GeoCheckError("The layer has no usable polygons after removing missing and empty geometries.")
    polys = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon", "GeometryCollection"])]
    if polys.empty:
        raise GeoCheckError("The layer has no polygon geometries; area cannot be computed.")
    target, why = target_crs(polys, crs, "area")
    polys = polys.to_crs(target)

    if stratum_field:
        _require_field(polys, stratum_field, "the layer")
        keys = polys[stratum_field].astype("string").fillna("<missing>")
    else:
        keys = pd.Series("all", index=polys.index)

    strata = []
    for key, part in polys.groupby(keys, sort=True):
        dissolved = part.geometry.union_all().area
        summed = part.geometry.area.sum()
        strata.append({
            "stratum": key,
            "features": int(len(part)),
            "area_ha": _ha(dissolved),
            "sum_of_feature_areas_ha": _ha(summed),
            "internal_overlap_ha": _ha(max(summed - dissolved, 0.0)),
        })

    total_union = polys.geometry.union_all().area
    sum_strata = sum(s["area_ha"] for s in strata)
    return {
        "file": Path(path).name,
        "source_crs": source_crs,
        "crs_used": target.to_string(),
        "crs_choice": why,
        "geometry_quality": quality,
        "strata": strata,
        "total_area_ha": _ha(total_union),
        "sum_of_strata_ha": round(sum_strata, 2),
        "overlap_between_strata_ha": round(max(sum_strata - _ha(total_union), 0.0), 2),
        "method": "Polygons are dissolved per stratum before measuring, so overlapping features are not counted twice.",
    }


# --------------------------------------------------------------------------- #
# 3. Declared vs calculated area
# --------------------------------------------------------------------------- #

def compare_declared_area(
    path: str,
    declared_ha: dict[str, float],
    stratum_field: str | None = None,
    tolerance_pct: float = 1.0,
    layer: str | None = None,
    crs: str | None = None,
) -> dict[str, Any]:
    if not declared_ha:
        raise GeoCheckError("Give at least one declared area, e.g. {'total': 12500} or one value per stratum.")
    calc = area_by_stratum(path, stratum_field, layer, crs)
    calculated = {s["stratum"]: s["area_ha"] for s in calc["strata"]}
    calculated["total"] = calc["total_area_ha"]

    rows = []
    for key, declared in declared_ha.items():
        if key not in calculated:
            rows.append({"item": key, "declared_ha": declared, "calculated_ha": None,
                         "status": "not found in the layer",
                         "available": sorted(calculated)})
            continue
        value = calculated[key]
        diff = value - declared
        pct = (diff / declared * 100) if declared else None
        ok = pct is not None and abs(pct) <= tolerance_pct
        rows.append({
            "item": key,
            "declared_ha": declared,
            "calculated_ha": value,
            "difference_ha": round(diff, 2),
            "difference_pct": round(pct, 3) if pct is not None else None,
            "status": "within tolerance" if ok else "outside tolerance",
        })
    return {
        "file": calc["file"],
        "crs_used": calc["crs_used"],
        "crs_choice": calc["crs_choice"],
        "tolerance_pct": tolerance_pct,
        "comparison": rows,
        "geometry_quality": calc["geometry_quality"],
        "overlap_between_strata_ha": calc["overlap_between_strata_ha"],
    }


# --------------------------------------------------------------------------- #
# 4. Overlap between two layers
# --------------------------------------------------------------------------- #

def check_overlap(
    path_a: str,
    path_b: str,
    id_field_a: str | None = None,
    id_field_b: str | None = None,
    layer_a: str | None = None,
    layer_b: str | None = None,
    crs: str | None = None,
    max_pairs: int = 20,
) -> dict[str, Any]:
    a, qa = clean(read_layer(path_a, layer_a))
    b, qb = clean(read_layer(path_b, layer_b))
    if a.empty or b.empty:
        raise GeoCheckError("One of the layers has no usable geometries.")
    target, why = target_crs(a, crs, "area")
    a, b = a.to_crs(target), b.to_crs(target)
    for gdf, field, label in ((a, id_field_a, "layer A"), (b, id_field_b, "layer B")):
        if field:
            _require_field(gdf, field, label)
    a["_id"] = a[id_field_a].astype(str) if id_field_a else a.index.astype(str)
    b["_id"] = b[id_field_b].astype(str) if id_field_b else b.index.astype(str)

    union_a, union_b = a.geometry.union_all(), b.geometry.union_all()
    inter = union_a.intersection(union_b)
    area_a, area_b, area_i = union_a.area, union_b.area, inter.area

    pairs = []
    if area_i > 0:
        joined = gpd.overlay(a[["_id", "geometry"]], b[["_id", "geometry"]], how="intersection", keep_geom_type=True)
        joined["area_m2"] = joined.geometry.area
        joined = joined[joined["area_m2"] > 0].sort_values("area_m2", ascending=False)
        for _, r in joined.head(max_pairs).iterrows():
            pairs.append({"id_a": r["_id_1"], "id_b": r["_id_2"], "overlap_ha": _ha(r["area_m2"])})

    return {
        "layer_a": Path(path_a).name,
        "layer_b": Path(path_b).name,
        "crs_used": target.to_string(),
        "crs_choice": why,
        "overlap": area_i > 0,
        "overlap_ha": _ha(area_i),
        "area_a_ha": _ha(area_a),
        "area_b_ha": _ha(area_b),
        "overlap_pct_of_a": round(area_i / area_a * 100, 3) if area_a else None,
        "overlap_pct_of_b": round(area_i / area_b * 100, 3) if area_b else None,
        "overlapping_pairs": pairs,
        "pairs_truncated": len(pairs) == max_pairs,
        "message": "The layers overlap." if area_i > 0 else "No overlap found: the intersection area is 0 ha.",
        "geometry_quality": {"a": qa, "b": qb},
    }


# --------------------------------------------------------------------------- #
# 5. Monitoring plots vs strata
# --------------------------------------------------------------------------- #

def plots_in_strata(
    plots_path: str,
    strata_path: str,
    stratum_field: str,
    plot_stratum_field: str | None = None,
    plot_id_field: str | None = None,
    edge_distance_m: float = 0.0,
    plots_layer: str | None = None,
    strata_layer: str | None = None,
    crs: str | None = None,
    max_listed: int = 50,
) -> dict[str, Any]:
    plots, qp = clean(read_layer(plots_path, plots_layer))
    strata, qs = clean(read_layer(strata_path, strata_layer))
    _require_field(strata, stratum_field, "the strata layer")
    if plot_stratum_field:
        _require_field(plots, plot_stratum_field, "the plots layer")
    if plot_id_field:
        _require_field(plots, plot_id_field, "the plots layer")
    if not plots.geom_type.isin(["Point"]).all():
        raise GeoCheckError("The plots layer must contain single points (plot centres).")

    target, why = target_crs(strata, crs, "distance")
    plots, strata = plots.to_crs(target), strata.to_crs(target)
    plots["_pid"] = plots[plot_id_field].astype(str) if plot_id_field else plots.index.astype(str)

    zones = strata[[stratum_field, "geometry"]].rename(columns={stratum_field: "_stratum"})
    joined = gpd.sjoin(plots[["_pid", "geometry"]], zones, how="left", predicate="within")
    # A plot on overlapping strata can match twice: keep every match to report it
    matches = joined.groupby("_pid")["_stratum"].apply(lambda s: sorted(set(s.dropna().astype(str))))

    boundary = strata.geometry.union_all().boundary
    outside, mismatched, ambiguous, near_edge = [], [], [], []
    per_stratum: dict[str, int] = {}
    for _, row in plots.iterrows():
        pid = row["_pid"]
        found = matches.get(pid, [])
        dist_edge = float(row.geometry.distance(boundary))
        if not found:
            outside.append({"plot": pid, "distance_to_strata_m": round(float(strata.distance(row.geometry).min()), 1)})
            continue
        if len(found) > 1:
            ambiguous.append({"plot": pid, "strata": found})
        for s in found:
            per_stratum[s] = per_stratum.get(s, 0) + 1
        if plot_stratum_field:
            declared = row[plot_stratum_field]
            declared = None if pd.isna(declared) else str(declared)
            if declared not in found:
                mismatched.append({"plot": pid, "declared_stratum": declared, "spatial_stratum": found})
        if edge_distance_m and dist_edge < edge_distance_m:
            near_edge.append({"plot": pid, "distance_to_boundary_m": round(dist_edge, 1)})

    coords = plots.geometry.apply(lambda g: (round(g.x, 1), round(g.y, 1)))
    duplicates = plots.loc[coords.duplicated(keep=False), "_pid"].tolist()

    return {
        "plots_file": Path(plots_path).name,
        "strata_file": Path(strata_path).name,
        "crs_used": target.to_string(),
        "crs_choice": why,
        "plots_total": int(len(plots)),
        "plots_inside": int(len(plots) - len(outside)),
        "plots_outside": len(outside),
        "plots_per_stratum": dict(sorted(per_stratum.items())),
        "outside": outside[:max_listed],
        "stratum_mismatches": mismatched[:max_listed] if plot_stratum_field else "not checked (no plot_stratum_field given)",
        "plots_on_overlapping_strata": ambiguous[:max_listed],
        "plots_near_boundary": near_edge[:max_listed] if edge_distance_m else "not checked (edge_distance_m = 0)",
        "duplicate_coordinates": duplicates[:max_listed],
        "geometry_quality": {"plots": qp, "strata": qs},
    }


# --------------------------------------------------------------------------- #
# 6. Forest loss inside an area (Hansen-style "lossyear" raster)
# --------------------------------------------------------------------------- #

def _pixel_area_m2(transform, crs: CRS, rows: np.ndarray, width: int) -> np.ndarray:
    """Area of every pixel. Geodesic per row for geographic rasters, constant otherwise."""
    if not crs.is_geographic:
        return np.full((len(rows), width), abs(transform.a * transform.e))
    geod = Geod(ellps="WGS84")
    dx, dy = transform.a, transform.e
    areas = np.empty(len(rows))
    for i, r in enumerate(rows):
        top = transform.f + r * dy
        bottom = top + dy
        lons = [0.0, dx, dx, 0.0]
        lats = [top, top, bottom, bottom]
        areas[i] = abs(geod.polygon_area_perimeter(lons, lats)[0])
    return np.repeat(areas[:, None], width, axis=1)


def forest_loss_in_area(
    aoi_path: str,
    lossyear_raster: str,
    aoi_layer: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    base_year: int = 2000,
) -> dict[str, Any]:
    import rasterio
    from rasterio.mask import mask

    aoi, quality = clean(read_layer(aoi_path, aoi_layer))
    if aoi.empty:
        raise GeoCheckError("The area of interest has no usable polygons.")
    rpath = resolve_path(lossyear_raster)
    with rasterio.open(rpath) as src:
        if src.crs is None:
            raise GeoCheckError(f"'{rpath.name}' has no CRS.")
        rcrs = CRS.from_user_input(src.crs)
        aoi_r = aoi.to_crs(rcrs)
        aoi_geom = aoi_r.geometry.union_all()
        raster_extent = box(*src.bounds)
        covered = aoi_geom.intersection(raster_extent)
        if covered.is_empty:
            raise GeoCheckError("The raster does not cover the area of interest at all. Check the tile and the CRS.")
        data, out_transform = mask(src, [covered], crop=True, filled=False)
        band = data[0]
        res = (abs(src.transform.a), abs(src.transform.e))
        nodata = src.nodata

    rows = np.arange(band.shape[0])
    areas = _pixel_area_m2(out_transform, rcrs, rows, band.shape[1])
    valid = ~np.ma.getmaskarray(band)
    values = np.ma.getdata(band)

    # Coverage: share of the AOI inside the raster extent (equal-area measurement)
    ea = equal_area_crs(aoi)
    aoi_area = gpd.GeoSeries([aoi_geom], crs=rcrs).to_crs(ea).area.iloc[0]
    covered_area = gpd.GeoSeries([covered], crs=rcrs).to_crs(ea).area.iloc[0]
    coverage_pct = covered_area / aoi_area * 100 if aoi_area else 0.0

    codes = np.unique(values[valid & (values > 0)])
    per_year = []
    for code in codes:
        year = base_year + int(code)
        if start_year and year < start_year:
            continue
        if end_year and year > end_year:
            continue
        sel = valid & (values == code)
        per_year.append({"year": year, "pixels": int(sel.sum()), "loss_ha": _ha(areas[sel].sum())})
    total_loss = round(sum(r["loss_ha"] for r in per_year), 2)
    period = f"{start_year or 'first'}-{end_year or 'last'}"

    warnings = []
    if coverage_pct < 99.9:
        warnings.append(f"The raster covers only {coverage_pct:.1f}% of the area of interest; loss outside it is not counted.")
    if not per_year:
        warnings.append("No loss pixels were found in the area and period requested (result is 0 ha, not missing data).")

    return {
        "aoi_file": Path(aoi_path).name,
        "raster_file": rpath.name,
        "raster_crs": crs_summary(rcrs)["crs"],
        "raster_resolution": [round(r, 8) for r in res],
        "raster_nodata": nodata,
        "pixel_area_method": "geodesic area per row (WGS84 ellipsoid)" if rcrs.is_geographic else "constant pixel area of the projected raster",
        "pixel_selection": "pixels whose centre falls inside the area of interest",
        "aoi_area_ha": _ha(aoi_area),
        "raster_coverage_pct": round(coverage_pct, 2),
        "period": period,
        "base_year": base_year,
        "loss_by_year": per_year,
        "total_loss_ha": total_loss,
        "loss_pct_of_aoi": round(total_loss / _ha(aoi_area) * 100, 3) if aoi_area else None,
        "geometry_quality": quality,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# 7. Attribute completeness
# --------------------------------------------------------------------------- #

def data_completeness(path: str, fields: list[str] | None = None, layer: str | None = None) -> dict[str, Any]:
    gdf = read_layer(path, layer)
    cols = fields or [c for c in gdf.columns if c != gdf.geometry.name]
    for c in cols:
        _require_field(gdf, c, "the layer")
    n = len(gdf)
    report = []
    for c in cols:
        s = gdf[c]
        missing = s.isna()
        if s.dtype == object or pd.api.types.is_string_dtype(s.dtype):
            blank = (s.astype("string").str.strip() == "").fillna(False).astype(bool)
            missing = missing | blank
        filled = n - int(missing.sum())
        report.append({
            "field": c,
            "filled": filled,
            "missing": int(missing.sum()),
            "filled_pct": round(filled / n * 100, 2) if n else None,
            "distinct_values": int(s.nunique(dropna=True)),
        })
    return {
        "file": Path(path).name,
        **crs_summary(gdf.crs),
        **geometry_quality(gdf),
        "fields": report,
        "fully_complete_fields": [r["field"] for r in report if r["missing"] == 0],
    }
