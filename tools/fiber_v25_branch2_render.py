"""Render stored, planner, V2.4, and V2.5 branch-2 paths left to right."""

import argparse
import json
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
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _materials():
    return (base._material("COLLIDERS", (.08, .11, .15), alpha=.22),
            base._material("STORED_V1", (1.0, .31, .03), emission=.22),
            base._material("PLANNER", (.02, .78, 1.0), emission=.22),
            base._material("V2_4", (.80, .14, 1.0), emission=.22),
            base._material("V2_5_BRANCH2", (.12, .95, .32), emission=.22),
            base._material("PINS", (1.0, .92, .05), emission=.16))


def _paths(record):
    visual = record["visual"]
    return tuple(np.asarray(visual[key], dtype=np.float64).reshape((-1, 3))
                 for key in ("source", "planner", "v24", "v25"))


def _frame(paths):
    cloud = np.vstack(tuple(row for row in paths if len(row))); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False)
    bounds = np.vstack(tuple((row - center) @ axes.T for row in paths if len(row)))
    span = np.maximum(np.ptp(bounds[:, :2], axis=0), 1.0e-4)
    return center, axes, max(span[0] / 1.35, span[1] / 1.05, 1.0e-4)


def _local(values, frame, offset):
    center, axes, scale = frame; points = np.asarray(values).reshape((-1, 3))
    return (points - center) @ axes.T / scale + np.asarray(offset)


def _curve(name, points, frame, offset, material):
    values = _local(points, frame, offset); values[:, 2] += .35
    base._curve(name, values, np.zeros(3), np.eye(3), 0.0, .025, material)


def _mesh(name, triangles, frame, offset, material):
    values = _local(triangles, frame, offset).reshape((-1, 3, 3))
    base._mesh(name, values, np.zeros(3), np.eye(3), 0.0, material)


def _pins(record, frame, offset, material):
    for index, point in enumerate(record["anchors"]):
        location = _local([point], frame, offset)[0]; location[2] += .35
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=.034,
            location=location)
        bpy.context.object.name = f"PIN_{index}"; bpy.context.object.data.materials.append(material)


def _metrics(points):
    from fiber_v25_branch2_sweep import _metrics as path_metrics
    return path_metrics(points)


def _label(name, metrics, offset, material):
    p5._text(name, (offset[0], .72, 1.1), .085, material)
    value = f"max {metrics['max_turn_deg']:.1f}°  p95 {metrics['p95_turn_deg']:.1f}°"
    p5._text(value, (offset[0], .59, 1.1), .052, material)


def _tile(record, path, name, index, frame, materials):
    offset = (2.0 * index, 0.0, 0.0)
    _mesh(f"MESH_{index}", record["visual"]["nearby_triangles"], frame, offset, materials[0])
    _curve(name, path, frame, offset, materials[index + 1])
    _pins(record, frame, offset, materials[5]); _label(name, _metrics(path), offset, materials[index + 1])


def _finish(output, blend_output):
    low, high = np.array((-.85, -.75, -1.0)), np.array((6.85, .85, 1.0))
    base._camera(low, high, 0.0, output); base._lights(low, high)
    scene = bpy.context.scene; scene.render.resolution_x = 3200; scene.render.resolution_y = 850
    scene.camera.data.ortho_scale = 8.5
    if blend_output:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    base._reset_scene(); paths = _paths(record); frame = _frame(paths); materials = _materials()
    for index, (name, path) in enumerate(zip(("Stored V1", "Planner", "V2.4", "V2.5 branch2"), paths)):
        _tile(record, path, name, index, frame, materials)
    _finish(output, args.blend_output)


if __name__ == "__main__":
    main()
