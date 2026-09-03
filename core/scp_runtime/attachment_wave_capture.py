"""Main-thread capture for pure-data attachment-wave execution."""

from collections import OrderedDict
from dataclasses import dataclass
from itertools import count

import numpy as np

from ..attachment_codec import fiber_surface_param
from ..deps.runtime_graph import tarjan_scc
from ..utils import deformation_generation, depsgraph_for_scene
from ..vcp.attachment_wave import (ATTACHMENT_WAVE_VERSION, AttachmentPropagationRequest,
                                   AttachmentSurfaceSnapshot, FiberNodeAttachmentOperation,
                                   SCPAttachmentOperation)
from ..vcp.fiber_modes import is_loop_fiber
from ..vcp.fiber_node_attachment_codec import decode_node_attachments
from .attachment_session import follow_rotation_enabled, tangent_strategy
from .common import (as_id, indexed_geometry_mesh_scp_obj, indexed_transform_scp_obj,
                     scp_object_maps)
from .parent_anchor import anchor_mode, stored_parent_binding
from .runtime_state import (attach_child_normal_local, attach_child_origin_local,
                            attach_child_tangent_local, attach_flow_param,
                            attach_initialized, attach_parent_offset_local,
                            attach_parent_tangent_hint_local)
from .surface import build_mesh_collision_data, resolve_tangent_strategy
from .tree import children_map


_TOKENS = count(1)
_ARRAY_CACHE = OrderedDict()
_ARRAY_BYTES = 0
_ARRAY_HITS = 0
_ARRAY_MISSES = 0
_MAX_ENTRIES = 128
_MAX_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class AttachmentCaptureOutcome:
    request: object
    scp_issues: tuple = ()
    fiber_issues: tuple = ()


def clear_attachment_surface_cache():
    global _ARRAY_BYTES, _ARRAY_HITS, _ARRAY_MISSES
    _ARRAY_CACHE.clear(); _ARRAY_BYTES = 0; _ARRAY_HITS = 0; _ARRAY_MISSES = 0


def attachment_surface_cache_stats():
    return {"entries": len(_ARRAY_CACHE), "bytes": _ARRAY_BYTES,
            "hits": _ARRAY_HITS, "misses": _ARRAY_MISSES}


def attachment_request_current(request, root, scene):
    if request.scene_id != _runtime_id(scene) or request.root_id != _runtime_id(root): return False
    objects = scp_object_maps(scene, root.name)
    for sid, generation in request.generations:
        obj = indexed_geometry_mesh_scp_obj(objects, sid)
        if obj is None or _current_generation(obj) != generation[:4]: return False
    return True


def capture_attachment_wave(root, scene, scp_by_id, target_ids, parent_ids, fibers=(),
                            blocked=(), backsolve=None, operation_limit=None, invalid_ids=()):
    builder = _WaveCapture(root, scene, scp_by_id, target_ids, parent_ids, blocked,
                           backsolve, operation_limit, invalid_ids)
    return builder.capture(tuple(fibers or ()))


def plan_attachment_waves(scps, target_ids, parent_ids, blocked=()):
    candidates = _candidate_ids(scps, set(target_ids or ()), set(parent_ids or ()))
    active = {sid for sid in candidates if _applicable_scp(scps, sid, blocked)}
    cyclic = _cyclic_ids(scps, active); invalid = _descendants(scps, cyclic) & active
    issues = tuple((sid, "Cyclic SCP attachment dependency.") for sid in sorted(invalid))
    return _topological_waves(scps, active - invalid), issues


