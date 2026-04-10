from dataclasses import dataclass
from mathutils import Matrix, Vector

from ..attachment_codec import (
    encode_scp_mesh_anchor,
    encode_surface_frame,
)
from ..visualization.scp_sync_helpers import frame_basis3
from ..effects import (
    ASPECT_POSITION,
    ASPECT_ROTATION,
    default_behavior_for_mode,
    normalize_behavior,
)


@dataclass
class RelationDescriptor:
    mode: str
    payload: object
    behavior: dict


@dataclass
class TransformIntent:
    matrix_world: Matrix
    aspects: tuple


class BehaviorStrategy:
    behavior_id = ""

    def compose_world_matrix(self, child_scp, parent_scp, parent_world, desc: RelationDescriptor):
        raise NotImplementedError

    def update_attachment_from_world(
        self,
        *,
        child_scp,
        parent_scp,
        parent_world,
        current_payload,
        behavior,
        target_matrix_world,
        nearest_parent_param_fn,
    ):
        raise NotImplementedError


class SurfaceFollowStrategy(BehaviorStrategy):
    behavior_id = "surface_follow"

    def compose_world_matrix(self, child_scp, parent_scp, parent_world, desc: RelationDescriptor):
        payload = dict(desc.payload or {})
        behavior = normalize_behavior(desc.mode, desc.behavior)
        aspects = tuple(behavior.get("aspects", []))
        follow_rot = ASPECT_ROTATION in aspects

        parent_param = payload.get("parent_param", 0.0)
        child_origin_local = payload.get("child_origin_local", Vector((0.0, 0.0, 0.0)))
        child_tangent_local = payload.get("child_tangent_local", Vector((1.0, 0.0, 0.0)))
        child_normal_local = payload.get("child_normal_local", Vector((0.0, 0.0, 1.0)))

        p_origin_local, p_tangent_local, p_normal_local = parent_scp.shape.sample_attachment_frame_local(parent_param)
        parent_world3 = parent_world.to_3x3()
        p_origin_world = parent_world @ p_origin_local
        p_tangent_world = parent_world3 @ p_tangent_local
        p_normal_world = parent_world3 @ p_normal_local

        if follow_rot:
            parent_basis = frame_basis3(p_tangent_world, p_normal_world)
            child_basis_local = frame_basis3(child_tangent_local, child_normal_local)
            attach_rot = parent_basis @ child_basis_local.inverted()
            final_rot = attach_rot @ child_scp.local_rotation
        else:
            final_rot = child_scp.local_rotation.copy()

        sx = max(1e-9, float(child_scp.local_scale.x))
        sy = max(1e-9, float(child_scp.local_scale.y))
        sz = max(1e-9, float(child_scp.local_scale.z))
        child_off_world = final_rot @ (Matrix.Diagonal((sx, sy, sz)) @ child_origin_local)
        obj_origin = p_origin_world - child_off_world

        out = final_rot.to_4x4()
        out.translation = obj_origin
        return TransformIntent(matrix_world=out, aspects=aspects)

    def update_attachment_from_world(
        self,
        *,
        child_scp,
        parent_scp,
        parent_world,
        current_payload,
        behavior,
        target_matrix_world,
        nearest_parent_param_fn,
    ):
        behavior_n = normalize_behavior("surface_frame_v1", behavior)
        aspects = tuple(behavior_n.get("aspects", []))
        follow_rot = ASPECT_ROTATION in aspects

        payload = dict(current_payload or {})
        obj_origin = target_matrix_world.to_translation()
        parent_param = nearest_parent_param_fn(parent_scp, parent_world, obj_origin)

        p_origin_local, p_tangent_local, p_normal_local = parent_scp.shape.sample_attachment_frame_local(parent_param)
        pw3 = parent_world.to_3x3()
        p_origin_world = parent_world @ p_origin_local
        p_tangent_world = pw3 @ p_tangent_local
        p_normal_world = pw3 @ p_normal_local

        child_tangent_local = payload.get("child_tangent_local", Vector((1.0, 0.0, 0.0)))
        child_normal_local = payload.get("child_normal_local", Vector((0.0, 0.0, 1.0)))

        if follow_rot:
            parent_basis = frame_basis3(p_tangent_world, p_normal_world)
            final_rot = target_matrix_world.to_3x3()
            child_basis_local = child_scp.local_rotation @ final_rot.inverted() @ parent_basis
            child_tangent_local = child_basis_local @ Vector((1.0, 0.0, 0.0))
            child_normal_local = child_basis_local @ Vector((0.0, 0.0, 1.0))
        else:
            final_rot = child_scp.local_rotation.copy()

        off_world = p_origin_world - obj_origin
        off_local_scaled = final_rot.inverted() @ off_world
        sx = max(1e-9, float(child_scp.local_scale.x))
        sy = max(1e-9, float(child_scp.local_scale.y))
        sz = max(1e-9, float(child_scp.local_scale.z))
        child_origin_local = Vector((off_local_scaled.x / sx, off_local_scaled.y / sy, off_local_scaled.z / sz))

        return encode_surface_frame(
            parent_param=parent_param,
            child_origin_local=child_origin_local,
            child_tangent_local=child_tangent_local,
            child_normal_local=child_normal_local,
            behavior=behavior_n,
        )


