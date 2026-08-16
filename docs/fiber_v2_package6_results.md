# Fiber V2 Package 6 Experiment Results

## Decision

Package 6 is a useful collision experiment, but it is **not a general upgrade to
Package 5.1 and must not be connected to runtime**.

The conservative distance certificates work: on the dense skeleton fixture they
reduce exact interval-CCD tests from 11,405 to 123 and lower median time from
323.90 ms to 229.94 ms. The same trust-step policy performs too many contact and
candidate rebuilds on simpler Fibers, however, making five of seven fixtures
40–91% slower than Package 5.1. Only the clear Direct fixture converges. Package
6 therefore passes its collision-filtering hypothesis and fails its general
latency and convergence gates.

## Isolation and implementation

- Entry point: `solve_package6(...)` in `core/vcp/v2/solver_p6.py`.
- V1, Package 5, Package 5.1, saved Fibers and runtime publication are unchanged.
- The Package 4.3 planner reference and exact authored pins remain fixed.
- Package 5.1 contact-space projection is bounded by an adaptive world-space
  trust radius.
- Each trial uses one linear native CCD path instead of four unconditional
  curved waypoint sweeps.
- A solve-local exact-distance cache excludes a pair only when its separation
  lower bound exceeds requested clearance plus maximum endpoint motion.
- Accepted motion reduces cached lower bounds conservatively; final validation
  never trusts a motion certificate.

## Fixture qualification

Every benchmark Fiber passed the Package 4.3 anchor preflight before timing.
Fibers with an authored endpoint/touch intersecting an unrelated collider, an
invalid exact-count handoff, or cyclic topology were excluded.

| File / Fiber | Branch | Anchors | Nodes | Segment collision | Preflight |
|---|---:|---:|---:|---:|---:|
| `skull_muscles/FIBER_4` | ROADMAP | 9 | 64 | off | eligible |
| `skull_muscles/FIBER_9` | ROADMAP | 3 | 64 | off | eligible |
| `skull_muscles/FIBER_13` | DIRECT | 2 | 64 | off | eligible |
| `skull_muscles/FIBER_14` | ROADMAP | 2 | 64 | off | eligible |
| `skull_muscles/FIBER_22` | SURFACE | 4 | 64 | off | eligible |
| `skull_muscles_skin/FIBER_1` | SURFACE | 4 | 64 | off | eligible |
| `skeleton_comb_base/FIBER_1` | ROADMAP | 2 | 64 | on | eligible |

Notable exclusions in the skull file were Fibers 5, 6, 7, 8, 20 and 21, whose
authored pins intersect `SCP_3:2`, and Fibers 11, 12 and 24, whose exact-count
handoff is invalid. The current skeleton file contains only one authored Fiber,
so a nonexistent second Fiber was not reported as data.

## Benchmark protocol

- Blender 5.0.1, Windows x64, current workstation.
- One read-only Blender process per fixture.
- One equal warm-up for V1, Package 5.1 and Package 6.
- Seven repetitions in deterministic randomized order (`seed=6006`).
- One immutable request, collider snapshot, node count and route policy per
  comparison.
- All timings below are medians; p95 and raw traces remain in the JSON artifacts.

## End-to-end results

| Fixture | V1 ms | P5.1 ms | P6 ms | P6 vs P5.1 | P5.1 exact CCD | P6 exact CCD | P6 state |
|---|---:|---:|---:|---:|---:|---:|---|
| skeleton F1 | 82.43 | 323.90 | 229.94 | **-29.0%** | 11,405 | 123 | BUDGET_EXHAUSTED |
| skull F13 | 138.91 | 32.11 | 30.27 | **-5.7%** | 61 | 0 | CONVERGED |
| skull F14 | 108.46 | 98.99 | 138.67 | +40.1% | 1,717 | 499 | BUDGET_EXHAUSTED |
| skull F22 | 126.64 | 31.28 | 59.58 | +90.5% | 359 | 187 | BLOCKED |
| skull F4 | 38.56 | 141.09 | 269.63 | +91.1% | 2,076 | 192 | BLOCKED |
| skull F9 | 41.07 | 141.27 | 224.74 | +59.1% | 1,984 | 762 | BUDGET_EXHAUSTED |
| skull-skin F1 | 96.88 | 88.62 | 142.35 | +60.6% | 472 | 502 | BLOCKED |

