"""Start the demo server over stdio, search, then fetch its first result."""

from pathlib import Path
import argparse
import asyncio
import json
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def run(database: str, query: str, syntax: str) -> None:
    transport = StdioTransport(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_server.py")), database],
        env=dict(os.environ),
    )
    async with Client(transport) as client:
        tools = await client.list_tools()
        print("Tools:", ", ".join(tool.name for tool in tools))
        response = await client.call_tool("search", {
            "query": query, "syntax": syntax, "limit": 3,
        })
        data = response.data
        print(json.dumps(data, ensure_ascii=False, indent=2))
        if data["results"]:
            fetched = await client.call_tool("fetch", {
                "result_id": data["results"][0]["result_id"], "max_chars": 1000,
            })
            print(json.dumps(fetched.data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("query")
    parser.add_argument("--syntax", choices=("infix", "rpn", "words"), default="rpn")
    args = parser.parse_args()
    asyncio.run(run(str(Path(args.database).expanduser().resolve()), args.query, args.syntax))
