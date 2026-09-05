# Fiber V2 current-state and full-cycle audit

Date: 2026-08-17

## Executive conclusion

V2.2 is not a production replacement for V1 and is not generally "super fast."
It is an isolated experiment with one strong integration result: compact
generation identities and persistent collision snapshots remove repeated
geometry hashing and make an already-warm solve faster. That result does not
carry over to a cold SCP geometry change yet.

- The live add-on still runs V1 by default. `solve_v22` has no production
  runtime caller.
- On eight deliberately compatible Fibers, a warm V2.2 solve plus strict final
  validation averages `60.98 ms`, versus `77.09 ms` for the direct V1 solver.
  That is a 20.9% aggregate advantage, not an order-of-magnitude improvement.
- A cold isolated V2.2 Fiber cycle averages `512.68 ms` for capture plus solve,
  before debounce, commit, downstream work, or viewport scheduling.
- A 24-Fiber skull batch costs `1,798.49 ms` for V2.2 capture plus cold numeric
  work, versus `1,304.71 ms` for the direct V1 batch.
- The actual V1 Cranium Lobe Width shortcut completes its complete synchronous
  runtime pass in `1,831.01 ms`. V2.2's `1,798.49 ms` comparison excludes the
  SCP, Muscle, mirror, commit, and scheduling work, so V2.2 is not faster for
  this real cold cycle.
- Only 12 of the 24 authored skull Fibers produce a validated V2.2 result. Six
  fail hard-anchor validation, three fail exact-count handoff, and three have a
  missing parent. Of the 12 valid results, one converges and 11 stop `BLOCKED`.
- V2.2 therefore passes a reuse/caching experiment and fails the current
  compatibility, convergence, cold-latency, and rollout gates.

## What is actually implemented

| Component | Current status |
|---|---|
| Production Fiber runtime | V1 remains active and is the only complete editing/publication path. |
| Package 1 | Pure-data request/result contracts retained. |
| Package 2 | O(N) banded structural solver retained; it is not the bottleneck. |
| Package 3 | Packaged native collision/CCD and independent static validator retained. |
| Package 4.3 | Fused native planner retained as the accepted V2 planner. |
| Package 5.1 | Fused contact, pair cache, curved recovery, and final-only full validation retained. |
| Package 6.1 | Dynamic light/dense collision dispatcher retained. |
| Packages 7.1/7.2 | Rejected: fixed-objective/adaptive recovery did not improve convergence or latency. |
| Packages 8/8.1/8.2 | Rejected as solvers; numerical contact primitives remain experiments. |
| V2.1 | Isolated route-reuse and sparse linear-first CCD experiment. |
| V2.2 | Isolated compact-identity, shared-snapshot, preview/final route-policy experiment. |
| V2.2 production adapter | Missing. No live RNA/depsgraph capture, scheduling, commit, or migration path calls `solve_v22`. |

The rollout environment flag remains off, and new Fibers therefore remain V1.
The old integrated `solver_version=2` path is not the Package 4.3/5.1/6.1/V2.2
experiment assessed here.

## Timing vocabulary

The earlier reports used overlapping terms. This audit uses the following exact
boundaries:

| Name | Included | Excluded |
|---|---|---|
| Event cost | One RNA/handle callback and debounce enqueue | Quiet wait, solve, commit |
| V1 live terminal cycle | Forced runtime flush, progressive slices, and any emitted solve-ready/downstream pass | The 125 ms quiet window, which is added separately |
| V1 direct solve | `FiberSolver.solve_points` | Dependency graph request, debounce, progressive scheduling, downstream publication |
| V2.2 warm solve | Compact signature, cache lookup, planner reuse, numeric solve, CCD, strict final validation | Blender capture, debounce, commit, downstream work |
| V2.2 cold solve | First native snapshot/world build, planning, solve, CCD, strict validation | Blender collider/request capture, debounce, commit, downstream work |
| V2.2 cold isolated cycle | Blender collider/request capture plus V2.2 cold solve | Debounce, commit, downstream work |
| Batch cycle | One shared collider/request capture followed by every Fiber solve | Product runtime scheduling and publication unless explicitly stated |

