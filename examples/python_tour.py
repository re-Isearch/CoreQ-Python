"""Run with an installed corequarry package: python examples/python_tour.py.

Creates temporary sources/indexes, exercises the programmer's guide workflows,
and removes the temporary files after the examples release their database views.
"""

import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import corequarry as cq


def translate(node):
    """Translate the small application AST used in the programmer's guide."""
    if "term" in node:
        return cq.SQUERY.term(node["term"], field=node.get("field", ""))
    left, right = map(translate, node["args"])
    if node["op"] == "and":
        return left & right
    if node["op"] == "peer":
        return left.peer(right, max_gap=node.get("max_gap"))
    raise ValueError("Unsupported application operator")


def write_records(path, records):
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")


def run(root):
    source = root / "articles.ndjson"
    records = [
        {"title": "Virus vaccine trial", "body": "A virus vaccine study includes a laser processor.",
         "count": 42, "price": 10.125},
        {"title": "Virus study", "body": "A virus study describes a memory system.",
         "count": 7, "price": 20.25},
        {"title": "Vaccine response", "body": "An immune response to a vaccine.",
         "count": 65, "price": 5.5},
    ]
    second_source = root / "more-articles.ndjson"
    write_records(source, records[:2])
    write_records(second_source, records[2:])
    index = root / "articles"
    stats = cq.index_files(index, [source, second_source], doctype="NDJSON",
                           merge=cq.Merge.ZIP, memory_mb=32)
    assert stats.records_added == stats.total_records == 3

    virus, vaccine = cq.SQUERY.term("virus"), cq.SQUERY.term("vaccine")
    with cq.VIDB(str(index)) as db:
        assert db.total_records == 3
        assert len(db.search(virus & vaccine)) == 1
        assert len(db.search(virus | vaccine)) == 3
        assert len(db.search(virus.and_not(vaccine))) == 1
        assert len(db.search(virus ^ vaccine)) == 2
        assert virus.term_count == vaccine.term_count == 1
        assert len(db.search(cq.SQUERY.from_rpn("virus vaccine AND"))) == 1
        assert len(db.search(cq.SQUERY.from_infix("virus AND vaccine"))) == 1
        assert len(db.search(cq.SQUERY.term("vacc", prefix=True))) == 2

        count = cq.SQUERY.field("COUNT", 40, relation=cq.Relation.GE, datatype="integer")
        price = cq.SQUERY.field("PRICE", Decimal("10.125"),
                                relation=cq.Relation.GE, datatype="numerical")
        assert len(db.search(count)) == 2
        assert len(db.search(price)) == 2

        attributes = cq.ATTRLIST()
        attributes.field = "TITLE"
        left, right = cq.STERM(), cq.STERM()
        left.text, right.text = "virus", "vaccine"
        left.attributes = right.attributes = attributes
        stack = cq.OPSTACK()
        stack.push(left)
        stack.push(right)
        stack.push(cq.OPERATOR(cq.Operator.AND))
        stacked = cq.SQUERY()
        stacked.SetOpstack(stack)
        assert len(db.search(stacked)) == 1

        same_field = cq.OPERATOR(cq.Operator.AND_WITHIN)
        same_field.argument = "BODY"
        assert len(db.search(virus.combine(vaccine, same_field))) == 1
        assert len(db.search(virus.before_peer(vaccine, max_gap=130))) == 1
        assert len(db.search(virus.after_peer(vaccine, max_gap=130))) == 0

        ast = {"op": "peer", "max_gap": 130,
               "args": [{"term": "virus"}, {"term": "vaccine"}]}
        query = translate(ast).within("BODY")
        matches = db.search(cq.QUERY(query, normalization=cq.Normalization.E2))
        assert len(matches) == 1
        page = matches.get_rset(1)
        retained = page[0]
        assert len(matches.get_rset(0)) == 0
        assert len(matches.get_rset(1, start=1)) == 0
        text, field = retained.evidence(max_bytes=160)
        assert "virus" in text.lower() and "vaccine" in text.lower()
        assert field == "BODY" and "**virus**" in text.lower()
        plain, plain_field = retained.evidence(before="", after="")
        assert plain_field == "BODY" and "\x1b" not in plain and "**" not in plain
        print("Evidence:", field, text)
        print("Title:", db.get_field_data(retained, "TITLE"))
        print("Headline:", db.headline(retained))
        print("Summary:", db.summary(retained))
        print("Display extent:", retained.get_display_evidence(160).display_extent)
        assert retained.get_evidence_covers(3)
        assert len(retained.hits) > 0

        table = db.get_mdt(retained.virtual_index or 1)
        output = cq.MDTREC()
        assert table.get_entry(retained.mdt_index, output)
        assert output.key == retained.key
        assert table.lookup_key(output.key) == retained.mdt_index
        assert table[retained.mdt_index - 1].filename == output.filename

        a, b = db.search(virus), db.search(vaccine)
        assert len(a & b) == 1 and len(a | b) == 3
        assert len(a.and_not(b)) == 1 and len(a.peer(b, max_gap=130)) == 1
        assert len(a) == len(b) == 2
        combined = (a | b).copy()
        combined.sort_by(cq.SortBy.SCORE)
        assert len(combined.get_rset(2, start=1)) == 2
        assert len(list(combined)) == 3

    assert db.closed
    assert "virus" in retained.get_record_data().lower()
    assert output.filename == str(source)
    assert retained.evidence()[0]

    # A convenience search owns its resources even after its internal with block.
    assert len(cq.search(index, virus & vaccine)) == 1

    note = root / "note.txt"
    note.write_text("A laser processor note.\n", encoding="utf-8")
    record = cq.RECORD(str(note))
    record.doctype, record.key = "PLAINTEXT", "python-note"
    with cq.IDB(str(root / "notes"), search_only=False) as writer:
        assert writer.add_record(record)
        assert writer.index(merge=cq.Merge.ZIP, memory_mb=32)
    with cq.VIDB(str(root / "notes")) as reader:
        assert reader.total_records == 1
        assert reader.get_mdt()[0].key == "python-note"

    assert cq.FC(100, 109).length == 10
    assert any(entry["name"].startswith("PEER") for entry in cq.SQUERY.operators())
    print("Python tour passed; version:", cq.__version__, "IB:", cq.ib_revision)


if __name__ == "__main__":
    with TemporaryDirectory(prefix="corequarry-tour-") as directory:
        run(Path(directory))
