# Fiber V2.1 — Hybrid Reuse and Conditional Collision Experiment

## Decision

V2.1 is a successful isolated performance experiment, but it is not ready for
runtime rollout.

- It preserves the accepted P6.1 baseline output exactly on all eight real
  fixtures and every result passes the independent native static validator.
- Aggregate warm complete-solve time is 38.42% lower than P6.1 and 21.48% lower
  than V1.
- Sequential property edits are 31.42% faster than P6.1.
- Sequential small handle edits are 19.17% faster than P6.1.
- Only Skull/FIBER_13 converges. Six cases remain `BLOCKED` and Skeleton/FIBER_1
  remains `BUDGET_EXHAUSTED`; V2.1 improves scheduling and collision cost, not
  the unresolved fixed-point/convergence design.
- Cold request capture and geometry-rich request hashing remain much slower
  than the numeric work. They must be replaced by stable generation/digest
  identities before live integration.

V2.1 therefore becomes the next experimental baseline over P4.3 + P5.1 + P6.1.
It does not enable V2, change saved Fibers, or publish runtime output.

## What V2.1 changes

### Planner work

V2.1 stores at most 128 validated route records. The cache key includes stable
scene/root/source identity, topology, quality, node count, authored owner/role
sequence, collider generations, symmetry, and collision policy.

- An identical request reuses the already validated planner corridor.
- A property-only change reuses the same validated route but reruns the numeric
  solve with the new objective weights.
- A small open-Fiber anchor edit warps the old corridor piecewise between hard
  pins, restores exact pins, rebuilds authored owner contacts, and runs the full
  independent native static validator. Failure falls back to the complete P4.3
  planner.
- Surface routes are never warped when anchors move; they fall back to complete
  planning because the stored surface path is not a safe deformation corridor.
- Unchanged surface routes may be reused for property edits.
- Direct anchor segments are preflighted with the accepted eight-radius owner
  policy. Only a proven direct case skips graph/A* construction.
- Roadmap cases retain P5.1's second eight-radius planning pass so baseline
  topology and anatomical shape remain unchanged.

