# Python API reference

This is the bound `corequarry` interface for `0.1.0a1`. See the
[programmer's guide](python-programmers-guide.md) for workflows and a complete
example. The shipped [_core.pyi](../src/corequarry/_core.pyi) supplies editor
signatures; [bindings/core.cxx](../bindings/core.cxx) defines the native adapters.

Names containing capitals are Python classes corresponding to IB concepts.
The binding exposes the methods below, rather than every method of each C++
class. A `/` in a signature marks positional-only arguments. Native STRING
arguments accept `str` and, at runtime, legacy `bytes`; the convenience path
helpers also accept `PathLike[str]`.

## Module functions and values

```text
index_files(database, paths, *, doctype="AUTODETECT", merge=Merge.NONE,
            append=True, doctype_options=(), memory_mb=256) -> IndexingResult
index_file(database, path, **options) -> IndexingResult
search(database, expression, *, syntax="infix", sort=SortBy.SCORE,
       normalization=Normalization.DEFAULT) -> IRSET
```

`index_files()` queues a batch and indexes it once. `index_file()` forwards the
same options for one file. They raise `RuntimeError` if queueing/indexing returns
false. `append=False` requests replacement indexing. See the
[known append issue](known-issues.md) for a replay observed in the tested
native build. `memory_mb` is a MiB buffer
budget; zero requests native automatic selection.

`IndexingResult` is a frozen dataclass with integer fields `records_added`,
`total_records` and `total_words`.

`search()` accepts `SQUERY`, `QUERY`, or a query string. String syntax is `infix`,
`rpn` or `words`; an unsupported string-parser selection raises `ValueError`. A passed
`QUERY` supplies its own sort and normalization settings. The returned `IRSET`
retains its native database resources.

| Value | Type | Meaning |
| --- | --- | --- |
| `__version__` | `str` | Python package version |
| `ib_revision` | `str` | Native dependency's Git commit recorded at build time |
| `gptype_bits` | `int` | Width of `GPTYPE` source/global positions |
| `index_id_bits` | `int` | Width of native `INDEX_ID` identifiers |
| `vector_enabled` | `bool` | Native vector feature enabled in this build |

## IDB and VIDB

```text
IDB(name, search_only=False, doctype_options=())
VIDB(name, search_only=True, doctype_options=())
```

`IDB` opens a physical database. `VIDB` opens a physical or configured virtual
database. Both implement `with`, `.close()` and a `.closed` property. Native-facing
path arguments require strings; use `str(path)` for a `pathlib.Path`.

| Property | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | Native database stem |
| `total_records` | `int` | Native record count |
| `total_words` | `int` | Native word count |
| `volume_count` | `int` | Physical component count; one for IDB |
| `closed` | `bool` | Whether this Python handle has been closed |

```text
add_file(path, doctype="AUTODETECT") -> bool
add_record(record, /) -> bool
index(append=True, merge=Merge.NONE, memory_mb=256) -> bool
search(query: QUERY) -> IRSET
search(query: SQUERY, sort=SortBy.SCORE,
       normalization=Normalization.DEFAULT) -> IRSET
search_smart(query: QUERY, default_field="") -> tuple[IRSET, QUERY]
get_mdt(volume=1) -> MDT
headline(result, /) -> str
summary(result, /) -> str
get_field_data(result, field, /) -> str | None
GetVersionID() -> str
SetLocale(locale, /) -> bool
close() -> None
```

Queueing is separate from `index()`. Indexing requires a writer handle and no
live dependent sets/rows/metadata views through that handle. A closed handle
rejects database operations; retained results/views keep native resources alive.

`get_mdt()` uses one-based volume numbers. IDB accepts only volume 1.
`headline`, `summary` and `get_field_data` use the document handlers; supply a
result produced by this database. `GetVersionID` and `SetLocale` retain their
native spellings. Choose locale consistently with the indexed data.

## SQUERY and QUERY

```text
SQUERY()
SQUERY(other, /)
SQUERY.term(text, field="", datatype="", relation=Relation.DEFAULT,
            weight=1.0, phrase=False, prefix=False) -> SQUERY
SQUERY.field(name, value, relation=Relation.EQ, datatype="") -> SQUERY
SQUERY.from_rpn(text, /) -> SQUERY
SQUERY.from_infix(text, /) -> SQUERY
SQUERY.from_words(text, /) -> SQUERY
SQUERY.operators() -> list[dict]
```

`term()` creates an operand directly; empty text and embedded NUL input are
rejected. `field()` passes `str(value)` to the native datatype parser. Unknown
nonempty datatype names raise `ValueError`. RPN/infix factories raise
`ValueError` on parser failure. Word-query construction follows native policy.

| Expression/method | Result |
| --- | --- |
| `a & b`, `a | b`, `a ^ b` | New AND, OR, XOR expression |
| `a.and_not(b)` | New difference expression |
| `a.peer(b, max_gap=None)` | PEER, optionally bounded by an exact integer byte gap |
| `a.before_peer(b, max_gap=None)` | Ordered PEERb |
| `a.after_peer(b, max_gap=None)` | Ordered PEERa |
| `a.within(field)` | New unary native field restriction |
| `a.boost(weight)` | New score-boost expression |
| `a.combine(other, operator)` | New expression using a binary OPERATOR |
| `a.apply(operator)` | New expression using a unary OPERATOR |
| `a.term_count` | Number of terms |
| `a.rpn`, `str(a)`, `a.GetRpnTerm()` | Native RPN rendering |

Builder/algebra methods preserve their input expressions. PEER bounds reject
negative values, bools, floats and integers outside the build's `GPTYPE` range.
`None` means unbounded; zero is a real bound.

The lower-level mutators/accessors are:

```text
SetOpstack(stack, /) -> None
GetOpstack() -> OPSTACK
SetRpnTerm(text, /) -> int
SetInfixTerm(text, /) -> int
LastErrorMessage() -> str
SetAttributes(attributes, replace=True) -> int
```

The stack operations copy values. Parser mutators return native status/count
values. Operator catalog dictionaries have keys `code`, `name`, `arity`,
`syntax` and `description`.

```text
QUERY(squery, sort=SortBy.SCORE, normalization=Normalization.DEFAULT)
```

QUERY properties `squery`, `sort` and `normalization` are writable; `term_count`
is read-only. The `squery` getter returns a copy; assign it back after editing.

## Low-level query objects

| Type | Constructor | Properties / methods |
| --- | --- | --- |
| `FIELDTYPE` | `FIELDTYPE(name)` | Read-only `name`; `str(value)` returns the native name |
| `ATTRLIST` | `ATTRLIST()` | Writable `field: str`, `datatype: FIELDTYPE`, `relation: int`, `weight: float`, `phrase: bool`, `prefix: bool` |
| `STERM` | `STERM()` | Writable `text: str`, `attributes: ATTRLIST` |
| `OPERATOR` | `OPERATOR(code)` | Writable `code: Operator`, `metric: float`, `argument: str` |
| `OPSTACK` | `OPSTACK()` | `push(STERM)` and `push(OPERATOR)` copy their arguments |

Use `Relation.GE.value`, for example, when assigning the integer-valued
`ATTRLIST.relation`; high-level builders take `Relation` enum members directly.
`STERM.attributes` returns a copy; edit and assign back. The stack's Python
interface currently exposes construction, not pop/iteration operations.

## IRSET and IRESULT

`IRSET` is returned by search and set algebra; it has no public Python
constructor. It supports `len()`, iteration and integer indexing, including
negative indexes. Indexing returns an owned `IRESULT` value.

```text
copy() -> IRSET
sort_by(sort, /) -> None
normalize(method, weight=1.0) -> None
get_rset(total=None, start=0) -> RSET
and_not(other, /) -> IRSET
peer(other, max_gap=None) -> IRSET
within(field, /) -> IRSET
```

`a & b` and `a | b` are also exposed. Set algebra, `peer()` and `within()` return
new sets and preserve inputs; `sort_by()` and `normalize()` mutate the receiver.
`hit_total` is a read-only native aggregate hit count.

Binary set operations require the same database handle, including its ownership
identity. Structural post-search operations on a multi-volume VIDB are rejected;
place structural operators in SQUERY before searching the VIDB.

`get_rset()` materializes a page. It does not limit evaluation. `start` is
zero-based and nonnegative; `total=None` means all remaining matches and zero
means none. A start past the end returns an empty RSET. Slices are not exposed.

| IRESULT property | Type | Meaning |
| --- | --- | --- |
| `score` | `float` | Native score |
| `hit_count` | `int` | Native match hit count |
| `hits` | `HITTABLE` | Global index-coordinate hits |
| `mdt_index` | `int` | One-based entry number in its physical MDT |
| `virtual_index` | `int` | Physical volume identifier; can be zero for a single database |

## RSET and RESULT

`RSET` is returned by `IRSET.get_rset()`. It supports `len()`, iteration and
integer/negative indexing, which returns an owned RESULT. No public constructor
or slicing interface is exposed.

- `sort_by(sort, /)` sorts the page in place.
- `hit_total` is the page's native aggregate hit count.
- `total_found` carries the native total on materialized pages. Empty pages
  constructed by the binding start with zero; use `len(irset)` as the query total.

RESULT properties are read-only:

| Properties | Type / meaning |
| --- | --- |
| `key`, `filename`, `doctype` | `str`: record key, source pathname and document handler name |
| `score` | `float`: native score |
| `date` | `SRCH_DATE` |
| `start`, `end` | Inclusive source-file byte offsets |
| `hits` | `HITTABLE` with record-relative coordinates |
| `mdt_index`, `virtual_index` | Native metadata position / volume identifier |

Record keys belong to their physical database. Include the volume when forming
identifiers across a federated VIDB.

```text
evidence(max_bytes=130, before="**", after="**") -> tuple[str, str]
get_evidence_covers(max_covers=3) -> list[EVIDENCE_COVER]
get_display_evidence(max_bytes=130) -> DISPLAY_EVIDENCE
get_record_data() -> str
```

`evidence()` returns `(text, field_name)` and raises `RuntimeError` if presentation
fails. It and `get_record_data()` use the record's document handler. Display-window
sizes are native byte-window requests, not Python character-count limits.

| Evidence type | Read-only properties |
| --- | --- |
| `EVIDENCE_COVER` | `extent: FC`, `energy: float`, `dispersion: float` |
| `DISPLAY_EVIDENCE` | `cover: EVIDENCE_COVER`, `display_extent: FC`, `container_extent: FC`, `container_name: str`, `has_container: bool` |

Check `has_container` before interpreting the container fields. RESULT-derived
evidence coordinates are relative to the record. Textual byte coordinates
should be interpreted with the document handler, particularly for UTF-8 and
entity-resolving formats.

## MDT and MDTREC

`MDT` is returned by `db.get_mdt(volume=1)` and has no public constructor. It
supports `len()`, iteration and integer/negative indexing. `table[i]` returns
an owned MDTREC using zero-based Python indexing.

```text
get_entry(index, record) -> bool
lookup_key(key, /) -> int
```

`get_entry()` uses native **one-based** entry numbers and fills an existing
MDTREC. It returns false for zero/out-of-range entry numbers. `lookup_key()`
returns a one-based position or zero for not found.

`MDTREC()` constructs an output record. Once loaded, its read-only properties
are `key`, `filename`, `doctype`, `start`, `end` and `date`. Start/end are
inclusive source-file byte positions; date is `SRCH_DATE`. Resolving `filename`
before loading the record raises `RuntimeError`. Records retain the native
database behind their pathname table; reusing an output record overwrites that
record's value.

## RECORD, dates and spans

| Type | Construction | Interface |
| --- | --- | --- |
| `RECORD` | `RECORD()` or `RECORD(filename)` | Writable `filename`, `key`, `doctype`, `start`, `end` |
| `SRCH_DATE` | `SRCH_DATE()` or `SRCH_DATE(text)` | Read-only `ok`, `iso`; `str(date)` uses native ISO rendering |
| `FC` | `FC()` or `FC(start, end)` | Writable `start`, `end`; read-only `length`, `empty`; `contains(fc, /)` |
| `FCHIT` | `FCHIT(start, end, source_id=0)` | Extends FC; read-only `source_id` |
| `HITTABLE` | Returned by result `.hits` | `len()`, iteration and integer/negative indexing returning FCHIT values |

FC endpoints are inclusive bytes. Its coordinate origin depends on where the
FC came from: raw internal hits are global; RESULT hits and evidence are
record-relative. `source_id` identifies query-source provenance, not a document.
An empty FC's endpoints should not be interpreted as valid source positions.

SRCH_DATE is a native date value, not an automatic Python `datetime` conversion.

## Enums

Use enum members rather than hard-coded integer codes.

| Enum | Members |
| --- | --- |
| `Merge` | `NONE`, `OPTIMIZE`, `MERGE`, `COLLAPSE`, `INCREMENTAL`, `ZIP` |
| `SortBy` | `UNSORTED`, `SCORE`, `DATE`, `REVERSE_DATE`, `HITS`, `KEY`, `INDEX`, `AUX_COUNT` |
| `Normalization` | `NONE`, `L2`, `L1`, `BM25`, `E2`, `HYBRID`, `MAX`, `DEFAULT` |
| `Relation` | `DEFAULT`, `LT`, `LE`, `EQ`, `GE`, `GT`, `NE`, `OVERLAPS`, `WITHIN`, `ENCLOSES` |

`Normalization.DEFAULT` currently aliases L2. Relation meanings depend on the
indexed datatype. Native feature availability and input data determine whether
a normalization or datatype is applicable.

`Operator` exposes the following codes; `SQUERY.operators()` supplies native
descriptions, arities and textual syntax. Code names and textual aliases can
differ, and some forms are reserved or implementation-dependent.

| Family | Operator members |
| --- | --- |
| Set logic | `AND`, `OR`, `AND_NOT`, `XOR`, `XNOR`, `NOT_AND`, `NAND`, `NOR`, `NOT` |
| Comparisons | `LT`, `LE`, `GT`, `GE` |
| Positional | `PROXIMITY`, `BEFORE`, `AFTER`, `ADJ`, `FOLLOWS`, `PRECEDES`, `NEAR`, `FAR`, `NEIGHBOR` |
| Structural | `PEER`, `PEER_BEFORE`, `PEER_AFTER`, `XPEER`, `ANCESTOR`, `SIBLING` |
| Fields | `WITHIN`, `XWITHIN`, `NOT_WITHIN`, `INSIDE`, `INCLUSIVE`, `AND_WITHIN`, `OR_WITHIN`, `BEFORE_WITHIN`, `AFTER_WITHIN` |
| Joins | `JOIN`, `JOIN_LEFT`, `JOIN_RIGHT` |
| Record/source selection | `WITH_KEY`, `WITHIN_DOCTYPE`, `WITHIN_FILE`, `WITHIN_FILE_EXTENSION`, `KEY`, `FILE` |
| Scores/order/reduction | `BOOST`, `SORT`, `REDUCE`, `FOCUS`, `HIT_COUNT`, `TRIM`, `MAYBE`, `NARROW`, `PROMOTE`, `DEMOTE` |

## Lifetimes and current execution model

Results and metadata views retain native database resources directly. Their
lifetimes can extend beyond the Python handle's `close()` or `with` block.
Database-handle operations after close raise `RuntimeError`; retained rows can
still present evidence while the source documents remain available.

The prototype retains the GIL during native calls. Use one opened VIDB per
worker process for parallel service work. GIL release, Python document-handler
callbacks and free-threaded native access are outside the current interface.
