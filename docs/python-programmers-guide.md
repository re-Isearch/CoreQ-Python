# Python programmer's guide

`corequarry` exposes IB's indexing, query algebra, result sets, metadata and
source evidence to Python. This guide describes the current `0.1.0a1` binding.
Use the [API reference](python-api-reference.md) for signatures and the
[runnable tour](../examples/python_tour.py) for an executable example.

## Contents

- [Install and check your interpreter](#install-and-check-your-interpreter)
- [A complete first example](#a-complete-first-example)
- [Choose the right objects](#choose-the-right-objects)
- [Index and append documents](#index-and-append-documents)
- [Construct queries](#construct-queries)
- [Use typed fields](#use-typed-fields)
- [Use the operator stack](#use-the-operator-stack)
- [Execute, score and page results](#execute-score-and-page-results)
- [Read evidence and source spans](#read-evidence-and-source-spans)
- [Work with evaluated sets](#work-with-evaluated-sets)
- [Read metadata](#read-metadata)
- [Manage resource lifetimes](#manage-resource-lifetimes)
- [Search several indexes](#search-several-indexes)
- [Build a search service](#build-a-search-service)
- [Handle errors and inspect the installed API](#handle-errors-and-inspect-the-installed-api)

## Install and check your interpreter

Install from this repository using your chosen Python environment:

```sh
python -m pip install . -Ccmake.define.COREQUARRY_IB_SOURCE_DIR=/path/to/ib
python -c 'import corequarry as cq; print(cq.__version__, cq.ib_revision)'
```

IB is a separate C++ source dependency. See the [build instructions](../README.md#build)
for native dependencies and configuration. Index widths must match the indexes
you open. The default build enables `BUILD_LARGE_INDEX` and disables optional
vector support.

```python
import corequarry as cq

print(cq.__version__)       # Python package version
print(cq.ib_revision)       # IB commit used to build the extension
print(cq.gptype_bits)       # Width of source/global position values
print(cq.index_id_bits)     # Width of native result identifiers
print(cq.vector_enabled)   # Whether this build enables native vector support
```

Use the interpreter that built the extension. For example,
`_core.cpython-314-darwin.so` is a Python 3.14 extension. A plain CMake build and
a Python package installation are separate operations; use pip as above, or
stage an existing CMake build:

```sh
cmake --install build --component python --prefix "$PWD/python-install"
PYTHONPATH="$PWD/python-install" python -c 'import corequarry'
```

## A complete first example

This creates three NDJSON records, indexes them, runs a structural query, and
prints evidence. The source files and index live in a temporary directory for
the duration of the example.

```python
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import corequarry as cq

with TemporaryDirectory(prefix="corequarry-") as directory:
    root = Path(directory)
    source = root / "articles.ndjson"
    records = [
        {"title": "Virus vaccine trial", "body": "A virus vaccine study.", "count": 42},
        {"title": "Virus study", "body": "A virus study of a memory system.", "count": 7},
        {"title": "Vaccine response", "body": "An immune response to a vaccine.", "count": 65},
    ]
    source.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    index = root / "articles"

    stats = cq.index_file(index, source, doctype="NDJSON",
                          merge=cq.Merge.ZIP, memory_mb=32)
    assert stats.records_added == 3

    with cq.VIDB(str(index)) as db:
        expression = cq.SQUERY.term("virus").peer(
            cq.SQUERY.term("vaccine"), max_gap=130,
        ).within("BODY")
        matches = db.search(cq.QUERY(expression, normalization=cq.Normalization.E2))
        print("Matching records:", len(matches))
        for row in matches.get_rset(10):
            text, field = row.evidence(max_bytes=160)
            print(row.key, row.score, field, text)
```

For a persistent index, use persistent paths for both the index and its input
files. IB uses the source documents for presentation and evidence. The remaining
examples use `MYINDEX` as an existing index; substitute your database path and
field names.

## Choose the right objects

| Object | Purpose | How to obtain it |
| --- | --- | --- |
| `IDB` | A physical database, including a writer | `cq.IDB(name)` |
| `VIDB` | A search handle over one or several physical databases | `cq.VIDB(name)` |
| `SQUERY` | The expression: terms, attributes and operators | Builders, a parser, or an `OPSTACK` |
| `QUERY` | An expression plus sort and normalization choices | `cq.QUERY(squery, ...)` |
| `IRSET` | Evaluated matches with scores and positional hits | `db.search(...)` |
| `IRESULT` | One internal match | `matches[i]` |
| `RSET` | A materialized result page | `matches.get_rset(...)` |
| `RESULT` | One result with source identity and presentation methods | `page[i]` |
| `MDT` / `MDTREC` | A physical volume's metadata table / an owned entry | `db.get_mdt(...)`, then indexing or `get_entry()` |

Opening a database does not evaluate a query. Evaluating returns an `IRSET`.
Materializing an `RSET` resolves the selected results for presentation. Choose
your page size at that last step.

The convenience functions accept `pathlib.Path` values for database/file paths.
Pass `str(path)` to native-facing constructors such as `IDB`, `VIDB` and `RECORD`.

## Index and append documents

### One file or a batch

```python
stats = cq.index_files(
    "NEWINDEX", ["part-1.ndjson", "part-2.ndjson"],
    doctype="NDJSON", merge=cq.Merge.ZIP,
)
print(stats.records_added, stats.total_records, stats.total_words)
```

This fragment expects the two named files to exist and uses a fresh `NEWINDEX`
database stem. `index_file()` accepts one
file and the same options. `index_files()` queues the files and indexes the batch
once. One input file can contain many records; the document handler defines the
record boundaries, fields and text processing.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `doctype` | `"AUTODETECT"` | IB document handler, for example `PLAINTEXT`, `NDJSON` or `CIRRUSNDJSON` |
| `append` | `True` | Add to the existing index; `False` requests replacement indexing |
| `merge` | `cq.Merge.NONE` | Shard merge policy, independent of `append` |
| `memory_mb` | `256` | Indexing buffer budget in MiB; zero requests IB's automatic selection |
| `doctype_options` | `()` | A sequence of option strings passed to the native document handlers |

`memory_mb` is a tuning parameter, not a process RSS limit. Document-handler
options and their interpretation depend on the selected handler. The helper
returns a frozen `IndexingResult` value with the three counters shown above.

### Current append limitation in the tested native build

The tested Linux build with IB `7726ce2` replayed earlier inputs when appending
a later file. This was observed with NDJSON and plain text. Reopening the writer
in a separate process did not avoid the NDJSON case. See the
[reproducer and observed counts](known-issues.md). Queue a complete initial batch
into a fresh index stem, and validate incremental behavior against your build.
The runnable tour demonstrates fresh-batch indexing.

| Merge policy | Behavior |
| --- | --- |
| `NONE` | Write shards without an automatic full merge |
| `ZIP` | Merge at the end of the batch using IB's multiway merge path |
| `OPTIMIZE` | Optimize at the end of indexing; current IB also uses the merge path |
| `MERGE` | Merge during indexing |
| `COLLAPSE` | Collapse the last two subindexes |
| `INCREMENTAL` | Collapse at the end when the subindex count exceeds two |

### Control the record and the indexing step

Use `RECORD` when you need to supply a key or source range yourself. This example
creates a separate index for one plain-text record:

```python
from pathlib import Path

note = Path("note.txt").resolve()
note.write_text("A laser processor note.\n", encoding="utf-8")
record = cq.RECORD(str(note))
record.doctype = "PLAINTEXT"
record.key = "python-note"

with cq.IDB("NOTES", search_only=False) as writer:
    if not writer.add_record(record):
        raise RuntimeError("Could not queue the record")
    if not writer.index(merge=cq.Merge.ZIP, memory_mb=32):
        raise RuntimeError("Could not index the queued records")
```

`add_file(path, doctype=...)` is the corresponding native-facing file helper.
Both methods queue work; `index()` performs it. `IDB` defaults to
`search_only=False`; `VIDB` defaults to `search_only=True`.

`RECORD.start` and `.end` let you describe a source-file byte range with inclusive
endpoints. Leave the constructor's range alone for the ordinary whole-file case.
The document handler can split an input record into further records.

## Construct queries

### Build expressions directly

```python
virus = cq.SQUERY.term("virus")
vaccine = cq.SQUERY.term("vaccine")

both = virus & vaccine
either = virus | vaccine
only_virus = virus.and_not(vaccine)
exactly_one = virus ^ vaccine
assert virus.term_count == vaccine.term_count == 1
```

These operations return new expressions and preserve their operands. Use `&`,
`|` and the methods shown here for query algebra. Python's `and`, `or` and `not`
perform Python truth-value operations. Parentheses make complex query composition
explicit.

`SQUERY.term()` makes a term operand, keeping the text separate from query
syntax. A term spelled `"AND"` is therefore an operand. Native tokenization,
case handling and the document handler's indexing rules still determine matches.

```python
title_term = cq.SQUERY.term("virus", field="TITLE")
prefix_term = cq.SQUERY.term("vacc", prefix=True)
phrase_term = cq.SQUERY.term("virus vaccine", phrase=True)
weighted_term = cq.SQUERY.term("virus", weight=2.0)
weighted_expression = both.boost(2.0)
```

Use field attributes on each term when each operand must occur in that field.
`within(field)` is the native unary filter on retained hits. To require two
operands in the same instance of a named field, use `AND_WITHIN` as shown under
[the operator stack](#use-the-operator-stack).

### Positional and structural operators

```python
peers = virus.peer(vaccine)                        # Native unbounded PEER
near_peers = virus.peer(vaccine, max_gap=130)       # PEER:130
ordered = virus.before_peer(vaccine, max_gap=130)  # PEERb:130
reverse = virus.after_peer(vaccine, max_gap=130)   # PEERa:130
body_peers = near_peers.within("BODY")
print(body_peers.rpn)
```

PEER requires the operand hits to share the same immediate, non-root structural
container. A bound limits the number of intervening source bytes for that same
pair. An ordered peer also requires the left operand to occur before or after
the right.

`max_gap=None` selects the unbounded form. Zero allows adjacent or overlapping
hits while applying the same structural test.
Bounds must be nonnegative Python integers within the build's `GPTYPE` range;
booleans and floating-point values are rejected. The helpers preserve integer
bounds exactly, including values beyond the exact range of a binary64 float.

### Parse existing query languages

```python
rpn = cq.SQUERY.from_rpn("virus vaccine PEER:130")
infix = cq.SQUERY.from_infix("virus AND vaccine")
words = cq.SQUERY.from_words("virus vaccine")
print(rpn.rpn, rpn.term_count)
```

These are IB's existing parsers. `from_words()` uses IB's word-query construction;
use an explicit expression when you need a particular operator. The RPN and infix
factory methods raise `ValueError` when parsing fails. Their mutating counterparts
`SetRpnTerm()` and `SetInfixTerm()` return native status/count values;
`LastErrorMessage()` supplies the parser diagnostic.

## Use typed fields

The query value is converted to text and parsed by IB in the requested datatype.
Use the datatype actually indexed for the field; a query attribute does not
convert or rebuild an index sidecar.

```python
from decimal import Decimal

count_filter = cq.SQUERY.field("COUNT", 40,
    relation=cq.Relation.GE, datatype="integer")
price_filter = cq.SQUERY.field("PRICE", Decimal("10.125"),
    relation=cq.Relation.GE, datatype="numerical")
filtered = cq.SQUERY.term("virus") & count_filter
```

Python `int`, `Decimal` and string values preserve their spelling through this
path. A Python `float` has already undergone floating-point conversion before
the binding sees it. Native datatype precision, parsing and range limits still
apply. `SQUERY.field()` defaults to equality; its `datatype` defaults to an empty
attribute, letting native field resolution apply.

| Native datatype name | Typical Python query value |
| --- | --- |
| `integer` | `int` or an integer string |
| `numerical` | `Decimal` or a decimal string for fixed-point numerical fields |
| `float64` | `float` or a numeric string for binary64 fields |
| `currency` | A decimal/monetary string accepted by IB's currency parser |
| `date`, `date-range` | A string accepted by the corresponding IB date parser |

`Relation` exposes `LT`, `LE`, `EQ`, `GE`, `GT`, `NE`, `OVERLAPS`, `WITHIN` and
`ENCLOSES`, plus `DEFAULT`. Choose relations supported by the field's datatype.
`cq.FIELDTYPE("integer")` validates a native datatype name; it is useful when
working with `ATTRLIST` directly.

## Use the operator stack

`combine()` and `apply()` expose operators beyond the convenience methods.
Here is `virus vaccine AND:BODY`, requiring a common BODY field instance:

```python
same_body = cq.OPERATOR(cq.Operator.AND_WITHIN)
same_body.argument = "BODY"
expression = virus.combine(vaccine, same_body)

proximity = cq.OPERATOR(cq.Operator.PROXIMITY)
proximity.metric = 130.0
positional = virus.combine(vaccine, proximity)
```

`combine()` requires a binary operator; `apply()` requires a unary operator.
`OPERATOR.argument` holds string arguments such as field names, and `.metric`
holds native floating-point parameters. Use the peer helpers for exact integer
PEER bounds.

For an application with its own query AST, construct `STERM`, `ATTRLIST` and an
`OPSTACK` directly. Push operands first and then their operator:

```python
attributes = cq.ATTRLIST()
attributes.field = "TITLE"

left, right = cq.STERM(), cq.STERM()
left.text, right.text = "virus", "vaccine"
left.attributes = attributes
right.attributes = attributes

stack = cq.OPSTACK()
stack.push(left)
stack.push(right)
stack.push(cq.OPERATOR(cq.Operator.AND))

stack_query = cq.SQUERY()
stack_query.SetOpstack(stack)
```

Push and `SetOpstack()` copy their inputs. `STERM.attributes`, `QUERY.squery`
and `SQUERY.GetOpstack()` also return copies. To change such a property, edit the
copy and assign it back. For example:

```python
attributes = left.attributes
attributes.weight = 2.0
left.attributes = attributes
```

Use the installed engine's operator catalog to inspect arity, syntax and meaning:

```python
for entry in cq.SQUERY.operators():
    print(entry["name"], entry["arity"], entry["syntax"], entry["description"])
```

The catalog includes source operators such as KEY/FILE and reserved forms.
Consult its arity and description rather than assuming every enum value is a
binary operator supported in every result-set context.

## Execute, score and page results

```python
with cq.VIDB("MYINDEX") as db:
    request = cq.QUERY(
        cq.SQUERY.term("virus"),
        sort=cq.SortBy.SCORE,
        normalization=cq.Normalization.E2,
    )
    matches = db.search(request)
    total = len(matches)
    first_page = matches.get_rset(10, start=0)
    next_page = matches.get_rset(10, start=10)
    print(total, len(first_page))
```

You can also call `db.search(squery, sort=..., normalization=...)` directly.
The convenience `cq.search(database, expression, ...)` opens a VIDB and returns
an owned `IRSET`; `expression` may be `SQUERY`, `QUERY`, or a string with
`syntax="infix"`, `"rpn"` or `"words"`. When it is a `QUERY`, the settings in
that object are used.

`get_rset()` limits materialization, not query evaluation. `start` is zero-based.
`total=None` selects the remaining matches; zero selects none. An out-of-range
start returns an empty page. Store `len(matches)` for the query total: an empty
page constructed by the binding does not carry that total in `page.total_found`.

`IRSET`, `RSET`, `MDT` and `HITTABLE` support `len()`, iteration and integer
indexing, including negative indexes. Slicing is not exposed. Out-of-range
integer indexing raises `IndexError`.

`matches.sort_by(...)` sorts the evaluated set in place before paging.
`page.sort_by(...)` sorts only that materialized page. `matches.copy()` gives an
independent set when you want to preserve the previous ordering.

Select normalization in `QUERY` before searching. `IRSET.normalize(method,
weight=1.0)` exposes native score computation for evaluated sets. Scores are
native numeric scores; do not assume the command-line display's 0–100 scale.
The reference lists the sort and normalization enums. A selectable enum alone
does not supply vector data or an embedding pipeline.

`db.search_smart(request, default_field="")` returns `(matches, returned_query)`.
The latter carries the query feedback supplied by IB's smart-search entry point.
Treat it as a diagnostic, not a complete execution plan; that feedback can depend
on the native path taken. Build explicit operators when application semantics
must be fixed.

## Read evidence and source spans

```python
with cq.VIDB("MYINDEX") as db:
    matches = db.search(cq.SQUERY.term("virus").peer(cq.SQUERY.term("vaccine")))
    for row in matches.get_rset(5):
        text, field = row.evidence(max_bytes=160, before="**", after="**")
        print(row.filename, row.key, row.score, field, text)
        print(db.headline(row))
        print(db.get_field_data(row, "TITLE"))  # str, or None when unavailable
```

`RESULT.evidence()` returns `(text, field_name)`. The default markers are `**`;
empty markers return plain text. `max_bytes` controls the native display-window
request. Container boundaries, presentation and inserted markers can affect the
returned text's length.

For structured evidence, use `get_evidence_covers(max_covers=3)` and
`get_display_evidence(max_bytes=130)`:

```python
with cq.VIDB("MYINDEX") as db:
    matches = db.search(cq.SQUERY.term("virus"))
    if len(matches):
        row = matches.get_rset(1)[0]
        for cover in row.get_evidence_covers(3):
            print(cover.extent, cover.energy, cover.dispersion)
        display = row.get_display_evidence(160)
        if display.has_container:
            print(display.container_name, display.container_extent)
        print(display.display_extent)
```

`row.get_record_data()` presents the record through its document handler.
`db.summary(row)` and `db.headline(row)` are document-handler presentation
operations too. Call the database methods on the handle that produced the row.
Their output can be empty when the handler does not provide that presentation.

### Coordinate conventions

| Value | Coordinate system |
| --- | --- |
| `RECORD.start/end`, `RESULT.start/end`, `MDTREC.start/end` | Byte offsets within the source file; inclusive endpoints |
| `IRESULT.hits` | Native global index positions |
| `RESULT.hits` | Positions relative to the record's source start |
| Evidence extents from a `RESULT` | Record-relative source coordinates |
| `FC.length` | Inclusive byte length, or zero for an empty FC |

`FCHIT` extends `FC` with a `source_id` for query-operand provenance. It is not a
document identifier. For example, `cq.FC(100, 109).length` is 10. An empty FC has
`.empty == True`; check this before using its endpoints.

These are byte positions, not Python string character indexes. UTF-8 decoding
and document-handler transformations such as entity resolution can change the
relationship to a displayed string. Use the evidence/presentation methods when
displaying hits rather than slicing a decoded string with byte coordinates.

## Work with evaluated sets

Use one open database handle when composing `IRSET` values:

```python
with cq.VIDB("MYINDEX") as db:
    a = db.search(cq.SQUERY.term("virus"))
    b = db.search(cq.SQUERY.term("vaccine"))
    intersection = a & b
    union = a | b
    difference = a.and_not(b)
    union.sort_by(cq.SortBy.SCORE)
    print(len(a), len(b), len(intersection), len(union))
```

These algebra operations return new sets and preserve their inputs. Set
`peer(other, max_gap=None)` and `within(field)` are also exposed for a physical
index. Structural operations on an already federated VIDB set are rejected;
put them in the `SQUERY` before searching instead.

Sets from different handles are rejected, even if both handles opened the same
database name. In particular, two separate `cq.search(...)` convenience calls
create different handles. Combine expressions first, or use a shared `VIDB`.

## Read metadata

```python
with cq.VIDB("MYINDEX") as db:
    table = db.get_mdt()                  # Physical volume 1
    if len(table):
        first = table[0]                 # Python indexing: zero-based
        output = cq.MDTREC()
        assert table.get_entry(1, output) # Native GetEntry index: one-based
        print(first.key, output.filename, output.start, output.end)
        position = table.lookup_key(first.key)
        assert position > 0
        same_record = table[position - 1]
```

`lookup_key()` returns a one-based metadata position, or zero when not found.
`get_entry(index, output)` fills the supplied `MDTREC` and returns a boolean.
Each new MDTREC is an independent value. Reusing the same output object replaces
its contents; use a new object, or `table[i]`, for each entry you retain.

To find metadata for a result, use its native `mdt_index` with the appropriate
physical volume:

```python
with cq.VIDB("MYINDEX") as db:
    matches = db.search(cq.SQUERY.term("virus"))
    if len(matches):
        row = matches.get_rset(1)[0]
        table = db.get_mdt(row.virtual_index or 1)
        record = cq.MDTREC()
        assert table.get_entry(row.mdt_index, record)
        print(record.key, record.doctype, record.date.iso)
```

`get_mdt(volume)` takes one-based volume numbers. A single physical database's
results can use virtual index zero; federated results use their volume numbers.
An MDT index belongs to its volume, not to the combined result ordering.

## Manage resource lifetimes

Database handles support `with` and explicit `close()`:

```python
with cq.VIDB("MYINDEX") as db:
    matches = db.search(cq.SQUERY.term("virus"))
    page = matches.get_rset(1)
    retained = page[0] if len(page) else None

assert db.closed
if retained is not None:
    text, field = retained.evidence()     # Retains its native database resource
```

Closing the Python handle prevents further operations through that handle.
Existing result sets, result rows, metadata tables and loaded metadata records
retain the native database resources they need. A later query or metadata lookup
does not overwrite an earlier copied row.

Release these objects when finished: retaining them also retains native files
and mappings. Loading the filename of an unfilled `MDTREC()` raises an error;
load it from an MDT first.

Indexing through a handle with live dependent sets, rows or metadata views raises
`RuntimeError`. Finish using those views before calling that handle's `index()`.
Use a separate writer handle for ingestion alongside readers; the
[append limitation](known-issues.md) still applies. Resource retention
is not a Python transaction or snapshot API; reader freshness/reopening is an
application policy. No explicit Python `refresh()` method is exposed yet.

## Search several indexes

A VIDB opens the normal IB virtual-database configuration. For example, a
`COLLECTION.vdb` file can list physical database stems, one per line:

```text
/data/indexes/news
/data/indexes/patents
```

```python
with cq.VIDB("COLLECTION") as db:
    print(db.volume_count, db.total_records)
    expression = cq.SQUERY.term("virus").peer(
        cq.SQUERY.term("vaccine"), max_gap=130,
    )
    matches = db.search(expression)
    for row in matches.get_rset(10):
        print(row.virtual_index, row.filename)
```

Structural operators in the expression are evaluated within the component
indexes. The prototype rejects post-search `IRSET.peer()` and `.within()` for a
multi-volume VIDB because their native implementations use a physical index's
field cache. Use `get_mdt(volume)` for a component metadata table.

## Build a search service

Keep a `VIDB` open per worker process and construct request-local expressions.
Here is a small application query translator; the application defines and
validates its own request schema:

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

def search_page(db, node, start=0, page_size=10):
    expression = translate(node)
    matches = db.search(cq.QUERY(expression, normalization=cq.Normalization.E2))
    rows = []
    for row in matches.get_rset(page_size, start=start):
        text, field = row.evidence(before="", after="")
        rows.append({"key": row.key, "volume": row.virtual_index, "score": row.score,
                     "evidence": text, "field": field})
    return {"total": len(matches), "rows": rows}
```

For example:

```python
import json

with cq.VIDB("MYINDEX") as db:
    response = search_page(db, {
        "op": "peer", "max_gap": 130,
        "args": [{"term": "virus"}, {"term": "vaccine"}],
    })
    print(json.dumps(response))
```

The returned dictionary contains ordinary Python values suitable for JSON.
For federated client identifiers, retain the volume alongside the physical
record key; `RESULT.key` is not a synthesized global key.
Pagination controls result materialization. The binding currently keeps the
Python GIL during native calls and has no Python document-handler callbacks;
use process workers for parallel searches. Open native handles inside each
worker, including when using Python's multiprocessing spawn model. Threaded
native access, GIL release and free-threaded operation have not been audited.
Pass database names and ordinary request values to workers, and create the
native handles inside them. Read-only file mappings can share physical pages
through the operating system; Python objects and native per-process caches
retain their own lifetimes.

The current Python API includes native vector-related datatype names and the
HYBRID normalization selection. `vector_enabled` reports the build capability.
A Python embedding-generation or HNSW-management API is not part of this first
binding; build-specific native support and suitable indexed data are required.

## Handle errors and inspect the installed API

| Exception or result | Typical meaning |
| --- | --- |
| `ValueError` | Invalid parsed query, unknown datatype, invalid operator arity, or combining sets from different handles |
| `TypeError` / conversion error | Wrong argument type, embedded NUL input, or an out-of-range native integer |
| `IndexError` | Container index or metadata volume is out of range |
| `RuntimeError` | Closed/read-only handle operation, live views blocking indexing, unsupported federated set operation, or a native operation failed |
| Empty `IRSET` | A valid search found no matching records |
| `None` from `get_field_data()` | The requested field data could not be obtained |

Exact conversion exception classes can vary by argument and nanobind path. The
convenience indexing helpers raise `RuntimeError` when queueing or indexing
returns false; the corresponding `IDB` methods expose the boolean. Native IB
diagnostics can contain further details.

Python strings are encoded as UTF-8. The low-level STRING conversion also
accepts `bytes` and uses `surrogateescape` on output to preserve legacy byte
values. Embedded NUL input is rejected. Spans remain byte coordinates.

The [API reference](python-api-reference.md) lists the bound interface. Use
`help(cq.SQUERY)` or the shipped [_core.pyi](../src/corequarry/_core.pyi) in your
editor for signatures. Native C++ methods absent from that interface, including
set persistence and Python subclass callbacks, are not implicitly available in
Python.
