# Fiber V3 coupled first-pass experiment

Status: isolated negative experiment, not imported by production, measured 2026-08-19.

## Question

The scalar V3 pass represents every node as:

`X[i] = D[i] + alpha[i] * (R[i] - D[i])`, with `0 <= alpha[i] <= 1`.

The original continuous refinement computes different scalar directions but applies one global
dimensionless alpha trust factor. Because corridor widths vary, the same alpha change is not the
same world-space movement. This experiment tests a coupled, world-metric update instead.

The approach follows the trajectory-metric principle in
[CHOMP](https://www.cs.cmu.edu/~mzucker/icra09-chomp.pdf) and the bounded update structure of
[projected Newton methods](https://epubs.siam.org/doi/10.1137/0320018).

## Implementation

The experiment keeps the existing planner, `D/R` corridor, layered seed, owner policy, native
collision world, CCD, objective and final validator unchanged. Only the continuous first-pass
direction changes.

For corridor vectors `v[i] = R[i] - D[i]`, it solves the reduced system:

`(J^T H J + lambda I) delta_alpha = -J^T gradient_x(E)`.

`H` contains the positive-semidefinite local length Hessian and exact quadratic curvature
Hessian. The reduced matrix is pentadiagonal, uses the existing custom V2 LDLT factorization,
eliminates hard pins and active alpha bounds, and costs `O(N)`. The trust limit is measured as
`max |v[i] * delta_alpha[i]|` in world space rather than `max |delta_alpha[i]|`. Rejected trials
halve this world trust up to eight times instead of terminating immediately.

## Real-file result

Blender 5.0.1, `fiber_sphere.blend`, 64 nodes, 64 accepted-step cap. Every path was independently
validated. The source stayed byte-identical with SHA-256
`D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

| Fiber / engine | Cold time | Free max turn | Free p95 turn | Objective | Trials / accepted | Result |
|---|---:|---:|---:|---:|---:|---|
| FIBER_2 V2 | 92.10 ms | 117.45 deg | 9.65 deg | n/a | 5 / 4 | valid `BLOCKED` |
| FIBER_2 scalar V3 | 130.54 ms | 137.40 deg | 33.22 deg | 356.1192 | 2 / 1 | valid `STALLED` |
| FIBER_2 coupled V3 | 317.87 ms median | 115.21 deg | 33.33 deg | 353.6346 | 26 / 9 | valid `STALLED` |
| FIBER_1 V2 | 36.43 ms | 20.61 deg | 10.79 deg | n/a | 1 / 1 | valid `STALLED` |
| FIBER_1 scalar V3 | 129.26 ms | 16.77 deg | 9.04 deg | 8.62268 | 1 / 0 | valid `STALLED` |
| FIBER_1 coupled V3 | 185.36 ms median | 17.12 deg | 9.04 deg | 8.62232 | 9 / 1 | valid `STALLED` |

On FIBER_2 the coupled step reduces the worst free-node turn by 16.1% and total turn by 5.2%, but
does not improve p95 and worsens the hard-pin-adjacent maximum from 152.72 to 166.10 degrees. Its
26 contact/CCD trials make it 2.43x slower than scalar V3 and 3.45x slower than V2. FIBER_1 changes
negligibly while becoming slower.

## Why it cannot remove the target kink

The target artifact is caused by collapsed segments beside hard pins, not only by a poor common
step size. In scalar V3, FIBER_2 segment lengths fall to 0.0043 world units beside normal segments
around 0.4-0.6. The visible turn is consequently extreme.

An exact static-clearance sweep around the first problematic pin found:

- node 23: every sampled alpha from 0 through 0.875 is invalid; only alpha 1 is valid;
- node 33: every sampled alpha from 0 through 0.875 is invalid; only alpha 1 is valid;
- node 35: only alpha values at or above 0.75 are valid.

Moving node 23 toward alpha 0.5 would reduce its local curvature and produce more even segment
lengths, but that obvious smoothing move intersects the collider. The feasible scalar interval
there pinches against the ROADMAP boundary immediately beside a hard pin. A better optimizer
cannot move through an invalid interval, and repeated trust reduction only adds CCD work.

## Verdict

Do not integrate this coupled first-pass implementation. It proves that world-space preconditioning
is mathematically better conditioned and can lower the objective, but it does not fix the actual
FIBER_2 artifact and materially regresses latency.

The remaining problem is representational: the fixed index-wise `D[i]--R[i]` cross-sections do not
contain a well-parameterized safe curve around the pin. The next useful experiment should change
the corridor parameterization itself—allow neighboring nodes to slide longitudinally along a safe
route/tube—rather than adding more alpha iterations or a second orthogonal displacement pass.

## Artifacts

- implementation: `core/vcp/v3_covariant_experiment.py`;
- focused tests: `tests/unit/test_fiber_v3_covariant_experiment.py`;
- benchmark: `tools/fiber_v3_corridor_experiment.py`;
- renderer: `tools/fiber_v3_covariant_render.py`;
- FIBER_2 data: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_covariant.json`;
- comparison image: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_covariant.png`;
- inspectable comparison: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_covariant.blend`.
