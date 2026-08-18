"""Render an all-Fiber V2.4 diagnostic contact sheet."""

import argparse
import json
from math import ceil
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_package5_render as p5
import fiber_v2_planner_41_blender_render as base


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    parser.add_argument("--fiber-id", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _materials():
    mesh = base._material("COLLIDERS", (.09, .12, .17), alpha=.34)
    source = base._material("CURRENT", (1.0, .33, .03), .28)
    planner = base._material("PLANNER", (.02, .78, 1.0), .35)
    final = base._material("V2.4", (.80, .14, 1.0), .45)
    pins = base._material("PINS", (1.0, .92, .05), .4)
    return mesh, source, planner, final, pins


def _paths(row):
    visual = row["visual"]
    return tuple(np.asarray(visual[key], dtype=np.float64).reshape((-1, 3))
                 for key in ("source", "planner", "v24"))


def _frame(row):
    paths = tuple(value for value in _paths(row) if len(value)); cloud = np.vstack(paths)
    center = cloud.mean(axis=0); _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False)
    local = tuple((value - center) @ axes.T for value in paths)
    bounds = np.vstack(local); span = np.maximum(np.ptp(bounds[:, :2], axis=0), 1.0e-4)
    scale = max(span[0] / 1.55, span[1] / 1.05, 1.0e-4)
    return center, axes, scale


def _local(values, frame, offset):
    center, axes, scale = frame; points = np.asarray(values).reshape((-1, 3))
    output = (points - center) @ axes.T / scale; output += np.asarray(offset)
    return output


def _curve(name, points, frame, offset, radius, material):
    if not len(points): return
    values = _local(points, frame, offset)
    base._curve(name, values, np.zeros(3), np.eye(3), 0.0, radius, material)


def _mesh(name, triangles, frame, offset, material):
    if not len(triangles): return
    values = _local(triangles, frame, offset).reshape((-1, 3, 3))
    base._mesh(name, values, np.zeros(3), np.eye(3), 0.0, material)


def _pin(name, point, frame, offset, material):
    value = _local([point], frame, offset)[0]
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=.035, location=value)
    bpy.context.object.name = name; bpy.context.object.data.materials.append(material)


def _label(row, offset, material):
    result = row["result"]; status = result["termination"]
    first = f'{row["fiber"]}  {status}  {result.get("route", "")}'
    second = _metric_label(row)
    p5._text(first, (offset[0], offset[1] + .72, .55), .085, material)
    p5._text(second, (offset[0], offset[1] + .59, .55), .052, material)


def _metric_label(row):
    current = row["metrics"].get("source", {}).get("length", 0.0)
    final = row["metrics"].get("v24", {}).get("length", 0.0)
    delta = row.get("planner_to_final", {}).get("max")
    ratio = final / current if current > 1.0e-12 else 0.0
    return f"L24/Lcur {ratio:.3f}   planner-final {delta if delta is not None else 0.0:.4g}"


def _tile(row, index, columns, materials):
    column, line = index % columns, index // columns
    offset = (2.05 * column, -1.65 * line, 0.0); frame = _frame(row)
    _mesh(f"MESH_{index}", row["visual"]["nearby_triangles"], frame, offset, materials[0])
    for name, points, radius, material in zip(("CURRENT", "PLANNER", "V24"), _paths(row),
                                               (.030, .021, .012), materials[1:4]):
        _curve(f"{name}_{index}", points, frame, offset, radius, material)
    for pin, point in enumerate(row["visual"]["anchors"]):
        _pin(f"PIN_{index}_{pin}", point, frame, offset, materials[4])
    _label(row, offset, materials[3])


def _filtered(record, identifier):
    rows = record["fibers"]
    selected = [row for row in rows if not identifier or row["fiber"] == identifier]
    return sorted(selected, key=lambda row: _number(row["fiber"]))


def _number(identifier):
    try: return int(str(identifier).rsplit("_", 1)[-1])
    except ValueError: return 0


def _finish(rows, columns, output, blend_output):
    lines = ceil(len(rows) / columns); low = np.array((-.95, -1.65 * (lines - 1) - .75, -1.0))
    high = np.array((2.05 * (columns - 1) + .95, .85, 1.0)); base._camera(low, high, 0.0, output)
    base._lights(low, high); scene = bpy.context.scene; scene.render.resolution_x = 1000 * columns
    scene.render.resolution_y = 800 * lines
    width, height = high[0] - low[0], high[1] - low[1]
    aspect = scene.render.resolution_x / scene.render.resolution_y
    scene.camera.data.ortho_scale = max(height, width / aspect) * 1.05
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output, identifier):
    base._reset_scene(); rows = _filtered(record, identifier); columns = min(5, len(rows))
    materials = _materials()
    for index, row in enumerate(rows): _tile(row, index, columns, materials)
    _finish(rows, columns, output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output, args.fiber_id)


if __name__ == "__main__":
    main()
