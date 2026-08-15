"""Render the real Maxilla/FIBER_21 Package 4.2 qualification result."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_planner_41_blender_render as base


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _basis(record):
    rows = (np.asarray(record["v1_after"]), np.asarray(record["anchors"]))
    cloud = np.vstack(rows); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False)
    return center, axes


def _marker(name, point, center, axes, shift, radius, material):
    value = base._transform((point,), center, axes, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=radius, location=value)
    obj = bpy.context.object; obj.name = name; obj.data.materials.append(material)


def _v1(record, center, axes, shift, radius, good, bad):
    points = record["v1_after"]; blocked = set(record["v1_validation"]["violating_edges"])
    for index, edge in enumerate(zip(points[:-1], points[1:])):
        base._curve(f"V1_{index}", edge, center, axes, shift, radius, bad if index in blocked else good)


def _failed_route(record, center, axes, shift, radius, material, prefix):
    points = record["anchors"]
    for index, edge in enumerate(zip(points[:-1], points[1:])):
        base._curve(f"{prefix}_{index}", edge, center, axes, shift, radius, material)


def _markers(record, center, axes, shift, radius, normal, blocked):
    failures = {4, 5}
    for index, point in enumerate(record["anchors"]):
        _marker(f"PIN_{index}", point, center, axes, shift, radius,
                blocked if index in failures else normal)


def _materials():
    mesh = base._material("COLLIDERS", (.10, .14, .20), alpha=.38)
    orange = base._material("V1", (1.0, .42, .05), .2)
    red = base._material("BLOCKED", (1.0, .03, .03), .35)
    cyan = base._material("PINS", (.02, .75, 1.0), .3)
    return mesh, orange, red, cyan


def _build(record, output):
    base._reset_scene(); center, axes = _basis(record); materials = _materials()
    triangles = record["nearby_triangles"]; values = base._transform(triangles, center, axes, 0.0)
    low, high = values.min(axis=0), values.max(axis=0); spread = max(high[0] - low[0], .1) * 1.18
    radius = max(spread * .006, .002); shifts = (-spread, 0.0, spread)
    for index, shift in enumerate(shifts):
        base._mesh(f"MESH_{index}", triangles, center, axes, shift, materials[0])
    _v1(record, center, axes, shifts[0], radius, materials[1], materials[2])
    _failed_route(record, center, axes, shifts[1], radius * .7, materials[2], "P4")
    _failed_route(record, center, axes, shifts[2], radius * .7, materials[2], "P42")
    _markers(record, center, axes, shifts[2], radius * 2.3, materials[3], materials[2])
    base._camera(low, high, spread, output); base._lights(low, high); bpy.ops.render.render(write_still=True)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output)


if __name__ == "__main__":
    main()
