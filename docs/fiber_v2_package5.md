# Fiber V2 Package 5 experiment

## Decision

Package 5 proves that the Package 2 structural system, Package 4.3 planner, native
CCD acceptance, and an independent final validator can form a deterministic
unaccelerated V2 solve. All four production fixtures terminated `CONVERGED`,
preserved their hard pins, and passed strict node/edge validation.

It is not ready for live rollout. Performance is mixed and the same-owner surface
fixture still shows visible scalloping. Package 5 therefore remains an isolated
pure-data experiment; it does not replace V1 or publish Blender geometry.

The implementation uses the prefactorized local/global pattern described by
[Projective Dynamics](https://www.projectivedynamics.org/projectivedynamics.pdf)
and applies conservative movement acceptance consistent with the feasibility-first
principle in [IPC](https://ipc-sim.github.io/file/IPC-paper-fullRes.pdf).

## Implemented scope

- The validated Package 4.3 reference is the fixed `q`; it is never replaced by
  the current iterate.
- Warm starts alter only the starting state and cannot change the objective.
- Exact authored pins remain eliminated from the free system.
- Local contact targets and the Package 2 banded global solve form the base map.
- Every movement is limited by the packaged native CCD backend.
- Accepted output is checked by a separate native static validator.
- Diagnostics report structural/length/curvature/contact energy, fixed-point and
  stationarity residuals, clearance residuals, CCD work, and accepted trials.
- No Anderson acceleration, adaptive levels, Blender publication, or live-runtime
  integration is present.

For surface routes, preflight tests fixed projection scales
`{1, 2, 4, 8, 16, 32, 64, 128}` and locks the first statically feasible value for
the solve. The two skull surface fixtures require scale 16. This is deterministic
and safe in the measured fixtures, but it is a heuristic and is the likely source
of the remaining scalloped shape.

The native backend now includes a nearest-surface query with collider-bounds
pruning. Its capability/version is `af_fiber_ccd-1.511`. End users do not need a
compiler or external executable.

## V1 comparison on production files

Medians are milliseconds from fresh Blender 5.0.1 processes. Package 5 timing
starts after immutable collider-snapshot capture because the V2 architecture shares
one snapshot across affected Fibers; capture time is recorded separately by the
benchmark. V1 uses its existing solve path. Source `.blend` files were read-only.

| Fixture | V1 median | Package 5 median | P5 / V1 | V1 strict | P5 strict | P5 result |
|---|---:|---:|---:|---|---|---|
| skull/FIBER_14 roadmap | 100.26 | **25.31** | **0.25x** | invalid | valid | CONVERGED |
| skull/FIBER_1 surface | **42.84** | 118.42 | 2.76x | invalid | valid | CONVERGED |
| skeleton/FIBER_1 roadmap | **80.00** | 99.10 | 1.24x | valid | valid | CONVERGED |
| skull-skin/FIBER_1 surface | **86.91** | 120.47 | 1.39x | invalid | valid | CONVERGED |

Package 5 is about 3.96x faster than V1 on skull/FIBER_14. It is slower on the
other three fixtures. The skull and skull-skin Package 5 outputs are numerically
identical and differ by only 2.05 ms, confirming that Draft Skin is not entering
the V2 collider world. The corresponding V1 timings differ substantially; that is
a V1/runtime variance, not additional Package 5 collision input.

## Package 5 phase profile

| Fixture | Planner | Global solve | CCD | Final validation | Accepted trials | Surface scale |
|---|---:|---:|---:|---:|---:|---:|
| skull/FIBER_14 | 9.62 | 0.54 | 3.23 | 6.33 | 1 | 1 |
| skull/FIBER_1 | 64.01 | 4.89 | 7.27 | 22.17 | 1 | 16 |
| skeleton/FIBER_1 | 17.85 | 2.12 | 34.61 | 39.56 | 2 | 1 |
| skull-skin/FIBER_1 | 47.28 | 5.10 | 7.11 | 24.34 | 1 | 16 |

The O(N) structural solve is not the bottleneck. Surface planning/contact
construction dominates the skull surface case; CCD plus independent validation
dominates the skeleton. These are the next native batching/algorithm targets.

## Shape changes

| Fixture | Planner length -> P5 | Planner curvature -> P5 |
|---|---:|---:|
| skull/FIBER_14 | 1.56015 -> 1.15658 (-25.9%) | 0.002286 -> 0.000049 (-97.8%) |
| skull/FIBER_1 | 0.80952 -> 0.78423 (-3.1%) | 0.002038 -> 0.000578 (-71.6%) |
| skeleton/FIBER_1 | 8.34490 -> 7.57067 (-9.3%) | 0.055650 -> 0.026585 (-52.2%) |
| skull-skin/FIBER_1 | 0.80952 -> 0.78423 (-3.1%) | 0.002038 -> 0.000578 (-71.6%) |

The roadmap cases visibly improve from angular planner polylines to smooth,
collision-valid curves. The skull surface curve is smoother than the planner but
retains small repeated bumps. That visual defect blocks anatomical qualification
even though the static validator passes.

## Reproducible artifacts

- `artifacts/fiber_v2_package5/skull_fiber14_comparison.png`
- `artifacts/fiber_v2_package5/skull_fiber14_review.blend`
- `artifacts/fiber_v2_package5/skull_fiber1_comparison.png`
- `artifacts/fiber_v2_package5/skull_fiber1_review.blend`
- `artifacts/fiber_v2_package5/skeleton_fiber1_comparison.png`
- `artifacts/fiber_v2_package5/skeleton_fiber1_review.blend`
- `artifacts/fiber_v2_package5/*_final.json`

The comparison layout is left-to-right: V1, Package 4.3 reference, Package 5.
Review `.blend` files contain the same three curves for direct viewport inspection.

## Verification

- complete unit suite: 396 passed, one pre-existing expected failure;
- Package 5 warm/cold, deterministic-merit, pin, collision, and termination tests;
- function-size ratchet passed; every new or modified function is at most 15 lines;
- `git diff --check` passed apart from Git line-ending notices;
- final source hashes:
  - skull: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`;
  - skeleton: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`;
  - skull-skin: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`.

## Required next work

1. Replace independent per-node surface offsets with a coherent surface corridor
   projection so contact targets cannot create scalloping.
2. Batch native CCD and static validation across all Fiber edges; skeleton spends
   74.17 ms in those two phases alone.
3. Re-run visual qualification and require human approval of the surface and rib
   paths before implementing adaptive convergence.
4. Only after the base map passes those gates, proceed to Package 6. Do not use
   iteration policy or Anderson acceleration to hide a poor fixed point.