Timings use Python `perf_counter` in fresh Blender 5.0.1 background processes.
The benchmark probe forces queued work ready, so the documented 125 ms quiet
window is added arithmetically rather than slept inside the benchmark.

## Benchmark inputs

| File | SHA-256 |
|---|---|
| `skull_muscles.blend` | `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06` |
| `skull_muscles_skin.blend` | `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96` |
| `skeleton_comb_base.blend` | `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42` |

The source files remained byte-identical after every run. The current skeleton
file contains one authored Fiber, `FIBER_1`.

## Current production V1 live-edit cycle

These rows are fresh real-runtime measurements. Property input uses 21 slider
events ending at a changed value. Handle input uses 20 monotonic moves ending
at 0.5 collision radius from the start. Both produce one coalesced Fiber solve.
`Terminal` includes the forced runtime flush and refinement drain plus the 125 ms
quiet window. It does not imply that every request committed; a rejected result
can terminate without emitting `FIBER_SOLVE_READY`.

| Fixture | Property terminal | Handle terminal | Property max slice | Handle max slice | Property collision queries | Handle collision queries |
|---|---:|---:|---:|---:|---:|---:|
| Skull/FIBER_1 | 263.30 | 241.78 | 28.69 | 26.99 | 23,815 | 23,190 |
| Skull/FIBER_13 | 209.64 | 199.47 | 45.98 | 44.63 | 241 | 238 |
| Skull/FIBER_14 | 426.68 | 215.04 | 39.28 | 61.41 | 64,990 | 2,898 |
| Skull/FIBER_22 | 265.65 | 260.72 | 17.20 | 17.86 | 18,437 | 19,948 |
| Skull/FIBER_4 | 307.31 | 322.36 | 28.41 | 21.91 | 38,512 | 39,942 |
| Skull/FIBER_9 | 336.96 | 305.28 | 25.99 | 22.97 | 40,116 | 39,836 |
| Skull-skin/FIBER_1 | 239.76 | 245.14 | 28.65 | 28.70 | 26,147 | 26,299 |
| Skeleton/FIBER_1 | 267.42 | 267.71 | 71.76 | 67.59 | 39,713 | 37,194 |
| **Average** | **289.59** | **257.19** |  |  |  |  |

The event callbacks themselves are fast: p95 stays below `0.20 ms`. The visible
drag remains responsive because work is debounced, but the post-quiet result is
not a one-frame operation. Only one fixture keeps every measured maximum slice
below 20 ms. Main-thread slices of 22-72 ms can still appear as viewport stalls.

## Current production V1 shortcut cycle

A fresh one-percent `Cranium Lobe Width` change on `skull_muscles.blend` gives:

| Phase | Time / count |
|---|---:|
| Complete synchronous runtime request | 1,831.01 ms |
| Fiber driver | 1,619.15 ms |
| SCP driver | 129.20 ms |
| Muscle driver | 63.35 ms |
| Mirror driver | 18.25 ms |
| Fiber solves | 24 |
| Fiber iterations | 285 |
| Collision queries | 303,854 |
| Fiber writes | 5 |
| BVHs built | 38 |
| Collider records built | 456 |

The previous recurring post-shortcut freeze is not reproduced: after the
1.83-second synchronous pass, the first explicit view-layer update costs
13.59 ms and later updates are effectively zero, with no pending tail request.
The remaining defect is the single long synchronous block and the fact that only
five of 24 solves publish a new Fiber result.

## Selected-fixture V1 versus V2.2 solver harness

The following is a solver-harness comparison, not a UI-cycle comparison. V2.2
is already warm and reuses its collision world and validated route. V1 is called
through `FiberSolver.solve_points`, without the live progressive/dependency
runtime. Values are fresh medians in milliseconds.