class MeshAnchorStrategy(BehaviorStrategy):
    behavior_id = "mesh_anchor"

    def compose_world_matrix(self, child_scp, parent_scp, parent_world, desc: RelationDescriptor):
        _parent_scp = parent_scp
        behavior = normalize_behavior(desc.mode, desc.behavior)
        aspects = tuple(behavior.get("aspects", []))
        parent_local_point, child_local_point = desc.payload
        anchor_world = parent_world @ parent_local_point
        rs = child_scp.local_rotation.to_4x4() @ Matrix.Diagonal((*child_scp.local_scale, 1.0))
        child_off = rs @ Vector((child_local_point.x, child_local_point.y, child_local_point.z, 1.0))
        obj_origin = anchor_world - Vector((child_off.x, child_off.y, child_off.z))
        out = Matrix.Translation(obj_origin) @ rs
        return TransformIntent(matrix_world=out, aspects=aspects)

    def update_attachment_from_world(
        self,
        *,
        child_scp,
        parent_scp,
        parent_world,
        current_payload,
        behavior,
        target_matrix_world,
        nearest_parent_param_fn,
    ):
        _current_payload = current_payload
        behavior_n = normalize_behavior("mesh_anchor", behavior)
        obj_origin = target_matrix_world.to_translation()
        parent_param = nearest_parent_param_fn(parent_scp, parent_world, obj_origin)
        parent_local_point = parent_scp.shape.compute_local_point(parent_param)
        rs = child_scp.local_rotation.to_4x4() @ Matrix.Diagonal((*child_scp.local_scale, 1.0))
        anchor_world = parent_world @ parent_local_point
        off4 = rs.inverted_safe() @ Vector(
            (
                anchor_world.x - obj_origin.x,
                anchor_world.y - obj_origin.y,
                anchor_world.z - obj_origin.z,
                1.0,
            )
        )
        child_local_point = Vector((off4.x, off4.y, off4.z))
        return encode_scp_mesh_anchor(parent_local_point, child_local_point, behavior=behavior_n)


class BehaviorStrategyRegistry:
    def __init__(self):
        self._by_id = {}

    def register(self, strategy):
        if strategy is None:
            return
        sid = str(getattr(strategy, "behavior_id", "") or "")
        if not sid:
            return
        self._by_id[sid] = strategy

    def resolve(self, mode, behavior):
        behavior_n = normalize_behavior(mode, behavior)
        sid = str(behavior_n.get("id", "") or "")
        if sid in self._by_id:
            return self._by_id[sid], behavior_n
        default_id = str(default_behavior_for_mode(mode).get("id", "") or "")
        if default_id in self._by_id:
            return self._by_id[default_id], behavior_n
        raise KeyError(f"No behavior strategy registered for mode={mode} behavior_id={sid}")


_REGISTRY = BehaviorStrategyRegistry()
_REGISTRY.register(SurfaceFollowStrategy())
_REGISTRY.register(MeshAnchorStrategy())


def compose_attachment_world_matrix(child_scp, parent_scp, parent_world, mode, payload, behavior):
    strategy, behavior_n = _REGISTRY.resolve(mode, behavior)
    desc = RelationDescriptor(mode=mode, payload=payload, behavior=behavior_n)
    intent = strategy.compose_world_matrix(child_scp, parent_scp, parent_world, desc)
    return intent.matrix_world


def update_attachment_from_world(
    *,
    child_scp,
    parent_scp,
    parent_world,
    mode,
    current_payload,
    behavior,
    target_matrix_world,
    nearest_parent_param_fn,
):
    strategy, behavior_n = _REGISTRY.resolve(mode, behavior)
    return strategy.update_attachment_from_world(
        child_scp=child_scp,
        parent_scp=parent_scp,
        parent_world=parent_world,
        current_payload=current_payload,
        behavior=behavior_n,
        target_matrix_world=target_matrix_world,
        nearest_parent_param_fn=nearest_parent_param_fn,
    )
