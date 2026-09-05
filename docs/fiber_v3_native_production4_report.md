# Fiber V3 production-4 native optimization report

Date: 2026-08-29

## Outcome

Production V3 now reuses collider topology and refits world-space triangle BVHs for transform-only
SCP batches. This is the only tested change retained from the native optimization pass.

The implementation deliberately keeps world-space collider coordinates. The tested local-mesh plus
instance-transform representation changed the accepted numerical trajectory by up to `0.01043 m`
on `skeleton_comb_base/FIBER_1`; it was rejected. The tested binned-SAH tree also changed
route/contact tie behavior, while compact-node traversal was slower. Neither is reachable in
production.

This matches the standard separation between immutable topology and refittable vertex/bounds data
used by dynamic ray-tracing structures. Embree documents `RTC_BUILD_QUALITY_REFIT` specifically for
vertex-buffer-only changes: <https://github.com/RenderKit/embree>. OpenMP allocator facilities were
reviewed, but the scratch/capacity changes were neutral and have been removed:
<https://www.openmp.org/spec-html/5.2/openmpse35.html>.

## Accepted implementation

1. Capture computes exact world vertices plus stable topology/local-geometry identity.
2. A cached native world retains its triangle topology and acceleration structures across edits.
3. A transform-only hierarchy update submits all changed world vertex buffers in one call.
4. Each triangle BLAS is refitted without changing face ordering; the world TLAS is refitted once.
5. An active solver session prevents in-place mutation; a private world is built for overlapping work.

Cache identity includes engine/backend version, collider identity, topology digest, local geometry
digest and exact world-position identity. Geometry deformation therefore rebuilds only its changed
BLAS, while descendant transform propagation uses the refit path.

## Result parity

| Fixture | Baseline point hash | Production-4 point hash | Accepted/rejected | Result |
|---|---|---|---:|---|
| `skull/FIBER_1` | `7fe91cd93a63` | `7fe91cd93a63` | `180 / 96` | exact |
| `skull/FIBER_14` | `c204e8f9826b` | `c204e8f9826b` | `70 / 20` | exact |
| `skeleton/FIBER_1` | `4e1e60ebde4e` | `4e1e60ebde4e` | `486 / 243` | exact |

Native refit validation also matched an independently rebuilt world for every fixture. Both source
`.blend` SHA-256 hashes remained unchanged.

## World-cache benchmark

Timings are milliseconds in fresh Blender 5.0.1 processes on the current Windows workstation.
Refit and cache-hit values are medians of three operations.

| Fixture | Cold world | Exact hit | Batch refit | Clean rebuild | Refit speedup |
|---|---:|---:|---:|---:|---:|
| `skull/FIBER_1` | 16.850 | 0.070 | 0.420 | 15.220 | 36.2x |
| `skull/FIBER_14` | 17.000 | 0.090 | 0.690 | 15.390 | 22.3x |
| `skeleton/FIBER_1` | 17.410 | 0.210 | 0.760 | 16.280 | 21.4x |

This is the relevant gain for an SCP transform that propagates transforms to descendants: the
collision world update remains below one millisecond instead of rebuilding 19 skull or 32 skeleton
collider BVHs. Cold construction keeps the existing fused native batch, so topology retention adds
no per-collider Python construction penalty.

Collision-only Blender capture was `89.27 / 5.59 / 77.90 ms` for skull `FIBER_1`, skull
`FIBER_14`, and skeleton `FIBER_1`. Against the earlier `66.24 / 5.35 / 189.01 ms` snapshot, the
large skeleton capture improved by 58.8%; the two skull measurements remained within or above
cross-process noise and are not claimed as wins.

## Full-solver benchmark

| Fixture | Production-4 cold | Production-4 warm median | Contact | CCD |
|---|---:|---:|---:|---:|
| `skull/FIBER_1` | 896.86 | 824.63 | 250.70 | 26.57 |
| `skull/FIBER_14` | 236.68 | 198.41 | 61.16 | 8.38 |
| `skeleton/FIBER_1` | 1979.39 | 2054.92 | 439.64 | 352.75 |

These runs do **not** show a full-solve speedup over the earlier 700/171/1711 ms snapshot. A direct
same-build ablation of shared snapshots versus the old one-call world construction measured
approximately 886 versus 900 ms for skull `FIBER_1`, so world ownership is not the source of the
larger cross-run difference. The accepted optimization removes about 15 ms of repeated native-world
construction during transform-driven recalculation; it does not reduce the SQP/contact/CCD work
which still dominates a complete solve. Allocation reuse was neutral within run noise.

After removing the neutral allocation and preallocation code, a fresh one-repeat parity run kept
the exact three point hashes. Refit versus clean rebuild measured `1.140 / 15.790 ms` for skull
`FIBER_1`, `1.269 / 16.304 ms` for skull `FIBER_14`, and `1.047 / 17.073 ms` for skeleton
`FIBER_1`: a retained `12.8x–16.3x` acceleration of collision-world refresh. The source file
hashes again remained unchanged.

## Rejected variants

| Variant | Reason for rejection |
|---|---|
| Local BLAS plus instance transform | Changed final geometry and iteration trajectory |
| 8-bin SAH | Changed deterministic contact/route tie behavior |
| Compact 64-byte nodes | Approximately 9% slower on the skull fixtures |
| Per-edge scratch vectors | No measurable advantage over per-worker scratch; larger session state |
| Per-worker scratch/persistent CCD buffers | Neutral within run noise; removed from production |
| BVH-build preallocation | No measurable end-to-end benefit; removed from production |
| Iterative query traversal | Slower than the accepted recursive traversal |

Benchmark artifacts are `native_opt_final_skull.json` and `native_opt_final_skeleton.json` in the
task visualization directory. The reproducible runner is
`tools/fiber_v3_native_production_benchmark.py`.
