# Known issues

## Append can replay earlier inputs in the tested native build

In the tested Linux x86_64 build with IB revision `7726ce2`, appending a second
NDJSON input to an existing index reprocessed the first input as well. The
first call added two records. The second call, given a one-record file,
reported three added records and five total instead of one added and three
total. Its native indexing log listed both source files.

The behavior also reproduced when the two indexing calls ran in separate Python
processes. A fresh process is therefore not a verified workaround. Replay was
also observed with plain-text append, including the existing `test_append_is_default`
integration test. The cause has not yet been isolated; the observation is
specific to the tested native build and has not been checked on macOS.

Use the following minimal reproducer in a test environment:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import corequarry as cq

with TemporaryDirectory(prefix="ndjson-append-check-") as directory:
    root = Path(directory)
    a, b = root / "a.ndjson", root / "b.ndjson"
    a.write_text('{"body":"a virus"}\n{"body":"a vaccine"}\n', encoding="utf-8")
    b.write_text('{"body":"b vaccine"}\n', encoding="utf-8")
    index = root / "index"
    first = cq.index_file(index, a, doctype="NDJSON", merge=cq.Merge.ZIP, memory_mb=32)
    second = cq.index_file(index, b, doctype="NDJSON", merge=cq.Merge.ZIP, memory_mb=32)
    print(cq.ib_revision, first, second)
    # Expected: first.total_records == 2; second.records_added == 1;
    #           second.total_records == 3.
    # Observed in the build above: 2, 3, 5 respectively.
```

For the documented initial ingestion workflow, queue the complete file
batch into a fresh database stem in one `index_files()` call. Validate incremental
ingestion against your native build before relying on append counts.
The [runnable tour](../examples/python_tour.py) demonstrates a fresh NDJSON batch
and separate RECORD-based plain-text indexing.
