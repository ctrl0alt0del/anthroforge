"""Render the four composite-SQP ablations with identical framing."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21


VARIANTS = ("BASE", "TANGENTIAL", "COMPOSITE", "COMPOSITE_SOC")
LABELS = {"BASE": "BASE", "TANGENTIAL": "TANGENTIAL",
          "COMPOSITE": "COMPOSITE", "COMPOSITE_SOC": "COMPOSITE + SOC"}


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record):
    return tuple(np.asarray(record["variants"][name]["result"]["points"]) for name in VARIANTS)


def _materials():
    colors = ((.05, .72, 1.0), (1.0, .65, .04), (.30, 1.0, .22), (.85, .16, 1.0))
    routes = tuple(v21.base._material(name, color, .3) for name, color in zip(VARIANTS, colors))
    mesh = v21.base._material("COLLIDERS", (.08, .11, .16), alpha=.42)
    marker = v21.base._material("WORST FREE NODE", (1., .03, .02), .5)
    return mesh, routes, marker


def _marker(point, center, axes, shift, radius, material, name):
    value = v21.base._transform((point,), center, axes, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=radius, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _label(record, name, shift, high, height, material):
    row = record["variants"][name]; geometry = row["geometry"]; timing = row["warm"]["median_ms"]
    status = row["result"]["termination"]; turn = geometry["worst_free_turn"]
    text = f"{LABELS[name]} | {timing:.0f} ms | {status} | {turn:.1f} deg"
    v21.p5._text(text, (shift, high[1] + .12 * height, high[2]), .032 * height, material)


def _panel(record, rows, triangles, frame, spread, radius, materials, high, height, index):
    name = VARIANTS[index]; shift = (index - 1.5) * spread; center, axes = frame
    v21._panel(triangles, rows[index], index, shift, center, axes, radius, (materials[0], materials[1]))
    worst = record["variants"][name]["geometry"]["worst_free_node"]
    _marker(rows[index][worst], center, axes, shift, 2.0 * radius, materials[2], f"WORST_{name}")
    _label(record, name, shift, high, height, materials[1][index])


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 2.0 * spread
    scene_high[0] += 2.0 * spread; v21.base._camera(scene_low, scene_high, 0.0, output)
    v21.base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 3200
    bpy.context.scene.render.resolution_y = 900
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    v21.base._reset_scene(); rows = _rows(record); triangles = np.asarray(record["nearby_triangles"])
    frame = v21._basis(rows); low, high = v21._bounds(rows, triangles, *frame)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4)
    spread = 1.32 * width; radius = max(.006 * spread, .001); base, routes, marker = _materials()
    for index in range(4): _panel(record, rows, triangles, frame, spread, radius,
                                  (base, routes, marker), high, height, index)
    _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
