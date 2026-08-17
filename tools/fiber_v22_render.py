"""Render V2.2 baseline and preview/final comparisons."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    parser.add_argument("--mode", choices=("baseline", "handle"), default="baseline")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record, mode):
    source = record["visual_handle"] if mode == "handle" else record["visual"]
    keys = (("package61", "v21", "v22_preview", "v22_final") if mode == "handle"
            else ("v1", "package61", "v21", "v22"))
    return tuple(np.asarray(source[key]) for key in keys), np.asarray(source["nearby_triangles"])


def _labels(mode):
    return (("P6.1 HANDLE", "V2.1 HANDLE", "V2.2 PREVIEW", "V2.2 FINAL") if mode == "handle"
            else ("V1", "P6.1", "V2.1", "V2.2"))


def _materials(labels):
    colors = ((1.0, .28, .02), (1.0, .82, .05), (.15, .55, 1.0), (.05, .85, .42))
    routes = tuple(v21.base._material(label, color, .25) for label, color in zip(labels, colors))
    return v21.base._material("COLLIDERS", (.10, .14, .20), alpha=.40), routes


def _build(record, output, blend_output, mode):
    v21.base._reset_scene(); (rows, triangles), labels = _rows(record, mode), _labels(mode)
    center, axes = v21._basis(rows); low, high = v21._bounds(rows, triangles, center, axes)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4)
    spread = width * 1.2; materials = _materials(labels)
    shifts = tuple((index - (len(rows) - 1) / 2) * spread for index in range(len(rows)))
    for index, shift in enumerate(shifts):
        v21._panel(triangles, rows[index], index, shift, center, axes, max(width * .008, .001), materials)
        v21.p5._text(labels[index], (shift, high[1] + .12 * height, high[2]), .06 * height, materials[1][index])
    v21._finish(low, high, spread, output, blend_output)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output, args.mode)


if __name__ == "__main__":
    main()
