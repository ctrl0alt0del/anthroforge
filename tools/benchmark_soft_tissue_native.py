"""Reproduce solver-only parity and timings against the frozen test reference."""
from pathlib import Path
import json
import statistics
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests/unit")]
from test_soft_tissue_static_envelope import envelope_fixture
import soft_tissue_reference as reference
from core.vcp.soft_tissue_static_envelope import StaticEnvelopeSettings, solve_static_envelope


def python_solve(mesh, fixed, settings):
    state = reference._create_state(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count, settings)
    reference._solve(state, settings, (), 1.e-5)
    reference._finalize_volume(state, settings)
    return state.points


def measure(call):
    call()
    times = []
    for _ in range(5):
        started = time.perf_counter()
        result = call()
        times.append((time.perf_counter()-started)*1000.)
    return result, statistics.median(times)


def benchmark(size):
    mesh, fixed = envelope_fixture(.8, size)
    settings = StaticEnvelopeSettings()
    expected, python_ms = measure(lambda: python_solve(mesh, fixed, settings))
    result, native_ms = measure(lambda: solve_static_envelope(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count, settings))
    error = float(np.max(np.linalg.norm(np.asarray(result.vertices)-expected, axis=1)))
    return dict(vertices=len(mesh.vertices), python_median_ms=python_ms, native_median_ms=native_ms,
                speedup=python_ms/native_ms, max_vertex_error=error, report=result.report)


if __name__ == "__main__":
    results = [benchmark(size) for size in (7, 17, 33, 65)]
    destination = ROOT / "artifacts/soft_tissue_native_regression/v1/benchmark.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
