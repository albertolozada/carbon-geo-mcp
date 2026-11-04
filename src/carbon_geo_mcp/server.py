"""carbon-geo-mcp: an MCP server with audit-oriented GIS checks for carbon projects.

Runs over stdio only and every tool is read-only: it reads local files and
returns short JSON summaries. Nothing is written, uploaded or sent anywhere.

Never use print() here: stdout is the MCP protocol channel. Use logging.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.types import Image
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import __version__, geo, maps, stac

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("carbon-geo-mcp")

INSTRUCTIONS = """\
Audit-oriented GIS checks for carbon projects (REDD+, ARR, IFM...).
Rules for using these tools:
1. Start with plan_crs on all the layers of the task. Read its coordinate problems,
   warnings and checks, and state which CRS will be used for areas and distances
   and why, before calling any measuring tool.
2. Use layer_info to see geometry problems and fields of each layer.
3. Never compute areas or distances yourself from coordinates: use the tools. They
   reproject to an equal-area or metric CRS and report which one they used.
4. In every answer, state the CRS used and how many features were missing, empty,
   invalid or repaired, as returned by the tool.
5. A result of 0 (no overlap, no loss, no plots outside) is a real result. If a tool
   returns an error, report it; do not replace it with an estimate.
6. Use create_map to show the layers behind a finding. Use check_raster_availability
   before planning any image download; it only sends the bounding box and dates to
   the catalog.
