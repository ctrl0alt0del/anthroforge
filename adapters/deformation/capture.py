"""Main-thread capture of contributor identities and persistent material addresses."""
import numpy as np
from types import SimpleNamespace
from .muscles import material_chart, consumed_fibers
from ...core.warm_start.signatures import structural_signature


def capture_anatomy(root, scene, depsgraph, progress=None):
    sources = source_geometry(root, scene, depsgraph)
    consumed = consumed_fibers(root); records, arrays, faces = [], {}, {}
    for source in sources:
        if source.entity_type == "FIBER" and source.entity_id in consumed: continue
        if progress: progress(source.entity_id, source.mirror_role)
        record, points, triangles = contributor(root, scene, source)
        records.append(record); arrays[record["key"]] = points; faces[record["key"]] = triangles
    records.sort(key=lambda row: row["key"])
    if len({r["key"] for r in records}) != len(records):
        raise ValueError("Duplicate deformation contributor identity.")
    return records, arrays, faces


def source_geometry(root, scene, depsgraph):
    from ..draft_skin.capture import _candidate_objects, _sort_key, _role, _entity_id, _mirror_role, _evaluated_arrays
    consumed = consumed_fibers(root)
    for obj in sorted(_candidate_objects(root,scene), key=_sort_key):
        role = _role(obj); entity_id = _entity_id(obj,role)
        if role == "FIBER" and entity_id in consumed: continue
        arrays = (None,None) if role == "MUSCLE" else _evaluated_arrays(obj,depsgraph)
        if arrays is None: raise ValueError("Contributor geometry is unavailable: " + obj.name)
        yield SimpleNamespace(entity_type=role,entity_id=entity_id,mirror_role=_mirror_role(obj),
                              vertices=arrays[0],triangles=arrays[1])


def contributor(root, scene, source):
    points, faces = source.vertices, source.triangles
    chart = {}
    if source.entity_type == "MUSCLE":
        muscle = next(m for m in root.af_vcp_system.muscles if m.id == source.entity_id)
        result = material_chart(root, scene, muscle, source.mirror_role)
        points, faces = result.inflated_vertices, result.faces
        chart = dict(rows=int(result.row_count), columns=int(result.column_count), mode=muscle.inflation_mode)
    record = dict(key=f"{source.entity_type}:{source.entity_id}:{source.mirror_role}",
        entity_id=source.entity_id, kind=source.entity_type, mirror=source.mirror_role,
        vertex_count=len(points), connectivity=structural_signature(len(points), faces), chart=chart)
    return record, np.asarray(points, np.float64), np.asarray(faces, np.int32)
