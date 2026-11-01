from pathlib import Path
import json
import time

import pytest
import corequarry as cq
from corequarry.service import Collection, SearchStore, read_catalog


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    root = tmp_path_factory.mktemp("service")
    collections = []
    for name, bodies in [("a", ["Alpha café virus vaccine.", "Beta virus study."]),
                         ("b", ["Gamma vaccine response.", "Virus vaccine technology."])]:
        source = root / (name + ".ndjson")
        source.write_text("".join(json.dumps({"title": name, "body": text, "count": i+1}, ensure_ascii=False)+"\n"
                                  for i, text in enumerate(bodies)), encoding="utf-8")
        database = root / name
        cq.index_file(database, source, doctype="NDJSON", memory_mb=32)
        collections.append(Collection(name, name.upper(), str(database)))
    return root, collections


def test_native_fields_scan_and_saved_sets(catalog):
    root, collections = catalog
    with cq.VIDB(collections[0].database) as db:
        assert {f["name"] for f in db.fields()} >= {"BODY", "TITLE", "COUNT"}
        terms = db.scan(field="BODY", term="vi", limit=5)
        assert any(t["term"] == "virus" and t["frequency"] > 0 for t in terms)
        assert db.scan(term="vi", limit=0) == []
        with pytest.raises(ValueError): db.scan(term="vi", limit=1001)
        query = cq.SQUERY.from_rpn("virus vaccine PEER:130")
        matches = db.search(query)
        path = root / "saved.irset"
        matches.save(str(path))
        loaded = db.load_results(str(path))
        assert len(loaded) == len(matches) == 1
        assert loaded.hit_total == matches.hit_total
        assert loaded.get_rset(1)[0].key == matches.get_rset(1)[0].key
        assert loaded.get_rset(1)[0].evidence() == matches.get_rset(1)[0].evidence()
        with cq.VIDB(collections[1].database) as other:
            with pytest.raises(RuntimeError): other.load_results(str(path))
        empty = db.search(cq.SQUERY.term("zzzzmissing"))
        empty.save(str(path))
        assert len(db.load_results(str(path))) == 0
        path.write_bytes(b"not an irset")
        with pytest.raises(RuntimeError): db.load_results(str(path))


def test_retention_spill_federation_and_owner(catalog, tmp_path):
    _, collections = catalog
    store = SearchStore(collections, directory=tmp_path, memory_mb=0)
    try:
        result = store.search("alice", ["b", "a"], "virus vaccine OR", "rpn", limit=1)
        search_id = result["search_id"]
        assert result["total_found"] == 4
        assert store.info()["spilled_searches"] == 1
        page = store.page("alice", search_id, start=1, limit=2)
        assert page["returned"] == 2 and page["search_id"] == search_id
        assert store.info()["evaluations"] == 1
        assert page["results"][0]["result_id"] != result["results"][0]["result_id"]
        with pytest.raises(KeyError): store.page("bob", search_id)
        with pytest.raises(KeyError): store.fetch("bob", result["results"][0]["result_id"])
        fetched = store.fetch("alice", result["results"][0]["result_id"], field="BODY")
        assert "virus" in fetched["text"].lower() or "vaccine" in fetched["text"].lower()
        assert any(v["term"] == "virus" for v in store.scan(["a", "b"], "BODY", "vi"))
        with pytest.raises(ValueError): store.fields(["../outside"])
    finally:
        directory = store.directory
        store.close()
        assert not directory.exists()


def test_expiration_and_catalog(catalog, tmp_path):
    _, collections = catalog
    config = tmp_path / "a.ini"
    config.write_text(f"[Collection]\ntitle = Example\ndatabase = {collections[0].database}\n")
    assert read_catalog(tmp_path)[0].title == "Example"
    store = SearchStore(collections, idle_seconds=0.01)
    try:
        result = store.search("alice", ["a"], "virus")
        time.sleep(0.02)
        with pytest.raises(KeyError): store.page("alice", result["search_id"])
    finally:
        store.close()
