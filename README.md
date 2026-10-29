# CoreQuarry for Python

Optional nanobind bindings for the current [IB engine](https://github.com/re-Isearch/ib).
The Python import is `corequarry`. This repository contains the bindings and
Python conveniences. IB remains a separate C++ dependency.

This first prototype covers file ingestion and search. It exposes
IDB, VIDB, SQUERY, QUERY, IRSET, IRESULT, RSET, RESULT, MDT, MDTREC, RECORD and
the term, attribute, operator, datatype and span types needed to use them.

## Build

Use Python 3.10 or newer, a C++17 compiler, CMake and GNU dbm development files.
Nanobind and scikit-build-core are supplied by Python build isolation.

```sh
python -m pip install . -Ccmake.define.COREQUARRY_IB_SOURCE_DIR=/path/to/ib
```
The binding consumes IB's compiler definitions so its public types match the
engine. `BUILD_LARGE_INDEX` defaults to ON. Set it explicitly to match the indexes
you use. `gptype_bits` and `index_id_bits` expose the resulting widths.

The default build supports lexical and scalar typed search without Schmate.
Enable `BUILD_VECTOR_INDEX` and supply IB's Schmate settings for vector support.
The extension and engine component libraries are installed inside the Python
package. GNU dbm remains a required platform library. Public wheel distribution
will also require platform-specific dependency repair.

## Append files

```python
import corequarry as cq

stats = cq.index_files(
    "WIKI", ["part-1.ndjson", "part-2.ndjson"],
    doctype="CIRRUSNDJSON", merge=cq.Merge.ZIP,
)
print(stats.records_added)
```

Append is the default. Merge policy is a separate choice. `Merge.NONE` is the
default and writes new shards. ZIP merges at the end of the queued batch.
Other policies are OPTIMIZE, MERGE, COLLAPSE and INCREMENTAL. `append=False`
explicitly requests replacement indexing. Source files must remain available.
`memory_mb` defaults to 256 for the indexing buffer budget; set zero for IB's
automatic selection. It is a tuning parameter, not a limit on process RSS.

For incremental control, open IDB, call `add_file()` or `add_record(RECORD)` as
needed, then call `index()`. Search-only handles reject indexing operations.

## Queries and result pages

```python
with cq.VIDB("PATENTS") as db:
    query = cq.SQUERY.term("virus").peer(
        cq.SQUERY.term("vaccine"), max_gap=130,
    ).within("CLAIM-TEXT")
    matches = db.search(cq.QUERY(query, normalization=cq.Normalization.E2))
    print(len(matches))
    page = matches.get_rset(10)
    for row in page:
        text, field = row.evidence()
        print(row.score, row.filename, field, text)
```

SQUERY contains the expression. QUERY adds sort and normalization settings.
Search returns IRSET. `get_rset(total, start=0)` materializes a page and does not
restrict query evaluation. `total=None` selects all remaining results and zero
selects none. Python indexing and page starts are zero-based.

`SQUERY.term()` constructs a literal operand, keeping operators and attributes
separate. `&`, `|`, `and_not()`, `peer()`, ordered peers, `within()` and `boost()`
create new expressions. `combine(other, OPERATOR)` and `apply(OPERATOR)` expose
the native algebra. Peer bounds retain exact integer byte spans, including zero.

```python
from decimal import Decimal

price = cq.SQUERY.field("price", Decimal("10.125"),
                        relation=cq.Relation.GE, datatype="numerical")
query = cq.SQUERY.term("laser", field="TEXT") & price
```

Typed query values use their text representation for IB's own datatype parser.
Python integers and Decimal values retain their exact spelling through this
path. `SQUERY.from_rpn`, `from_infix` and `from_words` expose the existing parsers.
STERM, ATTRLIST, OPERATOR, OPSTACK and SetOpstack support lower-level translators.
`SQUERY.operators()` provides IB's operator documentation.

A server can translate its own request syntax directly, without constructing
a textual query. For example, a small application AST could use:

```python
def translate(node):
    if "term" in node:
        return cq.SQUERY.term(node["term"], field=node.get("field", ""))
    left, right = map(translate, node["args"])
    if node["op"] == "and":
        return left & right
    if node["op"] == "peer":
        return left.peer(right, max_gap=node.get("max_gap"))
    raise ValueError("Unsupported application operator")

query = translate({
    "op": "peer", "max_gap": 130,
    "args": [{"term": "virus"}, {"term": "vaccine"}],
})
```

`Operator` exposes the native operator codes; `OPERATOR.argument` and `.metric`
carry field/key arguments and numeric parameters. Use `combine()` for binary
operators and `apply()` for unary operators. The application remains responsible
for validating its request schema and choosing permitted operations.

IRSET also exposes result-set intersection, union, difference, peer and field
operations. These return new sets and preserve their inputs. Sets must originate
from the same database handle. For a federated VIDB, place structural operators
such as PEER and WITHIN in SQUERY before searching: IB then evaluates them within
each volume. This prototype rejects structural IRSET operations after federation,
because the underlying implementation uses a physical index's field cache.
`volume_count` and `get_mdt(volume)` expose the component metadata tables.
`search_smart()` returns `(matches, query)` so
callers can inspect the rewritten QUERY supplied by the smart-search entry point.

## Metadata and lifetimes

```python
with cq.VIDB("PATENTS") as db:
    mdt = db.get_mdt()
    record = cq.MDTREC()
    if mdt.get_entry(1, record):       # Native GetEntry uses one-based indexes.
        print(record.filename)
    first = mdt[0]                    # Python indexing is zero-based.
```

The output-parameter GetEntry overload fills an independently owned MDTREC.
Records retain the database that owns their pathname hash table. Results,
metadata views and rows also retain their native database resources directly.
Reading another entry or running another query does not overwrite an earlier row.

`close()` prevents further operations through that handle and releases its
ownership. Native resources close after its last dependent result/view/record
is released. Existing results can therefore outlive a `with` block.
Indexing through a handle with live dependent views is rejected; use a separate
writer handle for concurrent ingestion and searches.

## Server use

Keep a VIDB open per worker process and construct request-local SQUERY/QUERY
objects. This prototype retains the Python GIL during native calls and has no
Python callbacks into document handlers. Use process workers for parallel calls.
Threaded access and GIL release need a separate audit of the engine's shared
state. File-backed mappings continue to follow IB and operating-system behavior.

Python strings use UTF-8. The low-level STRING conversion accepts bytes too and
uses surrogateescape on output so legacy non-UTF-8 bytes can round-trip.

## Development

```sh
python -m pip install -e '.[test]' -Ccmake.define.COREQUARRY_IB_SOURCE_DIR=/path/to/ib
python -m pytest
```

The integration tests create real indexes, append documents, execute parsed and
programmatic queries, inspect evidence and metadata, and exercise result
lifetimes across subsequent searches and handle closure.

The prototype was built on Linux x86_64 with CPython 3.12 and the engine revision
above plus the companion patch. All 17 tests passed from a separately installed
wheel, including typed NDJSON search, exact PEER bounds, metadata copies, result
lifetimes, append behavior, and evidence from two federated volumes. The installed
extension resolved its IB libraries from inside the package. macOS and optional
vector builds have not yet been validated.

Type stubs and a `py.typed` marker are included for application development.
# CoreQ-Python
# CoreQ-Python
