import gc
import os
from decimal import Decimal

import pytest
import corequarry as cq


@pytest.fixture
def corpus(tmp_path):
    documents = [
        "Alpha virus vaccine. Laser processor.\n",
        "Beta virus study without vaccination.\n",
        "Gamma vaccine response.\n",
    ]
    paths = []
    for i, text in enumerate(documents):
        path = tmp_path / f"document-{i}.txt"
        path.write_text(text)
        paths.append(path)
    name = tmp_path / "search-db"
    result = cq.index_files(name, paths, doctype="PLAINTEXT", merge=cq.Merge.ZIP)
    assert result.records_added == result.total_records == 3
    return name, paths


def test_programmatic_literal_and_parsed_queries(corpus):
    name, _ = corpus
    with cq.VIDB(os.fspath(name)) as db:
        virus = cq.SQUERY.term("virus")
        vaccine = cq.SQUERY.term("vaccine")
        both = virus & vaccine
        assert virus.term_count == vaccine.term_count == 1
        assert both.term_count == 2
        assert len(db.search(cq.QUERY(both))) == 1
        assert len(db.search(cq.SQUERY.from_rpn("virus vaccine AND"))) == 1
        assert len(db.search(virus | vaccine)) == 3
        assert len(db.search(virus.and_not(vaccine))) == 1
        assert len(db.search(cq.SQUERY.from_infix("virus AND vaccine"))) == 1


def test_operator_words_are_literal_operands():
    for text in ("AND", "OR", "PEER:130", 'quoted "value"', "field/value"):
        query = cq.SQUERY.term(text)
        assert query.term_count == 1
        stack = query.GetOpstack()
        reconstructed = cq.SQUERY()
        reconstructed.SetOpstack(stack)
        assert reconstructed.rpn == query.rpn


def test_low_level_query_stack(corpus):
    name, _ = corpus
    a, b = cq.STERM(), cq.STERM()
    a.text, b.text = "virus", "vaccine"
    stack = cq.OPSTACK()
    stack.push(a)
    stack.push(b)
    stack.push(cq.OPERATOR(cq.Operator.AND))
    query = cq.SQUERY()
    query.SetOpstack(stack)
    with cq.VIDB(os.fspath(name)) as db:
        assert len(db.search(query)) == 1


def test_exact_peer_bounds_and_input_preservation(corpus):
    name, _ = corpus
    a, b = cq.SQUERY.term("virus"), cq.SQUERY.term("vaccine")
    bound = (1 << 53) + 17
    assert str(bound) in a.peer(b, max_gap=bound).rpn
    assert "PEER:0" in a.peer(b, max_gap=0).rpn
    with pytest.raises((TypeError, ValueError, OverflowError, RuntimeError)):
        a.peer(b, max_gap=-1)
    with pytest.raises((TypeError, ValueError, OverflowError, RuntimeError)):
        a.peer(b, max_gap=1 << cq.gptype_bits)
    with pytest.raises(TypeError):
        a.peer(b, max_gap=1.5)
    with cq.VIDB(os.fspath(name)) as db:
        assert len(db.search(a.peer(b, max_gap=1))) == 1
        assert len(db.search(a.peer(b, max_gap=0))) == 0
    assert a.term_count == b.term_count == 1


def test_query_parameters_and_exact_decimal_terms():
    value = Decimal("12345678901234567890.1234567890123456")
    query = cq.SQUERY.field("price", value, relation=cq.Relation.GE, datatype="numerical")
    assert str(value) in query.rpn
    assert "PRICE" in query.rpn
    request = cq.QUERY(query, sort=cq.SortBy.DATE, normalization=cq.Normalization.E2)
    assert request.sort == cq.SortBy.DATE
    assert request.normalization == cq.Normalization.E2
    assert request.squery.rpn == query.rpn
    with pytest.raises(ValueError):
        cq.SQUERY.term("10", datatype="nonexistent-type")


def test_typed_field_query_against_real_index(tmp_path):
    path = tmp_path / "records.ndjson"
    path.write_text('{"title":"Laser device","count":42}\n'
                    '{"title":"Laser device","count":7}\n')
    name = tmp_path / "typed-db"
    cq.index_file(name, path, doctype="NDJSON", merge=cq.Merge.ZIP)
    with cq.VIDB(os.fspath(name)) as db:
        predicate = cq.SQUERY.field("count", 40, relation=cq.Relation.GE, datatype="integer")
        assert len(db.search(predicate)) == 1


def test_evidence_honors_markers_and_returns_container(tmp_path):
    path = tmp_path / "evidence.ndjson"
    path.write_text('{"body":"A virus vaccine study."}\n')
    name = tmp_path / "evidence-db"
    cq.index_file(name, path, doctype="NDJSON", memory_mb=32)
    with cq.VIDB(os.fspath(name)) as db:
        row = db.search(cq.SQUERY.term("virus", field="BODY")).get_rset(1)[0]
        marked, field = row.evidence(before="<hit>", after="</hit>")
        assert field == "BODY"
        assert "<hit>virus</hit>" in marked
        assert "\x1b" not in marked
        plain, field = row.evidence(before="", after="")
        assert field == "BODY"
        assert "virus" in plain and "\x1b" not in plain
        assert "<hit>" not in plain and "**" not in plain


