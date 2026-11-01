# Local web interface

The web example provides a collection selector, query form, field autocomplete,
ranked evidence, paging and source/field retrieval. It uses FastAPI, Jinja and a
vendored copy of HTMX 2.0.11. It runs locally with the installed native IB engine;
no browser dependency downloads or JavaScript build are required at runtime.

## Run the synthetic example

From this repository's root, using the same interpreter for installation and
execution:

```sh
python -m pip install '.[web]' -Ccmake.define.COREQUARRY_IB_SOURCE_DIR=/path/to/ib
python examples/make_web_demo.py web-demo
python examples/web_server.py web-demo/catalog --state-dir web-demo/state
```

Open `http://127.0.0.1:8000`. The builder creates 40 synthetic research notes and
technical briefs, their NDJSON sources, two indexes and a catalog. It requires a
fresh output directory. Keep the sources available for presentation.

Try `virus vaccine PEER:130` with **RPN** syntax. Select both collections to search
them together. Select `BODY`, type `vi`, and the input offers native Scan terms.
You can also select a normalization method and inspect the canonical evaluated
query under the results summary. Click a headline to retrieve its source record;
the record page can retrieve a named field such as `BODY`.

After installation the equivalent CLI is:

```sh
corequarry-web web-demo/catalog --state-dir web-demo/state --port 8000
```

The default listener is loopback. `--host` and `--port` control the listener. The
demo supplies browser session isolation and optional admin authentication, but
does not implement user accounts or per-user collection permissions. Add those
application policies before exposing private collections as a remote service.

## Use existing indexes

Create a catalog directory containing one INI per selectable collection:

```ini
[Collection]
title = Patents
description = Patent descriptions, claims and bibliographic data
database = /Volumes/D50/indexes/PATENTS
```

`database` is an existing physical database or VIDB stem. Relative stems resolve
against the INI's directory. The INI filename without its suffix is the collection
ID. The catalog can also read existing native `[DbInfo]` INI files: each such
file's stem is opened as its native database/VIDB. Copying a native INI alone to
another directory changes that stem; use a `[Collection]` entry to reference it
from elsewhere. Example descriptors are in `examples/web_catalog/`; remove
`.example` after setting valid paths.

Collection IDs are resolved only through the server's startup catalog. Browser
requests do not supply filesystem database paths. For multiple selections the
service creates one reusable `.vdb` description per canonical selection in its
private work directory. It does not write an INI for every query.

