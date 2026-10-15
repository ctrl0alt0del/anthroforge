"""Explicit artifact checks: capture on Blender thread, native work off-thread."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Event
from types import SimpleNamespace
from .mesh_issues import session, PROVIDER, _reference, _issue, _payload


def schedule(obj, scene, root):
    from ..core.visualization.warning_runtime import ensure_timer
    ref = _reference(obj, scene, root)
    session.SYSTEM.listening.schedule(PROVIDER, ref.scope, lambda _token: check(obj, scene, root, ref))
    ensure_timer()


def _capture(obj, scene, root):
    from .draft_skin.warm import _mesh_arrays
    from .draft_skin.capture import capture_skin
    import bpy
    points, faces = _mesh_arrays(obj)
    source = capture_skin(root, scene, bpy.context.evaluated_depsgraph_get()) if obj.get('af_draft_skin') else None
    return points, faces, source


def check(obj, scene, root, ref):
    ticket = session.SYSTEM.reporting.begin_check(ref.scope, PROVIDER)
    cancelled = Event(); pool = ThreadPoolExecutor(max_workers=1)
    try:
        inputs = _capture(obj, scene, root)
        future = pool.submit(_measure, inputs, cancelled)
        while not future.done():
            from ..core.issues.coordinator import WakeAfter
            yield WakeAfter(.1)
        if session.SYSTEM.reporting.current(ticket):
            _publish(obj, ref, ticket, future.result())
    except Exception as error:
        session.SYSTEM.reporting.fail_check(ticket, error)
    finally:
        cancelled.set(); pool.shutdown(wait=False)


def _measure(inputs, cancelled):
    from ..core.draft_skin.gap_quality import validate
    from ..core.draft_skin.gap_warm import revalidate
    from ..core.mesh_diagnostics import intersections
    points, faces, capture = inputs
    report, stats = (validate(points, faces) if capture is None else
                     revalidate(capture, points, faces, cancelled=cancelled.is_set))
    stats.update(intersections(points, faces, cancelled.is_set))
    return report, stats


def _publish(obj, ref, ticket, measured):
    from ..core.mesh_issues import quality_findings
    report, stats = measured; payload = _payload(obj)
    rows = quality_findings(report, stats, 'recheck')
    previous = [r for r in payload["issues"] if r["code"] in {"TOPOLOGY_STALE", "QUALITY_BOUNDARY_MATCH", "QUALITY_GUIDE_PRESERVED", "QUALITY_FIDELITY_OK", "QUALITY_VALENCE_OK"}]
    rows.extend(previous)
    payload.update(issues=rows, recheck=stats, recheck_quality=asdict(report))
    obj['af_issues_json'] = json.dumps(payload)
    session.SYSTEM.reporting.complete_check(ticket, tuple(_issue(ref, row, payload) for row in rows), payload)
