"""A local, read-only FastMCP server for one CoreQuarry database or VIDB."""

from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4
import argparse
import math

import corequarry as cq
from fastmcp import Context, FastMCP
from pydantic import Field


READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}


def extent(span: cq.FC) -> dict[str, int]:
    return {"start": span.start, "end": span.end}


def create_server(database: str, *, cache_size: int = 200) -> FastMCP:
    """Open the configured database at startup; release cached rows at shutdown."""
    if cache_size < 1:
        raise ValueError("cache_size must be positive")
    database = str(Path(database).expanduser().resolve())

    @asynccontextmanager
    async def lifespan(server: FastMCP):
        db = cq.VIDB(database, search_only=True)
        rows: OrderedDict[str, cq.RESULT] = OrderedDict()
        try:
            yield {"db": db, "rows": rows}
        finally:
            rows.clear()
            db.close()

    mcp = FastMCP(
        "CoreQuarry demo",
        instructions=(
            "Search the configured CoreQuarry collection. Use operators() to discover "
            "IB query syntax. Search returns evidence and temporary result IDs for fetch. "
            "The limit controls returned rows, not query evaluation. Evidence and hit "
            "spans are inclusive byte offsets relative to the source record."
        ),
        lifespan=lifespan,
    )

    # Run native calls on the event-loop thread, serially. The bindings currently
    # hold the GIL; dispatching these calls to a threadpool adds no parallelism.
    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def search(
        query: str,
        ctx: Context,
        syntax: Literal["infix", "rpn", "words"] = "infix",
        start: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        """Search using IB syntax; return a score-sorted page with source evidence.

        Args:
            query: Expression, for example "virus vaccine PEER:130" with syntax="rpn".
            syntax: Select the native infix, reverse Polish, or words parser.
            start: Zero-based page offset.
            limit: Rows to materialize; does not stop or truncate query evaluation.
        """
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit > cache_size:
            raise ValueError(f"limit must not exceed this server's cache size ({cache_size})")
        db = ctx.lifespan_context["db"]
        rows = ctx.lifespan_context["rows"]
        parser = {"infix": cq.SQUERY.from_infix, "rpn": cq.SQUERY.from_rpn,
                  "words": cq.SQUERY.from_words}[syntax]
        expression = parser(query)
        matches = db.search(cq.QUERY(expression, sort=cq.SortBy.SCORE))
        page = matches.get_rset(limit, start=start)
        output = []
        pending = []
        for row in page:
            result_id = uuid4().hex
            evidence = None
            if len(row.hits):
                display = row.get_display_evidence(max_bytes=240)
                text, field = row.evidence(max_bytes=240, before="**", after="**")
                evidence = {
                    "text": text,
                    "field": field,
                    "cover_extent": extent(display.cover.extent),
                    "display_extent": extent(display.display_extent),
                    "container_extent": extent(display.container_extent)
                    if display.has_container else None,
                }
            output.append({
                "result_id": result_id,
                "key": row.key,
                "volume": row.virtual_index,
                "score": row.score if math.isfinite(row.score) else None,
                "headline": db.headline(row),
                "filename": row.filename,
                "doctype": row.doctype,
                "record_extent": {"start": row.start, "end": row.end},
                "date": row.date.iso if row.date.ok else None,
                "evidence": evidence,
                "hits": [extent(row.hits[i]) for i in range(min(len(row.hits), 64))],
                "hit_count": len(row.hits),
            })
            pending.append((result_id, row))
        # Publish IDs only after the entire response has been prepared.
        rows.update(pending)
        while len(rows) > cache_size:
            rows.popitem(last=False)
        return {
            "query_rpn": expression.rpn,
            "total_found": len(matches),
            "start": start,
            "returned": len(output),
            "next_start": start + len(output) if start + len(output) < len(matches) else None,
            "span_coordinates": "record-relative inclusive byte offsets; record_extent is file-relative",
            "results": output,
        }

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def fetch(
        result_id: str,
        ctx: Context,
        field: str | None = None,
        start: Annotated[int, Field(ge=0)] = 0,
        max_chars: Annotated[int, Field(ge=1, le=20000)] = 4000,
    ) -> dict[str, Any]:
        """Fetch source text or a named field for an ID returned by search.

        IDs expire on cache eviction or server restart. Fetch offsets count Python
        Unicode characters, unlike the byte spans returned by search.
        """
        rows = ctx.lifespan_context["rows"]
        if result_id not in rows:
            raise ValueError("Unknown or expired result_id; search again")
        row = rows[result_id]
        db = ctx.lifespan_context["db"]
        text = row.get_record_data() if field is None else db.get_field_data(row, field)
        if text is None:
            raise ValueError(f"Field {field!r} is unavailable for this result")
        rows.move_to_end(result_id)
        end = min(start + max_chars, len(text))
        return {
            "result_id": result_id, "key": row.key, "volume": row.virtual_index,
            "field": field, "text": text[start:end], "start": start,
            "total_chars": len(text), "next_start": end if end < len(text) else None,
        }

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def operators() -> list[dict[str, Any]]:
        """Describe IB's query operators, arities and syntax, including PEER bounds."""
        return cq.SQUERY.operators()

    @mcp.tool(annotations=READ_ONLY, run_in_thread=False)
    def database_info(ctx: Context) -> dict[str, Any]:
        """Report the configured collection, record count, volumes and build identity."""
        db = ctx.lifespan_context["db"]
        return {
            "database": db.name, "total_records": db.total_records,
            "total_words": db.total_words, "volumes": db.volume_count,
            "version": db.GetVersionID(), "ib_revision": cq.ib_revision,
            "gptype_bits": cq.gptype_bits, "cache_capacity": cache_size,
            "cached_results": len(ctx.lifespan_context["rows"]),
        }

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="Existing database stem or VIDB name")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--cache-size", type=int, default=200)
    args = parser.parse_args()
    server = create_server(args.database, cache_size=args.cache_size)
    options = {"host": "127.0.0.1", "port": args.port} if args.transport == "http" else {}
    server.run(transport=args.transport, show_banner=False, **options)


if __name__ == "__main__":
    main()
