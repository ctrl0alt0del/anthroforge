# Fiber V2 Package 8 Contact-Slot Experiment

## Decision

**Reject Package 8 as a production solver, but retain the augmented banded core.**

Package 8 proves that fixed contact terms can be solved in the existing O(N)
pentadiagonal/Woodbury system. It is safe on all seven production fixtures and
is materially faster than Package 5.1/6.1 on five of them. It does not solve
the actual convergence problem: only one of seven Fibers converges, and visual
inspection shows several results stopping close to the angular planner route.

The implementation is isolated. It does not change runtime recompute,
publication, migration, saved Fiber data, or the V2 rollout flag.

## Implemented model

For fixed local targets, Package 8 minimizes

\[
E(x)=E_s(x)+w_C\sum_i\|x_i-p_i\|^2+
     w_C\sum_e\|\tfrac12(x_e+x_{e+1})-p_e\|^2.
\]

- Every node and chain edge has a fixed slot.
- Clear node targets are the current nodes.
- Clear edge targets are current edge midpoints.
- An active edge target translates its midpoint by the native contact
  projection at that edge's closest reported contact.
- Authored hard pins are eliminated exactly.
- Open systems remain pentadiagonal.
- A cyclic last-to-first midpoint is a rank-one Woodbury update.
- The matrix is factorized once per count, topology, pin mask, structural
  weights, and contact weight; only the right-hand side changes.
- The fixed reference `q` is the validated planner corridor and is independent
  of warm starts and accepted-step caps.

