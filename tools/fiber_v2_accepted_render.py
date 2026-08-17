"""Render the accepted full-cycle Fiber comparison from one benchmark JSON."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_package5_render as p5
import fiber_v2_planner_41_blender_render as base


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record):
    keys = ("v1", "package43", "package51", "package61")
    return tuple(np.asarray(record["visual"][key]) for key in keys)


def _labels():
    return "V1", "P4.3 PLANNER", "P5.1", "P6.1 FINAL"


def _materials():
    colors = ((1.0, .28, .02), (.06, .65, 1.0), (.72, .18, 1.0), (1.0, .82, .05))
    routes = tuple(base._material(label, color, .25) for label, color in zip(_labels(), colors))
    return base._material("COLLIDERS", (.10, .14, .20), alpha=.40), routes


def _basis(rows):
    cloud = np.vstack(rows); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False); return center, axes


def _bounds(rows, triangles, center, axes):
    values = np.vstack((base._transform(triangles, center, axes, 0.0),
                        base._transform(np.vstack(rows), center, axes, 0.0)))
    return values.min(axis=0), values.max(axis=0)


def _panel(triangles, route, index, shift, center, axes, radius, materials):
    base._mesh(f"COLLIDERS_{index}", triangles, center, axes, shift, materials[0])
    base._curve(f"ROUTE_{index}", route, center, axes, shift, radius, materials[1][index])


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 2.15 * spread
    scene_high[0] += 2.15 * spread; base._camera(scene_low, scene_high, 0.0, output)
    base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 3200
    bpy.context.scene.render.resolution_y = 900
    if blend_output:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    base._reset_scene(); rows = _rows(record); center, axes = _basis(rows)
    triangles = np.asarray(record["visual"]["nearby_triangles"]); low, high = _bounds(rows, triangles, center, axes)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4)
    spread = width * 1.2; materials = _materials(); shifts = tuple(value * spread for value in (-1.5, -.5, .5, 1.5))
    for index, shift in enumerate(shifts):
        _panel(triangles, rows[index], index, shift, center, axes, max(width * .008, .001), materials)
        p5._text(_labels()[index], (shift, high[1] + .12 * height, high[2]), .06 * height, materials[1][index])
    _finish(low, high, spread, output, blend_output)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
