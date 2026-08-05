import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ADDON_ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ADDON_ROOT.parent), str(ADDON_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from core.warm_start.invalidation import WarmChangeClass, classify_change
from core.warm_start.job import read_job, write_status, write_summary
from core.warm_start.model import WarmUpdateStatus


def run_job(job_dir):
    started, spec = time.perf_counter(), read_job(job_dir / "job.json")
    root, scene, depsgraph = _load_scene(spec)
    if spec.mode == "PREPARE":
        _run_prepare(root, scene, depsgraph, spec, started); return
    _run_update(root, scene, depsgraph, spec, started)


def _run_update(root, scene, depsgraph, spec, started):
    previous, skin_capture, topology_capture = _captures(root, scene, depsgraph, spec)
    decision = _decision(previous, skin_capture, topology_capture, spec.mode)
    skin_result, skin_type = _solve_skin(root, scene, depsgraph, skin_capture, decision, spec)
    if skin_result is not None:
        _install_skin(root, scene, skin_result)
    topology_result, topology_type = _solve_topology(root, scene, depsgraph, decision, skin_type, spec)
    _write_results(spec, skin_result, topology_result)
    summary = _summary(decision, skin_type, topology_type, started, skin_result, topology_result)
    write_summary(spec.summary_path, summary)
    _status(spec, "SUCCEEDED", "Complete", 1.0, _summary_message(summary), summary["update_type"])


def _run_prepare(root, scene, depsgraph, spec, started):
    from adapters.draft_skin.capture import capture_skin
    from adapters.warm_update.migration import migration_state
    state = migration_state(root, scene)
    if not any(state.values()):
        raise ValueError("Existing outputs already contain warm-start bindings.")
    skin, skin_type, warnings = _prepare_skin_stage(root, scene, depsgraph, spec, state)
    if skin is not None:
        _install_skin(root, scene, skin)
    topology, topology_type, topology_warning = _prepare_topology_stage(root, scene, depsgraph, spec, state, skin_type)
    warnings.extend(topology_warning)
    _write_results(spec, skin, topology)
    _finish_prepare(spec, started, skin_type, topology_type, warnings, skin, topology)


def _prepare_skin_stage(root, scene, depsgraph, spec, state):
    if not state["skin"]:
        return None, "retained", []
    from adapters.draft_skin.capture import capture_skin
    capture = capture_skin(root, scene, depsgraph)
    try:
        from adapters.warm_update.migration import prepare_skin
        _status(spec, "RUNNING", "Binding skin", 0.16, "Binding existing draft-skin vertices.")
        return prepare_skin(root, scene, capture), "prepared", []
    except Exception as error:
        _append_log(spec, f"Skin migration fallback: {error}")
        return _rebuild_skin(capture, spec), "rebuilt", [str(error)]


def _rebuild_skin(capture, spec):
    from core.draft_skin.solver import solve_capture
    _status(spec, "RUNNING", "Skin rebuild", 0.18, "Skin binding failed; rebuilding draft skin.")
    result = solve_capture(capture, _skin_progress(spec), lambda: _cancelled(spec))
    result.statistics["last_update_type"] = "rebuilt"
    return result


def _prepare_topology_stage(root, scene, depsgraph, spec, state, skin_type):
    obj = _topology_object(root, scene)
    if obj is None:
        return None, "missing", []
    if state["topology"]:
        return _prepare_or_rebuild_topology(root, scene, depsgraph, spec)
    if skin_type == "rebuilt":
        warm = _try_warm_topology(root, scene, depsgraph, "rebuilt", spec)
        if warm is not None:
            return warm, "rebound", []
        return _full_topology(root, scene, depsgraph, spec), "rebuilt", ["Topology rebinding failed."]
    return None, "retained", []


def _prepare_or_rebuild_topology(root, scene, depsgraph, spec):
    try:
        from adapters.topology.capture import capture_topology
        from adapters.warm_update.migration import prepare_topology
        _status(spec, "RUNNING", "Binding topology", 0.58, "Binding existing topology vertices and guides.")
        return prepare_topology(root, scene, capture_topology(root, scene, depsgraph)), "prepared", []
    except Exception as error:
        _append_log(spec, f"Topology migration fallback: {error}")
        return _full_topology(root, scene, depsgraph, spec), "rebuilt", [str(error)]


def _finish_prepare(spec, started, skin_type, topology_type, warnings, skin, topology):
    update = "rebuilt" if "rebuilt" in {skin_type, topology_type} else "prepared"
    summary = {"classification": "MIGRATION", "reasons": warnings,
               "skin_update": skin_type, "topology_update": topology_type,
               "update_type": update, "elapsed_seconds": time.perf_counter() - started,
               "has_skin_result": skin is not None, "has_topology_result": topology is not None,
               "fallback_diagnostic": "; ".join(warnings)}
    write_summary(spec.summary_path, summary)
    _status(spec, "SUCCEEDED", "Complete", 1.0, _summary_message(summary), update)


def _load_scene(spec):
    _status(spec, "RUNNING", "Loading", 0.01, "Loading scene for coordinated update.")
    import bpy
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=spec.source_path)
    root = bpy.context.scene.objects.get(spec.root_name)
    if root is None or not root.get("anthroforge_root"):
        raise RuntimeError(f"The update scene has no AF_ROOT named {spec.root_name}.")
    _bake(spec); return root, bpy.context.scene, bpy.context.evaluated_depsgraph_get()


