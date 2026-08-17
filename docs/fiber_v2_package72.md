# Fiber V2 Package 7.2 Experiment

## Decision

**Reject Package 7.2 as a production candidate.** It removes Package 7.1's
fixed-planner arch regression and reports failures more truthfully, but it does
not improve convergence or performance.

The implementation remains isolated from runtime recompute, publication,
migration, and saved Fiber data.

## Experiment implemented

Package 7.2 is a deterministic two-phase solver:

1. Spend at most one-third of the authored accepted-step cap, limited to four
   steps, on P5.1 proximal shape acquisition.
2. Freeze the resulting collision-safe curve as the structural fidelity
   reference `q`.
3. Spend the remaining accepted-step budget on the Package 7 fixed objective.
4. Compare achieved versus predicted merit reduction.
5. On a rejected fast step, activate bounded trust recovery.
6. Shrink below ratio `0.25`, accept from `0.10`, and grow above `0.75` when a
   boundary-limited full step agrees with the model.
7. Terminate repeated zero CCD steps as `BLOCKED`, repeated non-descent or poor
   minimum-trust agreement as `STALLED`, and continuing accepted progress at the
   cap as `BUDGET_EXHAUSTED`.

Acquisition and refinement share the original accepted-step cap. Rejected steps
do not consume that cap, but total trials are bounded. Every returned curve is
checked by the independent static validator.

