"""Draw outputs/maps/preview.png from the synthetic sample data and the tool results."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import rasterio
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from rasterio.features import shapes
from shapely.geometry import shape

from carbon_geo_mcp import geo

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "data" / "sample"
OUT = ROOT / "outputs" / "maps" / "preview.png"
UTM = "EPSG:32720"

STRATA_COLORS = {"dense_forest": "#2a78d6", "open_forest": "#eb6834", "non_forest": "#1baf7a"}
INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"


def main() -> None:
    strata = gpd.read_file(S / "project_strata.gpkg").to_crs(UTM)
    pa = gpd.read_file(S / "protected_area.gpkg").to_crs(UTM)
    plots = gpd.read_file(S / "plots.gpkg").to_crs(UTM)
    with rasterio.open(S / "lossyear_sample.tif") as src:
        band = src.read(1)
        loss = gpd.GeoDataFrame(
            geometry=[shape(g) for g, v in shapes(band, mask=band > 0, transform=src.transform)],
            crs=src.crs,
        ).to_crs(UTM)

    res_plots = geo.plots_in_strata(str(S / "plots.gpkg"), str(S / "project_strata.gpkg"),
                                    "stratum", "stratum", "plot_id", 50)
    res_area = geo.area_by_stratum(str(S / "project_strata.gpkg"), "stratum")
    res_ovl = geo.check_overlap(str(S / "project_strata.gpkg"), str(S / "protected_area.gpkg"))
    res_loss = geo.forest_loss_in_area(str(S / "project_strata.gpkg"), str(S / "lossyear_sample.tif"))

    flagged = {o["plot"]: f"{o['plot']} outside ({o['distance_to_strata_m']:.0f} m)" for o in res_plots["outside"]}
    flagged |= {m["plot"]: f"{m['plot']} declares {m['declared_stratum']}" for m in res_plots["stratum_mismatches"]}
    flagged |= {e["plot"]: f"{e['plot']} {e['distance_to_boundary_m']:.0f} m from edge" for e in res_plots["plots_near_boundary"]}
    dups = res_plots["duplicate_coordinates"]
    flagged[dups[-1]] = f"{' & '.join(dups)} same coordinates"

    fig, ax = plt.subplots(figsize=(12, 7.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for name, color in STRATA_COLORS.items():
        strata[strata.stratum == name].plot(ax=ax, color=color, alpha=0.28, edgecolor=color, linewidth=1.2)
    a = strata[strata.stratum == "dense_forest"].geometry.iloc[0]
    b = strata[strata.stratum == "open_forest"].geometry.iloc[0]
    gpd.GeoSeries([a.intersection(b)], crs=UTM).plot(ax=ax, facecolor="none", edgecolor=INK, hatch="////", linewidth=0)
    loss.plot(ax=ax, color=INK, linewidth=0)
    gpd.overlay(pa, strata, how="intersection").plot(ax=ax, facecolor="none", edgecolor=INK, hatch="..", linewidth=0)
    pa.boundary.plot(ax=ax, color=INK, linewidth=1.4, linestyle="--")

    ok = plots[~plots.plot_id.isin(flagged)]
    bad = plots[plots.plot_id.isin(flagged)]
    ok.plot(ax=ax, marker="o", color=SURFACE, edgecolor=INK, markersize=40, linewidth=1.2, zorder=4)
    bad.plot(ax=ax, marker="X", color=INK, edgecolor=SURFACE, markersize=110, linewidth=1, zorder=5)
    for _, r in bad.iterrows():
        if r.plot_id in flagged:
            ax.annotate(flagged[r.plot_id], (r.geometry.x, r.geometry.y), xytext=(8, 8), textcoords="offset points",
                        fontsize=9, color=INK, zorder=6,
                        bbox=dict(boxstyle="round,pad=0.25", fc=SURFACE, ec="none", alpha=0.9))

    minx, miny, maxx, maxy = strata.total_bounds
    ax.set_xlim(minx - 1500, maxx + 2800)
    ax.set_ylim(miny - 900, maxy + 2300)
    ax.set_axis_off()
    ax.set_aspect("equal")

    sb_x, sb_y = minx - 1200, miny - 600
    ax.plot([sb_x, sb_x + 2000], [sb_y, sb_y], color=INK, linewidth=3, solid_capstyle="butt")
    ax.text(sb_x + 1000, sb_y + 150, "2 km", ha="center", fontsize=9, color=INK)

    handles = [Patch(facecolor=c, alpha=0.5, edgecolor=c, label=n.replace("_", " ")) for n, c in STRATA_COLORS.items()]
    handles += [
        Patch(facecolor="none", edgecolor=INK, hatch="////", label=f"strata overlap ({res_area['overlap_between_strata_ha']:.0f} ha)"),
        Patch(facecolor=INK, label=f"forest loss 2015-2024 ({res_loss['total_loss_ha']:.0f} ha inside project)"),
        Line2D([], [], color=INK, linestyle="--", label=f"protected area (overlap {res_ovl['overlap_ha']:.0f} ha)"),
        Line2D([], [], marker="o", color="none", markeredgecolor=INK, markerfacecolor=SURFACE, markersize=7, label="plot OK"),
        Line2D([], [], marker="X", color="none", markerfacecolor=INK, markersize=9, label="plot flagged"),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=9.5,
              labelcolor=INK, title="Synthetic example", title_fontsize=10)
    fig.suptitle("carbon-geo-mcp: audit checks an AI agent can run on real files", x=0.02, ha="left",
                 fontsize=15, fontweight="bold", color=INK)
    fig.text(0.02, 0.905, f"Fictional 8,000 ha project, Paraguayan Chaco. Areas in local equal-area (LAEA), "
             "distances in UTM 20S. Every number on this map comes from the tools.", fontsize=10, color=MUTED)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, facecolor=SURFACE, bbox_inches="tight")
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
