"""Real MCP calls against a small native index; skipped without the mcp extra."""

from pathlib import Path
import asyncio
import importlib.util
import json
import os
import sys

import pytest
import corequarry as cq

pytest.importorskip("fastmcp")
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


SERVER = Path(__file__).resolve().parents[1] / "examples" / "mcp_server.py"
spec = importlib.util.spec_from_file_location("corequarry_mcp_demo", SERVER)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    root = tmp_path_factory.mktemp("mcp")
    source = root / "articles.ndjson"
    source.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in [
        {"title": "Alpha", "body": "Alpha café virus vaccine.", "count": 42},
        {"title": "Beta", "body": "Beta virus study.", "count": 7},
        {"title": "Gamma", "body": "Gamma vaccine response.", "count": 65},
    ]), encoding="utf-8")
    name = root / "database"
    stats = cq.index_file(name, source, doctype="NDJSON", memory_mb=32)
    assert stats.records_added == stats.total_records == 3
    return name


def test_search_fetch_and_operator_discovery(database):
    async def check():
        async with Client(demo.create_server(str(database))) as client:
            tools = {tool.name for tool in await client.list_tools()}
            assert tools == {"search", "fetch", "operators", "database_info"}
            info = (await client.call_tool("database_info")).data
            assert info["total_records"] == 3
            result = (await client.call_tool("search", {
                "query": "virus vaccine PEER:130", "syntax": "rpn", "limit": 1,
            })).data
            assert result["total_found"] == result["returned"] == 1
            row = result["results"][0]
            assert row["evidence"]["field"] == "BODY"
            assert "**virus**" in row["evidence"]["text"]
            assert "\x1b" not in row["evidence"]["text"]
            assert row["hits"] and row["record_extent"]["end"] >= 0
            fetched = (await client.call_tool("fetch", {
                "result_id": row["result_id"], "field": "BODY", "max_chars": 9,
            })).data
            assert fetched["text"] == "Alpha caf"
            assert fetched["next_start"] == 9
            tail = (await client.call_tool("fetch", {
                "result_id": row["result_id"], "field": "BODY", "start": 9,
            })).data
            assert "é virus vaccine" in tail["text"]
            source = (await client.call_tool("fetch", {
                "result_id": row["result_id"],
            })).data
            assert json.loads(source["text"])["count"] == 42
            catalog = (await client.call_tool("operators")).data
            assert any("PEER" in op["name"].upper() for op in catalog)
    asyncio.run(check())


@pytest.mark.parametrize("syntax,query", [
    ("infix", "virus OR vaccine"),
    ("rpn", "virus vaccine OR"),
    ("words", "virus"),
])
def test_paging_counts_and_empty_pages(database, syntax, query):
    async def check():
        async with Client(demo.create_server(str(database))) as client:
            result = (await client.call_tool("search", {
                "query": query, "syntax": syntax, "limit": 1,
            })).data
            assert result["total_found"] == (2 if syntax == "words" else 3)
            assert result["returned"] == 1 and result["next_start"] == 1
            empty = (await client.call_tool("search", {
                "query": query, "syntax": syntax, "start": 100, "limit": 1,
            })).data
            assert empty["total_found"] == result["total_found"]
            assert empty["results"] == [] and empty["next_start"] is None
    asyncio.run(check())


def test_validation_and_cache_eviction(database):
    async def check():
        server = demo.create_server(str(database), cache_size=2)
        async with Client(server) as client:
            async def search_one():
                result = await client.call_tool("search", {"query": "virus", "limit": 1})
                return result.data["results"][0]["result_id"]
            first, second = await search_one(), await search_one()
            await client.call_tool("fetch", {"result_id": first})
            await search_one()
            evicted = await client.call_tool("fetch", {"result_id": second}, raise_on_error=False)
            assert evicted.is_error
            assert "expired" in evicted.content[0].text
            assert not (await client.call_tool("fetch", {"result_id": first})).is_error
            for arguments in ({"query": ""}, {"query": "virus", "limit": 0},
                              {"query": "virus", "syntax": "sql"},
                              {"query": "virus", "limit": 3}):
                assert (await client.call_tool("search", arguments, raise_on_error=False)).is_error
            missing = await client.call_tool("fetch", {
                "result_id": first, "field": "DOES-NOT-EXIST",
            }, raise_on_error=False)
            assert missing.is_error
            info = (await client.call_tool("database_info")).data
            assert info["cached_results"] == info["cache_capacity"] == 2
        # A new lifespan opens a fresh handle and starts without stale result IDs.
        async with Client(server) as client:
            assert (await client.call_tool("database_info")).data["cached_results"] == 0
            assert (await client.call_tool("fetch", {"result_id": first},
                                           raise_on_error=False)).is_error
    asyncio.run(check())


def test_stdio_subprocess(database):
    async def check():
        transport = StdioTransport(
            command=sys.executable, args=[str(SERVER), str(database)], env=dict(os.environ),
        )
        async with Client(transport) as client:
            assert len(await client.list_tools()) == 4
            result = await client.call_tool("search", {
                "query": "virus vaccine PEER:130", "syntax": "rpn", "limit": 1,
            })
            assert result.data["total_found"] == 1
            row = result.data["results"][0]
            fetched = await client.call_tool("fetch", {
                "result_id": row["result_id"], "field": "BODY",
            })
            assert fetched.data["text"] == "Alpha café virus vaccine."
    asyncio.run(check())
