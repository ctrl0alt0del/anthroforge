"""Isolated CPU/CUDA Fiber collision-batch parity and crossover benchmark."""

import argparse
import ctypes
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CUDA_DLL = ROOT / "native" / "fiber_cuda_experiment" / "af_fiber_cuda_experiment.dll"
CPU_DLL = ROOT / "native" / "fiber_ccd" / "af_fiber_ccd_v3.dll"


def arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--dataset")
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--counts", default="64,128,256,512,1024,2048,4096,8192,16384,32768,65536")
    return parser.parse_args(sys.argv[1:])


def pointer(kind):
    return ctypes.POINTER(kind)


def configure_cuda(library):
    void, double, integer, timer = ctypes.c_void_p, pointer(ctypes.c_double), pointer(ctypes.c_int32), pointer(ctypes.c_float)
    library.af_cuda_world_create.argtypes = [double, ctypes.c_int, ctypes.c_int, ctypes.c_int, pointer(void)]
    library.af_cuda_world_destroy.argtypes = [void]
    library.af_cuda_upload_pairs.argtypes = [void, integer, integer, ctypes.c_int]
    library.af_cuda_distances.argtypes = [void, double, ctypes.c_int, integer, integer, ctypes.c_int, double, timer]
    library.af_cuda_distances_cached.argtypes = [void, double, ctypes.c_int, double, timer]
    return library


def configure_cpu(library):
    void, double, integer = ctypes.c_void_p, pointer(ctypes.c_double), pointer(ctypes.c_int64)
    library.af_triangle_snapshot_create.argtypes = [double, integer, ctypes.c_int]
    library.af_triangle_snapshot_create.restype = void
    library.af_triangle_snapshot_destroy.argtypes = [void]
    library.af_snapshot_segment_triangle_distances.argtypes = [void, double, integer, ctypes.c_int, double]
    return library


def load_libraries():
    cuda = configure_cuda(ctypes.CDLL(str(CUDA_DLL)))
    cpu = configure_cpu(ctypes.CDLL(str(CPU_DLL)))
    return cuda, cpu


def address(array, kind):
    return array.ctypes.data_as(pointer(kind))


def triangles_as_mesh(triangles):
    vertices = np.ascontiguousarray(triangles.reshape((-1, 3)), dtype=np.float64)
    faces = np.arange(len(vertices), dtype=np.int64).reshape((-1, 3))
    return vertices, faces


class CpuWorld:
    def __init__(self, library, triangles):
        self.library = library; vertices, self.faces = triangles_as_mesh(triangles)
        self.handle = library.af_triangle_snapshot_create(address(vertices, ctypes.c_double), address(self.faces, ctypes.c_int64), len(self.faces))
        if not self.handle: raise RuntimeError("CPU snapshot creation failed")

    def close(self):
        if self.handle: self.library.af_triangle_snapshot_destroy(self.handle); self.handle = None

    def distances(self, segments, faces):
        output = np.empty(len(segments), dtype=np.float64)
        code = self.library.af_snapshot_segment_triangle_distances(self.handle, address(segments, ctypes.c_double), address(faces, ctypes.c_int64), len(faces), address(output, ctypes.c_double))
        if code: raise RuntimeError(f"CPU distance query failed: {code}")
        return output


class CudaWorld:
    def __init__(self, library, triangles, segment_capacity, pair_capacity):
        self.library = library; self.handle = ctypes.c_void_p()
        values = np.ascontiguousarray(triangles.reshape((-1, 9)), dtype=np.float64)
        code = library.af_cuda_world_create(address(values, ctypes.c_double), len(values), segment_capacity, pair_capacity, ctypes.byref(self.handle))
        if code: raise RuntimeError(f"CUDA world creation failed: {code}")

    def close(self):
        if self.handle: self.library.af_cuda_world_destroy(self.handle); self.handle = None

    def upload_pairs(self, segments, triangles):
        code = self.library.af_cuda_upload_pairs(self.handle, address(segments, ctypes.c_int32), address(triangles, ctypes.c_int32), len(segments))
        if code: raise RuntimeError(f"CUDA pair upload failed: {code}")

    def distances(self, segments, segment_ids, triangle_ids, cached=False):
        output = np.empty(len(segment_ids), dtype=np.float64); times = np.empty(4, dtype=np.float32)
        args = (self.handle, address(segments, ctypes.c_double), len(segments))
        if cached: code = self.library.af_cuda_distances_cached(*args, address(output, ctypes.c_double), address(times, ctypes.c_float))
        else: code = self.library.af_cuda_distances(*args, address(segment_ids, ctypes.c_int32), address(triangle_ids, ctypes.c_int32), len(segment_ids), address(output, ctypes.c_double), address(times, ctypes.c_float))
        if code: raise RuntimeError(f"CUDA distance query failed: {code}")
        return output, times


def synthetic(seed=24051984, segments=1024, triangles=8192, pairs=65536):
    random = np.random.default_rng(seed)
    starts = random.normal(size=(segments, 3)); ends = starts + random.normal(scale=0.15, size=(segments, 3))
    origins = random.normal(size=(triangles, 3)); first = random.normal(scale=0.1, size=(triangles, 3))
    second = random.normal(scale=0.1, size=(triangles, 3)); faces = np.stack((origins, origins + first, origins + second), axis=1)
    segment_ids = random.integers(0, segments, size=pairs, dtype=np.int32)
    triangle_ids = random.integers(0, triangles, size=pairs, dtype=np.int32)
    return np.ascontiguousarray(np.stack((starts, ends), axis=1)), np.ascontiguousarray(faces), segment_ids, triangle_ids


