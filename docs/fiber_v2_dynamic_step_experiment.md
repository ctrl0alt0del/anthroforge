# Fiber V2 dynamic-step experiment

## Decision

Keep the active-set filter/trust SQP controller as an opt-in experiment. Do not
enable it for production V2 yet.

The experiment is valuable for contact-bound Fibers: `skull/FIBER_1` changed
from 403.12 ms and `STALLED` to 201.33 ms and `CONVERGED`. It is not a universal
controller: sparse-contact and long surface-travel cases became 1.4–3.6 times
slower. A production hybrid needs a measured activation rule and a way to stop
unproductive tangential descent.

Production `BASE` behavior is unchanged. The experiment is selected only by the
benchmark controller `SQP` or the internal `use_filter_sqp=True` injection.

## Method

The experiment implements an active-set trust-region SQP step rather than one
global scalar relaxation:

1. Freeze the current structural block-pentadiagonal system.
2. Acquire the active contact Jacobian rows.
3. Factor the structural system once in the native backend.
4. Solve the unconstrained structural direction and one native response per
   active contact.
5. Solve the small equality-constrained contact system.
6. Decompose the result into contact-normal and tangential motion.
7. Scale the full direction to a trust radius.
8. Accept with the existing feasibility filter and conservative CCD.
9. Grow or shrink the radius from actual/model reduction agreement.

This follows feasible/filter trust-region SQP practice while retaining the
production collision invariant. Limiting CCD pairs are injected into the active
set; three repeated limiters shrink the trust region rather than repeatedly
trying the same full step.

Primary references:

