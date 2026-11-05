"""Draw the README banner (outputs/maps/hero.png) from the synthetic sample data.

The background is a synthetic, satellite-like rendering of the fictional project
(no real imagery); the overlays and every number come from the tools.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib import font_manager, patheffects
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from scipy.ndimage import gaussian_filter

from carbon_geo_mcp import geo

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "data" / "sample"
OUT = ROOT / "outputs" / "maps" / "hero.png"
UTM = "EPSG:32720"
RES = 20.0

BG = "#0b1419"
PANEL = "#111d24"
TEXT = "#f2f5f3"
MUTED = "#9fb0ae"
PLAN, MEASURE, SHOW = "#2bc4e8", "#43d68a", "#ffa94d"
LOSS = LinearSegmentedColormap.from_list("loss", ["#ffe66d", "#ffa62b", "#ff5d3a", "#d7263d", "#8e0f3a"])

for f in font_manager.findSystemFonts():
    if "Inter" in f:
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = "Inter"


def noise(shape, rng, scales=(2, 6, 18), weights=(0.5, 0.3, 0.2)):
    out = np.zeros(shape)
    for s, w in zip(scales, weights):
        out += w * gaussian_filter(rng.standard_normal(shape), s)
    out -= out.min()
    return out / out.max()


def terrain(strata, extent, rng):
    minx, miny, maxx, maxy = extent
    w, h = int((maxx - minx) / RES), int((maxy - miny) / RES)
    tr = from_origin(minx, maxy, RES, RES)
    codes = {"dense_forest": 1, "open_forest": 2, "non_forest": 3}
    zone = rasterize([(g, codes[s]) for g, s in zip(strata.geometry, strata.stratum)],
                     out_shape=(h, w), transform=tr, fill=0, dtype="uint8")

    n = noise((h, w), rng)
    img = np.zeros((h, w, 3))

    # Outside the project: Chaco-like mosaic of fields of varied size, irregular forest remnants and a river
    fields = np.zeros((h, w, 3))
    palette = np.array([[222, 204, 150], [184, 196, 118], [232, 218, 172], [160, 184, 104], [204, 178, 126],
                        [138, 170, 92]]) / 255
    r0 = 0
    while r0 < h:
        fh = int(rng.integers(350, 800) / RES)
        c0 = 0
        while c0 < w:
            fw = int(rng.integers(500, 1400) / RES)
            fields[r0:r0 + fh, c0:c0 + fw] = palette[rng.integers(len(palette))]
            fields[r0:r0 + 1, c0:c0 + fw] *= 0.82
            fields[r0:r0 + fh, c0:c0 + 1] *= 0.82
            c0 += fw
        r0 += fh
    fields *= (0.9 + 0.2 * noise((h, w), rng, scales=(1, 4), weights=(0.5, 0.5)))[..., None]
    remnants = noise((h, w), rng, scales=(25, 60), weights=(0.6, 0.4))
    forest_out = (remnants > 0.58)[..., None]
    remnant_col = (np.array([40, 105, 58]) / 255) * (0.8 + 0.35 * n[..., None])
    img[:] = np.where(forest_out, remnant_col, fields)

    # River: a meandering line south-east of the project
    yy, xx = np.mgrid[0:h, 0:w]
    centre = h * 0.93 - xx * 0.12 + 18 * np.sin(xx / 45) + 9 * np.sin(xx / 13)
    river = np.abs(yy - centre) < 3.2
    banks = (np.abs(yy - centre) < 9) & ~river
    img[banks] = np.array([34, 96, 54]) / 255
    img[river] = np.array([52, 140, 200]) / 255

    dense = np.array([22, 92, 52]) / 255
    open_ = np.array([78, 150, 72]) / 255
    nonf = np.array([205, 183, 120]) / 255
    canopy = noise((h, w), rng, scales=(0.8, 2.5), weights=(0.6, 0.4))
    for code, base, amp in ((1, dense, 0.45), (2, open_, 0.4), (3, nonf, 0.25)):
        m = zone == code
        img[m] = base * (0.7 + amp * n[m, None] + 0.25 * canopy[m, None])

    shade = 0.85 + 0.3 * noise((h, w), rng, scales=(1, 3), weights=(0.6, 0.4))
    img = np.clip(img * shade[..., None], 0, 1)
    return img, tr, (w, h)


def loss_years(tr, shape):
    with rasterio.open(S / "lossyear_sample.tif") as src:
        dst = np.zeros((shape[1], shape[0]), dtype="uint8")
        reproject(rasterio.band(src, 1), dst, dst_transform=tr, dst_crs=UTM, resampling=Resampling.nearest)
    return np.ma.masked_where((dst == 0) | (dst == 255), dst.astype("int16") + 2000)


def badge(ax, x, y, text, color, ha="left"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=12.5, fontweight="bold", color="#0b1419", zorder=12,
            bbox=dict(boxstyle="round,pad=0.45,rounding_size=0.6", fc=color, ec="none"))


CHAR_W = 0.6 * 11.5 / (0.44 * 16 * 72)   # monospace glyph width as a fraction of the text panel
PAD_W = 2 * 0.42 * 11.5 / (0.44 * 16 * 72)


def chip(ax, x, y, text, color):
    ax.text(x + PAD_W / 2, y, text, ha="left", va="center", fontsize=11.5, color="#0b1419", family="DejaVu Sans Mono",
            fontweight="bold", transform=ax.transAxes, zorder=4,
            bbox=dict(boxstyle="round,pad=0.42,rounding_size=0.8", fc=color, ec="none"))
    return x + len(text) * CHAR_W + PAD_W + 0.02


def main() -> None:
    rng = np.random.default_rng(7)
    strata = gpd.read_file(S / "project_strata.gpkg").to_crs(UTM)
    pa = gpd.read_file(S / "protected_area.gpkg").to_crs(UTM)
    plots = gpd.read_file(S / "plots.gpkg").to_crs(UTM)
    bx = strata.total_bounds
    x_min, x_max = bx[0] - 2600, bx[2] + 2600
    height = (x_max - x_min) * 8 / (16 * 0.56)
    y_mid = (bx[1] + bx[3]) / 2 + 300
    extent = (x_min, y_mid - height / 2, x_max, y_mid + height / 2)

    area = geo.compare_declared_area(str(S / "project_strata.gpkg"), {"open_forest": 2800}, "stratum")
    ovl = geo.check_overlap(str(S / "project_strata.gpkg"), str(S / "protected_area.gpkg"))
    loss = geo.forest_loss_in_area(str(S / "project_strata.gpkg"), str(S / "lossyear_sample.tif"))
    pl = geo.plots_in_strata(str(S / "plots.gpkg"), str(S / "project_strata.gpkg"), "stratum", "stratum", "plot_id", 50)
    flagged = {o["plot"] for o in pl["outside"]} | {m["plot"] for m in pl["stratum_mismatches"]} | \
              {e["plot"] for e in pl["plots_near_boundary"]} | set(pl["duplicate_coordinates"])

    fig = plt.figure(figsize=(16, 8), dpi=120)
    fig.patch.set_facecolor(BG)

    # ---------------- map panel
    ax = fig.add_axes([0.0, 0.0, 0.56, 1.0])
    img, tr, shape = terrain(strata, extent, rng)
    ax.imshow(img, extent=(extent[0], extent[2], extent[1], extent[3]), interpolation="bilinear", zorder=0)
    years = loss_years(tr, shape)
    lm = ax.imshow(years, extent=(extent[0], extent[2], extent[1], extent[3]), cmap=LOSS, vmin=2015, vmax=2024,
                   interpolation="nearest", zorder=1)

    glow = [patheffects.withStroke(linewidth=6, foreground=(1, 1, 1, 0.25))]
    strata.boundary.plot(ax=ax, color="white", linewidth=2, zorder=3, path_effects=glow)
    pa.boundary.plot(ax=ax, color="#ffd23f", linewidth=2.4, linestyle=(0, (6, 4)), zorder=4)
    ok = plots[~plots.plot_id.isin(flagged)]
    bad = plots[plots.plot_id.isin(flagged)]
    ok.plot(ax=ax, color="white", markersize=26, edgecolor="#0b1419", linewidth=0.8, zorder=5)
    bad.plot(ax=ax, color="#ff3df2", markersize=120, edgecolor="white", linewidth=1.6, marker="X", zorder=6)

    ox = strata[strata.stratum == "open_forest"].total_bounds
    dpct = next(r for r in area["comparison"] if r["item"] == "open_forest")["difference_pct"]
    badge(ax, bx[0] - 2300, bx[3] + 1500, f"open forest:\n+{dpct:.1f} % vs. declared", "#7ee081")
    badge(ax, pa.total_bounds[0] - 300, pa.total_bounds[3] + 300, f"{ovl['overlap_ha']:.0f} ha inside a\nprotected area",
          "#ffd23f", ha="right")
    badge(ax, bx[0] - 2300, bx[1] + 2500, f"{pl['plots_outside']} plots outside\nthe strata", "#ff7af5")
    badge(ax, bx[0] - 2300, bx[1] - 1050, f"{loss['total_loss_ha']:.0f} ha of forest lost 2015-2024", "#ff8a5b")

    ax.add_patch(FancyBboxPatch((0.6, 0.025), 0.37, 0.095, boxstyle="round,pad=0,rounding_size=0.015",
                                fc=(0.04, 0.08, 0.1, 0.82), ec="none", transform=ax.transAxes, zorder=9))
    cax = ax.inset_axes([0.63, 0.06, 0.31, 0.022])
    cax.set_zorder(10)
    cb = fig.colorbar(lm, cax=cax, orientation="horizontal", ticks=[2015, 2020, 2024])
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=TEXT, labelsize=10, length=0)
    cax.set_title("forest loss year", color=TEXT, fontsize=10.5, pad=4)

    ax.set_xlim(extent[0], extent[2])
    ax.set_ylim(extent[1], extent[3])
    ax.set_axis_off()
    ax.set_aspect("equal")

    # ---------------- text panel
    tp = fig.add_axes([0.56, 0.0, 0.44, 1.0])
    tp.set_facecolor(PANEL)
    tp.set_xticks([]), tp.set_yticks([])
    for s in tp.spines.values():
        s.set_visible(False)
    x0 = 0.08
    tp.text(x0, 0.88, "carbon-geo-mcp", fontsize=40, fontweight="bold", color=TEXT, transform=tp.transAxes)
    tp.text(x0, 0.785, "GIS checks for carbon project audits,\nrun by an AI agent on real files.",
            fontsize=17, color=TEXT, transform=tp.transAxes, linespacing=1.35, va="center")
    tp.text(x0, 0.685, "AI assistant   →   MCP server   →   GeoPandas · Rasterio · STAC",
            fontsize=12.5, color=MUTED, transform=tp.transAxes)

    groups = [
        ("PLAN", PLAN, ["plan_crs", "layer_info"]),
        ("MEASURE", MEASURE, ["area_by_stratum", "compare_declared_area", "check_overlap",
                              "plots_in_strata", "forest_loss_in_area", "data_completeness"]),
        ("VERIFY & SHOW", SHOW, ["check_raster_availability", "create_map"]),
    ]
    y = 0.6
    for name, color, tools in groups:
        tp.text(x0, y, name, fontsize=11, fontweight="bold", color=color, transform=tp.transAxes)
        y -= 0.055
        x = x0
        for tool in tools:
            if x + len(tool) * CHAR_W + PAD_W > 0.95:
                x, y = x0, y - 0.068
            x = chip(tp, x, y, tool, color)
        y -= 0.085

    tp.text(x0, 0.075, "CRS first  ·  no double counting  ·  says what is missing  ·  read-only",
            fontsize=12, color=TEXT, transform=tp.transAxes, fontweight="bold")
    tp.text(x0, 0.035, "Synthetic example data (fictional project, Paraguayan Chaco). Background is a rendering, not imagery.",
            fontsize=9.5, color=MUTED, transform=tp.transAxes)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, facecolor=BG)
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
