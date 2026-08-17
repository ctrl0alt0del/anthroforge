# Fiber V2 Package 7.1 Experiment

## Decision

**Do not promote Package 7.1.** The fixed-reference formulation is now
executable and measurable, but it is neither a general performance improvement
nor a convergence improvement on the production set.

Package 7.1 is kept as an isolated experiment. It is not connected to normal
Fiber recompute, migration, or publication.

## What Package 7.1 changed

Package 5.1 and 6.1 replaced the structural fidelity reference with the current
iterate on every trial. That made fidelity energy zero at the evaluation point
and meant the executable map did not optimize the documented fixed objective.

Package 7.1 instead:

- freezes the exact-count planner corridor as `q` for the complete solve;
- evaluates structural, length, curvature, and fidelity energy against that
  immutable reference;
- runs contact construction before the structural global proposal;
- computes projected fixed-objective stationarity after removing active linear
  contact directions;
- requires both fixed-point and stationarity residuals for convergence;
- retains Package 6.1's dynamic P5.1/P6 collision-policy selection;
- retains native CCD and independent static final validation.

This is deliberately only the fixed-map experiment. Package 7.1 does not add
the adaptive rejection recovery, trust ratio, adaptive levels, or Anderson
acceleration specified for later Package 7 work.

The ordering and fixed merit follow the local/global block-coordinate pattern
in [Projective Dynamics](https://www.projectivedynamics.org/projectivedynamics.pdf).
The later recovery design uses the actual/predicted reduction principle from
[Trust Region Methods](https://epubs.siam.org/doi/10.1137/1.9780898719857), but
that controller is not part of this experiment.

## Method

- Blender 5.0.1, Windows x64, current workstation.
- Fresh Blender process per Fiber.
- One warm-up plus seven randomized repetitions per V1/P5.1/P6.1/P7.1 solver.
- Identical immutable captured request and collision snapshot within a fixture.
- Exact pins, native CCD, and independent static validation retained.
- Source blend files opened read-only and remained byte-identical.

Source hashes:

| File | SHA-256 |
|---|---|
| `skull_muscles.blend` | `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06` |
| `skull_muscles_skin.blend` | `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96` |
| `skeleton_comb_base.blend` | `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42` |

## Repeated benchmark

Times are medians in milliseconds. The delta is Package 7.1 relative to the
current Package 6.1 dispatcher. A negative delta is faster.

| Fixture | V1 | P5.1 | P6.1 | P7.1 | P7.1 vs P6.1 | P7.1 termination |
|---|---:|---:|---:|---:|---:|---|
| Skull / FIBER_4 | 50.98 | 168.12 | 180.14 | 199.43 | +10.7% | `BLOCKED` |
| Skull / FIBER_9 | 46.38 | 171.86 | 171.79 | 115.81 | -32.6% | `BLOCKED` |
| Skull / FIBER_13 | 132.70 | 29.02 | 28.66 | 30.24 | +5.5% | `CONVERGED` |
| Skull / FIBER_14 | 120.51 | 108.11 | 108.65 | 79.13 | -27.2% | `BLOCKED` |
| Skull / FIBER_22 | 142.29 | 36.50 | 36.62 | 121.00 | +230.4% | `BUDGET_EXHAUSTED` |
| Skull-skin / FIBER_1 | 104.13 | 92.89 | 90.55 | 194.38 | +114.7% | `BUDGET_EXHAUSTED` |
| Skeleton / FIBER_1 | 91.94 | 365.52 | 244.05 | 230.85 | -5.4% | `BUDGET_EXHAUSTED` |

Package 7.1 is faster than Package 6.1 on three of seven Fibers and slower on
four. The geometric mean is not useful here because only one result converged.
The apparent wins on FIBER_9 and FIBER_14 are early `BLOCKED` terminations, not
successful convergence wins.

## Convergence truth

| Fixture | Accepted/rejected | Fixed residual | Stationarity residual | Validated |
|---|---:|---:|---:|---|
| Skull / FIBER_4 | 3 / 2 | 0.007864 | 17.9674 | yes |
| Skull / FIBER_9 | 2 / 2 | 0.004769 | 20.2436 | yes |
| Skull / FIBER_13 | 1 / 0 | 3.29e-13 | 1.67e-12 | yes |
| Skull / FIBER_14 | 2 / 1 | 0.000685 | 0.004716 | yes |
| Skull / FIBER_22 | 2 / 10 | 0.002672 | 40.2669 | yes |
| Skull-skin / FIBER_1 | 2 / 10 | 0.003679 | 20.9653 | yes |
| Skeleton / FIBER_1 | 12 / 0 | 0.003413 | 5.5618 | yes |

All returned P7.1 paths pass the independent static validator. That is a safety
result, not a convergence result. Six of seven fail the P7.1 convergence gate.

The skeleton result is particularly informative: all 12 trials are accepted,
merit drops from `332.80` to `62.72`, but normalized stationarity remains
`5.56`. It is progressing, but the authored cap is insufficient and its fixed
planner attraction produces a visibly different trajectory.

## Where Package 7.1 spends time

The phase counters overlap where a higher-level phase calls contact or CCD, so
they must not be summed as independent totals.

| Fixture | Planner | Model | Contact queries | CCD | Final validation |
|---|---:|---:|---:|---:|---:|
| Skull / FIBER_4 | 63.53 | 39.47 | 14.05 | 97.79 | 5.69 |
| Skull / FIBER_9 | 36.69 | 40.13 | 8.92 | 35.43 | 3.47 |
| Skull / FIBER_13 | 19.32 | 2.82 | 2.27 | 3.46 | 2.98 |
| Skull / FIBER_14 | 23.22 | 10.46 | 6.78 | 40.22 | 3.07 |
| Skull / FIBER_22 | 14.47 | 38.94 | 31.08 | 62.38 | 4.49 |
| Skull-skin / FIBER_1 | 58.74 | 55.98 | 34.08 | 72.99 | 3.67 |
| Skeleton / FIBER_1 | 47.33 | 46.19 | 34.96 | 123.63 | 5.32 |

Fixing the objective does not remove the established collision bottleneck.
When the fixed map needs more trials, repeated model/contact/CCD work makes it
substantially slower. When it rejects early, the lower time is misleading.

## Visual result

The generated five-panel images compare V1, Package 4.3, Package 5.1, Package
6.1, and Package 7.1 using the same camera and collider geometry. Editable
`.blend` previews accompany every PNG.

- `artifacts/fiber_v2_package71/preview_skull_fiber4.png`
- `artifacts/fiber_v2_package71/preview_skull_fiber9.png`
- `artifacts/fiber_v2_package71/preview_skull_fiber13.png`
- `artifacts/fiber_v2_package71/preview_skull_fiber14.png`
- `artifacts/fiber_v2_package71/preview_skull_fiber22.png`
- `artifacts/fiber_v2_package71/preview_skull_skin_fiber1.png`
- `artifacts/fiber_v2_package71/preview_skeleton_fiber1.png`

The main visible regression is Skull/FIBER_14: P7.1 bows toward the immutable
planner corridor instead of retaining the tighter Package 5.1/6.1 wrap. The
skeleton result is smooth and safe, but also visibly changes the trajectory and
is not stationary at the step cap.

## Interpretation

The experiment proves two separate things:

1. The fixed objective is deterministic and internally coherent on a clear
   Fiber. A clear route reaches the direct banded solution in one step and is
   invariant to a higher accepted-step cap.
2. The raw planner polyline is not a suitable universal anatomical fidelity
   target. Freezing it gives a mathematically defined answer, but that answer
   can prefer an anatomically loose arch. Collision contacts also make the
   fixed map require many expensive repeated CCD trials.

Therefore Package 7.1 should not replace Package 6.1. The useful pieces to keep
are the fixed-reference diagnostics, real stationarity measurement, cap
invariance tests, and explicit evidence that early `BLOCKED` is not a speedup.

## Required redesign before another Package 7 experiment

Do not proceed by merely increasing iterations or adding Anderson acceleration.
Acceleration would converge faster to the same sometimes undesirable target.

The next experiment must first define a better immutable anatomical corridor
reference, for example a corridor-constrained closest path or a reference made
from the accepted Package 5.1 shape and then frozen. It must then add the
ratio-based rejection recovery from the Package 7 design so one rejected merit
trial does not terminate as `BLOCKED`. Only after shape parity and base-map
convergence pass should adaptive levels or Anderson acceleration be measured.

## Verification

- Full unit suite: `416` passed, `6` skipped, `1` expected failure.
- Focused P7.1/collision/architecture suite: `63` passed.
- Function-size guard: passed; all new and modified functions are at most 15
  lines.
- All seven production P7.1 outputs passed independent static validation.
- Repeated runs report deterministic P7.1 output.
- `git diff --check`: passed, with only line-ending conversion warnings.

