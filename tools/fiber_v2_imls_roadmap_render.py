"""Render the full ROADMAP, span-SQP, and selected IMLS Fiber result."""

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
    parser.add_argument("--variant", default="IMLS_F0.1_H2.5")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record, variant):
    target = record["variants"][variant]
    return (np.asarray(target["seed"]), np.asarray(record["baseline"]["result"]["points"]),
            np.asarray(target["points"]))


def _materials():
    mesh = v21.base._material("COLLIDERS", (.08, .11, .16), alpha=.38)
    seed = v21.base._material("ROADMAP", (1., .55, .05), .3)
    base = v21.base._material("SPAN_SQP", (.1, .78, 1.), .3)
    imls = v21.base._material("IMLS", (.92, .18, .72), .3)
    marker = v21.base._material("WORST_FREE", (1., .02, .01), .5)
    return mesh, seed, base, imls, marker


def _marker(point, center, axes, shift, radius, material, name):
    value = v21.base._transform((point,), center, axes, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=radius, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _panel(triangles, route, frame, shift, radius, materials, index, marker=None):
    center, axes = frame; v21.base._mesh(f"COLLIDER_{index}", triangles, center, axes, shift, materials[0])
    v21.base._curve(f"ROUTE_{index}", route, center, axes, shift, radius, materials[index + 1])
    if marker is not None: _marker(route[marker], center, axes, shift, 2.0 * radius, materials[4], f"WORST_{index}")


def _overlay(triangles, rows, frame, shift, radius, materials):
    center, axes = frame; v21.base._mesh("COLLIDER_OVERLAY", triangles, center, axes, shift, materials[0])
    v21.base._curve("SQP_OVERLAY", rows[1], center, axes, shift, 1.18 * radius, materials[2])
    v21.base._curve("IMLS_OVERLAY", rows[2], center, axes, shift, .68 * radius, materials[3])


def _label(record, variant, index, shift, high, height, material):
    if index == 0: text = "ROADMAP seed"
    elif index == 1:
        row = record["baseline"]; geo = row["geometry"]
        text = f"span-SQP {row['timing']['median_ms']:.0f} ms  worst free {geo['worst_free_turn']:.1f} deg @ {geo['worst_free_node']}"
    elif index == 2:
        row = record["variants"][variant]; geo = row["geometry"]
        text = f"IMLS {row['timing']['median_ms']:.0f} ms  worst free {geo['worst_free_turn']:.1f} deg @ {geo['worst_free_node']}"
    else: text = "OVERLAY  cyan span-SQP / magenta IMLS"
    v21.p5._text(text, (shift, high[1] + .12 * height, high[2]), .042 * height, material)


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 2.1 * spread
    scene_high[0] += 2.1 * spread; v21.base._camera(scene_low, scene_high, 0.0, output)
    v21.base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 3200
    bpy.context.scene.render.resolution_y = 1000
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, variant, output, blend_output):
    v21.base._reset_scene(); rows = _rows(record, variant); triangles = np.asarray(record["nearby_triangles"])
    frame = v21._basis(rows); low, high = v21._bounds(rows, triangles, *frame)
    width = max(high[0] - low[0], 1.0e-4); height = max(high[1] - low[1], 1.0e-4)
    spread = 1.1 * width; radius = max(.008 * width, .001); materials = _materials()
    markers = (None, record["baseline"]["geometry"]["worst_free_node"],
               record["variants"][variant]["geometry"]["worst_free_node"])
    for index, (row, shift, marker) in enumerate(zip(rows, (-1.5*spread, -.5*spread, .5*spread), markers)):
        _panel(triangles, row, frame, shift, radius, materials, index, marker)
        _label(record, variant, index, shift, high, height, materials[index + 1])
    _overlay(triangles, rows, frame, 1.5 * spread, radius, materials)
    _label(record, variant, 3, 1.5 * spread, high, height, materials[3])
    _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, args.variant, output, args.blend_output)


if __name__ == "__main__":
    main()
