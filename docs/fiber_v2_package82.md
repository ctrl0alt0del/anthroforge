# Fiber V2 Package 8.2 — Unilateral Active Contact Experiment

## Decision

**Reject Package 8.2 as a production solver, retain the experiment and its numerical core.**

The experiment proves that unilateral constraints can remove the immediate quadratic-penalty/CCD deadlock. Five difficult production Fibers accepted all 12 interactive steps with a final CCD fraction of `1.0`, while Package 8.1 stopped at zero. However, Package 8.2 is too slow, five cases still exhaust the accepted-step cap, one nonconvex case creates an infeasible set of linearized half-spaces, and the visual results preserve several planner-shaped kinks or overly broad arcs.

No production runtime, migration, or default-selection path uses Package 8.2.

## Formulation

For the fixed structural objective, hard pins are eliminated and each sampled contact is represented by a unilateral linearized constraint:

`J_i x >= d_i`

The constrained minimizer is computed in the existing structural metric. For an active set `A`:

`x = x_u + H^-1 J_A^T lambda`

`(J_A H^-1 J_A^T) lambda = d_A - J_A x_u`, with `lambda >= 0`.

The implementation uses the existing O(N) pentadiagonal/Woodbury factor to apply `H^-1`, a deterministic primal active-set loop, exact hard-pin elimination, warm active-set hints, and CCD-limited acceptance. It does not assemble a dense Fiber matrix. A small dense Schur system is solved only over active contact constraints.