def test_materialization_limit_and_indexing(corpus):
    name, _ = corpus
    with cq.VIDB(os.fspath(name)) as db:
        matches = db.search(cq.SQUERY.term("virus") | cq.SQUERY.term("vaccine"))
        assert len(matches) == 3
        assert len(matches.get_rset(0)) == 0
        assert len(matches.get_rset(1)) == 1
        assert len(matches.get_rset(10, start=2)) == 1
        assert len(matches.get_rset(None, start=1)) == 2
        assert len(matches.get_rset(10, start=20)) == 0
        page = matches.get_rset()
        assert len(list(page)) == 3
        assert page[-1].key == page[2].key
        with pytest.raises(IndexError):
            _ = page[3]
        with pytest.raises(IndexError):
            _ = matches[-4]


def test_result_survives_next_query_and_database_close(corpus):
    name, _ = corpus
    db = cq.VIDB(os.fspath(name))
    first = db.search(cq.SQUERY.term("alpha"))
    page = first.get_rset(1)
    row = page[0]
    second = db.search(cq.SQUERY.term("gamma"))
    assert len(second) == 1
    assert "Alpha" in row.get_record_data()
    db.close()
    assert db.closed
    del first, page, second, db
    gc.collect()
    assert "Alpha" in row.get_record_data()
    text, field = row.evidence()
    assert "alpha" in text.lower()


def test_metadata_output_record_is_stable(corpus):
    name, _ = corpus
    db = cq.VIDB(os.fspath(name))
    table = db.get_mdt()
    a, b = cq.MDTREC(), cq.MDTREC()
    assert table.get_entry(1, a)
    filename = a.filename
    assert table.get_entry(2, b)
    assert a.filename == filename != b.filename
    assert not table.get_entry(0, b)
    assert not table.get_entry(len(table) + 1, b)
    first = table[0]
    assert first.filename == a.filename
    db.close()
    del table, db, b
    gc.collect()
    assert a.filename == first.filename == filename


def test_irset_algebra_preserves_operands(corpus):
    name, _ = corpus
    with cq.VIDB(os.fspath(name)) as db:
        a, b = db.search(cq.SQUERY.term("virus")), db.search(cq.SQUERY.term("vaccine"))
        assert len(a) == len(b) == 2
        assert len(a & b) == 1
        assert len(a | b) == 3
        assert len(a.and_not(b)) == 1
        assert len(a.peer(b, max_gap=1)) == 1
        assert len(a) == len(b) == 2
        copy = a.copy()
        assert len(copy) == 2
        assert len(copy[0].hits) > 0


def test_append_is_default(corpus, tmp_path):
    name, _ = corpus
    path = tmp_path / "later.txt"
    path.write_text("Delta virus discovery.\n")
    stats = cq.index_file(name, path, doctype="PLAINTEXT")
    assert stats.records_added == 1
    assert stats.total_records == 4
    matches = cq.search(name, cq.SQUERY.term("virus"))
    assert len(matches) == 3


def test_closed_and_search_only_handles(corpus):
    name, paths = corpus
    db = cq.VIDB(os.fspath(name))
    with pytest.raises(RuntimeError):
        db.add_file(os.fspath(paths[0]))
    db.close()
    with pytest.raises(RuntimeError):
        db.search(cq.SQUERY.term("virus"))
    with pytest.raises(RuntimeError):
        _ = db.total_records


def test_writer_rejects_mutation_with_live_views(corpus):
    name, _ = corpus
    with cq.IDB(os.fspath(name)) as db:
        table = db.get_mdt()
        with pytest.raises(RuntimeError, match="live"):
            db.index()
        del table


def test_cross_handle_result_sets_rejected(corpus):
    name, _ = corpus
    with cq.VIDB(os.fspath(name)) as a, cq.VIDB(os.fspath(name)) as b:
        left, right = a.search(cq.SQUERY.term("virus")), b.search(cq.SQUERY.term("vaccine"))
        with pytest.raises(ValueError):
            _ = left & right


def test_wide_spans_and_operator_catalog():
    span = cq.FC((1 << 40) + 3, (1 << 40) + 19)
    assert span.start == (1 << 40) + 3
    assert span.length == 17
    assert span.contains(cq.FC(span.start + 1, span.end - 1))
    assert any(item["name"].startswith("PEER") for item in cq.SQUERY.operators())


def test_unicode_and_surrogateescape_query_values():
    assert cq.SQUERY.term("café").term_count == 1
    query = cq.SQUERY.term(b"legacy-\xff")
    assert "\udcff" in query.rpn
    with pytest.raises((TypeError, ValueError)):
        cq.SQUERY.term("a\x00b")


def test_federated_results_resolve_their_own_volume(tmp_path):
    names, paths = [], []
    for i, text in enumerate(("First shared virus", "Second shared vaccine")):
        path = tmp_path / f"source-{i}.ndjson"
        path.write_text('{"title":"' + text + '"}\n')
        name = tmp_path / f"part-{i}"
        cq.index_file(name, path, doctype="NDJSON", memory_mb=32)
        names.append(name)
        paths.append(path)
    name = tmp_path / "collection"
    name.with_suffix(".vdb").write_text("\n".join(map(os.fspath, names)) + "\n")
    with cq.VIDB(os.fspath(name)) as db:
        assert db.volume_count == 2
        query = cq.SQUERY.term("shared").within("TITLE")
        matches = db.search(query)
        page = matches.get_rset()
        assert len(page) == 2
        assert {row.virtual_index for row in page} == {1, 2}
        assert {row.filename for row in page} == set(map(os.fspath, paths))
        assert {db.get_mdt(i)[0].filename for i in (1, 2)} == set(map(os.fspath, paths))
        with pytest.raises(RuntimeError, match="SQUERY"):
            matches.within("TITLE")
    assert {"First" if "First" in row.get_record_data() else "Second" for row in page} == {"First", "Second"}
    for row in page:
        text, field = row.evidence()
        assert "shared" in text.lower()
