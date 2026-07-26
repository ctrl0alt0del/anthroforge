from dataclasses import replace

import numpy as np

try:
    from ...core.draft_skin.constants import AUTO_ZERO_TERMS, COLLAGEN_GROUP, TARGET_RESOLUTION
    from ...core.draft_skin.model import SkinCapture, SkinSource
    from ...core.draft_skin.protocol import capture_hash
except ImportError:
    from core.draft_skin.constants import AUTO_ZERO_TERMS, COLLAGEN_GROUP, TARGET_RESOLUTION
    from core.draft_skin.model import SkinCapture, SkinSource
    from core.draft_skin.protocol import capture_hash


def capture_skin(root, scene, depsgraph):
    warnings, weight_cache = [], {}
    objects = sorted(_candidate_objects(root, scene), key=_sort_key)
    sources = _capture_sources(objects, root, depsgraph, weight_cache, warnings)
    return _make_capture(root, sources, warnings)


def _capture_sources(objects, root, depsgraph, cache, warnings):
    regular = [_capture_object(obj, root, depsgraph, cache, warnings) for obj in objects if _role(obj) != "FIBER"]
    regular = [item for item in regular if item is not None]
    valid = {item.entity_id for item in regular if item.entity_type == "MUSCLE"}
    fibers = _capture_fibers(objects, root, depsgraph, valid, cache, warnings)
    return tuple(replace(item, source_index=i) for i, item in enumerate((*regular, *fibers)))


def _candidate_objects(root, scene):
    root_name = str(root.name)
    return [
        obj for obj in tuple(scene.objects)
        if obj.type in {"MESH", "CURVE"} and obj.get("af_root_name") == root_name
        and not obj.get("af_draft_skin") and _role(obj)
    ]


def _role(obj):
    if obj.get("af_scp_geometry"):
        return "SCP"
    if obj.get("af_muscle_proxy") and str(obj.get("af_muscle_surface") or "") == "INFL":
        return "MUSCLE"
    if obj.get("af_blob_proxy"):
        return "BLOB"
    return "FIBER" if obj.get("af_fiber_proxy") else ""


def _sort_key(obj):
    return (_role(obj), _entity_id(obj, _role(obj)), _mirror_role(obj), obj.name)


def _capture_fibers(objects, root, depsgraph, valid_muscles, cache, warnings):
    fibers = _fiber_properties(root)
    selected = [
        obj for obj in objects if _role(obj) == "FIBER"
        and _include_fiber(obj, fibers, valid_muscles)
    ]
    records = [_capture_object(obj, root, depsgraph, cache, warnings) for obj in selected]
    return [item for item in records if item is not None]


def _fiber_properties(root):
    return {str(item.id): item for item in root.af_vcp_system.fibers}


def _include_fiber(obj, fibers, valid_muscles):
    fiber = fibers.get(_entity_id(obj, "FIBER"))
    muscle_id = "" if fiber is None else str(getattr(fiber, "muscle_id", "") or "")
    return not muscle_id or muscle_id not in valid_muscles


def _capture_object(obj, root, depsgraph, cache, warnings):
    arrays = _evaluated_arrays(obj, depsgraph)
    if arrays is None:
        return None
    vertices, faces = arrays
    role = _role(obj)
    collagen = _collagen_values(obj, root, depsgraph, len(vertices), cache, warnings) if role == "SCP" else None
    return SkinSource(0, role, _entity_id(obj, role), _mirror_role(obj), obj.name, vertices, faces, collagen)


