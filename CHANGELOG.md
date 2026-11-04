# Changelog

## 0.2.0 (2026-11-04)

New tools, inspired by the lessons in *MCP for GIS: From Chatbots to Spatial Agents* (see "Related work" in the README):

- `plan_crs`: a "reflection" step before measuring. Reports CRS, datum and UTM zones of every layer, detects coordinates that do not match their CRS (e.g. UTM values labelled as degrees), flags mixed CRS, mixed datums and layers spanning several UTM zones, proposes the CRS for areas and distances with the reason, and estimates the UTM area distortion that can explain differences with declared areas.
- `check_raster_availability`: searches a STAC catalog (default Earth Search, Sentinel-2 L2A) before any download. Reports scenes per month, cloud cover and, for each date, the real coverage of the area of interest computed locally; lists usable dates. Only the bounding box and dates are sent to the catalog.
- `create_map`: quick check map of up to 6 layers, coloured by category if requested, in the local UTM zone with a scale bar. Returned as an image; nothing is written to disk.

Other changes:

- Server instructions now ask the agent to call `plan_crs` first and to state the CRS before measuring.
- New dependencies: `matplotlib`, `pystac-client`, `pydantic`.
- Tests for the new tools, including a live STAC test that runs in CI.
- README: "Related work" section; Spanish guide updated.

## 0.1.0 (2026-11-04)

First release with seven tools: `layer_info`, `area_by_stratum`, `compare_declared_area`, `check_overlap`, `plots_in_strata`, `forest_loss_in_area` and `data_completeness`.
