"""Render span-SQP, GCP, and GCP plus Planar-DAT on the full Fiber."""

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
    parser.add_argument("--variant", default="GCP_DAT_F0.1_H64_R0.9")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record, variant):
    return (np.asarray(record["baseline"]["result"]["points"]), np.asarray(record["gcp"]["points"]),
            np.asarray(record["variants"][variant]["points"]))


def _materials():
    mesh = v21.base._material("COLLIDERS", (.08, .11, .16), alpha=.38)
    base = v21.base._material("SPAN_SQP", (.1, .78, 1.), .3)
    gcp = v21.base._material("GCP", (.9, .2, 1.), .3)
    dat = v21.base._material("GCP_DAT", (1., .65, .04), .3)
    marker = v21.base._material("WORST_FREE", (1., .02, .01), .5)
    return mesh, base, gcp, dat, marker


def _marker(point, frame, shift, radius, material, name):
    value = v21.base._transform((point,), *frame, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=radius, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _panel(triangles, route, frame, shift, radius, materials, index, marker):
    center, axes = frame; v21.base._mesh(f"COLLIDER_{index}", triangles, center, axes, shift, materials[0])
    v21.base._curve(f"ROUTE_{index}", route, center, axes, shift, radius, materials[index + 1])
    _marker(route[marker], frame, shift, 2.0 * radius, materials[4], f"WORST_{index}")


def _overlay(triangles, rows, frame, shift, radius, materials):
    center, axes = frame; v21.base._mesh("COLLIDER_OVERLAY", triangles, center, axes, shift, materials[0])
    for index, row in enumerate(rows):
        v21.base._curve(f"OVERLAY_{index}", row, center, axes, shift, radius * (1.3 - .3 * index), materials[index + 1])


def _label_data(record, variant, index):
    if index == 0: return "span-SQP", record["baseline"]
    if index == 1: return "GCP", record["gcp"]
    return "GCP + Planar-DAT", record["variants"][variant]


def _label(record, variant, index, shift, high, height, material):
    if index == 3: text = "OVERLAY  cyan SQP / purple GCP / orange GCP+DAT"
    else:
        name, row = _label_data(record, variant, index); geo = row["geometry"]
        text = f"{name}  {row['timing']['median_ms']:.0f} ms  worst free {geo['worst_free_turn']:.1f} deg @ {geo['worst_free_node']}"
    v21.p5._text(text, (shift, high[1] + .12 * height, high[2]), .034 * height, material)


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
    records = (record["baseline"], record["gcp"], record["variants"][variant])
    for index, (row, shift, source) in enumerate(zip(rows, (-1.5*spread, -.5*spread, .5*spread), records)):
        _panel(triangles, row, frame, shift, radius, materials, index, source["geometry"]["worst_free_node"])
        _label(record, variant, index, shift, high, height, materials[index + 1])
    _overlay(triangles, rows, frame, 1.5 * spread, radius, materials)
    _label(record, variant, 3, 1.5 * spread, high, height, materials[3]); _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, args.variant, output, args.blend_output)


if __name__ == "__main__":
    main()