def load_dataset(path):
    with np.load(path) as data:
        return tuple(np.ascontiguousarray(data[name]) for name in ("segments", "triangles", "segment_ids", "triangle_ids"))


def timed(call):
    started = perf_counter(); value = call()
    return value, 1000.0 * (perf_counter() - started)


def percentile(values, quantile):
    return float(np.quantile(np.asarray(values, dtype=np.float64), quantile))


def cpu_trial(world, segments, segment_ids, triangle_ids):
    packed, pack_ms = timed(lambda: np.ascontiguousarray(segments[segment_ids]))
    (output, kernel_ms) = timed(lambda: world.distances(packed, triangle_ids.astype(np.int64)))
    return output, pack_ms, kernel_ms


def cuda_trial(world, segments, segment_ids, triangle_ids, cached):
    (result, wall_ms) = timed(lambda: world.distances(segments, segment_ids, triangle_ids, cached))
    output, stages = result
    return output, wall_ms, tuple(float(value) for value in stages)


def benchmark_count(libraries, data, count, repeats):
    segments, triangles, all_segments, all_triangles = data
    segment_ids = np.ascontiguousarray(all_segments[:count], dtype=np.int32)
    triangle_ids = np.ascontiguousarray(all_triangles[:count], dtype=np.int32)
    cpu, cpu_world_ms = timed(lambda: CpuWorld(libraries[1], triangles))
    cuda, cuda_world_ms = timed(lambda: CudaWorld(libraries[0], triangles, len(segments), count))
    _none, pair_upload_ms = timed(lambda: cuda.upload_pairs(segment_ids, triangle_ids))
    cpu_trial(cpu, segments, segment_ids, triangle_ids)
    cuda_trial(cuda, segments, segment_ids, triangle_ids, False); cuda_trial(cuda, segments, segment_ids, triangle_ids, True)
    rows = [benchmark_repeat(cpu, cuda, segments, segment_ids, triangle_ids) for _ in range(repeats)]
    cpu.close(); cuda.close(); result = summarize(count, rows)
    result.update(cpu_world_ms=cpu_world_ms, cuda_world_ms=cuda_world_ms, pair_upload_ms=pair_upload_ms)
    return result


def benchmark_repeat(cpu, cuda, segments, segment_ids, triangle_ids):
    expected, pack_ms, cpu_ms = cpu_trial(cpu, segments, segment_ids, triangle_ids)
    actual, cuda_ms, cuda_stages = cuda_trial(cuda, segments, segment_ids, triangle_ids, False)
    cached, cached_ms, cached_stages = cuda_trial(cuda, segments, segment_ids, triangle_ids, True)
    error = float(max(np.max(np.abs(expected - actual)), np.max(np.abs(expected - cached))))
    return pack_ms, cpu_ms, cuda_ms, cached_ms, cuda_stages, cached_stages, error


def summarize(count, rows):
    values = np.asarray([row[:4] for row in rows], dtype=np.float64)
    dynamic = np.asarray([row[4] for row in rows]); cached = np.asarray([row[5] for row in rows])
    cpu_total = values[:, 0] + values[:, 1]
    return {"pairs": count, "cpu_pack_ms": median(values[:, 0]), "cpu_kernel_ms": median(values[:, 1]),
            "cpu_total_ms": median(cpu_total), "cuda_dynamic_wall_ms": median(values[:, 2]),
            "cuda_cached_wall_ms": median(values[:, 3]), "cuda_dynamic_gpu_ms": median(dynamic[:, 3]),
            "cuda_cached_gpu_ms": median(cached[:, 3]), "cuda_kernel_ms": median(cached[:, 1]),
            "cuda_cached_p95_ms": percentile(values[:, 3], 0.95), "max_abs_error": max(row[6] for row in rows)}


def crossover(rows, key):
    for row in rows:
        if row[key] < row["cpu_total_ms"]: return row["pairs"]
    return None


def validate_rows(rows):
    error = max(row["max_abs_error"] for row in rows)
    if not np.isfinite(error) or error > 5.0e-13:
        raise RuntimeError(f"CUDA/CPU parity failed: {error}")


def main():
    args = arguments(); counts = tuple(int(value) for value in args.counts.split(","))
    data = load_dataset(args.dataset) if args.dataset else synthetic(pairs=max(counts))
    maximum = len(data[2]); counts = tuple(value for value in counts if value <= maximum)
    libraries = load_libraries(); rows = [benchmark_count(libraries, data, count, args.repeats) for count in counts]
    validate_rows(rows)
    payload = {"dataset": args.dataset or "synthetic", "segments": len(data[0]), "triangles": len(data[1]),
               "rows": rows, "dynamic_crossover_pairs": crossover(rows, "cuda_dynamic_wall_ms"),
               "cached_crossover_pairs": crossover(rows, "cuda_cached_wall_ms")}
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8"); print(json.dumps(payload)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
