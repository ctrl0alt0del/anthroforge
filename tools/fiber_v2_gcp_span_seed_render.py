"""Render corrected span-SQP seed beside its GCP refinement."""

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


def _materials():
    mesh = v21.base._material("COLLIDERS", (.07, .09, .13), alpha=.48)
    seed = v21.base._material("SPAN_SQP", (.08, .75, 1.), .3)
    final = v21.base._material("GCP", (.94, .16, .9), .3)
    return mesh, seed, final


def _nearby(record, rows):
    cloud = np.vstack(rows); low, high = cloud.min(axis=0), cloud.max(axis=0)
    margin = .18 * max(float(np.linalg.norm(high - low)), 1e-4)
    values = np.asarray(record["nearby_triangles"]); centers = values.mean(axis=1)
    return values[np.all((centers >= low - margin) & (centers <= high + margin), axis=1)]


def _panel(triangles, route, frame, shift, radius, materials, index):
    center, axes = frame; v21.base._mesh(f"COLLIDER_{index}", triangles, center, axes, shift, materials[0])
    v21.base._curve(f"ROUTE_{index}", route, center, axes, shift, radius, materials[index + 1])


def _overlay(triangles, rows, frame, shift, radius, materials):
    center, axes = frame; v21.base._mesh("COLLIDER_OVERLAY", triangles, center, axes, shift, materials[0])
    v21.base._curve("SEED_OVERLAY", rows[0], center, axes, shift, 1.2 * radius, materials[1])
    v21.base._curve("GCP_OVERLAY", rows[1], center, axes, shift, .7 * radius, materials[2])


def _label(record, index, shift, high, height, material):
    if index == 0: row = record["seed_geometry"]; text = f"span-SQP seed  {record['seed_timing']['median_ms']:.0f} ms  worst {row['worst_free_turn']:.1f} deg"
    elif index == 1: row = record["gcp_geometry"]; text = f"GCP refinement  {record['gcp_timing']['median_ms']:.0f} ms  worst {row['worst_free_turn']:.1f} deg"
    else: text = "OVERLAY  cyan seed / purple GCP"
    v21.p5._text(text, (shift, high[1] + .12 * height, high[2]), .043 * height, material)


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 1.65 * spread
    scene_high[0] += 1.65 * spread; v21.base._camera(scene_low, scene_high, 0.0, output)
    v21.base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 2700
    bpy.context.scene.render.resolution_y = 900
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    v21.base._reset_scene(); rows = tuple(np.asarray(record[name]) for name in ("seed_points", "gcp_points"))
    triangles = _nearby(record, rows); frame = v21._basis(rows); low, high = v21._bounds(rows, triangles, *frame)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4)
    spread = 1.1 * width; radius = max(.012 * width, .001); materials = _materials()
    for index, (row, shift) in enumerate(zip(rows, (-spread, 0.0))):
        _panel(triangles, row, frame, shift, radius, materials, index); _label(record, index, shift, high, height, materials[index + 1])
    _overlay(triangles, rows, frame, spread, radius, materials); _label(record, 2, spread, high, height, materials[2])
    _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