- [A Feasible Trust-Region Sequential Quadratic Programming Algorithm](https://optimization-online.org/2002/08/520/)
- [A Filter Active-Set Trust-Region Method](https://optimization-online.org/2007/09/1777/)
- [An Inexact Trust-Region SQP Filter Algorithm](https://optimization-online.org/2014/10/4596/)
- [Incremental Potential Contact](https://ipc-sim.github.io/file/IPC-paper-fullRes.pdf)

## Implementation

- `core/vcp/v2/trust_sqp.py`: active-set direction, model reduction, and trust
  update.
- `core/vcp/v2/contact_core.py`: optional controller, contact injection, traces,
  and filter acceptance.
- `native/fiber_ccd/af_fiber_contact3.hpp`: one-factor/multiple-RHS structural
  response API.
- `core/vcp/v2/collision_native.py`: native response binding.
- `tools/fiber_v2_production3_benchmark.py`: `--controller SQP` qualification.

The discarded tangential-extrapolation variant is not present in the code. It
reduced a little wall time but increased residuals and rejected steps.

## Real-file benchmark

Blender 5.0.1, accepted-step cap 60, two timed warm repetitions, source files
opened read-only. All reported outputs passed independent static validation.

| Fixture | BASE | SQP | Result |
|---|---:|---:|---|
| `skull/FIBER_1` | 403.12 ms, STALLED, 8/25 accepted/rejected | 201.33 ms, CONVERGED, 12/11 | 50.1% faster; clear success |
| `skull/FIBER_14` | 124.84 ms, STALLED, 11/11 | 175.80 ms, STALLED, 7/18 | 40.8% slower |
| `sphere/FIBER_2` | 213.75 ms, STALLED, 13/15 | 573.83 ms, BUDGET_EXHAUSTED, 60/12 | 2.68x slower |
| `skeleton/FIBER_1` | 259.94 ms, STALLED, 2/10 | 945.25 ms, BUDGET_EXHAUSTED, 60/5 | 3.64x slower |

Residuals explain the split:

| Fixture | BASE fixed / stationarity | SQP fixed / stationarity | Final active contacts |
|---|---:|---:|---:|
| `skull/FIBER_1` | 2.11e-5 / 4.40e-4 | 3.17e-9 / 3.91e-12 | 10 |
| `skull/FIBER_14` | 6.10e-7 / 1.37e-3 | 2.47e-4 / 6.45e-5 | 5 |
| `sphere/FIBER_2` | 1.26e-5 / 2.45e-2 | 6.99e-5 / 2.31e-5 | 7 |
| `skeleton/FIBER_1` | 3.05e-6 / 2.04e-3 | 4.88e-5 / 1.09e-5 | 4 |

SQP removes the contact-normal conflict on the successful skull case. On the
sphere and skeleton it obtains safe, near-stationary contact directions but then
spends the entire cap descending the structural objective tangentially along a
nonlinear surface. Per-node step scaling cannot eliminate that path length.

## Visual qualification

The four-panel images show DIRECT, planner seed, V1, and the measured V2 output.
The filenames identify the controller:

- `../.artifacts/fiber_v2_dynamic_step/skull_f1_base.png`
- `../.artifacts/fiber_v2_dynamic_step/skull_f1_sqp.png`
- `../.artifacts/fiber_v2_dynamic_step/skull_f14_base.png`
- `../.artifacts/fiber_v2_dynamic_step/skull_f14_sqp.png`
- `../.artifacts/fiber_v2_dynamic_step/sphere_f2_base.png`
- `../.artifacts/fiber_v2_dynamic_step/sphere_f2_sqp.png`
- `../.artifacts/fiber_v2_dynamic_step/skeleton_f1_base.png`
- `../.artifacts/fiber_v2_dynamic_step/skeleton_f1_sqp.png`

The skull pair is visually equivalent and smooth. SQP rounds part of the sphere
path but leaves a visible kink at much higher cost. The skeleton result is much
smoother and takes a different valid route, but its 3.6x cost and anatomical
choice require human judgment before it can be considered an improvement.

## Activation evidence and next gate

The current evidence supports a conservative future trigger only after BASE is
demonstrably contact-bound. Contact count alone is insufficient: the sphere has
several contacts but is dominated by long tangential travel. A candidate hybrid
gate must require all of:

- repeated BASE rejection or limiting-pair injection;
- high active-contact density (the successful case ended with 10 contacts);
- structural progress blocked primarily in contact-normal directions;
- a short SQP probe that predicts positive model agreement.

If the probe fails to reduce fixed-point residual within two accepted steps, the
session must return to BASE without losing its accepted state. This rule still
needs direct A/B qualification and therefore is not implemented here.

## Quality-first extended `sphere/FIBER_2` run

Increasing the cap confirms that the 60-step result is unfinished, but also
shows that waiting alone cannot produce the desired tight path:

| Allowed accepted steps | Actual accepted/rejected | Time | Termination | Path length | Fidelity / length / curvature energy |
|---:|---:|---:|---|---:|---:|
| 60 | 60 / 12 | 573.8 ms | `BUDGET_EXHAUSTED` | 20.70 | 28.12 / 408.40 / 491.24 |
| 200 | 200 / 14 | 1179.0 ms | `BUDGET_EXHAUSTED` | 20.49 | 22.75 / 396.44 / 393.15 |
| 1000 | 281 / 23 | 1689.9 ms | `STALLED` | 20.58 | 23.42 / 396.42 / 370.74 |

The first 200 accepted iterates are identical between the 200- and 1000-cap
runs. The longer run then makes 81 more accepted updates before rejecting eight
successive candidates with `MODEL_RATIO:-inf`. Its trust radius contracts from
0.867 to the 0.0005 floor. The final stationarity residual is 4.09e-6, but the
fixed-point residual rises to 1.86e-4 and convergence is not reached.

The route is loose for two independent reasons:

1. The active contact constraints are tangent-plane linearizations. On a curved
   obstacle, the locally exact SQP direction stops predicting the nonlinear
   surface movement, so making the step smaller eventually cannot repair its
   direction.
2. The objective is a weighted compromise, not “shortest collision-free path,
   then smooth it.” Once feasible, it can reduce curvature energy by maintaining
   a broad arch even when that is not the tightest route.

The next quality experiment should therefore be lexicographic: maintain
feasibility, minimize arc length first, and minimize curvature only within a
small allowed length increase. It also needs a curved-contact model or
retracted/tangential surface step. Raising the iteration cap or changing only
the scalar trust radius is insufficient.

## Verification

- Synthetic intersecting DIRECT box: BASE 17 accepted / 9 rejected; SQP 12 / 2,
  both converged and independently collision-valid.
- Native multi-response solve matches an independent dense reference.
- Focused V2 contact/structural/collision tests: 55 passed.
- Complete unit suite: 549 passed, 6 skipped, 1 expected failure.
- Function-size ratchet passes; all experiment functions are at most 15 lines.
- Benchmark source hashes match between BASE and SQP runs.
