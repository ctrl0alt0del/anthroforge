# Fiber V2 acceleration and unfinished-solve resume notes

Updated: 2026-08-20

## 2026-08-20 resumed pass outcome

The accelerator hypothesis was tested again after removing the demonstrated
inactive-contact assembly defect. It did **not** solve the unfinished-contact
cases and must remain disabled.

One production-quality numerical correction was retained in native ABI 3:

- the unilateral augmented-Lagrangian block `mu * J^T J` is now assembled only
  when `max(0, lambda - mu * gap) > 0`;
- an inactive clear contact now contributes neither gradient nor Hessian;
- `test_inactive_contact_has_zero_matrix_contribution` compares the DLL result
  against an independent dense reference.

This correction is required by the piecewise inequality AL formula. It reduced
skull/FIBER_1 stationarity and runtime in an intermediate controlled run, but it
does not by itself make the full active-contact iteration converge.

### Corrected-map accelerator matrix

The diagnostic controllers were tested on read-only production fixtures. All
outputs below remained independently collision-valid, but none converged.

| Case | Controller | Warm ms | Termination | Accepted / rejected | AA steps | Fixed residual | Stationarity |
|---|---|---:|---|---:|---:|---:|---:|
| skull/FIBER_1 | BASE | 319 | STALLED | 7 / 14 | 0 | 6.27e-7 | 2.22e-4 |
| skull/FIBER_1 | TRUST | 931 | BUDGET | 60 / 28 | 0 | 1.16e-4 | 4.04e-4 |
| skull/FIBER_1 | TRUST+AA | 868 | BUDGET | 60 / 45 | 1 | 1.16e-4 | 3.50e-4 |
| sphere/FIBER_2 | BASE | 520 | STALLED | 28 / 16 | 0 | 1.0e-2 | 1.70e-2 |
| sphere/FIBER_2 | TRUST | 625 | BUDGET | 60 / 17 | 0 | 8.91e-5 | 2.43e-2 |
| sphere/FIBER_2 | TRUST+AA | 625 | BUDGET | 60 / 17 | 1 | 5.94e-5 | 2.45e-2 |
| skeleton/FIBER_1 | BASE | 245 | STALLED | 2 / 12 | 0 | 1.62e-3 | 2.00e-3 |
| skeleton/FIBER_1 | TRUST | 1341 | STALLED | 43 / 36 | 0 | 2.57e-9 | 2.00e-3 |
| skeleton/FIBER_1 | TRUST+AA | 1684 | STALLED | 42 / 49 | 0 | 7.72e-9 | 2.01e-3 |

A second Anderson signature keyed by coherent collider/routing-span groups was
also tested. It enabled only one accelerated step per real case and did not
improve termination or wall time. That variant was reverted.

### Why acceleration still fails

- Anderson accelerates accepted fixed-point maps; contact-heavy Fibers keep
  changing or rejecting their local active set, so there is little stable
  history to accelerate.
- Adaptive trust converts rejection into many safe microsteps, but fixed-point
  movement can become tiny while KKT stationarity remains unchanged or worsens.
- Increasing accepted caps to 60 or 200 does not resolve this mismatch.
- Repeated CCD limiting pairs show that the finite-penalty contact solve is not
  enforcing the active nonlinear contact cone accurately enough. This is a
  contact subproblem issue, not an iteration-count issue.

### Rejected resumed experiments

The following were measured and then removed from the retained path:

- heuristic and projected-KKT limiter multiplier seeding;
- 256x penalty escalation;
- broad local-owner propagation;
- contact-group Anderson signatures;
- curvature reserve on limiter planes;
- batched predictive limiter injection;
- accepting geometry refresh as active-set stability.

They either increased runtime, worsened stationarity, produced contact churn, or
reintroduced an `INVALID_START`. Do not restore them without a new isolated
test proving the underlying model.

### Updated next algorithmic step

Do not spend more time tuning Anderson or trust factors on the present AL map.
The next solver task should replace the finite-penalty active-contact subproblem
with an exact or high-accuracy primal-dual active-set solve:

1. freeze a small coherent set of limiting contact Jacobians for one outer step;
2. solve structural degrees of freedom and active multipliers together, or use a
   native sparse Schur complement over the existing banded structural factor;
3. enforce nonnegative multipliers and drop constraints with negative duals;
4. use CCD only to discover missing inequalities and certify the accepted step;
5. update the contact geometry after acceptance;
6. apply Anderson only after this base map demonstrates linear, stable residual
   contraction on the real contact-heavy fixtures.

This is closely related to the already-tested exact unilateral active-set code
in `core/vcp/v2/contact_unilateral.py`, but the production version must avoid
Package 8's Python/dense performance costs by implementing the small dual solve
and response assembly natively.

### Verification after cleanup

- focused contact/native/architecture tests: 53/53 passed;
- full unit suite: 546 passed, 6 skipped, 1 expected failure;
- Blender V2 integration/workflow suite: 21/21 passed;
- function-size ratchet passed;
- packaged ABI 3 DLL rebuilt successfully.

