# Muscle contiguous numerical pipeline and native benchmark

## Production architecture

Muscle synchronization now captures every affected Muscle into immutable,
contiguous `float64` point grids and one fixed numerical specification. One
backend-neutral batch performs row resampling, closed-row alignment, transverse
densification, quad topology, normals, and both inflation modes. Blender code
only captures source data, publishes the returned arrays, and manages controls.

The production default is `NATIVE`. Set `AF_MUSCLE_NUMERIC_BACKEND=PYTHON` before
starting Blender to use the isolated reference backend. The native implementation
ships in `af_fiber_ccd_v3_11.dll` and uses one OpenMP work-sharing region across
Muscles. A calibrated input-work threshold of 1,024 avoids parallel overhead for
small updates. This follows OpenMP's work-sharing model; Blender data remains on
the main thread and is published with bulk mesh writes.

References:

- [OpenMP API 6.0](https://www.openmp.org/wp-content/uploads/OpenMP-API-Specification-6-0.pdf)
- [OpenMP worksharing-loop semantics](https://www.openmp.org/spec-html/5.1/openmpsu49.html)
- [Blender `foreach_set`](https://docs.blender.org/api/main/bpy.types.bpy_prop_collection.html)

## Real Blender result

Fixture: latest filesystem `E:\development\WIP_models\skull_muscles.blend`.
Flow: fresh Blender 5.0.1 process, production Cranium Lobe Width shortcut,
`7,1,7,1,7,1`. Source SHA-256 remained
`4855042f259135c569c3e89b50df5d0441e6794bef5e774aebf924fd8372287e`.

| Configuration | Full event median | Muscle driver | Numerical batch | Mesh publication |
|---|---:|---:|---:|---:|
| Previous production | 344.72 ms | 229.06 ms | not isolated | 45.91 ms |
| New Python reference | 365.15 ms | 280.92 ms | 213.11 ms | 61.85 ms |
| Native, Muscle kernel serial | 191.06 ms | 78.98 ms | 1.53 ms | 69.21 ms |
| Native + OpenMP production | **179.44 ms** | **75.91 ms** | **0.91 ms** | 68.01 ms |

Native/OpenMP improves the complete shortcut flow by 1.92x versus the previous
production baseline. It improves the numerical batch by roughly 234x versus the
Python reference. OpenMP improves the native numerical batch by 40.5% and the
full event by 6.1% versus the same four-worker runtime with only the Muscle
kernel forced serial.

## Correctness

- All quad topology is exactly equal between Python and native.
- Maximum base-coordinate delta: `1.1919576969887657e-7` world units.
- Maximum inflated-coordinate delta: `1.721898357898155e-6` world units.
- Native serial and native OpenMP outputs are bit-for-bit identical.
- The six-event round trip and handle states match; the source file is unchanged.
- Relevant unit, Muscle workflow, Fiber Surface, and Soft Tissue integration
  suites pass, and the function-size ratchet reports no new violations.

The Python/native difference is expected from the Python reference's
`mathutils.Vector` intermediate precision versus native double precision. The
next dominant Muscle cost is no longer numerical work: about 68 ms is Blender
mesh publication and roughly 7 ms is capture/control/material orchestration.

## Benchmark artifacts

- `muscle_numeric_python.json`
- `muscle_numeric_native_kernel_serial.json`
- `muscle_numeric_production_native.json`
- `muscle_numeric_parity_final.json`

These files are in the Codex visualization output directory for this task.
