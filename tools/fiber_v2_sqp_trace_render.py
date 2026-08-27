"""Render the iteration that creates the FIBER_2 uneven turn and its blocker."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--node", type=int, default=9)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _span(record, node):
    return next(row for row in record["trace"]["spans"]
                if row["first_node"] <= node <= row["last_node"])


def _uneven(row, index):
    values = row["turn_degrees"]; neighbors = values[max(1, index - 2):index] + values[index + 1:index + 3]
    return values[index] - float(np.median(neighbors))


def _stages(record, node):
    span = _span(record, node); local = node - span["first_node"]; rows = span["iterations"]
    accepted = [row for row in rows if row["stage"] == "DECISION" and row["decision"] == "ACCEPT"]
    first = next(row for row in accepted if _uneven(row, local) >= 3.0)
    before = accepted[max(0, accepted.index(first) - 1)]
    rejected = next(row for row in rows if row["proposal"] > first["proposal"] and
                    row["stage"] == "CCD" and _uneven(row, local) < 3.0)
    final = next(row for row in reversed(rows) if row["stage"] == "FINISH")
    return (before, first, rejected, final), local


def _materials():
    labels = ("BEFORE BUMP", "FIRST UNEVEN", "REJECTED SMOOTH STEP", "FINAL EQUILIBRIUM")
    colors = ((.04, .8, 1.0), (1.0, .25, .04), (1.0, .82, .04), (.72, .18, 1.0))
    routes = tuple(v21.base._material(label, color, .3) for label, color in zip(labels, colors))
    mesh = v21.base._material("COLLIDERS", (.08, .11, .16), alpha=.42)
    marker = v21.base._material("TARGET_NODE", (1.0, .02, .02), .5)
    return labels, mesh, routes, marker


def _marker(point, center, axes, shift, radius, material, name):
    value = v21.base._transform((point,), center, axes, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=radius, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _panel(rows, triangles, materials, frame, spread, high, height, index, local):
    labels, mesh, routes, marker = materials; shift = (index - 1.5) * spread
    radius = max(spread * .006, .001); center, axes = frame
    v21._panel(triangles, rows[index], index, shift, center, axes, radius, (mesh, routes))
    _marker(rows[index][local], center, axes, shift, 2.2 * radius, marker, f"NODE_{index}")
    v21.p5._text(labels[index], (shift, high[1] + .12 * height, high[2]),
                 .055 * height, routes[index])


def _build(record, output, node):
    v21.base._reset_scene(); stages, local = _stages(record, node)
    rows = tuple(np.asarray(row["points"]) for row in stages)
    triangles = np.asarray(record["visual"]["nearby_triangles"]); frame = v21._basis(rows)
    low, high = v21._bounds(rows, triangles, *frame); width = max(high[0] - low[0], 1e-4)
    height = max(high[1] - low[1], 1e-4); spread = width * 1.2; materials = _materials()
    for index in range(4): _panel(rows, triangles, materials, frame, spread, high, height, index, local)
    v21._finish(low, high, spread, output, "")


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.node)


if __name__ == "__main__":
    main()
