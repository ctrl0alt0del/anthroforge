"""Render ROADMAP, corrected span-SQP, and the best GCP contact substitution."""

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
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record):
    target = record["variants"]["GCP_0.1"]
    return (np.asarray(target["seed"][:17]), np.asarray(record["baseline"]["result"]["points"][:17]),
            np.asarray(target["points"][:17]))


def _nearby(triangles, rows):
    cloud = np.vstack(rows); low, high = cloud.min(axis=0), cloud.max(axis=0)
    margin = .18 * max(float(np.linalg.norm(high - low)), 1.0e-4)
    values = np.asarray(triangles); centers = values.mean(axis=1)
    mask = np.all((centers >= low - margin) & (centers <= high + margin), axis=1)
    return values[mask]


def _materials():
    mesh = v21.base._material("COLLIDERS", (.08, .11, .16), alpha=.42)
    seed = v21.base._material("ROADMAP", (1., .55, .05), .3)
    base = v21.base._material("SPAN_SQP", (.1, .78, 1.), .3)
    gcp = v21.base._material("GCP", (.9, .2, 1.), .3)
    marker = v21.base._material("NODE10", (1., .03, .02), .5)
    return mesh, seed, base, gcp, marker


def _marker(point, center, axes, shift, radius, material, name):
    value = v21.base._transform((point,), center, axes, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=radius, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _panel(triangles, route, frame, shift, radius, materials, index):
    center, axes = frame; v21.base._mesh(f"COLLIDER_{index}", triangles, center, axes, shift, materials[0])
    v21.base._curve(f"ROUTE_{index}", route, center, axes, shift, radius, materials[index + 1])
    _marker(route[10], center, axes, shift, 2.0 * radius, materials[4], f"NODE10_{index}")


def _overlay(triangles, rows, frame, shift, radius, materials):
    center, axes = frame; v21.base._mesh("COLLIDER_OVERLAY", triangles, center, axes, shift, materials[0])
    v21.base._curve("SQP_OVERLAY", rows[1], center, axes, shift, 1.18 * radius, materials[2])
    v21.base._curve("GCP_OVERLAY", rows[2], center, axes, shift, .68 * radius, materials[3])


def _label(record, index, shift, high, height, material):
    if index == 0: text = "ROADMAP seed"
    elif index == 1:
        row = record["baseline"]; text = f"span-SQP  {row['timing']['median_ms']:.0f} ms  node 10 {row['geometry']['node10_turn']:.2f} deg"
    elif index == 2:
        row = record["variants"]["GCP_0.1"]; text = f"GCP contact  {row['timing']['median_ms']:.0f} ms  node 10 {row['geometry']['node10_turn']:.2f} deg"
    else: text = "OVERLAY  cyan span-SQP / purple GCP"
    v21.p5._text(text, (shift, high[1] + .12 * height, high[2]), .045 * height, material)


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 2.1 * spread
    scene_high[0] += 2.1 * spread; v21.base._camera(scene_low, scene_high, 0.0, output)
    v21.base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 3200
    bpy.context.scene.render.resolution_y = 850
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    v21.base._reset_scene(); rows = _rows(record); triangles = _nearby(record["nearby_triangles"], rows)
    frame = v21._basis(rows); low, high = v21._bounds(rows, triangles, *frame)
    width = max(high[0] - low[0], 1.0e-4); height = max(high[1] - low[1], 1.0e-4)
    spread = 1.1 * width; radius = max(.012 * width, .001); materials = _materials()
    shifts = (-1.5 * spread, -.5 * spread, .5 * spread)
    for index, (row, shift) in enumerate(zip(rows, shifts)):
        _panel(triangles, row, frame, shift, radius, materials, index)
        _label(record, index, shift, high, height, materials[index + 1])
    _overlay(triangles, rows, frame, 1.5 * spread, radius, materials)
    _label(record, 3, 1.5 * spread, high, height, materials[3])
    _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
