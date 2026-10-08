from ctypes import POINTER, c_double, c_int, c_int64
import numpy as np
from .soft_tissue_native import library, _dp, STATES, REPORT_FIELDS
from ..scp_proxy.signature import open_evaluated_mesh
from ..utils import scene_for_id


def solve_point(tissue, rest, target):
    if target is None or target.type != "MESH":
        return rest.vertices, {"status": "NOT_APPLICABLE", "iterations": 1, "max_displacement": 0.0}
    evaluated, mesh = open_evaluated_mesh(scene_for_id(target), target)
    try:
        mesh.calc_loop_triangles()
        host = np.asarray([tuple(v.co) for v in mesh.vertices], dtype=np.float64)
        triangles = np.asarray([tuple(t.vertices) for t in mesh.loop_triangles], dtype=np.int64)
        matrix = evaluated.matrix_world.copy()
    finally:
        evaluated.to_mesh_clear()
    edges = sorted({tuple(sorted((f[i], f[(i+1) % len(f)]))) for f in rest.faces for i in range(len(f))})
    config = _configuration(tissue, matrix)
    return _call(rest.vertices, edges, host, triangles, config)


def _configuration(tissue, matrix):
    center = tuple(tissue.base_object_ref.matrix_world.translation)
    values = (tissue.iterations, tissue.sagginess*10.0, tissue.sag_limit, tissue.shape_retention,
              *tissue.gravity, *center)
    values += tuple(value for row in matrix for value in row)
    values += tuple(value for row in matrix.inverted() for value in row)
    return np.asarray(values, dtype=np.float64)


def _call(vertices, edges, host, triangles, config):
    points = np.asarray(vertices, dtype=np.float64)
    links = np.asarray(edges, dtype=np.int32)
    output, report = np.empty_like(points), np.zeros(7, dtype=np.float64)
    fn = library().af_soft_tissue_point
    dp = POINTER(c_double)
    fn.argtypes = [dp, c_int, POINTER(c_int), c_int, dp, POINTER(c_int64), c_int, dp, dp, dp]
    fn.restype = c_int
    code = fn(_dp(points), len(points), links.ctypes.data_as(POINTER(c_int)), len(links), _dp(host),
              triangles.ctypes.data_as(POINTER(c_int64)), len(triangles), _dp(config), _dp(output), _dp(report))
    if code or not np.all(np.isfinite(output)):
        raise ValueError("NUMERICAL_FAILURE: point tissue solve")
    values = dict(zip(REPORT_FIELDS, report.tolist()))
    values.update(status=STATES[int(report[0])], iterations=int(report[1]))
    return tuple(map(tuple, output.tolist())), values
