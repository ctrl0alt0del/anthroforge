# Fiber V2 Package 4 production profile

## Method

Each supplied `.blend` was opened read-only in a fresh Blender 5.0.1 process.
Reported wall times are medians of five unprofiled calls against one already-built
immutable collider snapshot. Low-overhead nested phase timers add at most normal
run-to-run variance. A separate deterministic `cProfile` pass identifies function
and call-count hotspots; its slower absolute time is not used as the benchmark.
The chart is stored at
`artifacts/fiber_v2_package4/package4_profile_breakdown.png`; raw phase and
`cProfile` rows are stored in the three adjacent `profile_*.json` files.

## End-to-end timing

Important: the first and third rows below are different authored Fibers. They are
production coverage, not a controlled measurement of adding Draft Skin.

| Production Fiber | V1 planner | Package 4 planner | Ratio | Snapshot capture | Single-Fiber P4 total |
|---|---:|---:|---:|---:|---:|
| `skull_muscles/FIBER_14` | 136.18 ms | 291.91 ms | 2.14x | 206.55 ms | 498.46 ms |
| `skeleton_comb_base/FIBER_1` | 73.43 ms | 730.91 ms | 9.95x | 319.26 ms | 1,050.17 ms |
| `skull_muscles_skin/FIBER_1` | 34.69 ms | 432.28 ms | 12.46x | 238.52 ms | 670.80 ms |

Snapshot capture is shown separately because a future multi-Fiber request can share
it. It is still real latency for a single affected Fiber with no compatible cached
snapshot.

## Controlled skull versus skull-skin comparison

The original profile compared `skull_muscles/FIBER_14` with
`skull_muscles_skin/FIBER_1`; their different planner branches and timings must not
be attributed to the Draft Skin object. A corrected comparison uses `FIBER_1` in
both files.

| Property | `skull_muscles/FIBER_1` | `skull_muscles_skin/FIBER_1` |
|---|---:|---:|
| Package 4 median | 385.02 ms | 399.77 ms |
| Branch | SURFACE | SURFACE |
| Authored anchors | 4 | 4 |
| SCP colliders | 19 | 19 |
| Evaluated triangles | 30,544 | 30,544 |
| Tested edges / rejected | 665 / 483 | 665 / 483 |
| Candidate / tested pairs | 3,179 / 3,076 | 3,179 / 3,076 |
| Exact reference difference | \- | maximum `0.0` BU |

The collider IDs, owner IDs, topology, triangle indices, anchor coordinates, and
solver settings match. Evaluated SCP vertex coordinates contain small differences
up to `1.0669e-5` BU in unrelated colliders, but `SCP_1`—the owner used by this
surface Fiber—is bit-identical, and the final Package 4 reference is bit-identical.
The added `AF_DRAFT_SKIN` and four derived Muscle 8 meshes do not appear in the SCP
collider list. The remaining timing difference is ordinary process/run variance,
not additional planner work caused by Draft Skin.

## Package 4 phase medians

| Exclusive phase | Skull F14 | Skeleton F1 | Skull-skin F1 |
|---|---:|---:|---:|
| Graph/A* search | 83.76 ms (28.6%) | 276.95 ms (39.1%) | 0 ms |
| Collision-batch Python work | 98.81 ms (33.9%) | 210.03 ms (29.7%) | 94.79 ms (22.2%) |
| Native distance | 35.55 ms (12.2%) | 123.32 ms (17.4%) | 28.88 ms (6.9%) |
| Native containment | 31.49 ms (10.8%) | 38.49 ms (5.4%) | 186.55 ms (44.3%) |
| Native broad phase | 10.40 ms (3.5%) | 26.38 ms (3.7%) | 26.68 ms (6.1%) |
| Candidate/surface construction | 31.16 ms (10.7%) | 28.64 ms (4.1%) | 85.21 ms (20.0%) |
| Exact-count handoff | 0.17 ms | 0.18 ms | 0.26 ms |

`Collision-batch Python work` includes pair assembly, owner-contact trimming,
containment-cache bookkeeping, result scattering, and repeated validator setup; it
excludes the separately timed native kernels.

## Why the slowdown occurs

The roadmap cases repeatedly search, validate the currently chosen path, invalidate
one or more edges, and search again. The skeleton case performs 112 geometric path
searches, 115 collision batches, 223 tested edges, 200 rejected edges, and 33,941
tested edge/triangle pairs. Its graph expansion loop visits 2,455 nodes. V1 obtains
the same visible four-point corridor without this strict lazy-revalidation loop.

The surface case follows a different slow path. It tests 665 route edges in 46
batches. Only 3,076 edge/triangle distance pairs survive broad phase, but 37 native
point-in-closed-mesh calls consume 186.55 ms. Repeated containment of surface-route
candidates is therefore its dominant cost.

The ctypes binding also resolves the DLL path and backend capabilities for nearly
every batch/native call: 202 loads on skull F14, 557 on skeleton, and 147 on the
surface Fiber. An in-memory experiment caching the already-loaded library and status
reduced medians to 211.96, 501.48, and 315.32 ms respectively (27–31% faster). That
optimization is worthwhile but insufficient: skeleton remains 6.8x V1 and the
surface Fiber remains 9.1x V1.

## Conclusion

Package 4 is slow for two independent reasons: avoidable native-binding dispatch
overhead, and a more important algorithmic amplification from iterative lazy graph
re-search plus repeated strict containment. The exact-count handoff is effectively
free and is not the problem. Production work should cache the backend handle/status,
then replace global lazy retries with local blocker repair and batched regional
validation. The surface branch also needs a cached/native collider containment
structure rather than repeated full-mesh point-in-mesh calls.
