"""Cross-SCP Fiber-anchor attachment capture."""

from dataclasses import dataclass, replace

from ..vcp.attachment_backend import (attachment_runtime, capture_attachment_from_object,
                                      capture_attachment_from_object_ray, resolve_surface_frame)
from . import fiber_view_capture


@dataclass(frozen=True)
class FiberAttachmentTarget:
    owner_id: str
    raw: str
    score: float


def capture_attachment_target(sync, root, scene, owner_id, moved_world, depsgraph=None):
    runtime = attachment_runtime(scene, depsgraph)
    ray = sync._view_ray_for_world_point(moved_world)
    rows = _surface_rows(sync, root, scene)
    candidates = _capture_candidates(rows, moved_world, ray, runtime, scene)
    return _preferred_target(candidates, str(owner_id or ""))


def with_attachment_raw(target, raw):
    return None if target is None else replace(target, raw=str(raw or ""))


def _surface_rows(sync, root, scene):
    rows = []
    for scp in root.af_scp_system.scps:
        owner = str(getattr(scp, "id", "") or "")
        obj = None if not owner else sync._get_scp_proxy(scene, root.name, owner)
        if obj is not None: rows.append((owner, obj))
    return tuple(rows)


def _capture_candidates(rows, moved, ray, runtime, scene):
    if ray is fiber_view_capture.NO_VIEW_RAY:
        return tuple(filter(None, (_nearest_target(row, moved, runtime, scene) for row in rows)))
    if ray is None: return ()
    return tuple(filter(None, (_ray_target(row, ray, runtime, scene) for row in rows)))


def _nearest_target(row, moved, runtime, scene):
    owner, obj = row
    raw = capture_attachment_from_object(obj, moved, runtime)
    point = _captured_point(obj, raw, runtime, scene)
    return None if point is None else FiberAttachmentTarget(owner, raw, float((point - moved).length))


def _ray_target(row, ray, runtime, scene):
    owner, obj = row; origin, direction = ray
    raw = capture_attachment_from_object_ray(obj, origin, direction, runtime)
    point = _captured_point(obj, raw, runtime, scene)
    depth = None if point is None else float((point - origin).dot(direction))
    return None if depth is None or depth < 0.0 else FiberAttachmentTarget(owner, raw, depth)


def _captured_point(obj, raw, runtime, scene):
    if raw is None: return None
    frame = resolve_surface_frame(obj, raw, runtime, scene)
    return None if frame is None else frame["point_world"]


def _preferred_target(candidates, owner_id):
    if not candidates: return None
    best = min(candidates, key=lambda row: (row.score, row.owner_id))
    current = next((row for row in candidates if row.owner_id == owner_id), None)
    return current if current is not None and _scores_tied(current.score, best.score) else best


def _scores_tied(first, second):
    scale = max(1.0, abs(float(first)), abs(float(second)))
    return float(first) <= float(second) + 1.0e-6 * scale
