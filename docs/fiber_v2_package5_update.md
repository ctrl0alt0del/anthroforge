# Fiber V2 Package 5 revised experiment

## Result

The revised Package 5 fixes the most visible shape defects in the original
experiment, but it is still not a rollout candidate. All four production outputs
are independently collision-valid and deterministic, yet all terminate
`BLOCKED` because CCD eventually finds no nonzero straight-line step. The
updated map is also slower than V1 on every measured fixture.

The sources for the redesign are the prefactorized local/global pattern in
[Projective Dynamics](https://www.projectivedynamics.org/projectivedynamics.pdf),
trajectory optimization with obstacle costs in
[CHOMP](https://personalrobotics.cs.washington.edu/publications/zucker2013chomp.pdf),
and feasibility-preserving acceptance in
[IPC](https://ipc-sim.github.io/file/IPC-paper-fullRes.pdf).

## What changed

The original P5 minimized a positional fidelity term to the planner reference.
On a clear Fiber_14 solve it had no active collision contacts, so the high arch
was the direct optimum of that fixed-reference objective. The planner reference
was therefore functioning as a shape target instead of only defining route
topology.

The revised experiment makes these changes:

- the planner result initializes the route but is not a positional fidelity
  target;
- each accepted trial performs proximal structural shortening from the current
  curve;
- roadmap contact intervals use the V1-compatible eight-radius local attachment
  span, while surface planning retains the conservative 2.5-radius span;
- roadmap contacts use structural-metric constraint projection rather than
  independent point offsets;
- a same-owner surface route retracts the complete proposal to one coherent
  owner-surface corridor at 1.5 times the requested clearance;
- every movement still passes native CCD and every returned curve passes the
  independent native static validator;
- warm seeds are deliberately ignored until the constrained fixed point can
  converge deterministically;
- trace data now separates planner, complete candidate construction, CCD,
  validation, and total time.

No production V1 path, Blender publication path, or source `.blend` file is
modified by this experiment.

## Real Blender benchmark

Blender 5.0.1 background processes, three timed repetitions, cached immutable
collider snapshot, current Windows workstation. Times are medians in milliseconds.

| Fixture | Mode | V1 | Original P5 | Revised P5 | Revised/V1 | Result |
|---|---|---:|---:|---:|---:|---|
| skull/FIBER_14 | ROADMAP | 103.06 | 25.31 | 160.46 | 1.56x | valid, BLOCKED |
| skull/FIBER_1 | SURFACE | 35.47 | 118.42 | 223.55 | 6.30x | valid, BLOCKED |
| skeleton/FIBER_1 | ROADMAP | 78.95 | 99.10 | 596.41 | 7.55x | valid, BLOCKED |
| skull-skin/FIBER_1 | SURFACE | 92.88 | 120.47 | 213.60 | 2.30x | valid, BLOCKED |

The original P5 numbers are retained historical measurements. The revised V1
and P5 numbers were captured together in the new benchmark run. Draft Skin does
not enter the captured V2 collider set: the skull and skull-skin revised P5
curves are numerically identical.

## Shape comparison

| Fixture | V1 length | Planner length | Original P5 | Revised P5 |
|---|---:|---:|---:|---:|
| skull/FIBER_14 | 0.76625 | 1.01407 | 1.15658 | **0.78575** |
| skull/FIBER_1 | 0.70153 | 0.80952 | 0.78423 | **0.71120** |
| skeleton/FIBER_1 | 8.34490 | 8.34490 | 7.57067 | **7.13279** |
| skull-skin/FIBER_1 | 0.70949 | 0.80952 | 0.78423 | **0.71120** |

Fiber_14 no longer arches above the obstacle. Its revised route is only 2.5%
longer than V1 rather than 51% longer. The skull surface curve loses the original
repeated scallops and its length is within about 1.4% of V1. The skeleton result
is collision-valid and shorter, but still has a visibly constrained corner and
requires human anatomical review.

## Phase profile

`candidate` contains contact discovery/projection and its nested structural
solves. It is therefore a complete candidate phase, while the smaller `global`
column is included only to show how little of that phase is banded algebra.

| Fixture | Planner | Candidate | Global (nested) | CCD | Validation | Total |
|---|---:|---:|---:|---:|---:|---:|
| skull/FIBER_14 | 19.33 | 56.83 | 2.74 | 31.39 | 43.57 | 153.20 |
| skull/FIBER_1 | 53.63 | 96.71 | 2.29 | 39.60 | 31.48 | 223.54 |
| skeleton/FIBER_1 | 30.97 | 148.69 | 4.61 | **314.79** | 99.67 | 596.40 |
| skull-skin/FIBER_1 | 70.29 | 87.37 | 2.28 | 30.09 | 24.26 | 213.59 |

The banded solve remains negligible. Repeated Python contact construction plus
native calls dominates the candidate phase; conservative CCD dominates the
skeleton. The revised result is slower because it performs four to eight real
trials instead of the original P5's one or two fixed-reference steps.

## Artifacts

- `artifacts/fiber_v2_package5/updated_compare_skull_fiber14.png`
- `artifacts/fiber_v2_package5/updated_compare_skull_fiber14.blend`
- `artifacts/fiber_v2_package5/updated_compare_skull_fiber1.png`
- `artifacts/fiber_v2_package5/updated_compare_skull_fiber1.blend`
- `artifacts/fiber_v2_package5/updated_compare_skeleton_fiber1.png`
- `artifacts/fiber_v2_package5/updated_compare_skeleton_fiber1.blend`
- `artifacts/fiber_v2_package5/updated_*.json`

Each four-panel comparison is left-to-right: V1, Package 4.3 planner, original
P5, revised P5. The `.blend` copies allow direct viewport inspection.

## Decision and next required work

Keep revised P5 experimental and disconnected from production. It proves the
fixed-reference arch and independent-contact scallops can be removed, but it
also exposes the real remaining blocker: straight-line CCD interpolation is a
poor retraction for motion constrained to a curved surface. Near the boundary,
safe fractions collapse toward zero even when the endpoint curve is valid.

The next solver experiment should implement a collision-safe curved retraction
or trust-region/contact-space step, then batch contact construction and CCD in
the native backend. Only after that change should convergence and performance be
requalified. Do not relabel the current `BLOCKED` terminal state as convergence.