V1 is still fastest on four fixtures, but V1 and V2 do not optimize the same
objective and their shape quality differs. Timing alone is not a rollout gate.

## Package 6 phase attribution

| Fixture | Planner | Candidate/contact | CCD | Final validation | Trials | Certificate exclusions |
|---|---:|---:|---:|---:|---:|---:|
| skeleton F1 | 45.54 | 48.96 | 119.14 | 6.12 | 12 | 4,804 |
| skull F13 | 21.98 | 3.26 | 2.99 | 2.95 | 1 | 61 |
| skull F14 | 21.01 | 41.06 | 57.03 | 2.87 | 12 | 1,240 |
| skull F22 | 9.30 | 4.89 | 37.23 | 3.46 | 8 | 956 |
| skull F4 | 50.34 | 146.57 | 56.25 | 3.17 | 12 | 1,454 |
| skull F9 | 33.29 | 141.87 | 58.53 | 3.01 | 12 | 895 |
| skull-skin F1 | 55.92 | 16.55 | 59.03 | 2.94 | 11 | 1,239 |

The skeleton case confirms that certificate filtering targets the intended
bottleneck. Its remaining 119 ms CCD time comes from only 123 ambiguous pairs
but 98,220 native interval subdivisions: a few near-grazing pairs are expensive.
On skull F4/F9, CCD is no longer dominant; repeated contact/candidate
construction across 12 trust trials is the regression.

## Correctness and visual assessment

- All seven Package 6 outputs pass the independent static node and edge
  clearance validator.
- Maximum authored-pin error is exactly `0.0` for all seven outputs.
- Seven repeated runs are deterministic for every fixture.
- Package 6 and Package 5.1 are bit-identical on skull F13 and visually/numerically
  equivalent on skull F22 and skull-skin F1.
- Skull F14 differs by at most 0.02876 world units and 0.52% path length.
- Skull F4 differs by 0.07855 world units and 3.77% path length.
- Skeleton F1 preserves the planner's rib-cage homotopy, but differs from P5.1 by
  up to 0.21530 world units and is 4.72% longer. This remains a human anatomical
  review item, not an automatically accepted improvement.
- Only skull F13 satisfies convergence. A valid curve is not being mislabeled
  converged in the other six cases.

## Gates

| Gate | Result |
|---|---|
| P6 outputs independently valid | PASS, 7/7 |
| Exact authored pins | PASS, 7/7 |
| Deterministic repeated output | PASS, 7/7 |
| Skeleton exact CCD tests <= 2,851 | PASS, 123 |
| Skeleton CCD < 100 ms | FAIL, 119.14 ms |
| Skeleton total < 200 ms | FAIL, 229.94 ms |
| Skull regression <= 10% | FAIL, five fixtures |
| Production convergence | FAIL, 1/7 |
| Runtime rollout | NOT ATTEMPTED / remains isolated |

## Verification

- Unit suite: 406 passed, 6 skipped, 1 pre-existing expected failure.
- Focused V2 collision/solver suite: 46 passed.
- Function-size/architecture guardrail: 7 passed; no new function exceeds 15
  lines.
- Canonical Blender suite: 473 tests passed and one existing Quick Fiber
  persistence test failed because `af_fiber_points_world` was absent after its
  asynchronous refinement. The same test fails in isolation, and Package 6 does
  not touch Quick Fiber/runtime code. Package 0 was explicitly skipped, so this
  baseline defect was recorded rather than changed here.
- Source `.blend` files were opened read-only and retained these hashes:
  - `skull_muscles.blend`: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
  - `skull_muscles_skin.blend`: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`
  - `skeleton_comb_base.blend`: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`

## Recommendation

Keep the distance-certificate concept for a future native fused implementation,
but do not keep the current Package 6 trust loop as the universal base map.
The next experiment should be conditional and evidence-driven:

1. use the normal Package 5.1 full step on clear/contact-light cases;
2. activate trust/contact-space stepping only after a materially limited CCD
   fraction or dense pair threshold;
3. preserve certificate state in the native collision world so Python does not
   rebuild exact-distance rows;
4. add a near-grazing native feature cache to reduce the skeleton's 98,220
   interval subdivisions;
5. implement adaptive progress/convergence only after this hybrid map is proven
   to preserve the same fixed point.

Package 6 demonstrates a valuable local optimization, not a rollout candidate.
