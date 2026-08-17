# Fiber V2 Package 8.1 Multi-Sample Contact Experiment

## Decision

**Reject Package 8.1 as the production collision solve.** Keep the sampled
banded numerical primitive and the benchmark as an isolated negative result.

Package 8.1 successfully observes multiple collision locations and multiple
blockers on one Fiber edge while preserving the O(N) structural factorization.
That does not remove the failure mode: six of seven production Fibers still
end at a zero CCD step, and their rendered shapes remain essentially Package 8
shapes. P8.1 is slower than P8 on every fixture.

No runtime recompute, publication, migration, saved Fiber data, or V2 rollout
flag uses Package 8.1.

## Hypothesis tested

Package 8 retained only one midpoint collision target per edge. P8.1 tests
whether P8 blocked because one edge could not represent contacts at different
positions or against different colliders.

For five fixed factors `t = {0.1, 0.3, 0.5, 0.7, 0.9}`, the frozen local/global
objective is

\[
E(x)=E_s(x)+\frac{w_C}{5}\sum_{e,k}
\|(1-t_k)x_e+t_kx_{e+1}-p_{e,k}\|^2.
\]

- The total edge penalty remains `wC=10`; adding samples does not multiply
  inactive drag.
- Every original edge is divided into five spatial bins.
- The existing native query returns one closest contact per bin, allowing up
  to five locations and blockers per original edge without an ABI change.
- Every bin uses the same localized authored-owner exemptions as the planner,
  CCD, and final validator.
- Clear targets are samples of the current feasible curve.
- Active targets are translated to the native closest-point clearance target.
- Authored hard pins remain eliminated exactly.
- Open systems remain pentadiagonal. A cyclic wrap edge contributes five
  low-rank Woodbury columns.

