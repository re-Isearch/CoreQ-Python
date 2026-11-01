"""Local FastMCP adapter using the same retained-search service as the web app."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
import argparse

import corequarry as cq
from corequarry.service import Collection, SearchStore
from fastmcp import Context, FastMCP
from pydantic import Field

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}


def create_server(database: str, *, cache_size: int = 200) -> FastMCP:
    if cache_size < 1:
        raise ValueError("cache_size must be positive")
    collection = Collection("database", "Database", str(Path(database).expanduser().resolve()))

    @asynccontextmanager
    async def lifespan(server):
        store = SearchStore([collection], max_searches=cache_size)
        try:
            yield {"store": store}
        finally:
            store.close()

    mcp = FastMCP("CoreQuarry demo", lifespan=lifespan, instructions=(
        "Search the configured collection. Discover syntax with operators(). "
        "Use the returned search_id with page() to reuse the evaluated query. "
        "Search limits affect returned rows, not query evaluation. Result IDs "
        "identify native rows for fetch(). Spans are inclusive byte offsets."))

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def search(query: str, ctx: Context,
               syntax: Literal["infix", "rpn", "words"] = "infix",
               start: Annotated[int, Field(ge=0)] = 0,
               limit: Annotated[int, Field(ge=1, le=50)] = 10) -> dict[str, Any]:
        """Evaluate an IB query and retain it for paging and retrieval.

        Args:
            query: For example "virus vaccine PEER:130" with syntax="rpn".
            syntax: Select the infix, reverse Polish, or words parser.
            start: Zero-based result offset.
            limit: Rows to materialize; does not limit query evaluation.
        """
        return ctx.lifespan_context["store"].search("mcp", ["database"], query,
                                                   syntax=syntax, start=start, limit=limit)

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def page(search_id: str, ctx: Context,
             start: Annotated[int, Field(ge=0)] = 0,
             limit: Annotated[int, Field(ge=1, le=50)] = 10) -> dict[str, Any]:
        """Page through an existing search without evaluating its query again."""
        return ctx.lifespan_context["store"].page("mcp", search_id, start, limit)

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def fetch(result_id: str, ctx: Context, field: str | None = None,
              start: Annotated[int, Field(ge=0)] = 0,
              max_chars: Annotated[int, Field(ge=1, le=20000)] = 4000) -> dict[str, Any]:
        """Retrieve source or a field. Fetch offsets count Unicode characters."""
        return ctx.lifespan_context["store"].fetch("mcp", result_id, field, start, max_chars)

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def fields(ctx: Context) -> list[dict[str, Any]]:
        """List collection fields and their native datatypes."""
        return ctx.lifespan_context["store"].fields(["database"])

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def scan(ctx: Context, field: str = "", prefix: str = "",
             limit: Annotated[int, Field(ge=1, le=50)] = 12) -> list[dict[str, Any]]:
        """Return bounded native Scan suggestions for a field and term prefix."""
        return ctx.lifespan_context["store"].scan(["database"], field, prefix, limit)

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def operators() -> list[dict[str, Any]]:
        """Describe IB's query operators, arities, syntax and PEER bounds."""
        return cq.SQUERY.operators()

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def database_info(ctx: Context) -> dict[str, Any]:
        """Report collection statistics and retained search-cache state."""
        return ctx.lifespan_context["store"].database_info(["database"])

    return mcp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--cache-size", type=int, default=200, help="Maximum retained searches")
    args = parser.parse_args()
    server = create_server(args.database, cache_size=args.cache_size)
    options = {"host": "127.0.0.1", "port": args.port} if args.transport == "http" else {}
    server.run(transport=args.transport, show_banner=False, **options)


if __name__ == "__main__":
    main()
