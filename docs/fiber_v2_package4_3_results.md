# Fiber V2 Package 4.3 results

## Decision

Package 4.3 succeeds as an opt-in planning experiment. It preserves the Package
4.1 route exactly on every measured production Fiber while removing the repeated
Python graph/collision orchestration that dominated Package 4. Package 4.3 must
remain isolated until its native world is connected to the resumable V2 solver,
CCD acceptance, lifecycle generations, and live Blender scheduling.

The implementation follows the hierarchy/instancing model exposed by
[Embree](https://github.com/RenderKit/embree) and moves the repeated expensive-edge
loop described by [LazySP](https://arxiv.org/abs/1803.04998) into the native module.
Candidate generation and anatomical route policy remain deterministic Python code.

## Implemented experiment

- one native collision world with one bottom-level BVH per collider and a
  refittable top-level collider BVH;
- fused owner trimming, broad phase, exact segment/triangle distance,
  containment, and edge-state output;
- native cached-metric Lazy A* for roadmap and surface-candidate graphs;
- native mesh-graph construction and shortest-path search for surface routes;
- hard-anchor preflight that reports the authored anchor and blocking collider;
- bounded persistent Python world cache and explicit lifecycle clear;
- unchanged Package 4, 4.1, and 4.2 entry points plus opt-in
  `plan_reference_v43`;
- packaged Windows DLL capability level `1.255`.

## Real-file planner benchmarks

Medians are milliseconds from fresh Blender 5.0.1 processes. These are planner
times, not complete V2 local/global solver times.

| Fixture | V1 | Package 4 | Package 4.1 | Package 4.2 | Package 4.3 |
|---|---:|---:|---:|---:|---:|
| skull/FIBER_14 roadmap | 152.95 | 295.84 | 199.37 | 201.91 | **19.35** |
| skeleton/FIBER_1 roadmap | 81.76 | 673.56 | 383.20 | 404.81 | **28.99** |
| skull/FIBER_1 surface | 50.28 | 212.17 | 197.43 | 7148.84 | **52.77** |
| skull-skin/FIBER_1 surface | 47.87 | 215.00 | 166.94 | 6967.63 | **51.58** |

Package 4.3 is 10.3x faster than Package 4.1 on skull/FIBER_14 and
13.2x faster on skeleton/FIBER_1. The surface case is 3.2-3.7x faster than
Package 4.1 and now approximately matches V1. Draft Skin does not enter the
collider request: Package 4.3 differs by only 1.19 ms between the two surface
files, compared with the multi-second Package 4.2 grouped-search regression.

Every Package 4.3 row terminates `CONVERGED`, passes the existing independent
static validator, has zero reference-point delta from Package 4.1, and has an
identical corridor. Package 4.2 intentionally remains disabled: on same-owner
surface chains it changes the route and takes about seven seconds.

## Maxilla hierarchy and hard-pin experiment

At Maxilla Top Radius `0.2`, the original FIBER_21 anchors are invalid. Package
4.3 reports `INVALID_ATTACHMENT: authored anchor 4 intersects collider SCP_4:3`
in 2.30 ms warm, before any graph search. Packages 4/4.1/4.2 spend roughly
0.98-2.51 seconds searching before returning `NO_FEASIBLE_PATH`.

After the controlled in-memory pin repair, Package 4.3 converges in 18.47 ms,
versus 95.25 ms for Package 4.1 and 99.15 ms for Package 4.2. The Package 4.3
reference is bit-identical to Package 4.1 and independently valid. The repaired
pins remain an experiment, not an authored anatomical correction.

Using the real 30,544-triangle skull collider set, a clean native-world build
takes 61.59 ms. Updating one Maxilla instance transform and refitting the top
level takes 0.0124 ms median, versus 59.62 ms for a clean rebuild: 4808x faster
for that controlled transform-only operation, with identical collision results.

## Profiling result

Before the final Package 4.3 pass, skull/FIBER_14 spent about 42 ms rebuilding
temporary single-collider snapshots during candidate filtering. Reusing the
world's existing collider BVHs reduced the complete planner from 54 ms to 19 ms.

The surface case previously spent about 66 ms constructing/searching the mesh
graph in Python and about 42 ms repeatedly resolving native status. Native mesh
search plus world-owned backend metadata reduced the complete planner from
105-136 ms to 48-53 ms. The remaining surface cost is primarily Python surface
candidate construction and 49 small native validation dispatches.

## Verification

- focused native collision/planner/ratchet: 44 passed;
- complete unit suite: 387 passed, one pre-existing expected failure;
- full Blender discovery: 459 tests ran; all reached Fiber tests passed, but the
  run ended with eight unrelated dependency/sandbox errors (Draft Skin vendor
  access and missing SciPy) and the already-known order-dependent Quick Fiber
  persistence error;
- source `.blend` files were read-only and their final hashes were:
  - skull: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`;
  - skeleton: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`;
  - skull-skin: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`.

## Remaining before production

1. Capture local collider meshes plus hierarchy transforms instead of flattening
   each request to world-space geometry.
2. Drive transform refits and geometry-only BLAS replacement from actual Blender
   generations; the current refit benchmark is a controlled native API test.
3. Connect the world to the resumable local/global V2 session and conservative
   movement CCD. Package 4.3 currently accelerates planning/static validation.
4. Batch the many small surface-validation calls if end-to-end V2 profiling still
   identifies them as material.
5. Resolve the baseline Quick Fiber persistence test, then run the complete clean
   Blender suite with Draft Skin dependencies available.
6. Keep Package 4.2 grouped search disabled; it is neither a speed nor route
   quality improvement on the measured same-owner production Fiber.
