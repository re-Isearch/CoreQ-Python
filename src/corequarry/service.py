"""Transport-independent retained searches for the web and MCP examples.

Native handles stay in the process that creates this store. Only plain data
crosses a web worker boundary. This is an optional application layer, not an
additional index format.
"""

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import configparser
import hashlib
import json
import math
import time
import uuid

import corequarry as cq


@dataclass(frozen=True)
class Collection:
    id: str
    title: str
    database: str
    description: str = ""


def read_catalog(directory):
    """Accept native [DbInfo] INIs or small [Collection] catalog descriptions."""
    output = []
    for path in sorted(Path(directory).glob("*.ini")):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(path, encoding="utf-8")
        section = parser["Collection"] if parser.has_section("Collection") else None
        if section is not None:
            database = Path(section["database"]).expanduser()
            if not database.is_absolute():
                database = path.parent / database
        elif parser.has_section("DbInfo"):
            section = parser["DbInfo"]
            database = path.with_suffix("")
        else:
            continue
        database = str(database.resolve())
        if "\n" in database or "\r" in database:
            raise ValueError("A catalog database name cannot contain a newline")
        output.append(Collection(path.stem, section.get("title", path.stem), database,
                                 section.get("description", "")))
    if not output:
        raise ValueError("The catalog has no [Collection] or [DbInfo] INI files")
    return output


def parse_query(text, syntax="infix", field=""):
    if not text.strip():
        raise ValueError("Enter a query")
    parsers = {"infix": cq.SQUERY.from_infix, "rpn": cq.SQUERY.from_rpn,
               "words": cq.SQUERY.from_words}
    if syntax not in parsers:
        raise ValueError("Unknown query syntax")
    query = parsers[syntax](text)
    return query.within(field) if field else query


def _extent(span):
    return {"start": span.start, "end": span.end}


def present_row(db, row, result_id, rank):
    evidence = None
    if len(row.hits):
        display = row.get_display_evidence(max_bytes=240)
        text, field = row.evidence(max_bytes=240, before="**", after="**")
        evidence = {"text": text, "field": field,
                    "cover_extent": _extent(display.cover.extent),
                    "display_extent": _extent(display.display_extent),
                    "container_extent": _extent(display.container_extent)
                    if display.has_container else None}
    return {"result_id": result_id, "rank": rank, "key": row.key,
            "volume": row.virtual_index,
            "score": row.score if math.isfinite(row.score) else None,
            "headline": db.headline(row), "filename": row.filename,
            "doctype": row.doctype, "date": row.date.iso if row.date.ok else None,
            "record_extent": {"start": row.start, "end": row.end},
            "evidence": evidence, "hit_count": len(row.hits),
            "hits": [_extent(row.hits[i]) for i in range(min(64, len(row.hits)))]}


@dataclass
class Search:
    owner: str
    db: object
    selection: tuple
    query: str
    syntax: str
    field: str
    normalization: str
    rpn: str
    total: int
    hits: int
    elapsed_ms: float
    created: float
    accessed: float
    matches: object
    path: Path

    @property
    def estimated_bytes(self):
        # A retention estimate, not a native allocator or RSS measurement.
        return self.total * 128 + self.hits * 40