def _bake(spec):
    import bpy
    from app.runtime_api import sync_context
    _status(spec, "RUNNING", "Baking", 0.04, "Finalizing SCP and VCP runtime surfaces.")
    sync_context(bpy.context, bake=True, source="warm_update", event_type="BAKE")
    bpy.context.view_layer.update(); _check_cancelled(spec)


def _captures(root, scene, depsgraph, spec):
    from adapters.draft_skin.capture import capture_skin
    from adapters.warm_update.classification import previous_change_state
    _status(spec, "RUNNING", "Capturing", 0.08, "Capturing updated contributors and guides.")
    previous = previous_change_state(root, scene)
    skin = capture_skin(root, scene, depsgraph)
    topology = _capture_topology(root, scene, depsgraph) if previous.has_skin else None
    return previous, skin, topology


def _capture_topology(root, scene, depsgraph):
    from adapters.topology.capture import capture_topology
    return capture_topology(root, scene, depsgraph)


def _decision(previous, skin_capture, topology_capture, mode):
    from adapters.warm_update.classification import current_change_state
    if topology_capture is None:
        return classify_change(previous, previous, "FULL")
    current = current_change_state(skin_capture, topology_capture)
    force = {"FORCE_SKIN": "SKIN", "FORCE_TOPOLOGY": "TOPOLOGY",
             "FORCE_FULL": "FULL"}.get(mode, "AUTO")
    return classify_change(previous, current, force)


def _solve_skin(root, scene, depsgraph, capture, decision, spec):
    if spec.mode == "FORCE_TOPOLOGY" and not decision.skin_rebuild:
        return None, "retained"
    if not decision.skin_rebuild:
        warm = _try_warm_skin(root, scene, depsgraph, capture, spec)
        if warm is not None:
            return warm, "warm"
    _status(spec, "RUNNING", "Skin rebuild", 0.18, "Rebuilding draft skin.")
    from core.draft_skin.solver import solve_capture
    result = solve_capture(capture, _skin_progress(spec), lambda: _cancelled(spec))
    result.statistics["last_update_type"] = "rebuilt"
    return result, "rebuilt"


def _try_warm_skin(root, scene, depsgraph, capture, spec):
    try:
        from adapters.draft_skin.warm import capture_warm_skin
        from core.warm_start.skin_solver import solve_warm_skin
        _status(spec, "RUNNING", "Warm skin", 0.16, "Deforming existing draft skin.")
        started = time.perf_counter()
        warm_capture = capture_warm_skin(root, scene, depsgraph)
        result = solve_warm_skin(warm_capture)
        elapsed = time.perf_counter() - started
        return _warm_skin_result(root, scene, capture, warm_capture, result, elapsed) if result.status.valid else None
    except Exception as error:
        _append_log(spec, f"Warm skin fallback: {error}")
        return None


def _warm_skin_result(root, scene, capture, warm_capture, warm_result, elapsed=0.0):
    from core.draft_skin.model import SkinResult
    from core.draft_skin.validation import validate_mesh
    obj = _skin_object(root, scene); stats = _updated_skin_stats(obj, capture, "warm")
    stats["update_elapsed_seconds"] = float(elapsed)
    collagen = _point_attribute(obj.data, "af_skin_collagen")
    validation = validate_mesh(warm_result.vertices, warm_capture.triangles, True)
    return SkinResult(warm_result.vertices, warm_capture.triangles, collagen,
                      stats, validation, warm_result.binding)


