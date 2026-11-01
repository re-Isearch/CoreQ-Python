"""Create a fresh, self-contained synthetic collection for the web demo."""

from pathlib import Path
import argparse
import json

import corequarry as cq


def create(directory):
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "catalog").mkdir()
    topics = [
        ("Vaccine delivery and viral antigens", "A virus vaccine study examined antigen delivery and immune response. The researchers compared formulations and reported their observations in a structured laboratory record."),
        ("Understanding immune memory", "The virus vaccine experiment followed changes in immune memory over time. Evidence from repeated measurements helped the team distinguish a persistent response from a short-lived signal."),
        ("Reducing viral binding in cell cultures", "A reduction in virus binding was observed after vaccine treatment in the cell culture model. The research note describes the assay conditions, controls and limitations."),
        ("Processor design and instruction decoding", "A RISC processor uses a decoding stage to select an instruction. The system architecture includes a register file, a memory interface and a small instruction cache."),
        ("Optical sensors and laser processing", "The optical sensor records light from the laser processor. Changes in the signal are associated with surface geometry and instrument settings."),
    ]
    for key, title, description, offset in [
        ("research", "Research notes", "Laboratory observations and experimental methods", 0),
        ("briefs", "Technical briefs", "Engineering summaries and applied research", 30),
    ]:
        source = root / (key + ".ndjson")
        documents = [{"title": topics[i % len(topics)][0] + f" · Note {i+1+offset:02d}",
                      "body": topics[i % len(topics)][1], "series": title,
                      "sample_count": (i+1) * 7} for i in range(20)]
        source.write_text("".join(json.dumps(d, ensure_ascii=False)+"\n" for d in documents), encoding="utf-8")
        database = root / key
        cq.index_file(database, source, doctype="NDJSON", memory_mb=32, merge=cq.Merge.ZIP)
        (root / "catalog" / (key + ".ini")).write_text(
            f"[Collection]\ntitle = {title}\ndescription = {description}\ndatabase = ../{key}\n", encoding="utf-8")
    print("Created synthetic demo sources and indexes:", root)
    print("Catalog:", root / "catalog")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="web-demo")
    create(parser.parse_args().directory)