This follows the achieved/predicted reduction mechanism described by
[Conn, Gould, and Toint](https://books.google.com/books/about/Trust_Region_Methods.html?id=5kNC4fqssYQC).
The fixed objective retains the local/global structure of
[Projective Dynamics](https://www.projectivedynamics.org/projectivedynamics.pdf).

## Benchmark method

- Blender 5.0.1 on the current Windows workstation.
- Fresh Blender process for each Fiber.
- One warm-up and seven randomized repetitions per V1/P5.1/P6.1/P7.2 solver.
- Total P7.2 time includes planner, shape acquisition, fixed refinement, contact
  queries, CCD, and independent final validation.
- The same immutable request and collider snapshot are shared inside a fixture.
- Source `.blend` files are opened read-only.

## Performance

Median wall times in milliseconds:

| Fixture | V1 | P5.1 | P6.1 | P7.2 | P7.2 vs P6.1 | Termination |
|---|---:|---:|---:|---:|---:|---|
| Skull / FIBER_4 | 41.28 | 146.51 | 153.46 | 281.97 | +83.7% | `STALLED` |
| Skull / FIBER_9 | 45.13 | 150.26 | 151.15 | 259.10 | +71.4% | `STALLED` |
| Skull / FIBER_13 | 125.49 | 23.77 | 25.99 | 29.94 | +15.2% | `CONVERGED` |
| Skull / FIBER_14 | 101.24 | 95.30 | 93.83 | 106.31 | +13.3% | `STALLED` |
| Skull / FIBER_22 | 123.69 | 34.25 | 32.44 | 72.19 | +122.6% | `STALLED` |
| Skull-skin / FIBER_1 | 88.06 | 73.23 | 78.48 | 127.65 | +62.6% | `STALLED` |
| Skeleton / FIBER_1 | 80.07 | 319.72 | 224.06 | 390.47 | +74.3% | `BUDGET_EXHAUSTED` |

P7.2 is slower than P6.1 on all seven Fibers. Only the clear Skull/FIBER_13
converges. Adaptive recovery does not improve the `1/7` convergence rate.

## Solver result truth

| Fixture | Acquired steps | Total accepted/rejected | Fixed trials | Stationarity | Validated |
|---|---:|---:|---:|---:|---|
| Skull / FIBER_4 | 3 | 7 / 6 | 9 | 6.8848 | yes |
| Skull / FIBER_9 | 4 | 9 / 5 | 10 | 1.0493 | yes |
| Skull / FIBER_13 | 1 | 1 / 0 | 1 | 1.81e-12 | yes |
| Skull / FIBER_14 | 4 | 4 / 5 | 5 | 0.000428 | yes |
| Skull / FIBER_22 | 2 | 2 / 6 | 5 | 40.1291 | yes |
| Skull-skin / FIBER_1 | 2 | 2 / 6 | 5 | 21.1032 | yes |
| Skeleton / FIBER_1 | 4 | 12 / 1 | 9 | 44.4987 | yes |

The controller correctly distinguishes the cases:

- FIBER_14 preserves the exact P5.1/P6.1 shape, then reports `STALLED` because
  every contact-projected fixed proposal is structural non-descent.
- FIBER_22 and skull-skin FIBER_1 reach the minimum trust radius with achieved
  ratios below `0.0006`; further retries repeat the same state.
- Skeleton/FIBER_1 recovers from a first ratio of `0.03` and accepts eight fixed
  steps, but remains far from stationarity when the shared cap is exhausted.

## Phase evidence

Phase counters overlap when a higher-level phase invokes collision work and
must not be summed as independent totals.

| Fixture | Planner | Acquisition | Fixed model | Contact | CCD | Validation |
|---|---:|---:|---:|---:|---:|---:|
| Skull / FIBER_4 | 62.05 | 84.29 | 93.05 | 31.65 | 104.74 | 4.34 |
| Skull / FIBER_9 | 31.23 | 66.19 | 95.90 | 28.45 | 80.50 | 2.77 |
| Skull / FIBER_13 | 16.19 | 4.64 | 2.26 | 3.19 | 2.50 | 2.22 |
| Skull / FIBER_14 | 20.86 | 52.24 | 15.84 | 16.88 | 52.51 | 2.28 |
| Skull / FIBER_22 | 9.78 | 17.53 | 13.64 | 10.78 | 39.56 | 4.48 |
| Skull-skin / FIBER_1 | 66.99 | 19.81 | 19.89 | 11.98 | 39.82 | 2.76 |
| Skeleton / FIBER_1 | 39.07 | 163.60 | 44.86 | 40.46 | 270.35 | 6.42 |

Shape acquisition duplicates a material portion of P5.1 collision work. Fixed
refinement then repeats model/contact/CCD work without producing a consistent
descent direction. The controller overhead itself is negligible; it exposes the
model mismatch rather than causing it.

## Visual qualification

Each image contains V1, Package 4.3, Package 5.1, Package 6.1, and Package 7.2.
Every PNG also has an editable `.blend` preview beside it.

- `artifacts/fiber_v2_package72/preview_skull_fiber4.png`
- `artifacts/fiber_v2_package72/preview_skull_fiber9.png`
- `artifacts/fiber_v2_package72/preview_skull_fiber13.png`
- `artifacts/fiber_v2_package72/preview_skull_fiber14.png`
- `artifacts/fiber_v2_package72/preview_skull_fiber22.png`
- `artifacts/fiber_v2_package72/preview_skull_skin_fiber1.png`
- `artifacts/fiber_v2_package72/preview_skeleton_fiber1.png`

P7.2 matches P5.1 exactly on FIBER_13, FIBER_14, FIBER_22, and skull-skin
FIBER_1. It differs by at most `0.02173` world units on Skull/FIBER_4,
`0.01182` on Skull/FIBER_9, and `0.03138` on Skeleton/FIBER_1. The FIBER_14
high-arch regression from P7.1 is eliminated.

## Root cause and next step

Package 7.2 demonstrates that the controller is not the missing component. The
fixed structural solve is followed by a heuristic metric contact projection.
That projection is not produced by minimizing the same fixed structural/contact
merit, so it can point uphill or predict a reduction that CCD cannot realize.
Shrinking the trust radius then repeats a smaller version of the same
inconsistent direction.

The next solver experiment must implement the originally specified fixed
contact slots inside the banded global system:

1. Preallocate node and edge contact operators.
2. Update only projected contact targets in the local step.
3. Include the fixed contact diagonal and right-hand side in the global solve.
4. Compute predicted and achieved reduction from that same augmented energy.
5. Reuse P7.2's ratio controller only after the map produces descent.

Do not attempt Package 7.3, Anderson acceleration, adaptive levels, or larger
iteration caps before that contact/global coherence gate passes.

## Verification

- Full unit suite: `421` passed, `6` skipped, `1` expected failure.
- Focused P7.2/P7.1/P6/P5 tests plus collision and architecture: `68` passed.
- Function-size guard passed; all new and modified functions are at most 15
  lines.
- All seven P7.2 outputs passed independent static validation.
- P7.2 outputs are deterministic in repeated tests and benchmarks.
- `git diff --check` passed with only line-ending conversion warnings.
- Source hashes remained unchanged:
  - Skull: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
  - Skull-skin: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`
  - Skeleton: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`