def _updated_skin_stats(obj, capture, update_type):
    from core.warm_start.invalidation import source_contact_signature
    from core.warm_start.signatures import geometry_state_hash, source_connectivity_signature, source_identity_signature
    stats = _object_stats(obj, "af_skin_stats_json")
    stats.update(source_identity_signature=source_identity_signature(capture.sources),
                 source_connectivity_signature=source_connectivity_signature(capture.sources),
                 source_contact_signature=source_contact_signature(capture.sources),
                 geometry_state_hash=geometry_state_hash(capture.sources), last_update_type=update_type)
    return stats


def _install_skin(root, scene, result):
    from adapters.draft_skin.output import replace_draft_skin
    replace_draft_skin(scene, root, result, result.statistics.get("source_map", []))


def _solve_topology(root, scene, depsgraph, decision, skin_type, spec):
    if not decision.topology_rebuild and _topology_object(root, scene) is not None:
        warm = _try_warm_topology(root, scene, depsgraph, skin_type, spec)
        if warm is not None:
            return warm, "rebound" if skin_type == "rebuilt" else "warm"
    _status(spec, "RUNNING", "Topology rebuild", 0.62, "Rebuilding guided quad topology.")
    return _full_topology(root, scene, depsgraph, spec), "rebuilt"


def _try_warm_topology(root, scene, depsgraph, skin_type, spec):
    try:
        from adapters.topology.warm import rebind_after_skin, update_topology
        _status(spec, "RUNNING", "Topology update", 0.58, "Reprojecting existing quad topology.")
        started = time.perf_counter()
        result = rebind_after_skin(root, scene, depsgraph) if skin_type == "rebuilt" else update_topology(root, scene, depsgraph)
        status = result[3] if skin_type == "rebuilt" else result[1]
        elapsed = time.perf_counter() - started
        capture = _capture_topology(root, scene, depsgraph)
        return _topology_result(root, scene, status.update_type or "rebound", elapsed, capture) if status.valid else None
    except Exception as error:
        _append_log(spec, f"Topology fallback: {error}")
        return None


def _full_topology(root, scene, depsgraph, spec):
    from adapters.topology.capture import capture_topology
    from adapters.topology.solver import solve_capture
    from adapters.topology.vendor import ensure_worker_dependencies
    capture = capture_topology(root, scene, depsgraph); vendor = ensure_worker_dependencies()
    result = solve_capture(capture, vendor, _topology_progress(spec), lambda: _cancelled(spec))
    result.statistics["last_update_type"] = "rebuilt"
    return result


def _topology_result(root, scene, update_type, elapsed=0.0, capture=None):
    from adapters.topology.warm import _face_values, _mesh_arrays, _read_bindings
    from core.topology.model import TopologyResult
    from core.topology.validation import validate_topology
    obj = _topology_object(root, scene); vertices, quads = _mesh_arrays(obj)
    skin, guide = _read_bindings(obj.data); stats = _object_stats(obj, "af_topology_stats_json")
    stats.update(last_update_type=update_type, update_elapsed_seconds=float(elapsed))
    stats.update(_warm_topology_metrics(obj, vertices, quads, guide, capture))
    owners = _optional_point_attribute(obj.data, "af_topology_owner_scp_index", np.int32)
    lengths = _optional_point_attribute(obj.data, "af_topology_target_edge_length", np.float32)
    return TopologyResult(vertices, quads, _face_values(obj.data, "af_topology_region"),
                          _face_values(obj.data, "af_topology_face_guide_index"), stats,
                          validate_topology(vertices, quads), owners, lengths, skin, guide)


def _warm_topology_metrics(obj, vertices, quads, binding, capture):
    if capture is None:
        return {}
    from adapters.topology.engine.instant import self_intersection_count
    from adapters.topology.warm import _current_patch_guides
    from core.warm_start.metrics import guide_error
    guides = _current_patch_guides(obj, capture.guides)
    values = guide_error(vertices, binding, guides)
    symmetry = _symmetry_metric(vertices, capture)
    return {"guide_error": values["max"], "symmetry_error": symmetry,
            "self_intersections": self_intersection_count(vertices, tuple(map(tuple, quads)))}


