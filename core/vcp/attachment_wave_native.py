"""ctypes bridge for the packaged dependency-wave attachment kernel."""

from ctypes import POINTER, Structure, c_double, c_int, c_int64

import numpy as np

from .attachment_wave import (AttachmentExecutorKind, AttachmentPropagationResult,
                              request_cost)
from .v2.collision_native import (ATTACHMENT_WAVE_CAPABILITY, _double, load_native,
                                  native_worker_threads)


class _Surface(Structure):
    _fields_ = [(name, c_int) for name in ("owner", "vertex_start", "vertex_count")]
    _fields_ += [("relative", c_double * 16), ("rotation", c_double * 9)]


class _ScpOp(Structure):
    _fields_ = [(name, c_int) for name in ("child", "parent", "surface", "depth",
                                             "mode", "follow", "backsolve", "back_parent")]
    _fields_ += [(name, c_int64 * 3) for name in ("tri", "flow_tri")]
    _fields_ += [(name, c_double * 3) for name in ("weights", "flow_weights", "hint",
        "offset", "origin", "child_tangent", "child_normal", "scale",
        "parent_local", "anchor_local")]


class _FiberOp(Structure):
    _fields_ = [(name, c_int) for name in ("fiber", "node", "owner", "surface", "output")]
    _fields_ += [("tri", c_int64 * 3)]
    _fields_ += [(name, c_double * 3) for name in ("weights", "offset")]


class _Stats(Structure):
    _fields_ = [(name, c_int) for name in ("workers", "parallel", "cost", "scp_operations",
                                             "fiber_operations", "waves")]
    _fields_ += [("elapsed_ms", c_double)]


def attachment_wave_status(path=None):
    try:
        library = load_native(path)
        return bool(library.af_fiber_ccd_capabilities() & ATTACHMENT_WAVE_CAPABILITY)
    except (AttributeError, OSError, ValueError):
        return False


def execute_attachment_wave(request, kind=AttachmentExecutorKind.NATIVE_WAVE, path=None):
    library = load_native(path); _configure(library)
    packed = _PackedRequest(request)
    code = _invoke(library, packed, kind == AttachmentExecutorKind.SERIAL_REFERENCE)
    if code: raise RuntimeError(f"native attachment wave failed: {code}")
    return packed.result()


class _PackedRequest:
    def __init__(self, request):
        self.request = request; self.matrices = np.array(request.matrices, dtype=np.float64, copy=True)
        self.rotations = np.array(request.rotations, dtype=np.float64, copy=True)
        self.vertices, self.surfaces = _pack_surfaces(request.surfaces)
        self.scp_ops = _pack_scp_ops(request.scp_operations)
        self.wave_offsets = _wave_offsets(request.waves)
        self.fiber_ops = _pack_fiber_ops(request.fiber_operations, request.fiber_ids)
        self.layout = _contribution_layout(request)
        self.points = np.zeros((len(request.fiber_operations), 3), dtype=np.float64)
        self.scp_status = np.ascontiguousarray(request.initial_scp_status, dtype=np.int32)
        self.node_status = np.zeros(len(request.fiber_operations), dtype=np.int32)
        self.stats = _Stats()

    def result(self):
        status = _fiber_status(self.request, self.node_status, self.layout)
        points = _fiber_points(self.request, _reduce_contributions(self.request, self.points, self.layout))
        telemetry = tuple(_stats_dict(self.stats).items())
        return AttachmentPropagationResult(self.matrices, self.rotations,
            tuple(map(int, self.scp_status)), points, status, telemetry)


def _pack_surfaces(surfaces):
    arrays = tuple(np.asarray(row.vertices, dtype=np.float64).reshape((-1, 3)) for row in surfaces)
    vertices = np.ascontiguousarray(np.concatenate(arrays) if arrays else np.zeros((1, 3)))
    rows = (_Surface * len(surfaces))(); offset = 0
    for index, (source, array) in enumerate(zip(surfaces, arrays)):
        rows[index] = _surface_row(source, offset, len(array)); offset += len(array)
    return vertices, rows


def _surface_row(source, offset, count):
    row = _Surface(int(source.owner_index), int(offset), int(count))
    row.relative[:] = tuple(np.asarray(source.relative_matrix).reshape(-1))
    row.rotation[:] = tuple(np.asarray(source.relative_rotation).reshape(-1))
    return row


def _pack_scp_ops(operations):
    rows = (_ScpOp * len(operations))()
    for index, source in enumerate(operations): rows[index] = _scp_row(source)
    return rows


def _scp_row(source):
    row = _ScpOp(source.child_index, source.parent_index, source.surface_index, source.depth,
                 source.tangent_mode, int(source.follow_rotation), int(source.backsolve),
                 source.back_parent_index)
    _assign_scp_arrays(row, source)
    return row


