import argparse
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np

ADDON_ROOT = Path(__file__).resolve().parents[1]
for value in (str(ADDON_ROOT), str(ADDON_ROOT.parent)):
    if value not in sys.path:
        sys.path.insert(0, value)


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--mode", choices=("BASELINE", "SMALL", "MEDIUM", "EXTREME", "ASYMMETRIC", "CONTACT"), default="SMALL")
    parser.add_argument("--shortcut")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--save")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--target", type=int)
    parser.add_argument("--symmetry", choices=("NONE", "X", "Y", "Z"))
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def register():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()


def root():
    return next((item for item in bpy.context.scene.objects if item.get("anthroforge_root")), None)


def run_update(mode):
    from app.use_cases.warm_update import complete_update, poll_update, start_update
    started = time.perf_counter(); action = start_update(bpy.context, mode)
    if not action.ok:
        raise RuntimeError(action.message)
    status = _wait(poll_update)
    action = complete_update(bpy.context, status)
    if not action.ok:
        raise RuntimeError(action.message)
    return time.perf_counter() - started


def _wait(poll):
    while True:
        status = poll(bpy.context)
        if status.state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return status
        time.sleep(0.25)


def edit_scene(root_obj, mode, shortcut_name):
    if mode == "BASELINE":
        return
    shortcut = _shortcut(root_obj, shortcut_name)
    if shortcut is not None:
        _edit_shortcut(shortcut, mode); return
    _edit_geometry(root_obj, mode)


def _shortcut(root_obj, name):
    values = tuple(root_obj.af_shortcut_system.shortcuts)
    if name:
        return next((item for item in values if name in {item.id, item.name}), None)
    return values[0] if values else None


def _edit_shortcut(shortcut, mode):
    from app.use_cases.shortcut_edit import resolve_shortcut_target, set_shortcut_value
    from core.shortcuts import target_value
    factor = {"SMALL": 1.01, "MEDIUM": 1.05, "EXTREME": 1.20,
              "ASYMMETRIC": 1.05, "CONTACT": 1.10}.get(mode, 1.0)
    target = resolve_shortcut_target(bpy.context, shortcut)
    current = float(target_value(target)) if target is not None else 0.0
    value = current * factor if abs(current) > 1e-9 else factor - 1.0
    if not set_shortcut_value(bpy.context, shortcut, value):
        raise RuntimeError(f"Could not edit shortcut {shortcut.name}.")


def _edit_geometry(root_obj, mode):
    objects = [item for item in bpy.context.scene.objects if item.get("af_scp_geometry")
               and item.get("af_root_name") == root_obj.name and not item.get("af_scp_mirror")]
    amount = {"SMALL": 1.01, "MEDIUM": 1.04, "EXTREME": 1.12,
              "ASYMMETRIC": 1.05, "CONTACT": 0.92}.get(mode, 1.0)
    selected = objects[:1] if mode == "ASYMMETRIC" else objects
    for item in selected:
        item.scale *= amount


def arrays(root_obj):
    skin = _output(root_obj, "af_draft_skin"); topology = _output(root_obj, "af_topology")
    return (_vertices(skin), _vertices(topology), _faces(topology),
            _stats(skin, "af_skin_stats_json"), _stats(topology, "af_topology_stats_json"))


def _output(root_obj, tag):
    return next(item for item in bpy.context.scene.objects if item.get(tag)
                and item.get("af_root_name") == root_obj.name)


def _vertices(obj):
    return np.asarray([vertex.co[:] for vertex in obj.data.vertices], dtype=float)


def _faces(obj):
    return np.asarray([tuple(face.vertices) for face in obj.data.polygons], dtype=np.int32)


def metrics(baseline, warm, full, times):
    from adapters.draft_skin.vendor import ensure_worker_dependencies
    ensure_worker_dependencies()
    from core.warm_start.metrics import inversion_count, surface_deviation
    warm_skin, warm_topology, quads = warm[:3]
    full_skin, full_topology = full[:2]
    times.update(warm_skin=warm[3].get("update_elapsed_seconds", 0.0),
                 topology_reprojection=warm[4].get("update_elapsed_seconds", 0.0))
    inversions = _inversions(baseline, warm, inversion_count)
    return _metric_payload(baseline, warm, times, inversions,
                           surface_deviation(warm_skin, full_skin),
                           surface_deviation(warm_topology, full_topology))


def _metric_payload(baseline, warm, times, inversions, skin_distance, topology_distance):
    return {"timing_seconds": times, "skin_surface_deviation": skin_distance,
            "topology_surface_deviation": topology_distance,
            "topology_inversions": inversions,
            "connectivity_preserved": bool(np.array_equal(baseline[2], warm[2])),
            "warm_skin_vertices": len(warm[0]), "topology_quads": len(warm[2]),
            "self_intersections": warm[4].get("self_intersections", 0),
            "guide_error": warm[4].get("guide_error", 0.0),
            "symmetry_error": warm[4].get("symmetry_error", 0.0)}


def _inversions(baseline, warm, function):
    if baseline[1].shape != warm[1].shape or not np.array_equal(baseline[2], warm[2]):
        return -1
    return function(baseline[1], warm[1], baseline[2])


def _stats(obj, name):
    try:
        return json.loads(obj.get(name, "{}"))
    except (TypeError, ValueError):
        return {}


def write_report(path, payload):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main():
    args = arguments(); register(); root_obj = root()
    if root_obj is None:
        raise RuntimeError("Acceptance scene has no AF_ROOT.")
    _configure(root_obj, args)
    if args.prepare_only:
        _prepare_acceptance(args, root_obj); return
    payload = _run_acceptance(args, root_obj)
    payload.update(scene=bpy.data.filepath, mode=args.mode)
    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save).resolve()), copy=True)
    write_report(args.report, payload); print("AF_WARM_ACCEPTANCE", json.dumps(payload), flush=True)


def _run_acceptance(args, root_obj):
    bootstrap = run_update("AUTO") if args.bootstrap else 0.0
    baseline = arrays(root_obj)
    edit_scene(root_obj, args.mode, args.shortcut)
    warm_time = run_update("AUTO"); warm = arrays(root_obj)
    full_time = run_update("FORCE_FULL"); full = arrays(root_obj)
    payload = metrics(baseline, warm, full, {"bootstrap": bootstrap,
                      "warm_total": warm_time, "full_generation": full_time})
    payload.update(warm_skin_update=warm[3].get("last_update_type", ""),
                   warm_topology_update=warm[4].get("last_update_type", ""))
    return payload


def _configure(root_obj, args):
    settings = root_obj.af_topology_settings
    if args.target:
        settings.target_quad_count = int(args.target)
    if args.symmetry:
        settings.symmetry_mode = args.symmetry


def _prepare_acceptance(args, root_obj):
    elapsed = run_update("PREPARE")
    skin = _optional_output(root_obj, "af_draft_skin")
    topology = _optional_output(root_obj, "af_topology")
    payload = {"scene": bpy.data.filepath, "mode": "PREPARE", "elapsed_seconds": elapsed,
               "skin_vertices": 0 if skin is None else len(skin.data.vertices),
               "topology_vertices": 0 if topology is None else len(topology.data.vertices)}
    write_report(args.report, payload)
    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save).resolve()), copy=True)
    print("AF_WARM_ACCEPTANCE", json.dumps(payload), flush=True)


def _optional_output(root_obj, tag):
    return next((item for item in bpy.context.scene.objects if item.get(tag)
                 and item.get("af_root_name") == root_obj.name), None)


if __name__ == "__main__":
    main()
