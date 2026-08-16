"""Render a true Blender V1 / Package 4.x left-to-right comparison."""

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


def _basis(record):
    visual = record["visual"]; rows = [np.asarray(visual["v1"])]
    rows.extend(np.asarray(visual["routes"][key]) for key in ("package4", "package41", "package42", "package43"))
    cloud = np.vstack(rows); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False)
    return center, axes


def _materials():
    colors = ((1.0, .34, .03), (.22, .85, .20), (.05, .58, 1.0), (.80, .20, 1.0), (.00, 1.0, .82))
    routes = [base._material(name, color, .25) for name, color in zip(_labels(), colors)]
    return base._material("COLLIDERS", (.10, .14, .20), alpha=.40), routes


def _labels():
    return ("V1", "PACKAGE 4", "PACKAGE 4.1", "PACKAGE 4.2", "PACKAGE 4.3")


def _route_rows(record):
    return (record["visual"]["v1"], *(record["visual"]["routes"][key]
                                      for key in ("package4", "package41", "package42", "package43")))


def _bounds(record, center, axes):
    triangles = np.asarray(record["visual"]["nearby_triangles"]); routes = np.vstack(_route_rows(record))
    values = np.vstack((base._transform(triangles, center, axes, 0.0),
                        base._transform(routes, center, axes, 0.0)))
    return values.min(axis=0), values.max(axis=0)


def _text(label, location, size, material):
    data = bpy.data.curves.new(f"LABEL_{label}", "FONT"); data.body = label
    data.align_x = "CENTER"; data.size = size; data.extrude = size * .015
    data.materials.append(material); obj = bpy.data.objects.new(f"LABEL_{label}", data)
    bpy.context.collection.objects.link(obj); obj.location = location


def _draw_panel(record, index, shift, center, axes, radius, materials):
    mesh, routes = materials; triangles = record["visual"]["nearby_triangles"]
    base._mesh(f"COLLIDERS_{index}", triangles, center, axes, shift, mesh)
    points = _route_rows(record)[index]; base._curve(f"ROUTE_{index}", points, center, axes, shift, radius, routes[index])
    if index:
        key = ("package4", "package41", "package42", "package43")[index - 1]
        corridor = record["planners"][key]["route"]["points"]
        base._curve(f"CORRIDOR_{index}", corridor, center, axes, shift, radius * 1.8, routes[index])


def _build(record, output, blend_output):
    base._reset_scene(); center, axes = _basis(record); low, high = _bounds(record, center, axes)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4); spread = width * 1.24
    shifts = tuple((index - 2) * spread for index in range(5)); materials = _materials(); radius = max(width * .007, .001)
    for index, shift in enumerate(shifts):
        _draw_panel(record, index, shift, center, axes, radius, materials)
        _text(_labels()[index], (shift, high[1] + .12 * height, high[2] + .01), .08 * height, materials[1][index])
    _finish_scene(low, high, spread, output, blend_output)


def _finish_scene(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 2.45 * spread; scene_high[0] += 2.45 * spread
    base._camera(scene_low, scene_high, 0.0, output); base._lights(scene_low, scene_high)
    bpy.context.scene.render.resolution_x = 3200; bpy.context.scene.render.resolution_y = 900
    if blend_output:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
