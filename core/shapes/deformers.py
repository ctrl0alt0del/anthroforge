from abc import ABC
from dataclasses import dataclass
from mathutils import Vector


class ShapeDeformer(ABC):
    """
    Stable deformer contract for all shape point pipelines.

    Required semantics:
    - forward(p, shape): map base/local point -> deformed/local point
    - inverse(p, shape): approximate inverse for control editing paths
    """
    deformer_id = "base"
    priority = 100

    def forward(self, p, shape):
        return self.forward_point(p, shape)

    def inverse(self, p, shape):
        return self.inverse_point(p, shape)

    def forward_point(self, p, _shape):
        return p

    def inverse_point(self, p, _shape):
        return p

    # Optional request channel used by interactive controls.
    # Deformer may request a shape-state update (for example mirrored pair edit).
    def request_handle_update(self, *, shape, proxy_obj, handle_world_location, vert_index, scp_prop):
        return None


@dataclass(frozen=True)
class DeformerUpdateRequest:
    request_type: str
    payload: dict


class LegacyShapeDeformerAdapter(ShapeDeformer):
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self.deformer_id = str(getattr(wrapped, "deformer_id", wrapped.__class__.__name__.lower()) or "legacy")
        self.priority = int(getattr(wrapped, "priority", 100))

    def forward_point(self, p, shape):
        return self._wrapped.forward(p, shape)

    def inverse_point(self, p, shape):
        return self._wrapped.inverse(p, shape)


def _as_vector3(v):
    if isinstance(v, Vector) and len(v) == 3:
        return v.copy()
    return Vector((float(v[0]), float(v[1]), float(v[2])))


def _validate_deformer_instance(d):
    if not hasattr(d, "forward") or not callable(getattr(d, "forward")):
        raise TypeError(f"invalid deformer {type(d).__name__}: missing callable forward(...)")
    if not hasattr(d, "inverse") or not callable(getattr(d, "inverse")):
        raise TypeError(f"invalid deformer {type(d).__name__}: missing callable inverse(...)")
    try:
        p = Vector((0.0, 0.0, 0.0))
        out_f = d.forward(p.copy(), None)
        out_i = d.inverse(p.copy(), None)
        _as_vector3(out_f)
        _as_vector3(out_i)
    except Exception as exc:
        raise TypeError(f"invalid deformer {type(d).__name__}: forward/inverse contract failed ({exc})")


def normalize_deformer_sequence(deformers):
    normalized = []
    for d in list(deformers or []):
        inst = d
        if not isinstance(inst, ShapeDeformer):
            inst = LegacyShapeDeformerAdapter(inst)
        _validate_deformer_instance(inst)
        normalized.append(inst)
    return tuple(sorted(normalized, key=lambda x: (int(getattr(x, "priority", 100)), str(getattr(x, "deformer_id", "")))))


class MirrorDeformer(ShapeDeformer):
    deformer_id = "mirror"
    # Mirror is orchestrated by mirror sync/controller at object level.
    # Keep this in pipeline for explicit priority ordering.
    priority = 10


class ResolutionDeformer(ShapeDeformer):
    deformer_id = "resolution"
    # Resolution affects mesh tessellation, not single point coordinates.
    priority = 30