class _WaveCapture:
    def __init__(self, root, scene, scps, targets, parents, blocked, backsolve, limit, invalid):
        self.root, self.scene, self.scps = root, scene, dict(scps)
        self.targets, self.parents = set(targets or ()), set(parents or ())
        self.blocked, self.backsolve = set(blocked or ()), dict(backsolve or {})
        self.limit = None if limit is None else set(limit)
        self.depsgraph = depsgraph_for_scene(scene); self.objects = scp_object_maps(scene, root.name)
        self.ids = tuple(sorted(self.scps)); self.lookup = {sid: i for i, sid in enumerate(self.ids)}
        self.matrices, self.rotations = self._transforms()
        self.surfaces, self.surface_lookup, self.surface_cache = [], {}, {}
        invalid = set(invalid or ())
        self.scp_status = [int(sid in invalid) for sid in self.ids]; self.scp_issues = {}

    def capture(self, fibers):
        waves = self._waves(); operations, operation_waves = self._scp_operations(waves)
        fiber_ids, counts, node_ops, fiber_issues = self._fiber_operations(fibers)
        request = AttachmentPropagationRequest(next(_TOKENS), _runtime_id(self.scene),
            _runtime_id(self.root), self.ids, self.matrices, self.rotations,
            tuple(self.scp_status), tuple(self.surfaces), operations, operation_waves,
            fiber_ids, counts, node_ops, self._generations())
        return AttachmentCaptureOutcome(request, tuple(sorted(self.scp_issues.items())), fiber_issues)

    def _transforms(self):
        matrices, rotations = [], []
        for sid in self.ids:
            obj = self._transform_object(sid)
            matrix = np.eye(4) if obj is None else _matrix4(obj.matrix_world)
            rotation = np.eye(3) if obj is None else _rotation3(obj.matrix_world)
            matrices.append(matrix); rotations.append(rotation)
        return np.ascontiguousarray(matrices).reshape((-1, 16)), np.ascontiguousarray(rotations).reshape((-1, 9))

    def _transform_object(self, sid):
        return indexed_transform_scp_obj(self.objects, sid) or indexed_geometry_mesh_scp_obj(self.objects, sid)

    def _waves(self):
        candidates = _candidate_ids(self.scps, self.targets, self.parents)
        active = {sid for sid in candidates if self._applicable(sid)}
        active = active if self.limit is None else active & self.limit
        cyclic = _cyclic_ids(self.scps, active); invalid = _descendants(self.scps, cyclic) & active
        for sid in invalid: self._fail_scp(sid, "Cyclic SCP attachment dependency.")
        return _topological_waves(self.scps, active - invalid)

    def _applicable(self, sid):
        return _applicable_scp(self.scps, sid, self.blocked)

    def _scp_operations(self, waves):
        values, normalized = [], []
        for depth, wave in enumerate(waves):
            rows = tuple(self._scp_operation(sid, depth) for sid in wave)
            rows = tuple(row for row in rows if row is not None)
            values.extend(rows); normalized.append(tuple(range(len(values) - len(rows), len(values))))
        return tuple(values), tuple(normalized)

    def _scp_operation(self, sid, depth):
        child = self.scps[sid]; parent_id = as_id(getattr(child, "parent_id", ""))
        child_obj, parent_obj = self._transform_object(sid), self._transform_object(parent_id)
        parent_geo = indexed_geometry_mesh_scp_obj(self.objects, parent_id)
        if child_obj is None or parent_obj is None: return self._fail_scp(sid, "Missing SCP attachment object.")
        binding = stored_parent_binding(child); surface = self._binding_surface(parent_id, binding)
        if surface == -2: return self._fail_scp(sid, "Missing SCP attachment surface.")
        return self._make_scp_operation(child, sid, parent_id, surface, binding, parent_geo, depth)

    def _binding_surface(self, parent_id, binding):
        return self._surface(parent_id) if str(binding.get("mode")) == "SURFACE_NEAREST" else -1

    def _make_scp_operation(self, child, sid, parent_id, surface, binding, parent_geo, depth):
        param = dict(binding.get("param", {}) or {}); flow = attach_flow_param(child) or {}
        child_obj = self._transform_object(sid); back = self._backsolve_values(sid, child_obj)
        strategy = resolve_tangent_strategy(parent_geo, tangent_strategy(child))
        return SCPAttachmentOperation(sid, parent_id, self.lookup[sid], self.lookup[parent_id], surface,
            depth, _tri(param), _weights(param), _tri(flow), _weights(flow), int(strategy == "DEFORMATION_FLOW"),
            follow_rotation_enabled(child), _vec(attach_parent_tangent_hint_local(child)),
            _vec(attach_parent_offset_local(child)), _vec(attach_child_origin_local(child)),
            _vec(attach_child_tangent_local(child)), _vec(attach_child_normal_local(child)),
            _vec(child_obj.matrix_world.to_scale()), *back)

    def _backsolve_values(self, sid, child_obj):
        if as_id(self.backsolve.get("owner_id")) != sid: return False, -1, (0.0,) * 3, (0.0,) * 3
        parent_id = as_id(self.backsolve.get("parent_id")); parent_index = self.lookup.get(parent_id, -1)
        anchor = _backsolve_anchor(self.root, self.scene, self.backsolve)
        if anchor is None or parent_index < 0: return False, -1, (0.0,) * 3, (0.0,) * 3
        local = child_obj.matrix_world.inverted_safe() @ anchor
        return True, parent_index, _vec(self.backsolve.get("parent_local")), _vec(local)

    def _surface(self, sid):
        if sid in self.surface_lookup: return self.surface_lookup[sid]
        index = len(self.surfaces); snapshot = self._surface_snapshot(sid)
        if snapshot is None: return -2
        self.surface_lookup[sid] = index; self.surfaces.append(snapshot)
        return index

    def _surface_snapshot(self, sid):
        obj = indexed_geometry_mesh_scp_obj(self.objects, sid); owner = self._transform_object(sid)
        if obj is None or owner is None or self.depsgraph is None: return None
        payload = build_mesh_collision_data(obj, self.depsgraph, self.surface_cache)
        if not payload: return None
        vertices, triangles = _cached_arrays(self.scene, self.root, sid, payload)
        evaluated = obj.evaluated_get(self.depsgraph); relative = owner.matrix_world.inverted_safe() @ evaluated.matrix_world
        rotation = owner.matrix_world.to_quaternion().inverted() @ evaluated.matrix_world.to_quaternion()
        generation = _surface_generation(obj, payload)
        return AttachmentSurfaceSnapshot(sid, self.lookup[sid], vertices, triangles,
            _matrix4(relative), _matrix3(rotation.to_matrix()), generation)

    def _fiber_operations(self, fibers):
        ids, counts, operations, issues = [], [], [], []
        for fiber in sorted(fibers, key=lambda row: str(row.id)):
            payload, error = _fiber_payload(fiber)
            if error: issues.append((str(fiber.id), error)); continue
            ids.append(str(fiber.id)); counts.append(len(payload.nodes))
            operations.extend(self._fiber_nodes(str(fiber.id), payload.nodes))
        return tuple(ids), tuple(counts), tuple(operations), tuple(issues)

    def _fiber_nodes(self, fiber_id, nodes):
        values = []
        for index, node in enumerate(nodes):
            param = fiber_surface_param(node.attach_raw) or {}
            owner = self.lookup.get(node.target_id, -1); surface = self._surface(node.target_id)
            values.append(FiberNodeAttachmentOperation(fiber_id, index, owner, surface,
                                                       _tri(param), _weights(param), _vec(node.offset_local)))
        return tuple(values)

    def _fail_scp(self, sid, reason):
        index = self.lookup.get(sid)
        if index is not None: self.scp_status[index] = 1
        self.scp_issues[sid] = str(reason); return None

    def _generations(self):
        return tuple((row.target_id, row.generation) for row in self.surfaces)


