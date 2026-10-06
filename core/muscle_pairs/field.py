"""Canonical native inflation directions and evaluated, cropped domain export."""
import ctypes as C
from dataclasses import replace
import numpy as np
from . import abi
from .model import snapshot, DomainKey


class FieldInput(C.Structure):
    _fields_ = [(k, abi.DP) for k in ('base', 'outer', 'reference', 'limiting')]
    _fields_ += [(k, abi.IP) for k in ('faces', 'sources', 'reference_faces')]
    _fields_ += [(k, C.c_int) for k in ('vertices', 'triangles', 'reference_vertices', 'reference_count', 'reference_width')]


def limiting(grid, spec, parity=1):
    grid = np.ascontiguousarray(grid, dtype=float)
    control = grid[len(grid)//2, grid.shape[1]//2] if spec.initialize_control else spec.control_world
    control = np.ascontiguousarray(control, dtype=float); output = np.empty_like(grid)
    mode = ('CTRL_POINT', 'DISTRIBUTED', 'SECTION_PROFILE').index(spec.inflation_mode)
    direction = ('LOCAL', 'SMOOTH', 'SECTION').index(spec.section_profile.direction) if mode == 2 else 0
    call = abi.library().af_pair_limiting
    call.argtypes = [abi.DP, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, abi.DP, C.c_double, abi.DP]
    call.restype = C.c_int
    status = call(abi.pointer(grid), *grid.shape[:2], mode, direction, (parity if mode == 2 else 1)*(-1 if spec.flip_normals else 1),
                  abi.pointer(control), spec.inflation_direction_depth, abi.pointer(output))
    if status: raise ValueError('PAIR_LIMITING_DIRECTION_FAILED')
    return output


def ordinary_reference(request, result):
    from ..vcp.muscle_numeric import execute_muscle_batch
    bare = replace(request, output_domain=None, envelope=None, spec=replace(request.spec, inflation_enabled=False, smoothing=None))
    raw = result if result.row_count else execute_muscle_batch((bare,), 'NATIVE').results[0]
    if raw.error: raise ValueError(raw.error)
    grid = raw.base_vertices.reshape(raw.row_count, raw.column_count, 3)
    return raw.base_vertices, raw.faces, limiting(grid, request.spec, request.orientation_parity).reshape(-1, 3)


def branched_reference(request, result):
    from ..vcp.branched_surface import assemble
    a = request.assembly; main = part_limiting(a.main, replace(request.part_specs[0], flip_normals=a.flip))
    children = []
    for branch, spec in zip(a.branches, request.part_specs[1:]):
        flip = a.flip != (branch.connection.boundary == -1)
        child = part_limiting(branch.grid, replace(spec, flip_normals=flip))
        mean = blend(main[branch.connection.boundary, branch.seam], child[:, 0])
        main[branch.connection.boundary, branch.seam] = mean; child[:, 0] = mean
        children.append(child)
    base, faces = assemble(a)
    directions, _ = assemble(a, main, tuple(children))
    return base, faces, directions


def part_limiting(grid, spec):
    return limiting(grid, spec) if spec.inflation_enabled else np.zeros_like(grid)


def blend(first, second):
    first, second = (np.ascontiguousarray(v, dtype=float) for v in (first, second))
    result = np.empty_like(first); call = abi.library().af_pair_blend_directions
    call.argtypes, call.restype = [abi.DP, abi.DP, C.c_int, abi.DP], C.c_int
    if call(abi.pointer(first), abi.pointer(second), len(first), abi.pointer(result)): raise ValueError('PAIR_SEAM_DIRECTION')
    return result


def triangles(faces, parts, sources):
    faces = np.asarray(faces, dtype=np.int64)
    if faces.shape[1] == 3: return faces, parts, sources
    if faces.shape[1] != 4: raise ValueError('PAIR_FACE_WIDTH')
    result = np.stack((faces[:, (0, 1, 2)], faces[:, (0, 2, 3)]), axis=1).reshape(-1, 3)
    return result, np.repeat(parts, 2), np.repeat(sources, 2)


def build_directions(base, outer, faces, sources, reference):
    ref, ref_faces, directions = reference
    arrays = [np.ascontiguousarray(v, dtype=float) for v in (base, outer, ref, directions)]
    indices = [np.ascontiguousarray(v, dtype=np.int64) for v in (faces, sources, ref_faces)]
    packed = FieldInput(*(abi.pointer(v) for v in (*arrays, *indices)), len(base), len(faces), len(ref), len(ref_faces), ref_faces.shape[1])
    output = np.empty_like(arrays[0]); call = abi.library().af_pair_build_field
    call.argtypes, call.restype = [C.POINTER(FieldInput), abi.DP], C.c_int
    if call(C.byref(packed), abi.pointer(output)): raise ValueError('PAIR_LIMITING_FRAME_DEGENERATE')
    return output


def side_inputs(request, result):
    from ..vcp.muscle_envelope import _side_requests
    if request.envelope:
        requests = _side_requests(request)
        return tuple(zip(('A', 'B'), requests, (result.side_a, result.side_b)))
    return (('A', request, result.inflated_vertices),)


def enabled(request):
    specs = request.part_specs if hasattr(request, 'assembly') else (request.spec,)
    return any(s.inflation_enabled for s in specs)


def export(root_id, muscle_id, group, revision, request, result, displacement):
    if result.error: raise ValueError(result.error)
    parts = np.zeros(len(result.faces), dtype=np.int64) if result.face_parts is None else result.face_parts
    sources = np.arange(len(result.faces), dtype=np.int64) if result.source_faces is None else result.source_faces
    faces, parts, sources = triangles(result.faces, parts, sources); values = []
    for side, side_request, outer in side_inputs(request, result):
        if not enabled(side_request) or not len(faces): continue
        reference = (branched_reference if hasattr(request, 'assembly') else ordinary_reference)(side_request, result)
        base, selected, fs, ps, ss = participating(side_request, result.base_vertices, outer, faces, parts, sources)
        if not len(fs): continue
        directions = build_directions(base, selected, fs, ss, reference)
        domain = snapshot(DomainKey(root_id, muscle_id, 'source', side), group, revision,
            base, selected, directions, orient(base, directions, fs), ps, ss, displacement)
        values.append(material_domain(domain, reference, result, side_request, faces, parts))
    return tuple(v for v in values if len(v.faces))


def material_domain(domain, reference, result, request, faces, parts):
    from ..muscle_stacking.material import attach
    specs = request.part_specs if hasattr(request, 'assembly') else (request.spec,)
    keep = np.asarray([s.inflation_enabled for s in specs])[parts]
    selected = np.arange(len(result.base_vertices)) if np.all(keep) else np.unique(faces[keep])
    return attach(domain, reference, result, selected)


def participating(request, base, outer, faces, parts, sources):
    specs = request.part_specs if hasattr(request, 'assembly') else (request.spec,)
    keep = np.asarray([s.inflation_enabled for s in specs])[parts]
    if np.all(keep): return base, outer, faces, parts, sources
    used, indices = np.unique(faces[keep], return_inverse=True)
    return base[used], outer[used], indices.reshape(-1, 3), parts[keep], sources[keep]


def orient(base, directions, faces):
    base, directions, faces = (np.ascontiguousarray(v) for v in (base, directions, faces))
    call = abi.library().af_pair_orientation; call.argtypes = [abi.DP, abi.DP, abi.IP, C.c_int]; call.restype = C.c_int
    sign = call(abi.pointer(base), abi.pointer(directions), abi.pointer(faces), len(faces))
    if not sign: raise ValueError('PAIR_ORIENTATION_FAILED')
    return faces if sign > 0 else faces[:, ::-1]