This is a conservative form of lazy replanning: expensive graph work is delayed
until direct or cached-corridor validation fails. It follows the validated-edge
principle of [LazySP](https://arxiv.org/abs/1603.03490); route reuse never counts
as collision proof by itself.

### Collision acceptance

P6.1's dynamic dense-workload dispatcher remains unchanged. On its light P5.1
path, V2.1 only changes sparse contact states:

1. Surface routes and contact sets above four active nodes use the accepted
   P5.1 curved feasible-step path unchanged.
2. A sparse contact state first runs one native linear CCD probe.
3. A full safe step is accepted directly.
4. A clipped, uncertain, or blocked result immediately falls back to the P5.1
   curved waypoint recovery.
5. Final output still passes the independent native static validator.

The optimization does not replace conservative CCD with endpoint sampling. It
avoids curved-waypoint construction only after the same native CCD authority
proves the linear movement safe. The fail-closed design follows the principles
benchmarked in [A Large Scale Benchmark and an Inclusion-Based Algorithm for
Continuous Collision Detection](https://arxiv.org/abs/2112.06300).

## Real-Blender protocol

- Blender 5.0.1, Windows workstation.
- Fresh Blender background process per fixture.
- Five timed warm repetitions for V1, P6.1, and V2.1.
- Same immutable V2 request and native triangle snapshot for P6.1 and V2.1.
- Cache-cleared V2.1 first call recorded separately.
- Five sequential curvature-weight edits and five sequential small handle
  movements of 0.1–0.5 collision radius.
- Every V2.1 result independently checks node and edge clearance.
- Supplied `.blend` files are opened read-only and their hashes recorded.

Source hashes:

| File | SHA-256 |
|---|---|
| `skull_muscles.blend` | `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06` |
| `skull_muscles_skin.blend` | `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96` |
| `skeleton_comb_base.blend` | `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42` |

## Warm baseline benchmark

Complete solve plus strict final validation, median milliseconds:

| Fixture | V1 | P6.1 | V2.1 | V2.1 vs P6.1 | Result |
|---|---:|---:|---:|---:|---|
| Skeleton/FIBER_1 | 73.41 | 192.56 | 162.83 | -15.4% | budget exhausted |
| Skull/FIBER_1 | 36.74 | 79.93 | 23.00 | -71.2% | blocked |
| Skull/FIBER_13 | 110.87 | 23.08 | 8.52 | -63.1% | converged |
| Skull/FIBER_14 | 99.08 | 84.90 | 36.23 | -57.3% | blocked |
| Skull/FIBER_22 | 113.84 | 30.45 | 19.65 | -35.5% | blocked |
| Skull/FIBER_4 | 39.22 | 136.76 | 86.00 | -37.1% | blocked |
| Skull/FIBER_9 | 41.91 | 137.02 | 106.85 | -22.0% | blocked |
| Skull-skin/FIBER_1 | 78.60 | 72.21 | 23.05 | -68.1% | blocked |
| **Aggregate** | **593.66** | **756.91** | **466.13** | **-38.42%** | 8/8 valid |

V2.1 is faster than V1 in five of eight cases. Skeleton/FIBER_1,
Skull/FIBER_4, and Skull/FIBER_9 remain slower because their accepted native
collision work is more expensive than V1's weaker collision policy.

## Editing benchmark

Median milliseconds across five sequential edits:

| Fixture | P6.1 property | V2.1 property | P6.1 handle | V2.1 handle |
|---|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 194.98 | 182.41 | 190.94 | 171.11 |
| Skull/FIBER_1 | 77.70 | 31.80 | 76.25 | 75.43 |
| Skull/FIBER_13 | 29.48 | 11.09 | 22.19 | 10.65 |
| Skull/FIBER_14 | 84.41 | 39.42 | 87.47 | 42.01 |
| Skull/FIBER_22 | 29.48 | 18.93 | 37.26 | 42.11 |
| Skull/FIBER_4 | 144.33 | 100.95 | 147.48 | 106.95 |
| Skull/FIBER_9 | 137.00 | 110.43 | 145.48 | 114.90 |
| Skull-skin/FIBER_1 | 69.56 | 30.94 | 75.96 | 69.79 |
| **Aggregate** | **766.93** | **525.97** | **783.03** | **632.96** |
| **Reduction** |  | **31.42%** |  | **19.17%** |

Property edits reused a validated corridor on all eight fixtures. Small handle
edits reused a validated warped corridor on five fixtures. The three surface
cases fell back to full planning as designed. Skull/FIBER_22 is 13.0% slower on
the handle test because V2.1 pays the failed reuse check and then executes two
full surface planning passes; the policy is safe but needs a cheaper early
surface exit.

All handle outputs validate. Seven differ from the fresh P6.1 handle result by
at most `0.00220` world units. Skull/FIBER_14 differs by `0.04020` world units;
the rendered routes remain visually close, but this establishes that validated
corridor repair is not fresh-planner equivalence. It should initially remain an
interactive-preview optimization, followed by a quiet-input fresh final plan.

Property-edit output is point-identical to P6.1 on six fixtures. The two
matching surface FIBER_1 cases differ by `0.01205` world units while remaining
strictly valid. This needs a deterministic surface-path investigation before
route reuse is allowed for committed final output.

## Correctness and visual review

- Baseline P6.1/V2.1 maximum point delta is exactly `0.0` on all eight fixtures.
- All eight baseline, property, and handle V2.1 outputs pass the independent
  native node/edge validator.
- Baseline termination and planner branch match P6.1 in every fixture.
- Baseline renders are visually identical between P6.1 and V2.1.
- Handle renders show the same anatomical side of the obstacles. The largest
  numerical difference, Skull/FIBER_14, is visible as a small corridor-shape
  change rather than an intersection.
- V2.1 does not improve the angular Skeleton/FIBER_1 solution, FIBER_4 contact
  ripple, or the six blocked outcomes. Those are fixed-point/contact-model
  issues outside this scheduling experiment.

## Cold-path blocker

| Fixture | Capture | V2.1 cold solve | Isolated full | Request signature |
|---|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 346.59 | 282.64 | 629.23 | 334.40 |
| Skull/FIBER_1 | 190.45 | 155.59 | 346.04 | 237.02 |
| Skull/FIBER_13 | 193.81 | 68.67 | 262.49 | 251.58 |
| Skull/FIBER_14 | 189.42 | 111.62 | 301.04 | 241.50 |
| Skull/FIBER_22 | 196.91 | 87.32 | 284.23 | 252.83 |
| Skull/FIBER_4 | 204.50 | 221.03 | 425.53 | 239.00 |
| Skull/FIBER_9 | 188.48 | 192.83 | 381.32 | 238.57 |
| Skull-skin/FIBER_1 | 192.75 | 157.08 | 349.83 | 245.33 |

`V2Request.signature()` currently serializes the full 30,544-triangle collider
payload. A property or handle edit therefore spends 237–334 ms hashing geometry
unless the benchmark precomputes the signature outside the timed numeric solve.
This would erase the editing gains in a naive runtime integration.

The required integration fix is not weaker caching. Capture must assign a
stable snapshot ID from scene/root identity plus collider geometry/transform
generations, and each Fiber request must hash that small ID rather than all
vertices and triangles. One SCP request should capture and hash the collider
snapshot once, then share it across every affected Fiber.

## Recommendation

Retain V2.1 as an experiment with these boundaries:

1. Accept exact validated route reuse for provisional and numeric experiments.
2. Accept linear-first CCD with fail-closed curved recovery.
3. Keep P6.1's dense-workload dispatcher unchanged.
4. Limit warped-corridor reuse to interactive previews until quiet-input fresh
   planning confirms the result.
5. Investigate the two surface property-path differences.
6. Replace geometry serialization in request signatures and share persistent
   collider snapshots before any runtime integration.
7. Do not call the remaining blocked/budget-exhausted results complete V2
   convergence.

## Artifacts

`artifacts/fiber_v21/` contains:

- `timing.png` with baseline, property-edit, and handle-edit comparisons;
- eight JSON records with exact points, traces, diagnostics, validation, source
  hashes, and signature timings;
- eight baseline Blender renders and review `.blend` files;
- eight handle-edit Blender renders and review `.blend` files.

Baseline render order is V1, P6.1, V2.1. Handle render order is P6.1, V2.1.