This is consistent with the feasibility-first direction in [Incremental Potential Contact](https://ipc-sim.github.io/file/IPC-paper-fullRes.pdf) and the active-contact/local-global combination in [Efficient IPC with Projective Dynamics](https://cgl.ethz.ch/Downloads/Publications/Papers/2023/Yan23b/Yan23b.pdf). Package 8.2 is deliberately narrower: it tests linearized unilateral constraints without adopting IPC's nonlinear barrier objective.

## Correctness evidence

- Single-node and edge-sample constraints match independent dense KKT references.
- Redundant inequalities keep only the binding plane.
- Pin-only infeasible constraints fail explicitly.
- Hard pins remain exact.
- Warm active-set hints remain deterministic when constraints are appended.
- All seven Package 8.2 production outputs pass the independent static node/edge validator.
- Function-size ratchet passes; every new or modified function is at most 15 lines.

## Real-file benchmark

Blender 5.0.1, current Windows workstation, three measured repeats after one warm-up. Times are medians in milliseconds. Benchmark files were opened read-only.

| Fixture | V1 | P5.1 | P6.1 | P8.1 | P8.2 | P8.2 termination |
|---|---:|---:|---:|---:|---:|---|
| skull / FIBER_4 | 70.99 | 272.84 | 269.23 | 188.41 | 1102.70 | BUDGET_EXHAUSTED |
| skull / FIBER_9 | 55.99 | 249.03 | 254.38 | 138.74 | 735.17 | BUDGET_EXHAUSTED |
| skull / FIBER_13 | 237.02 | 54.19 | 56.08 | 57.62 | 82.76 | CONVERGED |
| skull / FIBER_14 | 191.84 | 191.34 | 186.02 | 148.94 | 544.48 | BUDGET_EXHAUSTED |
| skull / FIBER_22 | 180.41 | 48.35 | 47.69 | 89.15 | 495.52 | BUDGET_EXHAUSTED |
| skull-skin / FIBER_1 | 104.81 | 111.13 | 114.27 | 159.39 | 233.53 | BLOCKED |
| skeleton / FIBER_1 | 121.80 | 506.41 | 343.89 | 173.40 | 949.70 | BUDGET_EXHAUSTED |

Package 8.2 is slower than Package 8.1 on every fixture. The overhead is not one dense Fiber factorization; it comes from repeated nonlinear contact discovery, active-set Schur work, and twelve conservative accepted steps.

## Package 8.2 phase breakdown

Times below are from the final recorded run and can differ slightly from the outer median.

| Fixture | Planner | Contact query | Active QP | CCD | Final validation | Trials |
|---|---:|---:|---:|---:|---:|---:|
| skull / FIBER_4 | 99.80 | 336.73 | 350.80 | 141.71 | 6.11 | 12 |
| skull / FIBER_9 | 46.94 | 286.28 | 216.22 | 69.84 | 4.76 | 12 |
| skull / FIBER_13 | 31.49 | 24.79 | 1.91 | 7.69 | 7.41 | 1 |
| skull / FIBER_14 | 39.73 | 297.92 | 80.36 | 93.64 | 6.25 | 12 |
| skull / FIBER_22 | 15.09 | 276.61 | 53.66 | 90.28 | 4.50 | 12 |
| skull-skin / FIBER_1 | 66.40 | 32.21 | 104.93 | 7.63 | 3.71 | 1 |
| skeleton / FIBER_1 | 55.70 | 469.35 | 192.32 | 181.75 | 9.08 | 12 |

The warm active-set hint reduced FIBER_4's experimental active-QP phase from roughly 1.45 seconds to 0.35 seconds, but end-to-end latency still misses the live-edit targets.

## What improved

- P8.1 ended with a zero CCD fraction on FIBER_4, FIBER_9, FIBER_14, FIBER_22, and skeleton/FIBER_1.
- P8.2 accepted 12 safe steps and ended with CCD fraction `1.0` on all five.
- FIBER_22 becomes visibly smoother than the piecewise P8.1 route.
- Skeleton/FIBER_1 rounds the lower planner corner while remaining independently valid.
- The no-contact FIBER_13 remains deterministic, cap-invariant, and converged.

## What did not improve

- The active half-spaces are local approximations to nonlinear, nonconvex collision geometry.
- Accumulating those planes can become over-conservative. Skull-skin/FIBER_1 reports a linearized primal residual of about `4.86e-4` even though its retained geometric output is independently safe.
- A fixed `0.5 * collision_radius` contact trust limit prevents tunneling but consumes the 12-step interactive budget on five fixtures.
- FIBER_4 and FIBER_9 retain conspicuous planner-shaped bends.
- FIBER_14 remains a broad external arc rather than the desired tighter anatomical wrap.
- Skeleton/FIBER_1 remains dominated by its triangular planner corridor.
- Contact queries are repeated for current, structural, and proposed states; this is now the largest phase on four fixtures.

## Artifacts

Each JSON contains exact inputs, output points, diagnostics, traces, timings, and file hash. Each comparison `.blend` is a generated, self-contained inspection scene; it is not the source production file.

- `artifacts/fiber_v2_package82/skull_fiber4.{json,png}` and `skull_fiber4_comparison.blend`
- `artifacts/fiber_v2_package82/skull_fiber9.{json,png}` and `skull_fiber9_comparison.blend`
- `artifacts/fiber_v2_package82/skull_fiber13.{json,png}` and `skull_fiber13_comparison.blend`
- `artifacts/fiber_v2_package82/skull_fiber14.{json,png}` and `skull_fiber14_comparison.blend`
- `artifacts/fiber_v2_package82/skull_fiber22.{json,png}` and `skull_fiber22_comparison.blend`
- `artifacts/fiber_v2_package82/skin_fiber1.{json,png}` and `skin_fiber1_comparison.blend`
- `artifacts/fiber_v2_package82/skeleton_fiber1.{json,png}` and `skeleton_fiber1_comparison.blend`

Recorded hashes:

- `skull_muscles.blend`: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
- `skull_muscles_skin.blend`: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`
- `skeleton_comb_base.blend`: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`

## Recommendation

Do not continue by merely increasing Package 8.2's step cap. That would make the safe progress longer but would not repair planner-shaped references or incompatible local half-spaces.

Retain the reusable numerical result: a warm-started unilateral Schur solve is viable and can replace quadratic penalties once the nonlinear contact model is correct. The next useful design should combine it with a corridor-aware nonlinear contact representation that can retire obsolete planes and take a curved feasible step. It should first prove better anatomy on FIBER_4, FIBER_14, and skeleton/FIBER_1 before further performance tuning.
