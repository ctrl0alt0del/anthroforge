import json
import time

import numpy as np

from .classification import current_change_state, previous_change_state

try:
    from ...core.draft_skin.protocol import write_capture as write_skin_capture
    from ...core.draft_skin.protocol import write_result as write_skin_result
    from ...core.topology.protocol import write_capture as write_topology_capture
    from ...core.topology.protocol import write_result as write_topology_result
except ImportError:
    from core.draft_skin.protocol import write_capture as write_skin_capture
    from core.draft_skin.protocol import write_result as write_skin_result
    from core.topology.protocol import write_capture as write_topology_capture
    from core.topology.protocol import write_result as write_topology_result


def prepare_array_job(context, root, spec):
    from ..draft_skin.vendor import ensure_worker_dependencies
    ensure_worker_dependencies()
    timings, started = {}, time.perf_counter()
    _bake(context); timings["bake"] = time.perf_counter() - started
    previous, skin, topology = _captures(root, context, timings)
    decision = _decision(previous, skin, topology, spec.mode)
    current_skin, current_topology = _current_outputs(root, context.scene)
    encoded = time.perf_counter()
    _write_payloads(spec, skin, topology, current_skin, current_topology)
    timings["serialization"] = time.perf_counter() - encoded
    _write_bound_skin(spec, root, context.scene, current_topology)
    _write_request(spec, decision, timings)


def _bake(context):
    try:
        from ...app.runtime_api import sync_context
    except ImportError:
        from app.runtime_api import sync_context
    sync_context(context, bake=True, source="warm_update", event_type="BAKE")
    context.view_layer.update()


def _captures(root, context, timings):
    from ..draft_skin.capture import capture_skin
    from ..topology.capture import capture_topology, capture_topology_surface
    depsgraph, started = context.evaluated_depsgraph_get(), time.perf_counter()
    previous = previous_change_state(root, context.scene)
    skin = capture_skin(root, context.scene, depsgraph)
    timings["skin_capture"] = time.perf_counter() - started
    started = time.perf_counter()
    topology = (capture_topology(root, context.scene, depsgraph) if previous.has_skin else
                _topology_without_skin(root, context.scene, depsgraph, skin, capture_topology_surface))
    timings["topology_capture"] = time.perf_counter() - started
    return previous, skin, topology


def _topology_without_skin(root, scene, depsgraph, skin, capture):
    vertices, triangles, offset = [], [], 0
    for source in skin.sources:
        vertices.append(np.asarray(source.vertices)); triangles.append(np.asarray(source.triangles) + offset)
        offset += len(source.vertices)
    return capture(root, scene, depsgraph, np.concatenate(vertices), np.concatenate(triangles))


def _decision(previous, skin, topology, mode):
    try:
        from ...core.warm_start.invalidation import classify_change
    except ImportError:
        from core.warm_start.invalidation import classify_change
    if topology is None:
        return classify_change(previous, previous, "FULL")
    force = {"FORCE_SKIN": "SKIN", "FORCE_TOPOLOGY": "TOPOLOGY",
             "FORCE_FULL": "FULL"}.get(mode, "AUTO")
    return classify_change(previous, current_change_state(skin, topology), force)


def _current_outputs(root, scene):
    from .current_output import current_skin_result, current_topology_result
    return current_skin_result(root, scene), current_topology_result(root, scene)


def _write_payloads(spec, skin, topology, old_skin, old_topology):
    write_skin_capture(spec.skin_capture_path, skin)
    if topology is not None:
        write_topology_capture(spec.topology_capture_path, topology)
    if old_skin is not None:
        write_skin_result(spec.current_skin_path, old_skin)
    if old_topology is not None:
        write_topology_result(spec.current_topology_path, old_topology)


def _write_request(spec, decision, timings):
    try:
        from ...core.warm_start.job import atomic_json
    except ImportError:
        from core.warm_start.job import atomic_json
    payload = {"classification": decision.change_class.value,
               "reasons": list(decision.reasons), "skin_rebuild": decision.skin_rebuild,
               "topology_rebuild": decision.topology_rebuild, "client_timings": timings,
               "dispatched_at": time.time()}
    atomic_json(spec.request_path, payload)


def _write_bound_skin(spec, root, scene, topology):
    from pathlib import Path
    from .current_output import bound_skin_result
    if topology is not None:
        result = bound_skin_result(root, scene)
        if result is not None:
            write_skin_result(Path(spec.job_dir) / "bound_skin.npz", result)
