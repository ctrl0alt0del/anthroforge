"""Render repaired-pin Package 4.1 and 4.2 routes side by side."""

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
    routes = [record["repaired"][key]["reference"] for key in ("package41", "package42")]
    cloud = np.vstack(routes); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False)
    return center, axes


def _marker(name, point, center, axes, shift, radius, material):
    value = base._transform((point,), center, axes, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=radius, location=value)
    obj = bpy.context.object; obj.name = name; obj.data.materials.append(material)


def _pins(record, center, axes, shift, radius, old_mat, new_mat):
    for index, point in enumerate(record["original_pins"]):
        _marker(f"OLD_{index}", point, center, axes, shift, radius, old_mat)
    for index, point in enumerate(record["fixed_pins"]):
        _marker(f"FIXED_{index}", point, center, axes, shift, radius, new_mat)


def _route(record, key, center, axes, shift, radius, material):
    row = record["repaired"][key]
    base._curve(f"{key}_REFERENCE", row["reference"], center, axes, shift, radius * .55, material)
    base._curve(f"{key}_CORRIDOR", row["corridor"], center, axes, shift, radius, material)


def _bounds(record, center, axes):
    triangles = record["nearby_triangles"]
    routes = [record["repaired"][key]["reference"] for key in ("package41", "package42")]
    values = np.vstack((base._transform(triangles, center, axes, 0.0),
                        base._transform(np.vstack(routes), center, axes, 0.0)))
    return values.min(axis=0), values.max(axis=0)


def _materials():
    mesh = base._material("COLLIDERS", (.10, .14, .20), alpha=.38)
    blue = base._material("P41", (.04, .55, 1.0), .3); green = base._material("P42", (.04, 1.0, .32), .3)
    old = base._material("OLD_PIN", (1.0, .03, .03), .3); fixed = base._material("FIXED_PIN", (1.0, .8, .03), .3)
    return mesh, blue, green, old, fixed


def _build(record, output):
    base._reset_scene(); center, axes = _basis(record); low, high = _bounds(record, center, axes)
    spread = max(high[0] - low[0], .1) * 1.25; shifts = (-spread * .55, spread * .55)
    radius = max(spread * .006, .002); mats = _materials()
    for index, shift in enumerate(shifts):
        base._mesh(f"MESH_{index}", record["nearby_triangles"], center, axes, shift, mats[0])
        _pins(record, center, axes, shift, radius * 1.8, mats[3], mats[4])
    _route(record, "package41", center, axes, shifts[0], radius, mats[1])
    _route(record, "package42", center, axes, shifts[1], radius, mats[2])
    base._camera(low, high, spread * .62, output); base._lights(low, high); bpy.ops.render.render(write_still=True)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output)


if __name__ == "__main__":
    main()
