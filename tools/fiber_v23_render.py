"""Render left-to-right V1, V2.2 and V2.3 route comparisons."""

import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21
import fiber_v22_render as v22


def _rows(record):
    source = record["visual"]
    keys = ("v1", "v22", "v23")
    return tuple(np.asarray(source[key]) for key in keys), np.asarray(source["nearby_triangles"])


def _materials():
    labels = ("V1", "V2.2", "V2.3")
    colors = ((1.0, .28, .02), (.15, .55, 1.0), (.05, .85, .42))
    routes = tuple(v21.base._material(label, color, .25) for label, color in zip(labels, colors))
    return labels, v21.base._material("COLLIDERS", (.10, .14, .20), alpha=.40), routes


def _build(record, output, blend_output):
    v21.base._reset_scene(); rows, triangles = _rows(record); labels, collider, routes = _materials()
    center, axes = v21._basis(rows); low, high = v21._bounds(rows, triangles, center, axes)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4); spread = width * 1.2
    shifts = tuple((index - 1.0) * spread for index in range(3))
    for index, shift in enumerate(shifts):
        v21._panel(triangles, rows[index], index, shift, center, axes, max(width * .008, .001), (collider, routes))
        v21.p5._text(labels[index], (shift, high[1] + .12 * height, high[2]), .06 * height, routes[index])
    v21._finish(low, high, spread, output, blend_output)


def main():
    args = v22._arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
