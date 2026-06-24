from dataclasses import dataclass
import uuid

import bpy

from ..scp_runtime.common import scp_prop_map
from ..scp_runtime.runtime_state import mirror_effective_axis, mirror_source_id
from ..visualization.mirror_objects import remove_obj
from ..visualization.mirror_rules import mirror_matrix
from .signature import mesh_topology_signature, open_evaluated_mesh
from .consts import ATTR_SLOT, ATTR_VERTEX, SIDE_MIRRORED, SIDE_ORIGINAL
from .scope import proxy_scope
from .session import ensure_proxy_collection, tag_proxy_object


@dataclass(frozen=True)
class ProxyBuild:
    ok: bool = False
    message: str = ""
    errors: tuple = ()
    payload: dict = None
    original: object = None
    mirrored: object = None


def build_proxy_view(root, scene, owner_id):
    scope = proxy_scope(root, owner_id)
    if not scope.contributors:
        return ProxyBuild(message="Active SCP subtree has no mesh geometry objects.")
    original = _build_side(root, scene, scope, SIDE_ORIGINAL)
    if original.errors:
        return _build_failure(original.errors)
    mirrored = _build_side(root, scene, scope, SIDE_MIRRORED)
    if mirrored.errors:
        _cleanup_objects(original.obj, mirrored.obj)
        return _build_failure(mirrored.errors)
    payload = _payload(scope, original, mirrored)
    _tag_objects(root, payload, original, mirrored)
    return ProxyBuild(True, "Proxy view ready.", (), payload, original.obj, mirrored.obj)


def _build_failure(errors):
    return ProxyBuild(False, "Could not build proxy view.", tuple(errors))


@dataclass(frozen=True)
class _SideBuild:
    obj: object = None
    errors: tuple = ()
    sources: tuple = ()


def _build_side(root, scene, scope, side):
    parts, errors = _parts_for_side(root, scene, scope, side)
    if errors or not parts:
        return _SideBuild(None, tuple(errors), tuple(_source_rows(parts)))
    obj = _new_proxy_object(scene, scope.owner_id, side)
    _write_proxy_mesh(obj, parts)
    return _SideBuild(obj, (), tuple(_source_rows(parts)))


def _parts_for_side(root, scene, scope, side):
    parts, errors = [], []
    for slot, item in enumerate(_side_items(scope, side)):
        part, error = _part_for_item(root, scene, item, slot, side)
        errors.extend(() if error is None else (error,))
        parts.extend(() if part is None else (part,))
    return parts, errors


def _side_items(scope, side):
    wanted = set(scope.mirror_ids if side == SIDE_MIRRORED else scope.scp_ids)
    return [item for item in scope.contributors if item.scp_id in wanted]


@dataclass(frozen=True)
class _Part:
    slot: int
    scp_id: str
    name: str
    object_name: str
    mesh_name: str
    signature: str
    verts: tuple
    faces: tuple
    source_vertex: tuple


def _part_for_item(root, scene, item, slot, side):
    eval_obj, eval_mesh = open_evaluated_mesh(scene, item.obj)
    try:
        if eval_mesh is None:
            raise RuntimeError("Could not evaluate mesh.")
        return _mesh_part(root, item, slot, side, eval_obj, eval_mesh), None
    except RuntimeError as exc:
        return None, f"{item.name}: {exc}"
    finally:
        None if eval_obj is None else eval_obj.to_mesh_clear()


def _mesh_part(root, item, slot, side, eval_obj, eval_mesh):
    rule = _mirror_rule(root, item.scp_id, side)
    verts = tuple(_world_vert(eval_obj, vert.co, rule) for vert in eval_mesh.vertices)
    faces = tuple(tuple(poly.vertices) for poly in eval_mesh.polygons)
    source = tuple(range(len(eval_mesh.vertices)))
    data = getattr(item.obj, "data", None)
    mesh_name = "" if data is None else data.name
    return _Part(slot, item.scp_id, item.name, item.obj.name, mesh_name, mesh_topology_signature(eval_mesh), verts, faces, source)


def _world_vert(obj, coord, rule):
    world = obj.matrix_world @ coord
    return world if rule is None else rule @ world


def _mirror_rule(root, scp_id, side):
    if side != SIDE_MIRRORED:
        return None
    scp = scp_prop_map(root).get(str(scp_id))
    source = scp_prop_map(root).get(mirror_source_id(scp))
    return None if source is None else mirror_matrix(mirror_effective_axis(scp), tuple(getattr(source, "mirror_origin", (0.0, 0.0, 0.0))))

def _new_proxy_object(scene, owner_id, side):
    mesh = bpy.data.meshes.new(f"AF_PROXY_{owner_id}_{side}_MESH")
    obj = bpy.data.objects.new(f"AF_PROXY_{owner_id}_{side}_{uuid.uuid4().hex[:8]}", mesh)
    ensure_proxy_collection(scene).objects.link(obj)
    obj.hide_render = True
    return obj


def _write_proxy_mesh(obj, parts):
    verts, faces, slots, source = _combined_geometry(parts)
    obj.data.from_pydata(verts, [], faces)
    _write_int_attr(obj.data, ATTR_SLOT, slots)
    _write_int_attr(obj.data, ATTR_VERTEX, source)
    obj.data.update()


def _combined_geometry(parts):
    verts, faces, slots, source, offset = [], [], [], [], 0
    for part in parts:
        verts.extend(part.verts)
        faces.extend(_offset_faces(part.faces, offset))
        slots.extend([part.slot] * len(part.verts))
        source.extend(part.source_vertex)
        offset += len(part.verts)
    return verts, faces, slots, source


def _offset_faces(faces, offset):
    return [tuple(index + offset for index in face) for face in faces]


def _write_int_attr(mesh, name, values):
    attr = mesh.attributes.new(name, "INT", "POINT")
    for index, item in enumerate(attr.data):
        item.value = int(values[index])


def _payload(scope, original, mirrored):
    return {
        "session_id": uuid.uuid4().hex,
        "owner_scp_id": scope.owner_id,
        "scp_ids": list(scope.scp_ids),
        "mirror_target_ids": list(scope.mirror_ids),
        "original": "" if original.obj is None else original.obj.name,
        "mirrored": "" if mirrored.obj is None else mirrored.obj.name,
        "source_snapshots": list(original.sources),
    }


def _tag_objects(root, payload, original, mirrored):
    None if original.obj is None else tag_proxy_object(original.obj, root, payload, SIDE_ORIGINAL, original.sources)
    None if mirrored.obj is None else tag_proxy_object(mirrored.obj, root, payload, SIDE_MIRRORED, mirrored.sources)


def _source_rows(parts):
    return ({"slot": part.slot, "scp_id": part.scp_id, "name": part.name, "object_name": part.object_name, "mesh_name": part.mesh_name, "signature": part.signature} for part in parts)


def _cleanup_objects(*objs):
    for obj in objs:
        if obj is not None:
            remove_obj(obj)