"""

mcp = MCPServer(name="carbon-geo-mcp", version=__version__, instructions=INSTRUCTIONS)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
READ_ONLY_NETWORK = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)


class MapLayer(BaseModel):
    """One layer to draw on a check map."""

    path: str = Field(description="Path to a vector file.")
    layer: str | None = Field(default=None, description="Layer name inside a multi-layer file.")
    label: str | None = Field(default=None, description="Legend label (defaults to the file name).")
    category_field: str | None = Field(default=None, description="Attribute used to colour features by category.")


def _run(fn: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    try:
        return fn(**kwargs)
    except geo.GeoCheckError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
def layer_info(path: str, layer: str | None = None) -> dict[str, Any]:
    """Describe a vector layer before any analysis: CRS (and whether it is in degrees),
    feature count, missing/empty/invalid geometries, geometry types, bounds and fields
    with their null counts. Call this first on every layer.

    Args:
        path: Path to a vector file (GeoPackage, Shapefile, GeoJSON, KML, FlatGeobuf...).
        layer: Layer name inside a multi-layer file such as a GeoPackage (optional).
    """
    return _run(geo.layer_info, path=path, layer=layer)


@mcp.tool(annotations=READ_ONLY)
def area_by_stratum(
    path: str,
    stratum_field: str | None = None,
    layer: str | None = None,
    crs: str | None = None,
) -> dict[str, Any]:
    """Area in hectares of a polygon layer, in total and per stratum, measured in an
    equal-area CRS. Overlapping polygons are dissolved so ground is never counted twice,
    and the overlap inside each stratum and between strata is reported.

    Args:
        path: Polygon layer (project area, strata, eligible area...).
        stratum_field: Attribute holding the stratum or class (optional).
        layer: Layer name inside a multi-layer file (optional).
        crs: Projected CRS to measure in, e.g. "EPSG:32720". If omitted, a local
            Lambert Azimuthal Equal Area projection centred on the data is used.
    """
    return _run(geo.area_by_stratum, path=path, stratum_field=stratum_field, layer=layer, crs=crs)


@mcp.tool(annotations=READ_ONLY)
def compare_declared_area(
    path: str,
    declared_ha: dict[str, float],
    stratum_field: str | None = None,
    tolerance_pct: float = 1.0,
    layer: str | None = None,
    crs: str | None = None,
) -> dict[str, Any]:
    """Compare areas declared in a project document (PD, monitoring report) with the
    areas calculated from the layer, and flag differences above a tolerance.

    Args:
        path: Polygon layer with the project area or strata.
        declared_ha: Declared hectares, keyed by stratum value and/or "total",
            e.g. {"total": 8000, "dense_forest": 5200}.
        stratum_field: Attribute holding the stratum (needed for per-stratum keys).
        tolerance_pct: Accepted absolute difference in percent (default 1.0).
        layer: Layer name inside a multi-layer file (optional).
        crs: Projected CRS to measure in (optional, equal-area by default).
    """
    return _run(
        geo.compare_declared_area, path=path, declared_ha=declared_ha, stratum_field=stratum_field,
        tolerance_pct=tolerance_pct, layer=layer, crs=crs,
    )


@mcp.tool(annotations=READ_ONLY)
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
    """Overlap between two polygon layers (e.g. project area vs. protected areas, other
    registered projects, leakage belt or reference region): hectares, percentage of
    each layer and the largest overlapping feature pairs. Reports 0 ha explicitly.

    Args:
        path_a: First polygon layer (usually the project area).
        path_b: Second polygon layer.
        id_field_a: Attribute used to name features of layer A (optional).
        id_field_b: Attribute used to name features of layer B (optional).
        layer_a: Layer name inside a multi-layer file A (optional).
        layer_b: Layer name inside a multi-layer file B (optional).
        crs: Projected CRS to measure in (optional, equal-area by default).
        max_pairs: Maximum number of overlapping pairs to list (default 20).
    """
    return _run(
        geo.check_overlap, path_a=path_a, path_b=path_b, id_field_a=id_field_a, id_field_b=id_field_b,
        layer_a=layer_a, layer_b=layer_b, crs=crs, max_pairs=max_pairs,
    )


@mcp.tool(annotations=READ_ONLY)
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
) -> dict[str, Any]:
    """Check monitoring or inventory plots against the strata: plots outside every
    stratum (with distance), plots whose declared stratum differs from the stratum they
    fall in, plots on overlapping strata, plots close to the boundary and duplicated
    coordinates. Distances are measured in the local UTM zone unless a CRS is given.

    Args:
        plots_path: Point layer with plot centres.
        strata_path: Polygon layer with the strata.
        stratum_field: Stratum attribute in the strata layer.
        plot_stratum_field: Stratum declared for each plot in the plots layer (optional).
        plot_id_field: Plot identifier attribute (optional).
        edge_distance_m: Flag plots closer than this to the strata boundary (0 = off).
        plots_layer: Layer name inside the plots file (optional).
        strata_layer: Layer name inside the strata file (optional).
        crs: Projected CRS for distances (optional).
    """
    return _run(
        geo.plots_in_strata, plots_path=plots_path, strata_path=strata_path, stratum_field=stratum_field,
        plot_stratum_field=plot_stratum_field, plot_id_field=plot_id_field, edge_distance_m=edge_distance_m,
        plots_layer=plots_layer, strata_layer=strata_layer, crs=crs,
    )


@mcp.tool(annotations=READ_ONLY)
def forest_loss_in_area(
    aoi_path: str,
    lossyear_raster: str,
    aoi_layer: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    base_year: int = 2000,
) -> dict[str, Any]:
    """Forest loss per year inside an area of interest from a local "lossyear" raster
    (e.g. a Hansen Global Forest Change tile, where 1 = 2001 ... 24 = 2024). Pixel areas
    are geodesic for rasters in degrees. Also reports how much of the area the raster
    actually covers, so a partial tile is never read as "no loss".

    Args:
        aoi_path: Polygon layer with the area of interest (project area, leakage belt...).
        lossyear_raster: Path to the GeoTIFF with loss years.
        aoi_layer: Layer name inside a multi-layer AOI file (optional).
        start_year: First year to include, e.g. 2015 (optional).
        end_year: Last year to include, e.g. 2024 (optional).
        base_year: Year added to the raster value (2000 for Hansen GFC).
    """
    return _run(
        geo.forest_loss_in_area, aoi_path=aoi_path, lossyear_raster=lossyear_raster, aoi_layer=aoi_layer,
        start_year=start_year, end_year=end_year, base_year=base_year,
    )


@mcp.tool(annotations=READ_ONLY)
def data_completeness(path: str, fields: list[str] | None = None, layer: str | None = None) -> dict[str, Any]:
    """Completeness of the attributes of a layer: filled and missing values per field
    (blank text counts as missing) and number of distinct values.

    Args:
        path: Vector layer to inspect.
        fields: Fields to check (optional, all fields by default).
        layer: Layer name inside a multi-layer file (optional).
    """
    return _run(geo.data_completeness, path=path, fields=fields, layer=layer)


@mcp.tool(annotations=READ_ONLY)
def plan_crs(paths: list[str], layers: list[str | None] | None = None) -> dict[str, Any]:
    """Reflect on the coordinate systems BEFORE measuring. For each layer: CRS, datum,
    UTM zones and suspicious coordinates (e.g. UTM values labelled as degrees). For the
    set: proposed CRS for areas (equal-area) and distances (UTM) with the reason, the UTM
    area distortion at the edge of the data, datum or CRS mismatches, and the questions
    to answer before measuring. Call this first.

    Args:
        paths: Paths of all the layers involved in the task.
        layers: Layer names inside multi-layer files, in the same order (optional).
    """
    return _run(geo.plan_crs, paths=paths, layers=layers)


@mcp.tool(annotations=READ_ONLY_NETWORK)
def check_raster_availability(
    aoi_path: str,
    start_date: str,
    end_date: str,
    collection: str = "sentinel-2-l2a",
    max_cloud_pct: float | None = 20.0,
    stac_url: str = stac.DEFAULT_STAC,
    aoi_layer: str | None = None,
) -> dict[str, Any]:
    """Check which satellite images exist over an area and period BEFORE downloading
    anything: scenes per month, cloud cover, and for each date how much of the area the
    scenes cover. Lists the dates with full coverage and acceptable cloud. Queries a STAC
    catalog (default: Earth Search, Sentinel-2 L2A) sending only the bounding box and dates.

    Args:
        aoi_path: Polygon layer with the area of interest.
        start_date: First date, YYYY-MM-DD.
        end_date: Last date, YYYY-MM-DD.
        collection: STAC collection, e.g. "sentinel-2-l2a" or "landsat-c2-l2".
        max_cloud_pct: Maximum scene cloud cover for a date to count as usable (None = ignore).
        stac_url: STAC API endpoint.
        aoi_layer: Layer name inside a multi-layer AOI file (optional).
    """
    return _run(
        stac.check_raster_availability, aoi_path=aoi_path, start_date=start_date, end_date=end_date,
        collection=collection, max_cloud_pct=max_cloud_pct, stac_url=stac_url, aoi_layer=aoi_layer,
    )


@mcp.tool(annotations=READ_ONLY, structured_output=False)
def create_map(layers: list[MapLayer], title: str | None = None) -> list[Any]:
    """Draw a quick check map of up to 6 layers (polygons, lines or points), optionally
    coloured by a category field, in the local UTM zone with a scale bar. Returns the
    image so the findings can be shown, plus a short summary. Nothing is saved to disk.

    Args:
        layers: Layers to draw, bottom to top.
        title: Map title (optional).
    """
    try:
        png, summary = maps.create_map([layer.model_dump() for layer in layers], title)
    except geo.GeoCheckError as exc:
        raise ToolError(str(exc)) from exc
    return [Image(data=png, format="png"), summary]


def main() -> None:
    roots = geo.allowed_roots()
    if roots:
        log.info("Reading restricted to: %s", ", ".join(str(r) for r in roots))
    else:
        log.warning("%s is not set: the server can read any path the user can read.", geo.ROOTS_ENV)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