| Fixture | V1 direct | V2.2 warm | V2.2 capture | V2.2 cold solve | V2.2 cold isolated |
|---|---:|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 71.16 | 172.49 | 340.44 | 432.69 | 773.13 |
| Skull/FIBER_1 | 37.89 | 23.58 | 194.11 | 289.17 | 483.27 |
| Skull/FIBER_13 | 118.24 | 8.89 | 192.63 | 219.57 | 412.20 |
| Skull/FIBER_14 | 109.81 | 37.25 | 219.23 | 247.12 | 466.34 |
| Skull/FIBER_22 | 116.06 | 20.25 | 198.70 | 207.39 | 406.09 |
| Skull/FIBER_4 | 41.12 | 90.75 | 200.75 | 340.26 | 541.01 |
| Skull/FIBER_9 | 40.18 | 109.56 | 199.93 | 322.96 | 522.89 |
| Skull-skin/FIBER_1 | 82.24 | 25.11 | 204.85 | 291.61 | 496.47 |
| **Average** | **77.09** | **60.98** | **218.83** | **293.85** | **512.68** |

V2.2 is warm-faster on five fixtures and slower on Skeleton/FIBER_1,
Skull/FIBER_4, and Skull/FIBER_9. Its aggregate warm advantage is 20.9%. The
cold isolated cycle is 6.65 times the average direct V1 solve and still excludes
the 125 ms debounce and Blender publication work.

This eight-Fiber set was selected earlier for nonblocking pins and valid Package
4.3 handoffs. It is useful for algorithm comparison but is not representative of
all authored Fibers. The full-file compatibility result below is the rollout
authority.

## V2.2 editing harness

These V2.2 rows include compact request identity, cache lookup, solve, CCD, and
strict validation. They exclude real event dispatch, Blender commit, downstream
drivers, and viewport scheduling.

| Scenario | Average numeric | Range | Approx. after 125 ms quiet |
|---|---:|---:|---:|
| Property edit | 76.15 | 8.76-160.98 | 201.15 average |
| Handle validated preview | 83.97 | 11.28-172.05 | 208.97 average |
| Handle fresh final after preview | 82.47 | 12.63-205.67 |  |
| Handle preview + fresh final | 166.44 | 23.90-377.72 | 291.44 average |

The property path has potential to beat the current V1 terminal average after
runtime integration. The complete handle preview-plus-final experiment is slower
than the current V1 handle average before adding commit/downstream cost. The
one-frame provisional display remains required.

## Shared full-file batch

This experiment captures collider arrays and requests once, then solves every
open Fiber through one persistent V2.2 collision snapshot.

| File | Fibers | Capture | V1 direct batch | V2.2 cold batch | V2.2 capture + cold | V2.2 warm batch |
|---|---:|---:|---:|---:|---:|---:|
| Skull | 24 | 244.98 | 1,304.71 | 1,553.52 | 1,798.49 | 934.94 |
| Skull-skin | 25 | 272.96 | 1,349.26 | 1,547.25 | 1,820.21 | 906.82 |
| Skeleton | 1 | 260.80 | 75.33 | 436.50 | 697.30 | 162.14 |

The shared snapshot works: the skull cold batch creates one entry and reuses it
for every solvable Fiber. It is beneficial only after the native world and route
caches are populated. A real shortcut deforms SCP geometry, so the cold row is
the relevant one. On that path V2.2 capture plus numeric work is 37.8% slower
than the V1 direct batch, before V2.2 pays product runtime and publication cost.

The actual V1 shortcut's `1,831.01 ms` and V2.2's `1,798.49 ms` must not be read
as a V2.2 win: the first is a complete product request, while the second omits
SCP synchronization, Muscle/mirror work, debounce, commits, and scheduling.

## Existing-Fiber compatibility

The full skull batch exposes the main rollout blocker hidden by the selected
eight-Fiber benchmark.

