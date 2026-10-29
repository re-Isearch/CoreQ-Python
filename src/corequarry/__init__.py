"""CoreQuarry's native query algebra, databases, results, and source evidence."""

from dataclasses import dataclass
from os import PathLike, fspath
from collections.abc import Iterable, Sequence
from typing import Literal

from ._core import (
    ATTRLIST, DISPLAY_EVIDENCE, EVIDENCE_COVER, FC, FCHIT, FIELDTYPE,
    HITTABLE, IDB, IRESULT, IRSET, MDT, MDTREC, OPERATOR, OPSTACK,
    QUERY, RECORD, RESULT, RSET, SQUERY, SRCH_DATE, STERM, VIDB,
    Merge, Normalization, Operator, Relation, SortBy,
    gptype_bits, ib_revision, index_id_bits, vector_enabled,
)

__version__ = "0.1.0a1"

__all__ = [
    "ATTRLIST", "DISPLAY_EVIDENCE", "EVIDENCE_COVER", "FC", "FCHIT", "FIELDTYPE",
    "HITTABLE", "IDB", "IRESULT", "IRSET", "MDT", "MDTREC", "OPERATOR", "OPSTACK",
    "QUERY", "RECORD", "RESULT", "RSET", "SQUERY", "SRCH_DATE", "STERM", "VIDB",
    "Merge", "Normalization", "Operator", "Relation", "SortBy", "IndexingResult",
    "index_file", "index_files", "search", "gptype_bits", "ib_revision",
    "index_id_bits", "vector_enabled", "__version__",
]


@dataclass(frozen=True)
class IndexingResult:
    records_added: int
    total_records: int
    total_words: int


def index_files(database: str | PathLike[str], paths: Iterable[str | PathLike[str]], *,
                doctype: str = "AUTODETECT", merge: Merge = Merge.NONE,
                append: bool = True, doctype_options: Sequence[str] = (),
                memory_mb: int = 256) -> IndexingResult:
    """Queue files and index them in one batch. Existing indexes are appended to.

    ``merge`` is independent of ``append``. NONE writes new shards without an
    automatic full optimization. ZIP merges shards once at the end of the batch.
    Input files must remain accessible for source presentation and evidence.
    ``memory_mb`` is IB's indexing buffer budget, not a limit on process RSS.
    """
    with IDB(fspath(database), search_only=False,
             doctype_options=list(doctype_options)) as db:
        before = db.total_records if append else 0
        for path in paths:
            if not db.add_file(fspath(path), doctype=doctype):
                raise RuntimeError(f"Could not queue {path!s}")
        if not db.index(append=append, merge=merge, memory_mb=memory_mb):
            raise RuntimeError("IB indexing failed")
        return IndexingResult(db.total_records - before, db.total_records,
                              db.total_words)


def index_file(database: str | PathLike[str], path: str | PathLike[str], **options) -> IndexingResult:
    """Append one file to a named index; see :func:`index_files`."""
    return index_files(database, [path], **options)


def search(database: str | PathLike[str], expression: QUERY | SQUERY | str, *,
           syntax: Literal["infix", "rpn", "words"] = "infix", sort: SortBy = SortBy.SCORE,
           normalization: Normalization = Normalization.DEFAULT) -> IRSET:
    """Search a named database. Returned IRSETs retain their native resources.

    Pass SQUERY/QUERY for programmatic construction, or explicitly select a
    parser for text. Materialize a page separately with IRSET.get_rset().
    """
    if isinstance(expression, QUERY):
        request = expression
    else:
        if isinstance(expression, SQUERY):
            query = expression
        elif syntax == "infix":
            query = SQUERY.from_infix(expression)
        elif syntax == "rpn":
            query = SQUERY.from_rpn(expression)
        elif syntax == "words":
            query = SQUERY.from_words(expression)
        else:
            raise ValueError("syntax must be 'infix', 'rpn', or 'words'")
        request = QUERY(query, sort=sort, normalization=normalization)
    with VIDB(fspath(database)) as db:
        return db.search(request)
