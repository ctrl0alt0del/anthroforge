"""Compare two evaluated Package 4 fixture dumps."""

import argparse
import json
from pathlib import Path

import numpy as np


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", required=True)
    parser.add_argument("--second", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _load(path):
    source = Path(path)
    return (json.loads(source.with_suffix(".json").read_text(encoding="utf-8")),
            np.load(source.with_suffix(".npz")))


def _collider_deltas(first, second, vertices):
    output, offset = [], 0
    for left, right in zip(first["colliders"], second["colliders"]):
        count = left["vertices"]; delta = vertices[offset:offset + count]
        output.append({"id": left["id"], "same_record": left == right,
                       "max_vertex_delta": float(np.max(delta)) if len(delta) else 0.0})
        offset += count
    return output


def _compare(first, second):
    left, a = first; right, b = second
    delta = np.abs(a["vertices"] - b["vertices"])
    return {"same_colliders": left["colliders"] == right["colliders"],
            "same_anchors": left["anchors"] == right["anchors"],
            "same_triangles": bool(np.array_equal(a["triangles"], b["triangles"])),
            "max_vertex_delta": float(np.max(delta)), "changed_values": int(np.count_nonzero(delta)),
            "per_collider": _collider_deltas(left, right, delta)}


def main():
    args = _arguments(); result = _compare(_load(args.first), _load(args.second))
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
