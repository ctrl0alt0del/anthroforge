"""Read-only, bounded native triangle intersections; contacts are separate evidence."""
import ctypes as ct
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import numpy as np
from .draft_skin.gap_native import library, point_array, face_array
from .draft_skin.resources import worker_memory_limit
from .draft_skin.status import check_cancelled


def _configure(lib):
    if lib.af_mesh_diagnostics_version() != 1:
        raise RuntimeError("Native mesh diagnostic capability v1 is unavailable")
    real = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
    integer = np.ctypeslib.ndpointer(dtype=np.int64, flags="C_CONTIGUOUS")
    lib.af_mesh_diagnostics_create.restype = ct.c_void_p
    lib.af_mesh_diagnostics_destroy.argtypes = [ct.c_void_p]
    lib.af_mesh_diagnostics_cancel.argtypes = [ct.c_void_p]
    lib.af_mesh_diagnostics_run.argtypes = [ct.c_void_p, real, ct.c_int, integer, ct.c_int,
                                           ct.c_int64, integer, ct.c_int, integer]


def intersections(vertices, faces, cancelled=None, budget=None):
    lib = library(); _configure(lib); check_cancelled(cancelled)
    points = point_array(vertices); triangles = face_array(faces, len(points))
    pairs, stats = np.full((256, 2), -1, np.int64), np.zeros(3, np.int64)
    handle = lib.af_mesh_diagnostics_create()
    if not handle:
        raise MemoryError("Cannot allocate mesh diagnostic task")
    try:
        args = (handle, points, len(points), triangles, len(triangles),
                worker_memory_limit() if budget is None else budget, pairs, len(pairs), stats)
        code = _run(lib, handle, args, cancelled)
        return _result(code, stats, pairs)
    finally:
        lib.af_mesh_diagnostics_destroy(handle)


def _run(lib, handle, args, cancelled):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lib.af_mesh_diagnostics_run, *args)
        while True:
            try:
                value = future.result(timeout=.1)
                check_cancelled(cancelled)
                return value
            except TimeoutError:
                if cancelled and cancelled():
                    lib.af_mesh_diagnostics_cancel(handle)


def _result(code, stats, pairs):
    if code:
        raise RuntimeError(f"Intersection diagnostic incomplete (native code {code}); quality unknown")
    return dict(self_intersections=int(stats[0]), contact_pairs=int(stats[1]), tested_pairs=int(stats[2]),
                intersection_witnesses=pairs[:min(int(stats[0]), len(pairs))].tolist(),
                intersection_tessellation="triangles; quads split on diagonal 0-2", intersection_check="COMPLETE")


def check_result(result, cancelled=None):
    check_cancelled(cancelled)
    faces = result.triangles if hasattr(result, "triangles") else result.quads
    triangles = faces if faces.shape[1] == 3 else np.concatenate((faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]))
    try:
        _completed(result.statistics, intersections(result.vertices, triangles, cancelled))
    except (OSError, AttributeError, RuntimeError, MemoryError) as error:
        check_cancelled(cancelled)
        result.statistics.update(intersection_check="FAILED", self_intersections=None)
        result.statistics.setdefault("warnings", []).append(str(error))
    return _quality_result(result)


def _quality_result(result):
    from dataclasses import replace
    report = result.validation
    count = result.statistics.get("self_intersections")
    if count and report is not None:
        message = re.sub(r"\s*Self-intersections: \d+\.", "", report.message)
        fields = dict(valid=False, message=(message + f" Self-intersections: {count}.").strip())
        if hasattr(report, "self_intersections"):
            fields["self_intersections"] = count
        return replace(result, validation=replace(report, **fields))
    return result


def _completed(stats, values):
    stats.update(values)
    stats["warnings"] = [text for text in stats.get("warnings", ())
                         if not text.startswith("Intersection diagnostic incomplete")
                         and not (text.startswith("Detected ") and "local self-intersections" in text)]
