"""Render matched span-SQP and High-Order IPC Fiber comparisons."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21


FULL = "HO_IPC_SPAN_SQP_S1_F0.03"
REDUCED = "HO_IPC_SPAN_SQP_S1.4_F0.03"


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _records(record):
    return record["baseline"], record["variants"][FULL], record["variants"][REDUCED]


def _routes(record):
    base, full, reduced = _records(record)
    return (np.asarray(base["result"]["points"]), np.asarray(full["points"]), np.asarray(reduced["points"]))


def _materials():
    mesh = v21.base._material("COLLIDERS", (.07, .09, .13), alpha=.42)
    base = v21.base._material("SPAN_SQP", (.08, .78, 1.), .3)
    full = v21.base._material("HO_64", (.92, .2, 1.), .3)
    reduced = v21.base._material("HO_48", (.25, 1., .22), .3)
    proxy = v21.base._material("DENSE_PROXY", (1., .6, .05), .18)
    marker = v21.base._material("WORST_FREE", (1., .04, .02), .5)
    return mesh, base, full, reduced, proxy, marker


def _marker(point, frame, shift, radius, material, name):
    value = v21.base._transform((point,), *frame, shift)[0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=radius, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _panel(triangles, route, proxy, frame, shift, radius, materials, index, marker):
    center, axes = frame; v21.base._mesh(f"COLLIDER_{index}", triangles, center, axes, shift, materials[0])
    if proxy is not None: v21.base._curve(f"PROXY_{index}", proxy, center, axes, shift, .45 * radius, materials[4])
    v21.base._curve(f"ROUTE_{index}", route, center, axes, shift, radius, materials[index + 1])
    _marker(route[marker], frame, shift, 2.0 * radius, materials[5], f"WORST_{index}")


def _label(record, index, shift, high, height, material):
    row = _records(record)[index]; names = ("span-SQP", "High-order 64 controls", "High-order 48 controls")
    timing = row["timing"]["median_ms"]; geometry = row["geometry"]
    controls = "" if index == 0 else f"  {row['stats']['control_count']} controls"
    text = f"{names[index]}  {timing:.0f} ms{controls}  worst {geometry['worst_free_turn']:.1f} deg"
    v21.p5._text(text, (shift, high[1] + .12 * height, high[2]), .037 * height, material)


def _finish(low, high, spread, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); scene_low[0] -= 1.65 * spread
    scene_high[0] += 1.65 * spread; v21.base._camera(scene_low, scene_high, 0.0, output)
    v21.base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 3000
    bpy.context.scene.render.resolution_y = 1050
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    v21.base._reset_scene(); routes = _routes(record); triangles = np.asarray(record["nearby_triangles"])
    frame = v21._basis(routes); low, high = v21._bounds(routes, triangles, *frame)
    width = max(high[0] - low[0], 1.0e-4); height = max(high[1] - low[1], 1.0e-4)
    spread = 1.15 * width; radius = max(.008 * width, .001); materials = _materials()
    proxies = (None, np.asarray(_records(record)[1]["proxy"]), np.asarray(_records(record)[2]["proxy"]))
    for index, (route, proxy, shift, source) in enumerate(zip(routes, proxies, (-spread, 0., spread), _records(record))):
        _panel(triangles, route, proxy, frame, shift, radius, materials, index, source["geometry"]["worst_free_node"])
        _label(record, index, shift, high, height, materials[index + 1])
    _finish(low, high, spread, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