The formulation follows the constant-matrix local/global structure of
[Projective Dynamics](https://www.projectivedynamics.org/projectivedynamics.pdf).
Localized collision constraints are also consistent with the motivation in
[Optimized Localized Collisions for Projective Dynamics](https://doi.org/10.1111/cgf.14385).

## Numerical qualification

The new contact structural backend passes independent dense references for:

- open and cyclic topology;
- arbitrary internal hard pins;
- node and edge midpoint slots;
- cyclic rank-one contact correction;
- frozen-local-energy descent;
- factor-cache reuse and bit-identical replay.

The clear production-independent fixture is cap-invariant and has a
stationarity residual below `1e-9`.

## Contact weight pilot

Skull/FIBER_14 was tested with the planned candidate set `{10, 100, 1000}`.

| Weight | Median ms | Accepted/rejected | Path length | Stationarity | Result |
|---:|---:|---:|---:|---:|---|
| 10 | 165.12 | 5 / 1 | 0.9353 | 0.0346 | `BLOCKED`, safe |
| 100 | 179.65 | 7 / 1 | 0.9716 | 0.141 | `BLOCKED`, safe |
| 1000 | 114.53 | 3 / 1 | 0.9995 | 3.30 | `BLOCKED`, safe |

The apparent speed at weight 1000 is early blocking, not faster convergence.
Weight 10 is the lowest feasible candidate and causes the least planner-shape
retention, so all production benchmarks use `wC=10`.

## Benchmark method

- Blender 5.0.1 on the current Windows workstation.
- Fresh Blender process for each Fiber.
- One warm-up and seven randomized repetitions per solver.
- V1, Package 5.1, Package 6.1, and Package 8 share the same captured request
  and collider snapshot inside each fixture.
- Package 8 timing includes planner, local contact construction, banded solve,
  native CCD, and independent final validation.
- Source `.blend` files were opened read-only.

## Performance

Median wall time in milliseconds:

| Fixture | V1 | P5.1 | P6.1 | P8 | P8 vs P5.1 | Termination |
|---|---:|---:|---:|---:|---:|---|
| Skull / FIBER_4 | 77.97 | 295.91 | 296.46 | 174.99 | -40.9% | `BLOCKED` |
| Skull / FIBER_9 | 88.77 | 325.31 | 334.97 | 126.77 | -61.0% | `BLOCKED` |
| Skull / FIBER_13 | 246.99 | 56.63 | 57.46 | 55.56 | -1.9% | `CONVERGED` |
| Skull / FIBER_14 | 200.92 | 217.68 | 224.98 | 151.08 | -30.6% | `BLOCKED` |
| Skull / FIBER_22 | 231.16 | 67.54 | 67.43 | 84.76 | +25.5% | `BLOCKED` |
| Skull-skin / FIBER_1 | 176.81 | 167.47 | 175.94 | 185.22 | +10.6% | `BLOCKED` |
| Skeleton / FIBER_1 | 146.91 | 690.65 | 443.93 | 168.16 | -75.7% | `BLOCKED` |

Package 8 beats Package 5.1 on five of seven fixtures and nearly removes the
Skeleton collision-processing explosion. It is slower on the light
Skull/FIBER_22 and skull-skin/FIBER_1 cases. Relative to V1 it is faster on
three fixtures and slower on four.

## Solver truth

| Fixture | Accepted/rejected | Fixed residual | Stationarity | Final validation |
|---|---:|---:|---:|---|
| Skull / FIBER_4 | 2 / 1 | 0.0189 | 72.67 | safe |
| Skull / FIBER_9 | 2 / 1 | 0.00386 | 13.74 | safe |
| Skull / FIBER_13 | 1 / 0 | 0 | <1e-9 | safe |
| Skull / FIBER_14 | 5 / 1 | 0.0014 | 0.0346 | safe |
| Skull / FIBER_22 | 2 / 1 | 0.00263 | 40.84 | safe |
| Skull-skin / FIBER_1 | 2 / 1 | 0.00982 | 45.94 | safe |
| Skeleton / FIBER_1 | 2 / 1 | 0.00535 | 18.42 | safe |

All frozen local energies are nonincreasing. That confirms the global solve is
coherent with the targets it receives. The model still cannot provide a usable
next feasible direction on six fixtures.

## Why it blocks

The recorded CCD fractions expose a common sequence:

- Skull/FIBER_4: `0.0442 -> 0.000038 -> 0`
- Skull/FIBER_9: `0.588 -> 0.00114 -> 0`
- Skull/FIBER_22: `0.138 -> 0.000153 -> 0`
- skull-skin/FIBER_1: `0.0741 -> 0.000069 -> 0`
- Skeleton/FIBER_1: `0.711 -> 0.00123 -> 0`

One midpoint slot per edge cannot represent a contact at an arbitrary edge
factor, two separated contacts on one edge, or simultaneous contacts with
different blockers. The native query selects the closest contact for an edge;
the banded model resolves that slot, then CCD finds another unrepresented
collision along the proposed motion. The next safe fraction collapses to zero.

This is not fixed by more iterations, larger weights, trust recovery, or
Anderson acceleration. Those methods would repeat or accelerate an incomplete
contact map.

## Visual qualification

Each comparison contains V1, Package 4.3, Package 5.1, Package 6.1, and Package
8. Editable `.blend` previews sit beside every PNG.

- `artifacts/fiber_v2_package8/preview_skull_fiber4.png`
- `artifacts/fiber_v2_package8/preview_skull_fiber9.png`
- `artifacts/fiber_v2_package8/preview_skull_fiber13.png`
- `artifacts/fiber_v2_package8/preview_skull_fiber14.png`
- `artifacts/fiber_v2_package8/preview_skull_fiber22.png`
- `artifacts/fiber_v2_package8/preview_skull_skin_fiber1.png`
- `artifacts/fiber_v2_package8/preview_skeleton_fiber1.png`

Package 8 matches Package 5.1 only on the clear FIBER_13. Maximum pointwise
differences from Package 5.1 are `0.1338` on FIBER_4, `0.0283` on FIBER_9,
`0.1494` on FIBER_14, `0.00319` on FIBER_22, `0.0322` on skull-skin/FIBER_1,
and `0.5542` on Skeleton/FIBER_1. Several P8 curves visibly retain angular
planner features. They are safe, but not qualified anatomical results.

## Reusable result and next experiment

Keep `contact_structural.py`: it is the required O(N) augmented linear algebra
and is independently correct. Reject the one-midpoint local contact map in
`solver_p8.py`.

A justified next experiment is a fixed quadrature contact layout:

1. Preallocate several fixed sample factors per edge, not one midpoint.
2. Query each sample with identical owner exemptions.
3. Preserve multiple blocker targets instead of selecting only one per edge.
4. Add every fixed sample's rank-one two-node term to the same tridiagonal
   bands; the matrix remains constant and O(N).
5. Require a production fixture to produce nonzero feasible steps through
   convergence before running all seven benchmarks.

Do not add adaptive recovery or acceleration until that richer base map passes.

## Verification

- Full unit suite: `429` passed, `6` skipped, `1` expected failure.
- Focused contact-structural and solver tests: `32/32` passed.
- Function-size ratchet passed with only the 21 existing legacy exceptions.
- Every new or modified function is at most 15 lines.
- All seven P8 outputs passed independent final owner-aware validation.
- Every seven-repeat P8 result was deterministic.
- Source file hashes remained unchanged:
  - Skull: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
  - Skull-skin: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`
  - Skeleton: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`
