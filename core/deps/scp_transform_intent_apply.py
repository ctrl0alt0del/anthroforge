from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
import bpy

from ..attachment_codec import parse_scp_attach_descriptor
from ..registry import SCPRegistry
from .conflict_resolver import resolve_conflict
from .transform_behaviors import (
    compose_attachment_world_matrix,
    update_attachment_from_world,
)


def _get_scp_prop(root, scp_id):
    for scp in root.af_scp_system.scps:
        if scp.id == scp_id:
            return scp
    return None


def _props_by_id(root):
    return {scp.id: scp for scp in root.af_scp_system.scps}


def _find_proxy_in_scene(scene, root_name, scp_id):
    if scene is None:
        return None
    sid = str(scp_id or "")
    for obj in scene.objects:
        if (
            obj.get("af_proxy")
            and not obj.get("af_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and str(obj.get("af_scp_id") or "") == sid
        ):
            return obj
    return None


def build_scp_transform_apply_context(root, scene=None):
    if root is None:
        return {"runtime_registry": {}, "props": {}, "cache": {}, "scene": scene}
    runtime = SCPRegistry(root)
    runtime.build()
    return {
        "runtime_registry": runtime.registry,
        "props": _props_by_id(root),
        "cache": {},
        "scene": scene,
    }


def _local_matrix_from_prop(scp_prop):
    loc = Vector(scp_prop.local_origin)
    rot = scp_prop.local_rotation
    scale = scp_prop.local_scale
    return Matrix.Translation(loc) @ rot.to_matrix().to_4x4() @ Matrix.Diagonal((float(scale[0]), float(scale[1]), float(scale[2]), 1.0))


def _world_matrix_for_scp(scp_id, runtime_registry, props_by_id, cache, *, root=None, scene=None):
    if scp_id in cache:
        return cache[scp_id]

    scp = runtime_registry.get(scp_id)
    scp_prop = props_by_id.get(scp_id)
    if scp is None or scp_prop is None:
        out = Matrix.Identity(4)
        cache[scp_id] = out
        return out

    if not scp_prop.parent_id:
        out = _local_matrix_from_prop(scp_prop)
        cache[scp_id] = out
        return out

    parent = runtime_registry.get(scp_prop.parent_id)
    if parent is None:
        out = _local_matrix_from_prop(scp_prop)
        cache[scp_id] = out
        return out

    parent_world = _world_matrix_for_scp(
        scp_prop.parent_id,
        runtime_registry,
        props_by_id,
        cache,
        root=root,
        scene=scene,
    )
    mode, payload, behavior = parse_scp_attach_descriptor(scp_prop.attach_param)
    parent_proxy = None
    depsgraph = None
    if root is not None and scene is not None:
        parent_proxy = _find_proxy_in_scene(scene, str(getattr(root, "name", "") or ""), scp_prop.parent_id)
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
        except Exception:
            depsgraph = None
    out = compose_attachment_world_matrix(
        child_scp=scp,
        parent_scp=parent,
        parent_world=parent_world,
        mode=mode,
        payload=payload,
        behavior=behavior,
        parent_proxy=parent_proxy,
        depsgraph=depsgraph,
    )
    cache[scp_id] = out
    return out


def _nearest_parent_param(parent_scp, parent_world, target_world, parent_proxy=None, depsgraph=None):
    params = parent_scp.shape.get_attach_params() or [0.0]
    best_param = params[0]
    best_d2 = None
    bvh = None
    if (
        parent_proxy is not None
        and depsgraph is not None
        and str(getattr(parent_proxy, "type", "") or "") == "MESH"
    ):
        try:
            bvh = BVHTree.FromObject(parent_proxy, depsgraph)
        except Exception:
            bvh = None

    for p in params:
        lp = parent_scp.shape.compute_local_point(p)
        wp = parent_world @ lp
        if bvh is not None:
            try:
                q_local = parent_proxy.matrix_world.inverted() @ wp
                nearest = bvh.find_nearest(q_local)
            except Exception:
                nearest = None
            if nearest is not None and nearest[0] is not None:
                wp = parent_proxy.matrix_world @ nearest[0]
        d2 = (wp - target_world).length_squared
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_param = p
    return best_param


def _set_root_from_world(scp_prop, matrix_world, *, source="unknown", payload=None):
    loc, rot, scale = matrix_world.decompose()
    changed = False
    sid = str(getattr(scp_prop, "id", "") or "")

    cur_origin = tuple(scp_prop.local_origin)
    in_origin = (loc.x, loc.y, loc.z)
    new_origin = resolve_conflict(
        entity_type="SCP",
        entity_id=sid,
        aspect="transform.local_origin",
        source=source,
        current=cur_origin,
        incoming=in_origin,
        payload=payload,
    )
    try:
        new_origin = (float(new_origin[0]), float(new_origin[1]), float(new_origin[2]))
    except Exception:
        new_origin = in_origin
    if tuple(scp_prop.local_origin) != tuple(new_origin):
        scp_prop.local_origin = tuple(new_origin)
        changed = True

    cur_rot = tuple(scp_prop.local_rotation)
    in_rot = (rot.w, rot.x, rot.y, rot.z)
    new_rot = resolve_conflict(
        entity_type="SCP",
        entity_id=sid,
        aspect="transform.local_rotation",
        source=source,
        current=cur_rot,
        incoming=in_rot,
        payload=payload,
    )
    try:
        new_rot = (float(new_rot[0]), float(new_rot[1]), float(new_rot[2]), float(new_rot[3]))
    except Exception:
        new_rot = in_rot
    if tuple(scp_prop.local_rotation) != tuple(new_rot):
        scp_prop.local_rotation = tuple(new_rot)
        changed = True

    cur_scale = tuple(scp_prop.local_scale)
    in_scale = (scale.x, scale.y, scale.z)
    new_scale = resolve_conflict(
        entity_type="SCP",
        entity_id=sid,
        aspect="transform.local_scale",
        source=source,
        current=cur_scale,
        incoming=in_scale,
        payload=payload,
    )
    try:
        new_scale = (float(new_scale[0]), float(new_scale[1]), float(new_scale[2]))
    except Exception:
        new_scale = in_scale
    if tuple(scp_prop.local_scale) != tuple(new_scale):
        scp_prop.local_scale = tuple(new_scale)
        changed = True
    return changed


def _set_parented_from_world(
    root,
    scp_prop,
    matrix_world,
    runtime_registry=None,
    props=None,
    cache=None,
    scene=None,
    *,
    source="unknown",
    payload=None,
):
    runtime_registry = runtime_registry if runtime_registry is not None else {}
    props = props if props is not None else _props_by_id(root)
    cache = cache if cache is not None else {}

    if not runtime_registry:
        runtime = SCPRegistry(root)
        runtime.build()
        runtime_registry = runtime.registry

    child = runtime_registry.get(scp_prop.id)
    parent = runtime_registry.get(scp_prop.parent_id)
    if child is None or parent is None:
        return False

    parent_world = _world_matrix_for_scp(
        scp_prop.parent_id,
        runtime_registry,
        props,
        cache,
        root=root,
        scene=scene,
    )
    parent_proxy = _find_proxy_in_scene(scene, str(getattr(root, "name", "") or ""), scp_prop.parent_id)
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get() if scene is not None else None
    except Exception:
        depsgraph = None
    mode, payload, behavior = parse_scp_attach_descriptor(scp_prop.attach_param)

    def _nearest_fn(parent_scp_i, parent_world_i, target_world_i):
        return _nearest_parent_param(
            parent_scp_i,
            parent_world_i,
            target_world_i,
            parent_proxy=parent_proxy,
            depsgraph=depsgraph,
        )

    new_attach = update_attachment_from_world(
        child_scp=child,
        parent_scp=parent,
        parent_world=parent_world,
        mode=mode,
        current_payload=payload,
        behavior=behavior,
        target_matrix_world=matrix_world,
        nearest_parent_param_fn=_nearest_fn,
    )

    changed = False
    sid = str(getattr(scp_prop, "id", "") or "")
    cur_attach = str(scp_prop.attach_param or "")
    next_attach = str(
        resolve_conflict(
            entity_type="SCP",
            entity_id=sid,
            aspect="attachment.param",
            source=source,
            current=cur_attach,
            incoming=str(new_attach or ""),
            payload=payload,
        )
        or ""
    )
    if cur_attach != next_attach:
        scp_prop.attach_param = next_attach
        changed = True

    cur_origin = tuple(scp_prop.local_origin)
    origin_in = (0.0, 0.0, 0.0)
    next_origin = resolve_conflict(
        entity_type="SCP",
        entity_id=sid,
        aspect="transform.local_origin",
        source="deps_attachment_normalize",
        current=cur_origin,
        incoming=origin_in,
        payload=payload,
    )
    try:
        next_origin = (float(next_origin[0]), float(next_origin[1]), float(next_origin[2]))
    except Exception:
        next_origin = origin_in
    if tuple(scp_prop.local_origin) != tuple(next_origin):
        scp_prop.local_origin = tuple(next_origin)
        changed = True
    return changed


def apply_scp_transform_intent(root, scp_id, matrix_world, context=None, *, source="unknown", payload=None):
    if root is None or not scp_id or matrix_world is None:
        return False
    scp_prop = _get_scp_prop(root, scp_id)
    if scp_prop is None:
        return False
    if str(source or "") == "blender_proxy_transform":
        return False
    if not scp_prop.parent_id:
        return _set_root_from_world(scp_prop, matrix_world, source=source, payload=payload)
    ctx = dict(context or {})
    return _set_parented_from_world(
        root,
        scp_prop,
        matrix_world,
        runtime_registry=ctx.get("runtime_registry"),
        props=ctx.get("props"),
        cache=ctx.get("cache"),
        scene=ctx.get("scene"),
        source=source,
        payload=dict(payload or {}),
    )