| V2.2 result on 24 skull Fibers | Count |
|---|---:|
| Valid and `CONVERGED` | 1 |
| Valid but `BLOCKED` | 11 |
| `INVALID_ATTACHMENT` | 6 |
| `NO_FEASIBLE_PATH` | 3 |
| Missing parent SCP before request construction | 3 |

Specific failures:

- `FIBER_5`, `FIBER_6`, `FIBER_7`, `FIBER_8`, `FIBER_20`, and `FIBER_21`:
  an authored endpoint intersects collider `SCP_3:2` under V2's unified strict
  collider policy.
- `FIBER_11`, `FIBER_12`, and `FIBER_24`: the exact-count handoff fails the
  independent validator.
- `FIBER_15`, `FIBER_17`, and `FIBER_18`: missing parent SCP.

V1 returns a curve for 21 of the 24 Fibers; V2.2 returns a validated curve for
12. Existing Fibers are therefore not drop-in compatible with V2.2. Migration
needs an explicit attachment repair or compatibility workflow, and the
exact-count handoff needs correction for the three no-path Fibers. Strictness
must not be weakened merely to increase the count.

Among the selected eight Fibers, all V2.2 outputs pass the native validator, but
only Skull/FIBER_13 converges. Skeleton/FIBER_1 exhausts its budget; the other
six stop blocked. That is an 8.3% convergence rate among the 12 valid skull
outputs, far below the 90% rollout target.

## Where V2.2 time goes

On the selected warm set, average V2.2 phase time is:

| Phase | Average | Interpretation |
|---|---:|---|
| CCD acceptance | 36.27 ms | Dominant warm cost; 58.7% of traced total |
| Candidate/contact construction | 18.82 ms | Second largest cost; contact query is 7.61 ms of this |
| Independent final validation | 3.28 ms | Small and required |
| Structural banded solve | 2.60 ms | Small; replacing it will not materially improve latency |
| Dispatch | 0.50 ms | P6.1 mode-selection overhead is acceptable |
| Compact request signature | 0.24 ms | Solved problem; no longer worth optimizing |
| Complete traced warm solve | 61.76 ms | Close to the measured 60.98 ms median average |

For cold work, Blender capture averages 218.83 ms and first native-world/route
construction adds roughly another 233 ms over the warm solve. Persistent
hierarchical collision state is therefore more important than further matrix or
signature optimization.

The reproducible C++ migration map and cold-start profile are in
`docs/fiber_v22_cpp_migration_and_cold_start.md`.

## Correctness and visual status

- All selected V2.2 baseline, property, preview, and fresh-final results pass
  independent node/edge validation.
- Selected V2.2 baseline, property, and fresh-final points exactly match the
  accepted P6.1 reference.
- The V2.2 preview can differ from the fresh final; Skull/FIBER_14 differs by
  0.04020 world units but remains on the same validated obstacle side.
- V2.2 does not solve the visible FIBER_4 contact ripple or the angular skeleton
  route. Skull/FIBER_9 is 8.17% longer than its V1 result.
- Seven of the selected V1 curves fail the stricter V2 validator. This explains
  part of V1's speed and means timing and visual output are not quality-equivalent.
  It does not establish that the V2 curve is anatomically preferable; that still
  needs human review.
- A known warm-seed versus cold convergence-tolerance test remains an expected
  failure. V2.2 caching does not repair the fixed-point definition.

## Release-gate status

