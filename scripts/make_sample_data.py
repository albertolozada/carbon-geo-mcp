"""Generate the synthetic sample data used in the demo notebook and the README.

Everything here is FICTIONAL: a made-up 8,000 ha project placed in the
Paraguayan Chaco only so that coordinates, UTM zone and pixel areas are realistic.
It contains a few deliberate problems that the tools should find:

* the "open_forest" stratum overlaps "dense_forest" by 50 ha;
* the declared area of "open_forest" in the fictional PD is 2,800 ha (the layer has 2,850 ha);
* a protected area overlaps the project by 150 ha;
* two plots fall outside the strata, one plot declares the wrong stratum,
  one plot sits 20 m from the boundary and two plots share the same coordinates.

Run:  python scripts/make_sample_data.py
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import Point, box

OUT = Path(__file__).resolve().parents[1] / "data" / "sample"
UTM = "EPSG:32720"  # UTM zone 20S
X0, Y0 = 600_000, 7_620_000  # south-west corner of the fictional project (about 21.5 S, 62.0 W)


def strata() -> gpd.GeoDataFrame:
    dense = box(X0, Y0, X0 + 6000, Y0 + 8000)                       # 4,800 ha
    non_forest = box(X0 + 7000, Y0 + 3000, X0 + 9000, Y0 + 5000)     # 400 ha
    open_ = box(X0 + 5937.5, Y0, X0 + 10_000, Y0 + 8000).difference(non_forest)  # 2,850 ha, 50 ha over dense
    return gpd.GeoDataFrame(
        {"stratum": ["dense_forest", "open_forest", "non_forest"], "name": ["Stratum 1", "Stratum 2", "Stratum 3"]},
        geometry=[dense, open_, non_forest],
        crs=UTM,
    )


def protected_area() -> gpd.GeoDataFrame:
    pa = box(X0 + 8500, Y0 + 7000, X0 + 12_000, Y0 + 10_000)  # 1.5 km x 1 km inside the project = 150 ha
    return gpd.GeoDataFrame({"pa_name": ["Fictional Reserve"]}, geometry=[pa], crs=UTM)


def plots() -> gpd.GeoDataFrame:
    rows = []
    n = 0
    for ix, x in enumerate(range(500, 10_000, 1500)):
        for iy, y in enumerate(range(700, 8000, 1600)):
            n += 1
            px, py = X0 + x, Y0 + y
            if 7000 <= x <= 9000 and 3000 <= y <= 5000:
                s = "non_forest"
            elif x < 6000:
                s = "dense_forest"
            else:
                s = "open_forest"
            rows.append({"plot_id": f"P{n:02d}", "stratum": s, "geometry": Point(px, py)})
    rows.append({"plot_id": "P90", "stratum": "dense_forest", "geometry": Point(X0 - 300, Y0 + 4000)})   # outside, 300 m
    rows.append({"plot_id": "P91", "stratum": "open_forest", "geometry": Point(X0 + 10_800, Y0 + 2000)})  # outside, 800 m
    rows.append({"plot_id": "P92", "stratum": "dense_forest", "geometry": Point(X0 + 8000, Y0 + 6500)})   # wrong stratum
    rows.append({"plot_id": "P93", "stratum": "dense_forest", "geometry": Point(X0 + 3000, Y0 + 20)})     # 20 m from edge
    rows.append({"plot_id": "P94", "stratum": "dense_forest", "geometry": Point(X0 + 500, Y0 + 700)})     # duplicate of P01
    return gpd.GeoDataFrame(rows, crs=UTM)


def lossyear_raster(strata_utm: gpd.GeoDataFrame) -> None:
    """Hansen-style lossyear raster (EPSG:4326, about 25 m pixels). Value 15 = 2015 ... 24 = 2024."""
    rng = np.random.default_rng(42)
    minx, miny, maxx, maxy = strata_utm.to_crs("EPSG:4326").total_bounds
    res = 0.00025
    pad = 0.02
    west, north = minx - pad, maxy + pad
    width = int(np.ceil((maxx - minx + 2 * pad) / res))
    height = int(np.ceil((maxy - miny + 2 * pad) / res))
    transform = from_origin(west, north, res, res)

    patches = []
    # More clearing in open forest, some in dense forest, a few outside the project
    centres = (
        [(X0 + rng.uniform(6200, 9800), Y0 + rng.uniform(300, 7700)) for _ in range(45)]
        + [(X0 + rng.uniform(300, 5700), Y0 + rng.uniform(300, 7700)) for _ in range(20)]
        + [(X0 + rng.uniform(-1500, 11_500), Y0 + rng.uniform(-1500, 9500)) for _ in range(15)]
    )
    for cx, cy in centres:
        year = int(rng.integers(15, 25))
        w, h = rng.uniform(60, 400), rng.uniform(60, 300)
        patches.append((box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), year))
    shapes = gpd.GeoSeries([p for p, _ in patches], crs=UTM).to_crs("EPSG:4326")
    data = rasterize(
        [(g, y) for g, (_, y) in zip(shapes, patches)],
        out_shape=(height, width), transform=transform, fill=0, dtype="uint8",
    )
    with rasterio.open(
        OUT / "lossyear_sample.tif", "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint8", crs="EPSG:4326", transform=transform, nodata=255, compress="deflate",
    ) as dst:
        dst.write(data, 1)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = strata()
    # Saved in EPSG:4326 on purpose: project layers often arrive in degrees
    s.to_crs("EPSG:4326").to_file(OUT / "project_strata.gpkg", layer="strata", driver="GPKG")
    protected_area().to_crs("EPSG:4326").to_file(OUT / "protected_area.gpkg", driver="GPKG")
    plots().to_crs("EPSG:4326").to_file(OUT / "plots.gpkg", driver="GPKG")
    lossyear_raster(s)
    print(f"Sample data written to {OUT}")


if __name__ == "__main__":
    main()