def _runtime_id(value):
    try: return int(getattr(value, "session_uid", 0) or value.as_pointer())
    except Exception: return id(value)


def _matrix4(value):
    return np.asarray([[float(cell) for cell in row] for row in value], dtype=np.float64)


def _matrix3(value):
    return np.asarray([[float(cell) for cell in row] for row in value], dtype=np.float64)


def _rotation3(matrix):
    return _matrix3(matrix.to_quaternion().to_matrix())


def _vec(value):
    try: return tuple(float(value[index]) for index in range(3))
    except Exception: return (0.0, 0.0, 0.0)


def _tri(param):
    values = tuple(dict(param or {}).get("tri_vidx", (-1, -1, -1)))
    return tuple(int(values[index]) if index < len(values) else -1 for index in range(3))


def _weights(param):
    values = tuple(dict(param or {}).get("tri_weights", (1.0, 0.0, 0.0)))
    return tuple(float(values[index]) if index < len(values) else 0.0 for index in range(3))


def _candidate_ids(scps, targets, parents):
    kids = children_map(scps); values, visited = set(), set()
    parent_children = {child for sid in set(parents) for child in kids.get(sid, ())}
    stack = list((set(targets) | parent_children) & set(scps))
    while stack:
        sid = stack.pop()
        if sid in visited: continue
        visited.add(sid); values.add(sid); stack.extend(kids.get(sid, ()))
    return values


