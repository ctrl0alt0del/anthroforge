"""Render DIRECT, planner, V1, and production-3 comparisons."""

import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21
import fiber_v22_render as v22


def _rows(record):
    visual = record["visual"]; keys = ("direct", "planner", "v1", "v2")
    return tuple(np.asarray(visual[key]) for key in keys), np.asarray(visual["nearby_triangles"])


def _v2_label(record):
    if record.get("controller") == "SPAN_SQP_FIXED": return "V2 corrected span-SQP"
    return "V2 span-SQP" if record.get("controller") == "SPAN_SQP" else "V2 production-3"


def _materials(record):
    labels = ("DIRECT", "PLANNER", "V1", _v2_label(record))
    colors = ((.95, .16, .05), (.04, .75, 1.0), (1.0, .50, .02), (.74, .16, 1.0))
    routes = tuple(v21.base._material(label, color, .25) for label, color in zip(labels, colors))
    return labels, v21.base._material("COLLIDERS", (.10, .14, .20), alpha=.40), routes


def _build(record, output, blend_output):
    v21.base._reset_scene(); rows, triangles = _rows(record); labels, collider, routes = _materials(record)
    center, axes = v21._basis(rows); low, high = v21._bounds(rows, triangles, center, axes)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4); spread = width * 1.2
    for index in range(4):
        _panel(rows, triangles, labels, collider, routes, center, axes, spread, height, high, index)
    v21._finish(low, high, spread, output, blend_output)


def _panel(rows, triangles, labels, collider, routes, center, axes, spread, height, high, index):
    shift = (index - 1.5) * spread
    v21._panel(triangles, rows[index], index, shift, center, axes,
               max(spread * .006, .001), (collider, routes))
    v21.p5._text(labels[index], (shift, high[1] + .12 * height, high[2]),
                 .06 * height, routes[index])


def main():
    args = v22._arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
