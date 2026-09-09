"""Create comparable 0.3 boundary-conformance trials without altering 0.2 evidence."""
import json
import sys
from pathlib import Path


def convert(document):
    document["version"] = "0.3.0"
    document.pop("$schema",None)
    for recipe in document["recipes"].values():
        build = recipe["construction"]
        build["boundary_conformance"] = dict(stations=[build["stations"][i]["id"] for i in (0,-1)],
            max_error=dict(value=.0001,unit="scene"),blend_span=.08,max_samples=257)
    for policy in document["policies"].values():
        policy.update(max_surface_vertices=40000,total_budget_ms=120000)
    return document


def main():
    source,destination = map(Path,sys.argv[1:])
    destination.mkdir(parents=True,exist_ok=True)
    for path in source.glob("muscle_*_dsl.json"):
        value = convert(json.loads(path.read_text()))
        value["document_id"] = path.stem
        (destination/path.name).write_text(json.dumps(value,indent=2))


if __name__ == "__main__":
    main()