class SearchStore:
    def __init__(self, collections, *, max_searches=32, idle_seconds=900,
                 memory_mb=128, directory=None):
        self.catalog = {c.id: c for c in collections}
        if not self.catalog or max_searches < 1 or idle_seconds <= 0 or memory_mb < 0:
            raise ValueError("Invalid search store configuration")
        self.max_searches, self.idle_seconds = max_searches, idle_seconds
        self.memory_bytes = memory_mb * 1024 * 1024
        self.temporary = TemporaryDirectory(prefix="corequarry-search-", dir=directory)
        self.directory = Path(self.temporary.name)
        self.databases = OrderedDict()
        self.searches = OrderedDict()
        self.evaluations = 0

    def close(self):
        databases = {id(s.db): s.db for s in self.searches.values()}
        databases.update({id(db): db for db in self.databases.values()})
        self.searches.clear()
        self.databases.clear()
        for db in databases.values():
            db.close()
        self.temporary.cleanup()

    def _expire(self):
        now = time.monotonic()
        for key, search in list(self.searches.items()):
            if now - search.accessed > self.idle_seconds:
                self._remove(key)

    def _remove(self, key):
        search = self.searches.pop(key)
        search.path.unlink(missing_ok=True)

    def _db(self, selection):
        selection = tuple(sorted(set(selection)))
        if not selection or any(key not in self.catalog for key in selection):
            raise ValueError("Select a collection from the catalog")
        if selection not in self.databases:
            paths = [self.catalog[key].database for key in selection]
            if len(paths) == 1:
                stem = paths[0]
            else:
                name = hashlib.sha256(json.dumps(paths).encode()).hexdigest()
                path = self.directory / (name + ".vdb")
                path.write_text("\n".join(paths) + "\n", encoding="utf-8")
                stem = str(path.with_suffix(""))
            self.databases[selection] = cq.VIDB(stem, search_only=True)
        db = self.databases[selection]
        self.databases.move_to_end(selection)
        # Active searches retain their database object even after cache eviction.
        while len(self.databases) > 8:
            self.databases.popitem(last=False)
        return db, selection

    def fields(self, selection):
        self._expire()
        db, _ = self._db(selection)
        return sorted(db.fields(), key=lambda item: item["name"])

    def scan(self, selection, field="", prefix="", limit=12):
        if not 1 <= limit <= 50 or len(prefix) > 128:
            raise ValueError("Invalid autocomplete request")
        self._expire()
        db, _ = self._db(selection)
        if field and field.upper() not in {f["name"].upper() for f in db.fields()}:
            raise ValueError("Unknown field")
        # Scan starts at a native dictionary term. Filter its bounded output to
        # the requested prefix; native frequencies are not document counts.
        values = db.scan(field=field, term=prefix, limit=limit)
        return [v for v in values if v["term"].casefold().startswith(prefix.casefold())]

    def _search(self, owner, search_id):
        self._expire()
        search = self.searches.get(search_id)
        if search is None or search.owner != owner:
            raise KeyError("Search expired or unavailable; run the query again")
        search.accessed = time.monotonic()
        self.searches.move_to_end(search_id)
        return search

    def _matches(self, search):
        if search.matches is None:
            search.matches = search.db.load_results(str(search.path))
        return search.matches

    def _balance(self):
        resident = sum(s.estimated_bytes for s in self.searches.values() if s.matches is not None)
        for search in self.searches.values():
            if resident <= self.memory_bytes:
                break
            if search.matches is not None:
                temporary = search.path.with_suffix(".tmp")
                search.matches.save(str(temporary))
                temporary.replace(search.path)
                search.matches = None
                resident -= search.estimated_bytes

    def search(self, owner, selection, query, syntax="infix", field="",
               normalization="default", start=0, limit=10):
        self._expire()
        expression = parse_query(query, syntax, field)
        methods = {"default": cq.Normalization.DEFAULT, "e2": cq.Normalization.E2,
                   "l2": cq.Normalization.L2, "bm25": cq.Normalization.BM25}
        if normalization not in methods:
            raise ValueError("Unknown normalization")
        db, selected = self._db(selection)
        before = time.perf_counter()
        matches = db.search(cq.QUERY(expression, sort=cq.SortBy.SCORE,
                                     normalization=methods[normalization]))
        elapsed = (time.perf_counter() - before) * 1000
        self.evaluations += 1
        search_id = uuid.uuid4().hex
        now = time.monotonic()
        self.searches[search_id] = Search(owner, db, selected, query, syntax, field,
            normalization, expression.rpn, len(matches), matches.hit_total, elapsed,
            time.time(), now, matches, self.directory / (search_id + ".irset"))
        while len(self.searches) > self.max_searches:
            self._remove(next(iter(self.searches)))
        return self.page(owner, search_id, start, limit)

    def page(self, owner, search_id, start=0, limit=10):
        if start < 0 or not 1 <= limit <= 50:
            raise ValueError("Invalid page range")
        search = self._search(owner, search_id)
        matches = self._matches(search)
        page = matches.get_rset(limit, start=start)
        rows = [present_row(search.db, row, f"{search_id}.{start+i}", start+i+1)
                for i, row in enumerate(page)]
        result = {"search_id": search_id, "query": search.query, "query_rpn": search.rpn,
                  "syntax": search.syntax, "field": search.field,
                  "normalization": search.normalization, "collections": list(search.selection),
                  "databases": [self.catalog[key].database for key in search.selection],
                  "ib_revision": cq.ib_revision,
                  "total_found": search.total, "hit_total": search.hits,
                  "elapsed_ms": search.elapsed_ms, "created": search.created,
                  "start": start, "limit": limit, "returned": len(rows),
                  "next_start": start + len(rows) if start + len(rows) < search.total else None,
                  "previous_start": max(0, start-limit) if start else None,
                  "span_coordinates": "record-relative inclusive byte offsets; record_extent is file-relative",
                  "results": rows}
        self._balance()
        return result

    def fetch(self, owner, result_id, field=None, start=0, max_chars=4000):
        if start < 0 or not 1 <= max_chars <= 20000:
            raise ValueError("Invalid retrieval range")
        try:
            search_id, position = result_id.split(".")
            position = int(position)
        except (ValueError, AttributeError):
            raise ValueError("Invalid result ID") from None
        search = self._search(owner, search_id)
        if not 0 <= position < search.total:
            raise ValueError("Invalid result position")
        row = self._matches(search).get_rset(1, start=position)[0]
        text = row.get_record_data() if field is None else search.db.get_field_data(row, field)
        if text is None:
            raise ValueError("The requested field is unavailable")
        end = min(start + max_chars, len(text))
        result = {"result_id": result_id, "search_id": search_id, "key": row.key,
                  "volume": row.virtual_index, "headline": search.db.headline(row),
                  "field": field, "text": text[start:end], "start": start,
                  "total_chars": len(text), "next_start": end if end < len(text) else None}
        self._balance()
        return result

    def info(self):
        self._expire()
        return {"evaluations": self.evaluations,
                "cached_searches": len(self.searches), "cache_capacity": self.max_searches,
                "estimated_resident_bytes": sum(s.estimated_bytes for s in self.searches.values()
                                                 if s.matches is not None),
                "spilled_searches": sum(s.matches is None for s in self.searches.values()),
                "ib_revision": cq.ib_revision,
                "searches": [{"search_id": key, "query": s.query, "rpn": s.rpn,
                              "collections": s.selection, "total_found": s.total,
                              "elapsed_ms": s.elapsed_ms, "created": s.created,
                              "spilled": s.matches is None} for key, s in self.searches.items()]}

    def database_info(self, selection):
        db, _ = self._db(selection)
        return {"database": db.name, "total_records": db.total_records,
                "total_words": db.total_words, "volumes": db.volume_count,
                "version": db.GetVersionID(), "gptype_bits": cq.gptype_bits, **self.info()}
