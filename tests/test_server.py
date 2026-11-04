"""The tools as an MCP client sees them, connected in-process."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest
from mcp import Client

from carbon_geo_mcp.server import mcp

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"
EXPECTED = {
    "layer_info", "area_by_stratum", "compare_declared_area", "check_overlap",
    "plots_in_strata", "forest_loss_in_area", "data_completeness",
}


def _run(coro):
    return anyio.run(coro)


def test_tools_are_listed_and_read_only():
    async def go():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(go).tools
    assert {t.name for t in tools} == EXPECTED
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


@pytest.mark.skipif(not (SAMPLE / "project_strata.gpkg").exists(), reason="sample data not generated")
def test_area_tool_returns_structured_result():
    async def go():
        async with Client(mcp) as client:
            return await client.call_tool(
                "area_by_stratum", {"path": str(SAMPLE / "project_strata.gpkg"), "stratum_field": "stratum"}
            )

    res = _run(go)
    assert not res.is_error
    assert res.structured_content["overlap_between_strata_ha"] == pytest.approx(50, rel=0.01)


def test_errors_come_back_as_tool_errors():
    async def go():
        async with Client(mcp) as client:
            return await client.call_tool("layer_info", {"path": "does/not/exist.gpkg"})

    res = _run(go)
    assert res.is_error
    assert "not found" in res.content[0].text
