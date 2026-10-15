"""Capture the native material chart, independently of the cropped display mesh."""
from dataclasses import replace


def request_for(root, scene, muscle):
    from ...core.visualization.muscle_numeric_runtime import _safe_branched_request, _numeric_input, _make_request
    from ...core.visualization.muscle_sync import register_muscle_sync
    request = _safe_branched_request(root, scene, muscle)
    return request or _make_request(muscle, _numeric_input(register_muscle_sync(), root, scene, muscle))


def material_chart(root, scene, muscle, role):
    from ...core.visualization.mirror_rules import effective_rule_for_muscle
    from ...core.visualization.geometry_instance import mirrored
    from ...core.vcp.muscle_numeric import execute_muscle_batch
    rule = effective_rule_for_muscle(muscle, {f.id:f for f in root.af_vcp_system.fibers},
                                   {s.id:s for s in root.af_scp_system.scps})
    with mirrored(rule if role == "MIRROR" else None):
        request = request_for(root, scene, muscle)
        result = execute_muscle_batch((replace(request, output_domain=None),), "NATIVE").results[0]
    if result.error: raise ValueError(result.error)
    return result


def consumed_fibers(root):
    surfaces = {s.id:s for s in root.af_vcp_system.fiber_surfaces}
    pending = list(root.af_vcp_system.muscles); fibers, seen = set(), set()
    while pending:
        source = pending.pop()
        if source.id in seen: continue
        seen.add(source.id); fibers.update(r.fiber_id for r in source.fiber_refs)
        keys = [getattr(source, "fiber_surface_id", ""), getattr(source, "main_surface_id", "")]
        keys.extend(b.surface_id for b in getattr(source, "branches", ()))
        pending.extend(surfaces[key] for key in keys if key in surfaces)
    return fibers