def _applicable_scp(scps, sid, blocked=()):
    child = dict(scps).get(sid); parent = as_id(getattr(child, "parent_id", ""))
    return bool(child and parent and sid not in set(blocked or ()) and attach_initialized(child))


def _cyclic_ids(scps, active):
    graph = {sid: set() for sid in active}
    for sid in active:
        parent = as_id(getattr(scps[sid], "parent_id", ""))
        if parent in active: graph[parent].add(sid)
    components = tarjan_scc(graph)
    cyclic = {sid for group in components if len(group) > 1 for sid in group}
    cyclic |= {sid for sid in active if as_id(getattr(scps[sid], "parent_id", "")) == sid}
    return cyclic


def _descendants(scps, seeds):
    kids, values, stack = children_map(scps), set(seeds), list(seeds)
    while stack:
        current = stack.pop()
        for child in kids.get(current, ()):
            if child not in values: values.add(child); stack.append(child)
    return values


def _topological_waves(scps, active):
    remaining, waves = set(active), []
    while remaining:
        ready = tuple(sorted(sid for sid in remaining if as_id(getattr(scps[sid], "parent_id", "")) not in remaining))
        if not ready: break
        waves.append(ready); remaining -= set(ready)
    return tuple(waves)


def _fiber_payload(fiber):
    payload = decode_node_attachments(getattr(fiber, "node_attachments_json", ""))
    if payload is None: return None, "Fiber node attachments are missing or invalid."
    if payload.point_count != int(fiber.node_count): return None, "Fiber node count changed."
    if payload.cyclic != is_loop_fiber(fiber): return None, "Fiber topology changed."
    return payload, ""


def _backsolve_anchor(root, scene, snapshot):
    try:
        from ..shortcuts.owner_backsolve import _backsolve_state
        state = _backsolve_state(root, scene, snapshot)
        return None if state is None else state[2]
    except Exception:
        return None


def _surface_generation(obj, payload):
    data = getattr(obj, "data", None)
    return (_runtime_id(obj), _runtime_id(data), deformation_generation(obj),
            deformation_generation(data), id(payload), len(payload["verts_local"]), len(payload["triangles"]))


def _current_generation(obj):
    data = getattr(obj, "data", None)
    return (_runtime_id(obj), _runtime_id(data), deformation_generation(obj), deformation_generation(data))


def _cached_arrays(scene, root, sid, payload):
    global _ARRAY_HITS, _ARRAY_MISSES
    key = (_runtime_id(scene), _runtime_id(root), str(sid), id(payload), ATTACHMENT_WAVE_VERSION)
    value = _ARRAY_CACHE.get(key)
    if value is not None:
        _ARRAY_HITS += 1; _ARRAY_CACHE.move_to_end(key); return value
    _ARRAY_MISSES += 1
    vertices = np.ascontiguousarray(payload["verts_local"], dtype=np.float64)
    triangles = np.ascontiguousarray(payload["triangles"], dtype=np.int64)
    vertices.flags.writeable = False; triangles.flags.writeable = False
    _cache_arrays(key, (vertices, triangles)); return vertices, triangles


def _cache_arrays(key, value):
    global _ARRAY_BYTES
    size = sum(array.nbytes for array in value); _ARRAY_CACHE[key] = value; _ARRAY_BYTES += size
    while len(_ARRAY_CACHE) > _MAX_ENTRIES or _ARRAY_BYTES > _MAX_BYTES:
        _old, arrays = _ARRAY_CACHE.popitem(last=False)
        _ARRAY_BYTES -= sum(array.nbytes for array in arrays)