The native ABI must match the existing indexes. The normal binding build uses
large indexes; see the [build instructions](../README.md#build).

## Search lifetime and paging

`corequarry.service.SearchStore` is the common backend for this web interface and
the MCP example. Its evaluated searches retain the VIDB, IRSET, expression,
normalization, collection selection, native hit count and evaluation timing.
The standalone web and MCP examples create separate store instances; they share
the implementation, and their result IDs are not interchangeable. A combined
deployment can point both adapters at one worker service with an explicit mapping
of authenticated session owners.

A signed cookie identifies a browser session. Each query gets a separate random
search ID, and each returned result ID identifies a position within that retained
set. Page requests materialize a slice with `get_rset`; they do not rerun the
query. Retrieval uses that same retained set. Another browser session cannot use
those IDs to read the search or record. Browser Back/Forward and result links
preserve search IDs; query definitions and collection IDs are also represented in
the URL so an expired search can be rerun with the form.

The defaults retain at most 32 searches with a 15-minute idle timeout. Expiry is
checked on service access. Native database handles are reused by collection
selection, with up to eight otherwise idle selections cached. Active searches
retain their own handles after database-cache eviction.

The service estimates retained-set memory from record and hit counts. Above the
default 128 MiB estimate it spills older sets to private disk files, restoring
them for subsequent pages. This is a retention estimate, not an RSS or query
execution memory limit. The largest query must still be evaluated in memory.
State is temporary: active search IDs and spill files do not survive a server
restart. The SQLite event history does. Native saved-set APIs can be used by an
application implementing explicit persistent sessions.

A retained result set fixes its evaluated membership and ordering. It is not a
transactional snapshot of all database/source files. The demo does not refresh a
reader after external indexing; restart to reopen updated collections. Keep source
files available and unchanged while presenting their indexed records.

## Workers and interaction

The web process renders HTML and owns browser/job metadata. Two spawned worker
processes own native handles: one retains evaluated searches and handles pages
and retrieval; the other handles short field and Scan requests. The current
bindings hold the GIL, so native searches are not dispatched to Python threads.
The short-request lane remains available while the search worker is occupied.

The browser submits a search and receives a job ID, then uses server-sent events
to learn when it completes or fails. The pending state includes queueing and
evaluation; the application does not manufacture a progress percentage. Closing
the event stream or changing the browser query does not cancel native execution.
There are at most 16 pending jobs. This initial implementation has one native
search worker; additional search workers need explicit routing so each search
ID continues to reach its owning process.
Run one web process for this demo. Adding independent Uvicorn web workers would
also require routing or a shared job/session registry.

Autocomplete uses bounded native Scan requests after a 200 ms input delay.
HTMX replaces stale browser requests. Suggestions are scoped to the selected
collections and field; frequencies are native Scan frequencies, not a promise
of document counts. Field metadata for a federated VIDB follows IB's merged
DFDT behavior, which keeps the first field definition for a repeated name.

## Administration and feedback

Set `COREQUARRY_ADMIN_TOKEN` in the server environment to enable `/admin`. The
browser's HTTP Basic sign-in uses username `admin` and that token as its password.
With no token, the admin routes return 404. Avoid putting the token in a URL or
command-line argument. Serve a remote admin interface through HTTPS.

The admin view lists pending/completed/failed requests and can inspect a retained
search's results. `state-dir/events.sqlite` records completed query definitions,
collection paths, engine revision, normalization and timings. Browser acknowledgments
record impressions with result keys, volumes, displayed ranks and scores; headline
clicks are logged separately. Source retrieval and arbitrary HTTP GET requests are
not automatically counted as clicks. Events are associated with the session and
search ID. The admin view displays the latest 100 events; the database keeps the
full history for subsequent analysis, retention management and ranking evaluation.

Only source text escaped by Jinja is rendered in the document view. Evidence is
escaped before inserting the application's fixed highlight tags.

## Additional binding methods

```python
with cq.VIDB("PATENTS") as db:
    fields = db.fields()  # [{"name": "CLAIM-TEXT", "datatype": "string"}, ...]
    terms = db.scan(field="CLAIM-TEXT", term="vir", limit=12)
    matches = db.search(cq.SQUERY.from_rpn("virus vaccine PEER:130"))
    matches.save("query.cqrs")
    restored = db.load_results("query.cqrs")
```

`scan(field="", term="", limit=20)` returns dictionaries containing `term` and
`frequency`. It delegates expression semantics and ordering to native Scan. The
limit is 0–1000; zero returns an empty list. Native Scan does not scan an empty
term. The service applies a prefix filter to its bounded native output for UI
autocomplete. `fields()` returns copied dictionaries, not borrowed DFDT pointers.

`IRSET.save(path)` and `IDB/VIDB.load_results(path)` use a Python result-file header
around the native IRSET payload. The header checks IB revision, index widths,
database stem, record/word counts and native modification stamp. These files are
distinct from raw C++ `SaveTable` files. Loading rejects a different database,
generation or ABI and retains the supplied database owner. Empty sets round-trip.
Files are trusted application artifacts; do not accept arbitrary uploads for this
native reader. An application's persistent-session manifest must preserve the
database/VIDB definition and its identity.

This explicit generation check also avoids a native clock-comparison problem
observed during validation: MDT modification stamps used local time while the
IRSET payload's save timestamp used UTC, causing a freshly saved set to appear
expired in an eastern timezone. The wrapper validates the saved generation
instead of using that wall-clock comparison. The engine source is unchanged.

## Verification

Install `.[web,mcp,test]`, then run:

```sh
python -m pytest tests/test_search_service.py tests/test_web_demo.py tests/test_mcp_demo.py -q
```

The tests use real NDJSON indexes and spawned native workers. They cover native
fields/Scan, saved sets including empty sets, forced disk spill, unchanged
evaluation counts across pages, multi-collection search, expiry, browser ownership,
SSE completion, escaped evidence/source retrieval, admin authentication, feedback
events and MCP subprocess calls. The existing append replay issue is tracked
separately in [known issues](known-issues.md).

The full suite passed on Linux x86_64 with CPython 3.12: **29 tests passed**.
The native build used IB `7726ce2` and the same Linux compilation fixes used for
the earlier bindings validation. JavaScript syntax and template compilation also
passed. Visual browser QA was unavailable because the managed preview daemon was
absent; HTTP/HTML interactions were checked with the real app and native workers.
macOS has not been validated here.

HTMX's license is included beside the vendored script. The web UI's other assets
are part of this repository.