def _symmetry_metric(vertices, capture):
    if capture.plane is None:
        return 0.0
    from core.warm_start.metrics import symmetry_error
    return symmetry_error(vertices, capture.plane.origin, capture.plane.normal)["max"]


def _write_results(spec, skin, topology):
    if skin is not None:
        from core.draft_skin.protocol import write_result
        write_result(spec.skin_result_path, skin)
    if topology is not None:
        from core.topology.protocol import write_result
        write_result(spec.topology_result_path, topology)


def _summary(decision, skin_type, topology_type, started, skin, topology):
    values = [value for value in (skin_type, topology_type) if value]
    update_type = "rebuilt" if "rebuilt" in values else ("rebound" if "rebound" in values else "warm")
    fallback = _fallback_diagnostic(decision, skin_type, topology_type)
    return {"classification": decision.change_class.value, "reasons": list(decision.reasons),
            "skin_update": skin_type, "topology_update": topology_type,
            "update_type": update_type, "elapsed_seconds": time.perf_counter() - started,
            "has_skin_result": skin is not None, "has_topology_result": topology is not None,
            "fallback_diagnostic": fallback}


def _fallback_diagnostic(decision, skin_type, topology_type):
    values = []
    if not decision.skin_rebuild and skin_type == "rebuilt":
        values.append("warm skin validation failed; rebuilt skin")
    if not decision.topology_rebuild and topology_type == "rebuilt":
        values.append("topology reprojection/rebinding failed; rebuilt topology")
    return "; ".join(values)


def _summary_message(summary):
    return (f"Update {summary['update_type']} in {summary['elapsed_seconds']:.2f}s "
            f"({summary['classification']}).")


def _status(spec, state, stage, progress, message, update_type=""):
    write_status(spec.status_path, WarmUpdateStatus(state != "FAILED", stage, progress,
                 message, state=state, update_type=update_type))


def _skin_progress(spec):
    return lambda stage, value, message="": _status(spec, "RUNNING", stage, 0.18 + 0.34 * value, message)


def _topology_progress(spec):
    return lambda stage, value, message="": _status(spec, "RUNNING", stage, 0.62 + 0.34 * value, message)


def _skin_object(root, scene):
    return next(obj for obj in scene.objects if obj.get("af_draft_skin")
                and obj.get("af_root_name") == root.name)


def _topology_object(root, scene):
    return next((obj for obj in scene.objects if obj.get("af_topology")
                 and obj.get("af_root_name") == root.name), None)


def _object_stats(obj, name):
    try:
        return json.loads(obj.get(name, "{}"))
    except (TypeError, ValueError):
        return {}


def _point_attribute(mesh, name):
    attribute = mesh.attributes.get(name); values = np.zeros(len(mesh.vertices), np.float32)
    if attribute is not None:
        attribute.data.foreach_get("value", values)
    return values


def _optional_point_attribute(mesh, name, dtype):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        return None
    values = np.empty(len(mesh.vertices), dtype=dtype)
    attribute.data.foreach_get("value", values)
    return values


def _cancelled(spec):
    return Path(spec.cancel_path).exists()


def _check_cancelled(spec):
    if _cancelled(spec):
        raise RuntimeError("Coordinated update cancelled.")


def _append_log(spec, message):
    with Path(spec.log_path).open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def fail_job(job_dir, error):
    spec = read_job(job_dir / "job.json"); _append_log(spec, traceback.format_exc())
    cancelled = _cancelled(spec)
    state, message = ("CANCELLED", "Update cancelled.") if cancelled else ("FAILED", str(error))
    write_status(spec.status_path, WarmUpdateStatus(False, state.title(), 0.0, message,
                 state=state, cancelled=cancelled))


def job_argument():
    args = sys.argv[sys.argv.index("--") + 1:]
    return Path(args[args.index("--job") + 1])


def main():
    job_dir = job_argument()
    try:
        from adapters.draft_skin.vendor import ensure_worker_dependencies
        ensure_worker_dependencies(); run_job(job_dir)
    except Exception as error:
        fail_job(job_dir, error)
        if not _cancelled(read_job(job_dir / "job.json")):
            raise


if __name__ == "__main__":
    main()