def _assign_scp_arrays(row, source):
    row.tri[:] = source.triangle; row.flow_tri[:] = source.flow_triangle
    names = ("weights", "flow_weights", "hint", "offset", "origin", "child_tangent",
             "child_normal", "scale", "parent_local", "anchor_local")
    values = (source.weights, source.flow_weights, source.tangent_hint, source.parent_offset,
              source.child_origin, source.child_tangent, source.child_normal, source.child_scale,
              source.back_parent_local, source.back_anchor_local)
    for name, value in zip(names, values): getattr(row, name)[:] = value


def _pack_fiber_ops(operations, fiber_ids):
    lookup = {value: index for index, value in enumerate(fiber_ids)}
    rows = (_FiberOp * len(operations))()
    for output, source in enumerate(operations): rows[output] = _fiber_row(source, lookup, output)
    return rows


def _fiber_row(source, lookup, output):
    row = _FiberOp(lookup[source.fiber_id], source.node_index, source.owner_index,
                   source.surface_index, output)
    row.tri[:] = source.triangle; row.weights[:] = source.weights; row.offset[:] = source.offset
    return row


def _wave_offsets(waves):
    values = [0]
    for wave in waves: values.append(values[-1] + len(wave))
    return np.ascontiguousarray(values, dtype=np.int32)


def _fiber_status(request, node_status, layout):
    failed = np.zeros(len(request.fiber_ids), dtype=np.int32)
    np.maximum.at(failed, layout[2], np.asarray(node_status) != 0)
    return tuple(map(int, failed))


def _contribution_layout(request):
    lookup = {fiber_id: index for index, fiber_id in enumerate(request.fiber_ids)}
    offsets = np.cumsum((0,) + request.fiber_counts); nodes, fibers, weights = [], [], []
    for row in request.fiber_operations:
        index = lookup.get(row.fiber_id, -1)
        if index < 0 or not 0 <= row.node_index < request.fiber_counts[index]: raise ValueError('Invalid attachment node')
        nodes.append(offsets[index] + row.node_index); fibers.append(index); weights.append(row.influence_weight)
    nodes, fibers, weights = np.asarray(nodes, dtype=np.int64), np.asarray(fibers, dtype=np.int64), np.asarray(weights)
    totals = np.bincount(nodes, weights=weights, minlength=int(offsets[-1]))
    if not np.isfinite(weights).all() or np.any(weights <= 0) or not np.allclose(totals, 1, rtol=0, atol=1e-9):
        raise ValueError('Invalid attachment influence weights')
    return nodes, weights, fibers


def _reduce_contributions(request, points, layout):
    result = np.zeros((sum(request.fiber_counts), 3), dtype=np.float64)
    np.add.at(result, layout[0], points * layout[1][:, None])
    return result


def _fiber_points(request, points):
    values, cursor = [], 0
    for count in request.fiber_counts:
        values.append(np.array(points[cursor:cursor + count], copy=True)); cursor += count
    return tuple(values)


def _stats_dict(stats):
    return {name: getattr(stats, name) for name, _kind in stats._fields_}


def _configure(library):
    if getattr(library, "_af_attachment_configured", False): return
    library.af_attachment_wave_execute.argtypes = _argument_types()
    library.af_attachment_wave_execute.restype = c_int
    library._af_attachment_configured = True


def _argument_types():
    double, plain = POINTER(c_double), POINTER(c_int)
    return [double, double, c_int, double, c_int, POINTER(_Surface), c_int,
            POINTER(_ScpOp), c_int, plain, c_int, POINTER(_FiberOp), c_int,
            double, plain, plain, c_int, POINTER(_Stats)]


def _invoke(library, packed, serial):
    args = packed.matrices, packed.rotations, len(packed.request.scp_ids), packed.vertices
    args += len(packed.vertices), packed.surfaces, len(packed.request.surfaces)
    args += packed.scp_ops, len(packed.request.scp_operations), packed.wave_offsets, len(packed.request.waves)
    args += packed.fiber_ops, len(packed.request.fiber_operations), packed.points
    args += packed.scp_status, packed.node_status, int(serial), packed.stats
    return library.af_attachment_wave_execute(*_native_args(args))


def _native_args(args):
    values = list(args)
    for index in (0, 1, 3, 13): values[index] = _double(values[index])
    for index in (9, 14, 15): values[index] = values[index].ctypes.data_as(POINTER(c_int))
    return tuple(values)


def attachment_executor_stats(request, result):
    values = dict(result.telemetry)
    values.update({"requested_workers": native_worker_threads(), "request_cost": request_cost(request)})
    return values