## Scope and pause point

This document records the exact state at the user-requested pause. The goal is to
resume work on V2 Fibers that stop before reaching a satisfactory fixed point,
after the production-3 collision core removed invalid-output publication.

No accelerator is enabled by the production facade at this pause point. The
experimental controller switches default to `False`, so normal `solve_v2()`
does not request Anderson acceleration, adaptive trust, or feasible-stall
recovery. Several collision/contact-core changes made while diagnosing the map
do affect the base path and still require acceptance or reversion after broader
qualification.

## Research basis

The acceleration work was based on primary sources:

- Peng et al., *Anderson Acceleration for Geometry Optimization and Physics
  Simulation*: https://arxiv.org/abs/1805.05715
- Walker and Ni, *Anderson Acceleration for Fixed-Point Iterations*:
  https://doi.org/10.1137/10078356X
- Zhang, O'Donoghue, and Boyd, *Globally Convergent Type-I Anderson
  Acceleration*: https://web.stanford.edu/~boyd/papers/anderson_accel.html

The key requirement from these methods applies directly here: acceleration can
only improve a meaningful and repeatable fixed-point map. It cannot repair a
map that repeatedly proposes a geometrically inconsistent contact state.

## Original production-3 stopping evidence

Before this acceleration pass, accepted-cap 60 produced:

| Fixture | Termination | Accepted | Rejected | Fixed residual | Stationarity |
|---|---:|---:|---:|---:|---:|
| skull/FIBER_14 | STALLED | 18 | 14 | 1.56e-6 | 3.51e-5 |
| skull/FIBER_1 | STALLED | 5 | 16 | about 1e-2 | 4.8e-4 |
| skeleton/FIBER_1 | STALLED | 14 | 23 | 7.36e-6 | 2.76e-4 |

Raising the cap alone did not finish these cases.

## Instrumentation added

`core/vcp/v2/contact_core.py` now records:

- fixed-point residual history;
- stationarity history;
- trust-radius history;
- exact feasible-step rejection reasons.

`tools/fiber_v2_production3_benchmark.py` now accepts:

- `--accepted-cap`;
- `--controller BASE|TRUST|ANDERSON|RECOVERY|ALL`.

The controller flags are diagnostic/experimental. Production calls remain BASE.

## Accelerator implementation in the tree

`core/vcp/v2/acceleration.py` contains a safeguarded Type-II Anderson history:

- memory depth 4;
- Tikhonov-regularized least squares;
- coefficient norm cap 10;
- reset when the active-contact signature changes;
- exact pin restoration;
- structural/contact energy safeguard;
- the accelerated proposal still passes through the same CCD and static
  feasibility checks.

Tests were added for a stable affine fixed point, signature reset, and collision
safety from an intersecting DIRECT fixture.

## Important contact-map defects found

### 1. Static and moving owner semantics were inconsistent

The static query exempted the locally attached part of a pin-adjacent owner
edge using a world span. The CCD motion query shortened its parametric exemption
when a proposed edge became longer. A curve that static validation called valid
could therefore be reported `INVALID_START` at CCD time zero.

Observed skull/FIBER_1 rejection before correction:

`INVALID_START:((62, 7135),)`

Face 7135 belongs to `SCP_1:0`, the owner of the final authored pin; edge 62 is
the pin-adjacent chain edge.

Current diagnostic correction in the tree:

- motion fully exempts only the immediately adjacent chain edge(s) for the
  authored owner;
- static/contact owner span is resolved from the exact candidate being tested,
  not the previous accepted points.

After this, skull/FIBER_1 changed from zero accepted steps to 43 accepted steps.
That confirms this was a real blocker, but the exact owner policy still needs a
dedicated regression and real-file visual review before final acceptance.

### 2. CCD limiter was linearized at the wrong state

The limiting pair was measured at the impact position, then inserted into a
solve around the earlier current position with `linearized_gap=0`. The affine
contact plane was therefore located inconsistently.

Current diagnostic correction computes the injected gap at the current iterate
from the impact feature's factor, closest point, and normal.

### 3. Injected limiters became stale

A special `LIMITING` contact and an ordinary `DISTANCE`/`CROSSING` contact for
the same edge and collider used different keys. The old limiter could remain in
the matrix after a new exact contact measurement existed.

Current diagnostic correction migrates the limiter multiplier to the newly
measured contact and clears a stale affine gap while retiring unmatched rows.

### 4. A rejected newly injected contact never gained multiplier strength

A limiter began with multiplier zero. Because the candidate was rejected, the
normal accepted-state multiplier update never ran. The same pair could alternate
between injection and collision indefinitely.

The latest diagnostic patch initializes/increments the limiting multiplier by a
bounded clearance-sized amount. This change performed poorly and should be the
first candidate for reversion on resume; see the last benchmark below.

## Accelerator ablation before the contact corrections

### skull/FIBER_14, accepted-cap 60

