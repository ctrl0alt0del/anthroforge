"""Render a true Blender V1 / Package 4.3 / Package 5 comparison."""

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
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record):
    visual = record["visual"]
    return tuple(np.asarray(visual[key]) for key in ("v1", "package43", "package5"))


def _basis(record):
    cloud = np.vstack(_rows(record)); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False)
    return center, axes


def _materials():
    colors = ((1.0, .28, .02), (.06, .65, 1.0), (.04, 1.0, .42))
    routes = tuple(base._material(label, color, .25) for label, color in zip(_labels(), colors))
    return base._material("COLLIDERS", (.10, .14, .20), alpha=.40), routes


def _labels():
    return "V1", "PACKAGE 4.3 PLANNER", "PACKAGE 5 SOLVER"


def _bounds(record, center, axes):
    triangles = np.asarray(record["visual"]["nearby_triangles"]); routes = np.vstack(_rows(record))
    values = np.vstack((base._transform(triangles, center, axes, 0.0),
                        base._transform(routes, center, axes, 0.0)))
    return values.min(axis=0), values.max(axis=0)


def _text(label, location, size, material):
    data = bpy.data.curves.new(f"LABEL_{label}", "FONT"); data.body = label
    data.align_x = "CENTER"; data.size = size; data.extrude = size * .015
    data.materials.append(material); obj = bpy.data.objects.new(f"LABEL_{label}", data)
    bpy.context.collection.objects.link(obj); obj.location = location


def _panel(record, index, shift, center, axes, radius, materials):
    base._mesh(f"COLLIDERS_{index}", record["visual"]["nearby_triangles"], center, axes,
               shift, materials[0])
    base._curve(f"ROUTE_{index}", _rows(record)[index], center, axes, shift,
                radius, materials[1][index])


def _build(record, output, blend_output):
    base._reset_scene(); center, axes = _basis(record); low, high = _bounds(record, center, axes)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4)
    spread = width * 1.25; shifts = (-spread, 0.0, spread); materials = _materials()
    for index, shift in enumerate(shifts):
        _panel(record, index, shift, center, axes, max(width * .008, .001), materials)
        _text(_labels()[index], (shift, high[1] + .12 * height, high[2]), .065 * height,
              materials[1][index])
    _finish(low, high, spread, output, blend_output)


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 1.55 * spread
    scene_high[0] += 1.55 * spread; base._camera(scene_low, scene_high, 0.0, output)
    base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 2400
    bpy.context.scene.render.resolution_y = 900
    if blend_output:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
