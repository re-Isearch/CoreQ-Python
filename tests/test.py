import corequarry as cq

stats = cq.index_files(
    "BARD", ["shakespeare.xml"],
    doctype="AUTODETECT", merge=cq.Merge.ZIP,
)
print(stats.records_added)