| Gate | Status |
|---|---|
| Event processing p95 below 5 ms | Pass for tested property/handle callbacks |
| Immediate provisional display below 16.7 ms | Existing provisional path retained; V2.2 numeric preview does not meet this generally |
| 64-node validated result within 250 ms after quiet | Mixed; several V1/V2.2 cases exceed it |
| Progressive p95 <=12 ms, max <20 ms | Fail on nearly every current live fixture |
| Two-Fiber skeleton update below 200 ms | Not applicable to the current one-Fiber skeleton file; one cold V2.2 Fiber is 697.30 ms including capture |
| 24-Fiber first synchronization below 1 second | Fail cold; V2.2 warm is 934.94 ms but cold capture+solve is 1,798.49 ms |
| 24-Fiber stretch target below 500 ms | Fail |
| 512-node solve below 220 ms | Not requalified by V2.2; prior collision-bound result failed |
| At least 90% feasible production Fibers converge | Fail; one of 12 valid skull outputs converges |
| Existing-Fiber migration | Fail; only 12 of 24 skull Fibers produce V2.2 output |
| Product runtime integration | Missing |

## Required next work, in order

1. **Compatibility before more speed work.** Diagnose and provide an authored
   repair flow for the six `SCP_3:2` pin conflicts. Correct exact-count handoff
   for FIBER_11, FIBER_12, and FIBER_24 without weakening independent safety.
2. **Persistent hierarchy integration.** Capture/deform one SCP BLAS, refit
   descendant transforms, and share one generation-keyed collision world across
   all affected Fibers. Do not recapture arrays per Fiber.
3. **Replace synchronous all-Fiber shortcut solving.** Schedule selected/visible
   previews first and process affected Fibers round-robin. The current 1.83-second
   synchronous Fiber driver is the main live freeze.
4. **Repair the fixed-point/contact map.** Current valid outputs mostly stop at
   zero CCD movement. CCD is detecting the blockage; it is not generating the bad
   direction. Contact-aware global directions must improve before acceleration.
5. **Human visual qualification.** Specifically review FIBER_4 ripple,
   Skeleton/FIBER_1 angularity, FIBER_9 length, and FIBER_14 preview/final motion.
6. **Only then integrate V2.2.** Add a real event-to-commit benchmark including
   debounce, capture, solver slices, commit, Muscle/mirror propagation, stale
   rejection, and cancellation. The isolated harness must not be called a full
   product cycle again.

## Verification and artifacts

- Fresh V2.2 per-Fiber records: `artifacts/fiber_v22_audit/*.json`.
- Shared batch records: `artifacts/fiber_v22_audit/*_batch.json`.
- Shortcut telemetry: `artifacts/fiber_v22_audit/shortcut_cranium_lobe_width.json`.
- Existing visual review: `artifacts/fiber_v22/*.png` and adjacent review
  `.blend` files.
- Unit suite: 463 passed, six standalone-native skips, one known expected
  warm/cold failure.
- Function-size ratchet: pass, 21 unchanged legacy violations.
- Source blend hashes: unchanged after qualification.

Python's `perf_counter` is the monotonic high-resolution timing source used by
the probes ([Python documentation](https://docs.python.org/3/library/time.html#time.perf_counter)).
Blender evaluated geometry is dependency-graph state and can differ from source
IDs; capture therefore uses the evaluated dependency graph
([Blender ID evaluated access](https://docs.blender.org/api/5.0/bpy.types.ID.html)).

## V2.3 cold-start follow-up

The V2.3 experiment removes duplicate collision-world/topology construction and
adds array capture without changing V2.2 geometry. Across eight production
fixtures it reduced mean capture+cold time from 419.27 ms to 247.60 ms (40.94%),
with maximum V2.2/V2.3 point delta `0.0`. It does not repair the convergence or
compatibility failures above. See [`fiber_v23.md`](fiber_v23.md).

## V2.4 C++ cold-preparation follow-up

V2.4 adds one array-backed C++ batch boundary for collider validation,
open/closed topology classification, transforms, and native-world construction.
It preserves V2.3 points exactly. The eight-fixture mean capture+cold time drops
from 322.10 ms for tuple V2.3 to 175.60 ms for array-backed V2.3 and 143.44 ms
for V2.4. The additional C++ contribution over the array ablation is 18.31%.
Warm time changes only 1.72%, and convergence/compatibility remain unchanged.
See [`fiber_v24_cpp_experiment.md`](fiber_v24_cpp_experiment.md).