def _evaluated_arrays(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        arrays = None if mesh is None else _mesh_arrays(evaluated, mesh)
    finally:
        evaluated.to_mesh_clear()
    return arrays if arrays is not None else _original_arrays(obj, depsgraph)


def _original_arrays(obj, depsgraph):
    mesh = obj.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        return None if mesh is None else _mesh_arrays(obj, mesh)
    finally:
        obj.to_mesh_clear()


def _mesh_arrays(evaluated, mesh):
    mesh.calc_loop_triangles()
    if not len(mesh.vertices) or not len(mesh.loop_triangles):
        return None
    coordinates = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.vertices.foreach_get("co", coordinates)
    mesh.loop_triangles.foreach_get("vertices", triangles)
    world = _world_vertices(coordinates.reshape(-1, 3), evaluated.matrix_world)
    return world, triangles.reshape(-1, 3)


def _world_vertices(vertices, matrix):
    transform = np.asarray(matrix, dtype=np.float64)
    homogeneous = np.column_stack((vertices, np.ones(len(vertices), dtype=np.float64)))
    return (homogeneous @ transform.T)[:, :3]


def _entity_id(obj, role):
    fields = {
        "SCP": ("af_source_scp_id", "af_scp_id"),
        "MUSCLE": ("af_source_muscle_id", "af_muscle_id"),
        "BLOB": ("af_source_blob_id", "af_blob_id"),
        "FIBER": ("af_source_fiber_id", "af_fiber_id"),
    }
    return next((str(obj.get(key)) for key in fields[role] if obj.get(key)), "")


def _mirror_role(obj):
    flags = ("af_scp_mirror", "af_muscle_mirror_proxy", "af_blob_mirror_proxy", "af_fiber_mirror_proxy")
    return "MIRROR" if any(obj.get(key) for key in flags) else "ORIGINAL"


def _collagen_values(obj, root, depsgraph, count, cache, warnings):
    scp = _scp_by_id(root).get(_entity_id(obj, "SCP"))
    if scp is None:
        warnings.append(f"Missing SCP settings for {obj.name}; collagen defaulted to 1.")
        return np.ones(count, dtype=np.float32)
    base = _base_collagen(scp, obj)
    if str(getattr(scp, "skin_collagen_mode", "AUTO")) != "PAINTED":
        return np.full(count, base, dtype=np.float32)
    return _painted_values(scp, depsgraph, count, base, cache, warnings)


def _scp_by_id(root):
    return {str(item.id): item for item in root.af_scp_system.scps}


def _base_collagen(scp, obj):
    mode = str(getattr(scp, "skin_collagen_mode", "AUTO"))
    if mode != "AUTO":
        return float(getattr(scp, "skin_collagen", 1.0))
    text = f"{getattr(scp, 'name', '')} {obj.name}".lower()
    return 0.0 if any(term in text for term in AUTO_ZERO_TERMS) else 1.0


def _painted_values(scp, depsgraph, count, base, cache, warnings):
    source = getattr(scp, "geometry_object_ref", None)
    key = None if source is None else int(source.as_pointer())
    if key not in cache:
        cache[key] = _read_group_values(source, depsgraph, base)
    values = cache.get(key)
    if values is not None and len(values) == count:
        return values.copy()
    warnings.append(f"Painted collagen mismatch for {getattr(scp, 'name', scp.id)}; using {base:.3f}.")
    return np.full(count, base, dtype=np.float32)


def _read_group_values(obj, depsgraph, base):
    group = None if obj is None else obj.vertex_groups.get(COLLAGEN_GROUP)
    if group is None:
        return None
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return _mesh_group_values(mesh, group.index, base)
    finally:
        evaluated.to_mesh_clear()


def _mesh_group_values(mesh, group_index, base):
    values = np.full(len(mesh.vertices), float(base), dtype=np.float32)
    for vertex in mesh.vertices:
        match = next((item for item in vertex.groups if item.group == group_index), None)
        if match is not None:
            values[vertex.index] = float(match.weight)
    return values


def _make_capture(root, sources, warnings):
    if not sources:
        raise ValueError("No finalized SCP or VCP skin contributors were found.")
    vertices = np.concatenate([item.vertices for item in sources])
    lower, upper = vertices.min(axis=0), vertices.max(axis=0)
    voxel = float(np.max(upper - lower) / TARGET_RESOLUTION)
    digest = capture_hash(root.name, sources)
    return SkinCapture(root.name, sources, lower, upper, digest, voxel, TARGET_RESOLUTION, tuple(warnings))
