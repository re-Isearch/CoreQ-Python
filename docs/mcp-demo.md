# CoreQuarry FastMCP demo

The [server](../examples/mcp_server.py) exposes one existing physical database or
VIDB through the standalone `fastmcp` package. Its four read-only tools provide
search, evidence, source retrieval and operator discovery. The
[client](../examples/mcp_client.py) starts the server, discovers its tools, runs a
query and fetches the first matching record.

## Install

From a checkout of this repository, install the bindings with the optional MCP
dependency into the Python environment that will run both scripts:

```sh
python -m pip install '.[mcp]' -Ccmake.define.COREQUARRY_IB_SOURCE_DIR=/path/to/ib
```

If the bindings are already installed in that environment, install just the extra
dependency with `python -m pip install 'fastmcp>=4.1.4,<5'`. This demo was tested with
FastMCP 4.1.4 and Python 3.12 on Linux. The engine's index ABI must match the
database being opened; see the [build instructions](../README.md#build).

## Try it with a temporary collection

Create a directory for the demo and keep the source file alongside the index:

```sh
mkdir -p /tmp/corequarry-mcp-demo
```

```python
from pathlib import Path
import corequarry as cq

root = Path("/tmp/corequarry-mcp-demo")
source = root / "articles.ndjson"
source.write_text(
    '{"title":"Vaccination","body":"A virus vaccine study."}\n'
    '{"title":"Other work","body":"A laser processor study."}\n',
    encoding="utf-8",
)
cq.index_file(root / "DEMO", source, doctype="NDJSON", memory_mb=32)
```

Run this initial indexing example once against a fresh stem. The server itself
performs no indexing. Use an existing collection instead if desired, including
PATENTS or WIKI_ALL. Source files must remain available for evidence and fetch.

From the repository root:

```sh
python examples/mcp_client.py /tmp/corequarry-mcp-demo/DEMO 'virus vaccine PEER:130'
```

The client prints the four tool names, a structured search response and fetched
source text. It launches the server with the same Python interpreter, preserving
the environment, so the native module and FastMCP are available in the child.

## Connect an MCP client over stdio

The client starts the server process and owns its lifetime. A typical MCP client
configuration is:

```json
{
  "mcpServers": {
    "corequarry": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": [
        "/absolute/path/to/CoreQ-Python/examples/mcp_server.py",
        "/absolute/path/to/index/PATENTS"
      ]
    }
  }
}
```

Use absolute paths and the interpreter where `import corequarry` succeeds. A
stdio server reserves stdout for MCP messages; the demo does not print on it.

## Connect over local Streamable HTTP

```sh
python examples/mcp_server.py /absolute/path/to/index/PATENTS --transport http --port 8000
```

Connect to `http://127.0.0.1:8000/mcp`. The CLI binds to loopback and does not
implement authentication or tenant separation. It is a local demo; remote
deployment requires an application access policy and HTTP authentication.

## Tool parameters and responses

| Tool | Parameters | Returns |
| --- | --- | --- |
| `search` | `query`; `syntax="infix"` (`infix`, `rpn`, `words`); `start=0`; `limit=10` | Total matches, canonical RPN, page offsets, rows and evidence |
| `fetch` | `result_id`; optional `field`; `start=0`; `max_chars=4000` | Source record or named field, character count and next offset |
| `operators` | None | Native operator names, arities, syntax and descriptions |
| `database_info` | None | Record/word counts, volumes, engine identity and cache occupancy |

For example, call `search` with:

```json
{"query": "virus vaccine PEER:130", "syntax": "rpn", "start": 0, "limit": 3}
```

`search` sorts by native score with the binding's default normalization. Its
`limit` is between 1 and 50 and cannot exceed the configured cache capacity.
The native query still evaluates the complete match set. An empty page retains
the correct `total_found`; `next_start` is null at the end.

Each row includes a temporary `result_id`, native key, volume, score, headline,
source filename, doctype, source record extent, date and evidence. Keys can be
repeated across volumes; the result ID identifies the retained native row.
Evidence includes a marked snippet, container field, cover extent and display
extent. A result without positional hits has null evidence. Up to 64 hit extents
are returned per row; compare the list length with `hit_count` for truncation.
Non-finite native scores are represented as null for valid JSON.

Hit and evidence extents are **inclusive byte offsets relative to the record**.
`record_extent` is the record's inclusive extent in its source file. Snippets can
be transformed by a doctype, so byte spans do not index the rendered snippet.

Pass a returned ID to `fetch`, optionally selecting a field such as `BODY`:

```json
{"result_id": "ID-FROM-SEARCH", "field": "BODY", "start": 0, "max_chars": 4000}
```

Omit `field` for the source record. Fetch pagination counts Python Unicode
characters and uses a zero-based start. `max_chars` is between 1 and 20,000.
The response is bounded, but the native method reads the complete selected record
or field before the Python slice. Unknown IDs and unavailable fields return MCP
tool errors, as do invalid query arguments.

## Lifetime and concurrency

One search-only VIDB stays open for the server lifespan. Searches reuse its
native caches. A bounded LRU cache retains up to 200 RESULT objects by default;
change it with `--cache-size`. Search inserts returned rows and fetch refreshes
their recency. IDs expire on eviction or shutdown. The cache belongs to the
server process and is shared by its clients; it is not a persistent session store.

Native tools run serially on the event-loop thread using FastMCP's
`run_in_thread=False`. The current bindings hold the GIL; a threadpool would not
make native searches parallel. For concurrent searches, run separate processes
that each open their own handles. Long calls block this demo's event loop, and a
client timeout does not cancel native query execution.

The demo does not automatically refresh readers after an external append. Reader
refresh, persistent sets and worker scheduling belong to the application's
session model. Shutdown clears retained results and closes the database handle.

## Verification

With the test and MCP dependencies installed:

```sh
python -m pytest tests/test_mcp_demo.py -q
```

Tests build a fresh native NDJSON index and exercise discovery, all three parsers,
PEER evidence, paging, Unicode fetch, argument errors, cache eviction, lifespan
cleanup and an actual stdio subprocess connection. The MCP tests skip if FastMCP
is absent, so the base bindings do not require a server framework.

Validation passed for the six MCP cases plus the existing evidence-marker
regression. The documented client example and local Streamable HTTP discovery,
search and fetch also passed. The native test build used IB `7726ce2` with the
Linux build fixes described in the programmer's guide; macOS was not tested.

The demo uses the evidence-marker fix in the programmer-documentation branch.
It does not change the native engine or the binding API.
