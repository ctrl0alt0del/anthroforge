"""Render roadmap, V2, and the three isolated V3 refinements."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_package5_render as p5
import fiber_v2_planner_41_blender_render as base


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record):
    keys = (("roadmap", "path"), ("v2", "path"), ("v3_cold", "path"),
            ("v3_covariant", "path"), ("v3_joint", "path"))
    return tuple(np.asarray(record[first][second]["points"]) if second in record[first]
                 else np.asarray(record[first]["points"]) for first, second in keys)


def _materials():
    labels = ("ROADMAP", "V2", "V3 SCALAR", "V3 COUPLED", "V3 JOINT SAFE")
    colors = ((1.0, .25, .08), (.75, .25, 1.0), (.15, 1.0, .25),
              (.1, .8, 1.0), (1.0, .8, .1))
    routes = tuple(base._material(label, color, .25) for label, color in zip(labels, colors))
    return labels, base._material("COLLIDERS", (.1, .14, .2), alpha=.42), routes


def _basis(rows):
    cloud = np.vstack(rows); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False); return center, axes


def _bounds(rows, triangles, center, axes):
    cloud = np.vstack((base._transform(triangles, center, axes, 0.0),
                       base._transform(np.vstack(rows), center, axes, 0.0)))
    return cloud.min(axis=0), cloud.max(axis=0)


def _panel(triangles, route, index, shift, center, axes, radius, collider, materials):
    base._mesh(f"COLLIDERS_{index}", triangles, center, axes, shift, collider)
    base._curve(f"ROUTE_{index}", route, center, axes, shift, radius, materials[index])


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 2.3 * spread
    scene_high[0] += 2.3 * spread; base._camera(scene_low, scene_high, 0.0, output)
    base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 4000
    bpy.context.scene.render.resolution_y = 900
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    base._reset_scene(); rows = _rows(record); center, axes = _basis(rows)
    triangles = np.asarray(record["nearby_triangles"]); low, high = _bounds(rows, triangles, center, axes)
    spread = max(high[0] - low[0], 1e-4) * 1.25; height = max(high[1] - low[1], 1e-4)
    labels, collider, materials = _materials(); shifts = tuple(value * spread for value in (-2, -1, 0, 1, 2))
    for index, shift in enumerate(shifts):
        _panel(triangles, rows[index], index, shift, center, axes, max(spread * .006, .001), collider, materials)
        p5._text(labels[index], (shift, high[1] + .12 * height, high[2]), .06 * height, materials[index])
    _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


main()