This retains the constant-matrix local/global structure described by
[Projective Dynamics](https://www.projectivedynamics.org/projectivedynamics.pdf).
The choice to keep the total proxy weight constant follows the practical
warning in
[Optimized Localized Collisions for Projective Dynamics](https://doi.org/10.1111/cgf.14385)
that predeclared inactive collision proxies can add drag.

## Numerical qualification

Independent dense references pass for:

- open and cyclic topology;
- internal hard pins;
- arbitrary increasing fixed sample factors;
- cyclic rank-five contact correction;
- frozen-local-energy descent;
- cached, bit-identical replay.

The clear fixture is cap-invariant and has stationarity below `1e-9`.

## Benchmark method

- Blender 5.0.1 on the current Windows workstation.
- Fresh Blender process for each Fiber.
- One warm-up and seven randomized repetitions per solver.
- V1, P5.1, P6.1, P8, and P8.1 share one captured request and collider snapshot
  within each fixture.
- P8.1 timing includes planning, binned native contact acquisition, the sampled
  banded solve, native CCD, and independent final validation.
- Source `.blend` files were opened read-only and their hashes were unchanged.

## Performance

Median wall time in milliseconds:

| Fixture | V1 | P5.1 | P6.1 | P8 | P8.1 | P8.1 vs P8 | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| Skull / FIBER_4 | 79.48 | 251.15 | 248.37 | 149.99 | 182.98 | +22.0% | `BLOCKED` |
| Skull / FIBER_9 | 79.73 | 235.84 | 232.51 | 92.85 | 135.10 | +45.5% | `BLOCKED` |
| Skull / FIBER_13 | 194.65 | 34.75 | 34.32 | 36.14 | 42.14 | +16.6% | `CONVERGED` |
| Skull / FIBER_14 | 140.46 | 110.31 | 103.65 | 81.60 | 104.75 | +28.4% | `BLOCKED` |
| Skull / FIBER_22 | 154.43 | 33.73 | 32.73 | 47.20 | 72.18 | +52.9% | `BLOCKED` |
| Skull-skin / FIBER_1 | 111.76 | 96.27 | 100.18 | 110.22 | 153.44 | +39.2% | `BLOCKED` |
| Skeleton / FIBER_1 | 106.50 | 364.73 | 240.90 | 100.07 | 131.37 | +31.3% | `BLOCKED` |

P8.1 is faster than V1 only for FIBER_13, FIBER_14, and FIBER_22. Its clear
case pays about 6 ms for binned contact acquisition that finds no contacts.

## What the richer map proved

| Fixture | Active sample slots per trial | Distinct blockers | CCD fractions |
|---|---:|---:|---|
| Skull / FIBER_4 | 101 | 3 | `0.0413 -> 0.000038 -> 0` |
| Skull / FIBER_9 | 175 | 2 | `0.4688 -> 0.000877 -> 0` |
| Skull / FIBER_13 | 0 | 0 | `1` |
| Skull / FIBER_14 | 22 | 1 | `1 -> 0.9003 -> 0.001274 -> 0` |
| Skull / FIBER_22 | 72 | 1 | `0.1390 -> 0.000153 -> 0` |
| Skull-skin / FIBER_1 | 300 | 1 | `0.0670 -> 0.000061 -> 0` |
| Skeleton / FIBER_1 | 37 | 1 | `0.6418 -> 0.000984 -> 0` |

The experiment does retain the information P8 lacked. FIBER_4 simultaneously
contains three blockers and FIBER_9 contains two. Yet their feasible step still
collapses. Therefore the primary issue is not contact discovery cardinality.

## Root cause after P8.1

The fixed slots are quadratic penalties, not unilateral feasibility
constraints. The global structural objective continues to supply an inward
component at contacts. A weighted average of projected targets can still point
through another face or back into an already active face. CCD correctly clips
that direction. Once an accepted curve lies on the clearance boundary, the
same inward component has a zero collision-free prefix.

Increasing sample density can measure that conflict more accurately, but it
does not create a tangent/outward feasible direction. Increasing the weight
only trades structural motion for more proxy drag. More iterations,
acceleration, or recovery would repeat the same infeasible map.

The next justified solver experiment is an active unilateral contact solve:

1. Build linearized nonpenetration rows for active sample contacts.
2. Solve the structural quadratic subject to nonnegative normal motion.
3. Reuse the banded structural factor and solve the active constraints through
   a Schur complement or projected multiplier iteration.
4. Keep CCD as the conservative nonlinear acceptance check.
5. Require the active solve to produce a nonzero feasible direction on the six
   blocked fixtures before adding acceleration or adaptive recovery.

## Visual qualification

Every comparison is left-to-right: V1, P5.1, P6.1, P8, and P8.1. Editable
`.blend` previews sit beside the PNG files.

- `artifacts/fiber_v2_package81/preview_skull_fiber4.png`
- `artifacts/fiber_v2_package81/preview_skull_fiber9.png`
- `artifacts/fiber_v2_package81/preview_skull_fiber13.png`
- `artifacts/fiber_v2_package81/preview_skull_fiber14.png`
- `artifacts/fiber_v2_package81/preview_skull_fiber22.png`
- `artifacts/fiber_v2_package81/preview_skull_skin_fiber1.png`
- `artifacts/fiber_v2_package81/preview_skeleton_fiber1.png`

Maximum pointwise P8.1-to-P8 differences are `0.000882`, `0.002396`, `0`,
`0.001115`, `0.000234`, `0.000491`, and `0.034186` world units respectively.
Visual inspection confirms that P8.1 retains the same angular or planner-like
shape on the blocked cases. It does not recover V1's anatomical wrapping.

## Verification

- Full unit suite: `437` tests passed, `6` skipped, `1` expected failure.
- Focused sampled-contact and V2 solver suite: `35/35` passed after the final
  contact-energy accounting correction.
- Function-size ratchet passed with only the 21 existing legacy exceptions.
- Every new or modified function is at most 15 lines.
- All seven P8.1 outputs pass independent owner-aware final validation.
- Source hashes:
  - skull: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`;
  - skull-skin: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`;
  - skeleton: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`.
