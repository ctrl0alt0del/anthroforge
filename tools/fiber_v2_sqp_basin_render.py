"""Render corrected span-SQP multistart minima and an overlay."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21


VARIANTS = ("PLANNER", "V1", "V2_BASE", "WHOLE_SQP")
COLORS = ((.05, .75, 1.0), (1.0, .38, .05), (.20, 1.0, .28), (.88, .16, 1.0))


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record):
    return tuple(np.asarray(record["cases"][name]["result_points"]) for name in VARIANTS)


def _materials():
    mesh = v21.base._material("COLLIDERS", (.07, .09, .13), alpha=.48)
    routes = tuple(v21.base._material(name, color, .3) for name, color in zip(VARIANTS, COLORS))
    marker = v21.base._material("WORST FREE NODE", (1., .02, .01), .5)
    return mesh, routes, marker


def _marker(point, center, axes, shift, radius, material, name):
    value = v21.base._transform((point,), center, axes, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=radius, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _label(record, name, shift, high, height, material):
    row = record["cases"][name]; energy = row["result_energy"]["total"]
    turn = row["result_geometry"]["worst_free_turn"]; status = row["result"]["termination"]
    text = f"{name} | E {energy:.6f} | {status} | worst {turn:.2f} deg"
    v21.p5._text(text, (shift, high[1] + .12 * height, high[2]), .027 * height, material)


def _panel(record, triangles, rows, frame, shift, radius, materials, index):
    center, axes = frame; name = VARIANTS[index]
    v21.base._mesh(f"COLLIDER_{name}", triangles, center, axes, shift, materials[0])
    v21.base._curve(f"ROUTE_{name}", rows[index], center, axes, shift, radius, materials[1][index])
    worst = record["cases"][name]["result_geometry"]["worst_free_node"]
    _marker(rows[index][worst], center, axes, shift, 2.0 * radius, materials[2], f"WORST_{name}")


def _overlay(triangles, rows, frame, shift, radius, materials):
    center, axes = frame
    v21.base._mesh("COLLIDER_OVERLAY", triangles, center, axes, shift, materials[0])
    for index, row in enumerate(rows):
        size = radius * (1.25 - .15 * index)
        v21.base._curve(f"OVERLAY_{VARIANTS[index]}", row, center, axes, shift, size, materials[1][index])


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 2.55 * spread
    scene_high[0] += 2.55 * spread; v21.base._camera(scene_low, scene_high, 0.0, output)
    v21.base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 4200
    bpy.context.scene.render.resolution_y = 1000
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    v21.base._reset_scene(); rows = _rows(record); triangles = np.asarray(record["nearby_triangles"])
    frame = v21._basis(rows); low, high = v21._bounds(rows, triangles, *frame)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4)
    spread = 1.12 * width; radius = max(.007 * width, .001); materials = _materials()
    shifts = tuple((index - 2.0) * spread for index in range(5))
    for index in range(4):
        _panel(record, triangles, rows, frame, shifts[index], radius, materials, index)
        _label(record, VARIANTS[index], shifts[index], high, height, materials[1][index])
    _overlay(triangles, rows, frame, shifts[-1], radius, materials)
    v21.p5._text("OVERLAY", (shifts[-1], high[1] + .12 * height, high[2]), .035 * height, materials[1][2])
    _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
