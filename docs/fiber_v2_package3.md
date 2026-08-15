# Fiber V2 Package 3 — standalone native collision backend

Package 3 is implemented as an isolated V2 component. It is not connected to the live V1 planner, solver, preview, persistence, or downstream dependency graph.

## Implemented

- Immutable world-space triangle snapshots with cached native face bounds.
- Exact native point/triangle and segment/triangle distances.
- Static chain-clearance validation for nodes and edges.
- Closed-manifold containment checks, so a Fiber wholly inside an SCP is not incorrectly considered clear merely because it is far from the surface.
- Conservative swept segment/triangle CCD and safe-step composition.
- Fail-closed invalid-start and interval-budget handling.
- Explicit `BACKEND_UNAVAILABLE` behavior for a missing or incompatible DLL; no reference fallback is used in V2.
- Local owner-contact filters expressed as exact node exemptions and per-edge parameter intervals. An owner exemption cannot remove the complete SCP or affect unrelated colliders.
- Broad-phase calls in batches of at most 64 Fiber edges and narrow-phase calls in batches of at most 128 candidate pairs.
- A packaged Windows x64 DLL. Runtime users do not need a compiler or C++ installation.

The built 127,488-byte DLL was inspected with `dumpbin /dependents`; its only
runtime dependency is the Windows system `KERNEL32.dll`.

The implementation is in `core/vcp/v2/collision.py`, its private binding is in `core/vcp/v2/collision_native.py`, and the additive ABI is in `native/fiber_ccd/af_fiber_ccd.cpp`.

## Correctness qualification

The focused suite covers:

- randomized primitive distance parity against an independent Python reference;
- 50 randomized swept motions checked against dense temporal samples, with zero detected misses;
- thin, degenerate, coplanar, grazing, invalid-start, and tunneling cases;
- fail-closed interval-budget exhaustion;
- rigid, mirrored, and negative-orientation equivalence;
- 100 random tetrahedron containment queries against an analytic reference;
- open-surface versus closed-solid semantics;
- local same-owner contact beside another same-owner obstacle;
- unrelated-collider preservation;
- native edge/pair batch limits;
- missing and incompatible DLL handling.

This is qualification evidence, not a mathematical proof for every degenerate production mesh. Package 4 must still reject invalid planner handoffs, and the final V2 validator must remain independent from local contact projections.

## Read-only production benchmark

Blender 5.0.1 was run against the supplied files without saving them. The native CCD probe is a known-valid motion through a real evaluated SCP triangle; the reference probe uses the same motion and collider arrays.

| File / Fiber | Triangles | N | Static validation | Native CCD | Python reference | Speedup |
|---|---:|---:|---:|---:|---:|---:|
| `skull_muscles.blend / FIBER_14` | 30,544 | 64 | 14.49 ms | 30.74 ms | 236.79 ms | 7.70x |
|  |  | 512 | 103.26 ms | 221.43 ms | 1,839.58 ms | 8.31x |
| `skeleton_comb_base.blend / FIBER_1` | 39,180 | 64 | 11.81 ms | 11.68 ms | 248.81 ms | 21.31x |
|  |  | 512 | 76.61 ms | 81.60 ms | 1,829.37 ms | 22.42x |
| `skull_muscles_skin.blend / FIBER_1` | 30,544 | 64 | 19.29 ms | 30.08 ms | 251.44 ms | 8.36x |
|  |  | 512 | 141.37 ms | 216.03 ms | 1,828.17 ms | 8.46x |

Native snapshot capture, including Blender evaluated-surface extraction and contract conversion, took 196.76–287.23 ms. This cost must be shared across affected Fibers; rebuilding it per Fiber would miss the live-SCP target.

All three persisted V1 examples fail strict Package 3 validation. The visual report shows the exact invalid edges and also colors edges adjacent to nodes contained inside closed SCPs. This is expected evidence that Packages 4 and 5 still need to construct and optimize a valid route; Package 3 intentionally does not move the Fiber or hide existing intersections.

The 512-node skull CCD probe is at roughly 216–221 ms by itself. Therefore the full 512-node V2 solve target of 220 ms is not yet secure. Later integration should reduce repeated candidate work or use a stronger native spatial hierarchy before rollout; validation thresholds must not be weakened.

## Artifacts

- `artifacts/fiber_v2_package3/real_file_collision_preview.png`
- `artifacts/fiber_v2_package3/collision_benchmark_scaling.png`
- One JSON manifest per production Fiber in the same directory.

Source blend hashes remained unchanged:

- `skull_muscles.blend`: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
- `skeleton_comb_base.blend`: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`
- `skull_muscles_skin.blend`: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`

## Package boundary

Package 3 does not choose routes, resample planner corridors, project contacts, optimize the centerline, publish previews, or migrate saved Fibers. Those responsibilities remain in Packages 4, 5, 8, 9, and 10. The next independent step is Package 4: deterministic V2 planning and safe exact-count handoff using this backend as its only collision authority.
