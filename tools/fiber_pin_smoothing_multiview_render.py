"""Render stored, planner, V2.4, and guarded recovery from three views."""

import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_pin_smoothing_render as view
import fiber_v25_branch2_render as render


def _views(axes):
    return (("Principal", axes), ("Profile", axes[[0, 2, 1]]),
            ("End", axes[[1, 2, 0]]))


def _frame(paths, center, axes):
    bounds = np.vstack(tuple((row - center) @ axes.T for row in paths))
    span = np.maximum(np.ptp(bounds[:, :2], axis=0), 1.0e-4)
    return center, axes, max(span[0] / 1.35, span[1] / 1.05, 1.0e-4)


def _tile(record, path, name, line, column, frame, materials):
    offset = (2.0 * column, -2.1 * line, 0.0)
    render._mesh(f"MESH_{line}_{column}", record["visual"]["nearby_triangles"], frame, offset, materials[0])
    render._curve(f"{name}_{line}", path, frame, offset, materials[column + 1])
    render._pins(record, frame, offset, materials[5])
    if line == 0: render._label(name, render._metrics(path), offset, materials[column + 1])


def _view_label(name, line, material):
    render.p5._text(name, (-1.28, .02 - 2.1 * line, 1.1), .070, material)


def _finish(output, blend_output):
    low, high = np.array((-1.45, -5.35, -1.0)), np.array((7.45, 1.15, 1.0))
    render.base._camera(low, high, 0.0, output); render.base._lights(low, high)
    scene = render.bpy.context.scene; scene.render.resolution_x = 3200; scene.render.resolution_y = 2400
    scene.camera.data.ortho_scale = 7.2
    if blend_output: render.bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    render.bpy.ops.render.render(write_still=True)


def _build(record, output, blend_output):
    render.base._reset_scene(); paths = render._paths(record); center, axes, _scale = render._frame(paths)
    names = "Stored V1", "Planner", "V2.4", "Guarded recovery"; materials = view._materials()
    for line, (view_name, basis) in enumerate(_views(axes)):
        frame = _frame(paths, center, basis); _view_label(view_name, line, materials[5])
        for column, (name, path) in enumerate(zip(names, paths)):
            _tile(record, path, name, line, column, frame, materials)
    _finish(output, blend_output)


def main():
    args = render._args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output, args.blend_output)


if __name__ == "__main__":
    main()
