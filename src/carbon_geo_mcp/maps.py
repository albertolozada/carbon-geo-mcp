"""Quick check maps returned as images, so the agent can show its work.

These are inspection maps, not cartography. Nothing is written to disk: the PNG
goes back to the host inside the tool result.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .geo import GeoCheckError, _require_field, clean, distance_crs, read_layer  # noqa: E402

# Fixed categorical order (validated palette); never cycled
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#9a9893"
INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"
MAX_LAYERS = 6
MAX_CATEGORIES = 8


def _nice_length(span_m: float) -> float:
    target = span_m / 5
    for mag in (1, 10, 100, 1000, 10_000, 100_000):
        for step in (1, 2, 5):
            if step * mag >= target:
                return step * mag
    return 1_000_000


def create_map(layers: list[dict[str, Any]], title: str | None = None) -> tuple[bytes, dict[str, Any]]:
    if not layers:
        raise GeoCheckError("Give at least one layer to draw.")
    if len(layers) > MAX_LAYERS:
        raise GeoCheckError(f"At most {MAX_LAYERS} layers per map.")

    frames = []
    for spec in layers:
        gdf, quality = clean(read_layer(spec["path"], spec.get("layer")))
        if gdf.empty:
            raise GeoCheckError(f"'{Path(spec['path']).name}' has no usable geometries.")
        if spec.get("category_field"):
            _require_field(gdf, spec["category_field"], Path(spec["path"]).name)
        frames.append((spec, gdf, quality))

    crs = distance_crs(frames[0][1])
    fig, ax = plt.subplots(figsize=(10, 7), dpi=120)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    handles, summary_layers = [], []
    slot = 0
    for spec, gdf, quality in frames:
        gdf = gdf.to_crs(crs)
        label = spec.get("label") or Path(spec["path"]).stem
        field = spec.get("category_field")
        groups: list[tuple[str, gpd.GeoDataFrame, str]] = []
        if field:
            values = gdf[field].astype("string").fillna("<missing>")
            cats = list(values.value_counts().index)
            if len(cats) > MAX_CATEGORIES:  # fold the rest into "other" instead of inventing colours
                keep = cats[: MAX_CATEGORIES - 1]
                values = values.where(values.isin(keep), "other")
                cats = keep + ["other"]
            for i, cat in enumerate(cats):
                color = OTHER if cat == "other" and len(cats) == MAX_CATEGORIES else PALETTE[(slot + i) % len(PALETTE)]
                groups.append((f"{label}: {cat}", gdf[values == cat], color))
            slot += len(cats)
        else:
            groups.append((label, gdf, PALETTE[slot % len(PALETTE)]))
            slot += 1

        for name, part, color in groups:
            kinds = set(part.geom_type)
            if kinds & {"Polygon", "MultiPolygon", "GeometryCollection"}:
                part.plot(ax=ax, color=color, alpha=0.3, edgecolor=color, linewidth=1.2)
                handles.append(Patch(facecolor=color, alpha=0.5, edgecolor=color, label=name))
            elif kinds & {"LineString", "MultiLineString"}:
                part.plot(ax=ax, color=color, linewidth=2)
                handles.append(Line2D([], [], color=color, linewidth=2, label=name))
            else:
                part.plot(ax=ax, color=color, edgecolor=SURFACE, markersize=36, linewidth=1, zorder=4)
                handles.append(Line2D([], [], marker="o", color="none", markerfacecolor=color,
                                      markeredgecolor=SURFACE, markersize=8, label=name))
        summary_layers.append({"label": label, "features": int(len(gdf)), "categories": len(groups) if field else None,
                               "geometry_quality": quality})

    minx, maxx = ax.get_xlim()
    miny, maxy = ax.get_ylim()
    miny -= (maxy - miny) * 0.1  # free band at the bottom for the scale bar
    ax.set_ylim(miny, maxy)
    span = maxx - minx
    length = _nice_length(span)
    x0, y0 = minx + span * 0.02, miny + (maxy - miny) * 0.03
    ax.plot([x0, x0 + length], [y0, y0], color=INK, linewidth=3, solid_capstyle="butt")
    ax.text(x0 + length / 2, y0 + (maxy - miny) * 0.015,
            f"{length / 1000:g} km" if length >= 1000 else f"{length:g} m", ha="center", fontsize=9, color=INK)

    ax.set_axis_off()
    ax.set_aspect("equal")
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=9, labelcolor=INK)
    crs_name = crs.to_string()
    fig.suptitle(title or "Check map", x=0.02, ha="left", fontsize=14, fontweight="bold", color=INK)
    fig.text(0.02, 0.92, f"Drawn in {crs_name}. Quick inspection map, not cartography.", fontsize=9, color=MUTED)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue(), {"crs_used": crs_name, "layers": summary_layers}
