"""Render ROADMAP shortcut and curvature-ablation results."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v21_render as v21


NAMES = ("BASELINE", "SHORTCUT", "CURVATURE_HALF", "CURVATURE_THIRD",
         "UNSHORTCUT_CURVATURE_ZERO", "CURVATURE_ZERO", "CURVATURE_ZERO_HIGHCAP")
ZERO_NAMES = ("UNSHORTCUT_CURVATURE_ZERO", "CURVATURE_ZERO")
BROAD_NAMES = ("BASELINE", *ZERO_NAMES)
CAP_NAMES = ("BASELINE", "CURVATURE_ZERO", "CURVATURE_ZERO_HIGHCAP")
IRLS_NAMES = ("SQUARED_LENGTH_ZERO", "TRUE_LENGTH_IRLS",
              "TRUE_LENGTH_IRLS_FIDELITY_01", "TRUE_LENGTH_IRLS_FIDELITY_001")
FIX_PERF_NAMES = ("BASE_IRLS", "MANIFOLD", "ALL_01")
FIX_QUALITY_NAMES = ("BASE_IRLS", "SPACING_05", "CURV_001_SPACE_05", "CURV_01_SPACE_05")
FIX_FINAL_NAMES = ("BASE_IRLS", "ADAPTIVE")
REG_NAMES = ("BASE", "REG_ADAPTIVE", "REG_ADAPTIVE_SPACING")
COLORS = ((.05, .68, 1.), (.1, 1., .42), (1., .8, .05), (1., .38, .04),
          (.2, .7, 1.), (.95, .08, .6), (1., .42, .03))
IRLS_COLORS = {IRLS_NAMES[0]: (.15, .65, 1.), IRLS_NAMES[1]: (1., .12, .62),
               IRLS_NAMES[2]: (1., .62, .04), IRLS_NAMES[3]: (.3, 1., .25)}
FIX_COLORS = {"BASE_IRLS": (.15, .65, 1.), "MANIFOLD": (1., .2, .55),
              "ALL_01": (.25, 1., .35), "SPACING_05": (1., .65, .05),
              "CURV_001_SPACE_05": (.65, .25, 1.), "CURV_01_SPACE_05": (.2, 1., .8)}
FIX_COLORS["ADAPTIVE"] = (.25, 1., .4)
FIX_COLORS.update({"BASE": (.15, .65, 1.), "REG_ADAPTIVE": (1., .62, .04),
                   "REG_ADAPTIVE_SPACING": (.25, 1., .4)})


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    modes = ("seeds", "results", "zero", "broad", "cap", "irls", "irls-selected",
             "fix-performance", "fix-quality", "fix-final", "regularized")
    parser.add_argument("--mode", choices=modes, default="results")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _rows(record, mode):
    key = "seed_points" if mode == "seeds" else "result_points"
    names = _mode_names(mode)
    return names, tuple(np.asarray(record["variants"][name][key]) for name in names)


def _mode_names(mode):
    if mode == "seeds": return NAMES[:2]
    if mode == "zero": return ZERO_NAMES
    if mode == "broad": return BROAD_NAMES
    if mode == "cap": return CAP_NAMES
    if mode == "irls-selected": return IRLS_NAMES[0], IRLS_NAMES[-1]
    if mode == "fix-performance": return FIX_PERF_NAMES
    if mode == "fix-quality": return FIX_QUALITY_NAMES
    if mode == "fix-final": return FIX_FINAL_NAMES
    if mode == "regularized": return REG_NAMES
    return IRLS_NAMES if mode == "irls" else NAMES[:-1]


def _materials(names):
    mesh = v21.base._material("COLLIDERS", (.07, .09, .13), alpha=.48)
    routes = tuple(v21.base._material(name, _color(name), .3) for name in names)
    return mesh, routes


def _color(name):
    return FIX_COLORS.get(name, IRLS_COLORS.get(
        name, COLORS[NAMES.index(name)] if name in NAMES else (1., 1., 1.)))


def _label(record, name, mode):
    row = record["variants"][name]; key = "seed_geometry" if mode == "seeds" else "result_geometry"
    geometry = row.get(key, row.get("geometry"))
    if mode == "seeds": return f"{name} SEED | L {geometry['path_length']:.3f} | turn {geometry['worst_free_turn']:.1f}°"
    status = row["result"]["termination"]
    return f"{name} | L {geometry['path_length']:.3f} | turn {geometry['worst_free_turn']:.1f}° | {status}"


def _panel(triangles, route, name, shift, frame, radius, materials, index):
    center, axes = frame; v21.base._mesh(f"COLLIDER_{name}", triangles, center, axes, shift, materials[0])
    v21.base._curve(f"ROUTE_{name}", route, center, axes, shift, radius, materials[1][index])


def _finish(low, high, spread, count, output, blend_output):
    scene_low, scene_high = low.copy(), high.copy(); extra = .62 * count * spread
    scene_low[0] -= extra; scene_high[0] += extra; v21.base._camera(scene_low, scene_high, 0.0, output)
    v21.base._lights(scene_low, scene_high); bpy.context.scene.render.resolution_x = 850 * count
    bpy.context.scene.render.resolution_y = 1000
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    bpy.ops.render.render(write_still=True)


def _build(record, mode, output, blend_output):
    v21.base._reset_scene(); names, rows = _rows(record, mode); triangles = np.asarray(record["nearby_triangles"])
    frame = v21._basis(rows); low, high = v21._bounds(rows, triangles, *frame)
    width = max(high[0] - low[0], 1e-4); height = max(high[1] - low[1], 1e-4)
    spread = 1.2 * width; radius = max(.008 * width, .001); materials = _materials(names)
    shifts = tuple((index - (len(rows) - 1) / 2) * spread for index in range(len(rows)))
    for index, (name, route, shift) in enumerate(zip(names, rows, shifts)):
        _panel(triangles, route, name, shift, frame, radius, materials, index)
        v21.p5._text(_label(record, name, mode), (shift, high[1] + .12 * height, high[2]), .026 * height, materials[1][index])
    _finish(low, high, spread, len(rows), output, blend_output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, args.mode, output, args.blend_output)


if __name__ == "__main__":
    main()
