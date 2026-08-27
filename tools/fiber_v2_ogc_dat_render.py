"""Render span-SQP, GCP, OGC isotropic, and OGC Planar-DAT."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21

ISOTROPIC = "OGC_ISOTROPIC_F0.3_H16_R0.9"
PLANAR = "OGC_PLANAR_F0.03_H16_R0.9"


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _records(record):
    return (record["baseline"], record["gcp"], record["variants"][ISOTROPIC], record["variants"][PLANAR])


def _rows(record):
    return tuple(np.asarray(row["result"]["points"] if "result" in row else row["points"]) for row in _records(record))


def _materials():
    mesh = v21.base._material("COLLIDERS", (.08, .11, .16), alpha=.38)
    base = v21.base._material("SPAN_SQP", (.1, .78, 1.), .3)
    gcp = v21.base._material("GCP", (.9, .2, 1.), .3)
    isotropic = v21.base._material("OGC_ISOTROPIC", (1., .28, .05), .3)
    planar = v21.base._material("OGC_PLANAR", (.35, 1., .18), .3)
    marker = v21.base._material("WORST_FREE", (1., 1., .02), .5)
    return mesh, base, gcp, isotropic, planar, marker


def _marker(point, frame, shift, radius, material, name):
    value = v21.base._transform((point,), *frame, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=radius, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _panel(triangles, route, frame, shift, radius, materials, index, marker):
    center, axes = frame; v21.base._mesh(f"COLLIDER_{index}", triangles, center, axes, shift, materials[0])
    v21.base._curve(f"ROUTE_{index}", route, center, axes, shift, radius, materials[index + 1])
    _marker(route[marker], frame, shift, 2.0 * radius, materials[5], f"WORST_{index}")


def _label(record, index, shift, high, height, material):
    names = ("span-SQP", "GCP", "OGC isotropic", "OGC + Planar-DAT"); row = _records(record)[index]
    geo = row["geometry"]; text = f"{names[index]}  {row['timing']['median_ms']:.0f} ms  worst {geo['worst_free_turn']:.1f} deg @ {geo['worst_free_node']}"
    v21.p5._text(text, (shift, high[1] + .12 * height, high[2]), .035 * height, material)


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 2.1 * spread
    scene_high[0] += 2.1 * spread; v21.base._camera(scene_low, scene_high, 0.0, output)
    v21.base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 3200
    bpy.context.scene.render.resolution_y = 1000
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    v21.base._reset_scene(); rows = _rows(record); triangles = np.asarray(record["nearby_triangles"])
    frame = v21._basis(rows); low, high = v21._bounds(rows, triangles, *frame)
    width = max(high[0] - low[0], 1.0e-4); height = max(high[1] - low[1], 1.0e-4)
    spread = 1.1 * width; radius = max(.008 * width, .001); materials = _materials()
    shifts = (-1.5 * spread, -.5 * spread, .5 * spread, 1.5 * spread)
    for index, (route, shift, source) in enumerate(zip(rows, shifts, _records(record))):
        _panel(triangles, route, frame, shift, radius, materials, index, source["geometry"]["worst_free_node"])
        _label(record, index, shift, high, height, materials[index + 1])
    _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