- BASE: STALLED, 18 accepted / 14 rejected.
- TRUST: CONVERGED, 12 accepted / 8 rejected, fixed residual 6.43e-8,
  stationarity 3.43e-5, about 123-130 ms.
- TRUST output matched the cap-60 BASE final output exactly.
- ANDERSON alone: STALLED, 17 accepted / 12 rejected, 4 accelerated steps,
  about 204 ms.

Conclusion: adaptive trust fixed this clear/trust-clipped case. Anderson did not.

### Contact-bound cases before owner correction

- skull/FIBER_1 ANDERSON: zero accelerated steps and no improvement.
- skull/FIBER_1 RECOVERY: more work, same result.
- skeleton/FIBER_1 TRUST: substantially slower and worse residual.

These results were contaminated by the invalid-start owner mismatch and should
not be used as the final controller decision.

## Post-owner-correction controller results

For skull/FIBER_1 at cap 60, with a conservative fixed trust after contact:

| Controller | Warm time | Termination | Accepted | Rejected | Accelerated | Stationarity |
|---|---:|---|---:|---:|---:|---:|
| TRUST | 598 ms | BUDGET_EXHAUSTED | 60 | 4 | 0 | 2.36e-3 |
| ALL | 580 ms | BUDGET_EXHAUSTED | 60 | 4 | 5 | 1.32e-3 |

Anderson reduced stationarity by about 44%, but did not reduce the accepted-step
count or wall time. At cap 200 both remained unfinished and stationarity later
worsened. Therefore the present Anderson controller must remain disabled.

Aggressively growing trust after every accepted contact step also failed: it
moved to different limiting contacts, increased stationarity, and roughly
doubled runtime. A three-full-step growth experiment still eventually collapsed
to minimum trust and stalled.

## Latest exact benchmark at pause

File:

`.artifacts/fiber_v2_p3/multiplier_skull_f1_base_cap60.json`

Read-only fixture: `E:/development/WIP_models/skull_muscles.blend`, FIBER_1,
accepted-cap 60, BASE controller.

- warm: 486.54 ms;
- termination: STALLED;
- independently validated: true;
- accepted/rejected: 33 / 19;
- fixed-point residual: 3.587e-5;
- stationarity: 2.1996e-2;
- maximum recorded violation: 1.99925e-5;
- active/injected/retired contacts: 18 / 65 / 38;
- recurring limiter: edge 44, face 7916.

This is worse numerically than the preceding stale-limiter migration result:

`.artifacts/fiber_v2_p3/migrated_skull_f1_base_cap60.json`

That result was 220.51 ms, 9 accepted / 17 rejected, fixed residual 1.219e-6,
stationarity 3.503e-3. It still stalled, but the latest multiplier-increment
change made stationarity and runtime worse. Revert or redesign the multiplier
initialization before further qualification.

## Current code-state warning

The working tree contains both production-3 work and the paused diagnostic
acceleration/contact changes. In particular:

- `core/vcp/v2/contact_core.py` is untracked and contains the current experiment;
- `core/vcp/v2/acceleration.py` is untracked;
- benchmark and test helpers are untracked;
- the production facade does not enable the optional controllers;
- owner-span, limiter-gap, stale-limiter migration, and limiter-multiplier edits
  do affect BASE behavior;
- no full-suite qualification was run after the latest diagnostic changes.

Do not describe the paused state as production-ready.

## Recommended resume sequence

1. Revert only the latest `_limiting_multiplier` initialization/increment and
   reproduce the 220 ms stale-limiter checkpoint.
2. Add a focused regression proving static validation and CCD agree for a
   moving pin-adjacent owner edge, while an unrelated collider still blocks it.
3. Add a focused nonlinear limiter test that repeatedly relinearizes the same
   curved/triangulated obstacle and must make monotone stationarity progress.
4. Replace heuristic limiter multiplier seeding with a local KKT estimate from
   the structural gradient projected onto the contact Jacobian, clamped to a
   bounded nonnegative interval.
5. Keep adaptive trust, but update it from measured merit/model agreement rather
   than contact presence or a fixed accepted-step streak.
6. Re-run BASE/TRUST/ANDERSON/ALL on skull FIBER_1, skull FIBER_14, skeleton
   FIBER_1, and sphere FIBER_2 at stored caps and diagnostic cap 60.
7. Enable Anderson only if it reduces accepted steps and wall time on at least
   the contact-bound real cases without changing the validated final fixed point.
8. Run visual comparisons before accepting any path-shape change.
9. Run full unit, focused Blender, full Blender, compilation, function-size
   ratchet, and diff checks only after the controller decision.

## Decision at pause

- Adaptive trust is promising for clear/trust-clipped Fibers such as FIBER_14.
- Current Anderson is mathematically functional and collision-safeguarded, but
  it has not yet earned production activation.
- The dominant unfinished-solve problem is still the accuracy and lifecycle of
  the active contact map, especially repeated nonlinear limiter relinearization.
- Increasing the iteration cap or enabling acceleration globally is not an
  acceptable fix while that map is unstable.
