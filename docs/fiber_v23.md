# Fiber V2.3 Cold-Start Experiment

Date: 2026-08-17

Status: **experiment accepted as a structural optimization; not approved for
product rollout**.

V2.3 tests the cold-start changes identified in
[`fiber_v22_cpp_migration_and_cold_start.md`](fiber_v22_cpp_migration_and_cold_start.md):

- capture collider vertices and triangles through contiguous NumPy arrays;
- compute closed/open topology once per collider per solve;
- build one generation-keyed native collision world and inject it into planner
  and solver;
- retain all V2.2 route, merit, CCD, validation, and cache policy.

It deliberately does not alter the V2 curve objective or collision answer. The
experiment answers one question: how much of V2.2 cold time is avoidable Python
capture and repeated collision-world construction?

## Implementation

- `core/vcp/v2/solver_v23.py` owns the V2.3 experiment and route cache.
- `core/vcp/v2/contracts.py` has a vectorized NumPy input path while preserving
  immutable tuple contracts at the pure-data boundary.
- `core/vcp/v2/collision.py` accepts a solve-local topology memo when building a
  triangle snapshot or native world.
- `core/vcp/v2/planner.py` accepts an injected native world.
- `core/vcp/v2/solver.py` reuses that world for main candidate, contact, CCD,
  and final-validation work. A deliberately filtered owner-only subset may
  still require a separate subset world.

V2.2 remains unchanged when the new optional arguments are omitted. Explicitly
empty collider subsets also remain empty; they never fall back to the complete
request collider set.

## Benchmark protocol

- Blender 5.0.1, Windows x64, background factory-startup process.
- Each fixture is captured from a read-only production `.blend`.
- Three cold and three warm repetitions per fixture.
- V2.2 and V2.3 use the same request settings and native backend.
- `V1` is the direct legacy solver harness. It is useful as a latency reference,
  but is not quality-equivalent to V2's stricter capture and validation boundary.
- `Total` below means request capture plus isolated cold solve, not debounce,
  viewport scheduling, downstream consumers, or a full shortcut cycle.

| Fixture | V1 direct | V2.2 capture | V2.3 capture | V2.2 cold | V2.3 cold | V2.2 total | V2.3 total | V2.2 warm | V2.3 warm |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| skeleton / FIBER_1 | 162.18 | 184.51 | 73.28 | 404.19 | 277.95 | 588.70 | 351.23 | 162.03 | 139.67 |
| skull-skin / FIBER_1 | 78.76 | 136.45 | 68.97 | 294.98 | 197.36 | 431.43 | 266.33 | 22.90 | 22.74 |
| skull / FIBER_1 | 34.98 | 148.47 | 66.61 | 275.97 | 188.32 | 424.44 | 254.93 | 24.40 | 26.23 |
| skull / FIBER_13 | 106.03 | 132.48 | 61.70 | 189.52 | 92.20 | 322.00 | 153.90 | 7.68 | 8.06 |
| skull / FIBER_14 | 91.14 | 140.21 | 65.27 | 241.41 | 135.82 | 381.62 | 201.09 | 38.34 | 32.48 |
| skull / FIBER_22 | 113.92 | 115.31 | 60.01 | 202.82 | 117.55 | 318.13 | 177.56 | 22.27 | 21.48 |
| skull / FIBER_4 | 52.03 | 135.64 | 79.41 | 316.30 | 210.40 | 451.93 | 289.80 | 87.07 | 87.84 |
| skull / FIBER_9 | 37.87 | 134.35 | 72.39 | 301.55 | 213.57 | 435.90 | 285.96 | 101.83 | 99.50 |
| **Mean** | **84.61** | **140.93** | **68.46** | **278.34** | **179.15** | **419.27** | **247.60** | **58.32** | **54.75** |

All values are milliseconds. Relative to V2.2, V2.3 reduced:

- mean capture by **51.43%**;
- mean isolated cold solve by **35.64%**;
- mean capture+cold by **40.94%**;
- mean warm solve by **6.12%**.

The limited warm improvement is expected: V2.2 already caches much of the work
that V2.3 removes from the cold path.

## Correctness and visual result

For all eight fixtures, V2.2 and V2.3 have:

- maximum point delta exactly `0.0`;
- identical route and termination;
- identical final validation state.

Therefore V2.3 is a performance-only change. It neither improves nor regresses
V2.2 path shape. The side-by-side renders use orange for V1, blue for V2.2, and
green for V2.3; blue and green overlap exactly.

Review artifacts:

- `artifacts/fiber_v23/skull_f14.png` and `skull_f14_review.blend`;
- `artifacts/fiber_v23/skull_f4.png` and `skull_f4_review.blend`;
- `artifacts/fiber_v23/skeleton_f1.png` and `skeleton_f1_review.blend`;
- `artifacts/fiber_v23/skin_f1.png` and `skin_f1_review.blend`;
- full machine-readable records in `artifacts/fiber_v23/*.json`.

Only skull/FIBER_13 converged. Six skull/skin cases remain `BLOCKED`, and
skeleton/FIBER_1 remains `BUDGET_EXHAUSTED`. V2.3 must not be described as a
working replacement for V1 on those cases.

## Where cold time remains

A representative skull/FIBER_14 V2.3 cold trace was 133.56 ms:

| Phase | Time |
|---|---:|
| Immutable triangle snapshot | 61.40 ms |
| Native collision world | 18.29 ms |
| Planner | 21.83 ms |
| Candidate/global work | 9.24 ms |
| Contact query | 4.37 ms |
| CCD | 18.41 ms |
| Final validation | 2.21 ms |

Some timers overlap because contact work is nested in candidate evaluation.
The next credible native-migration boundary remains collider capture/snapshot
construction: Blender should extract evaluated coordinates on the main thread,
then a native builder can validate, transform, classify topology, hash, and build
the persistent collision structure from contiguous arrays.

## Qualification

- V2.3 focused unit tests: 6/6 pass.
- Full unit suite: 469 pass, six optional-native skips, one existing expected
  warm/cold convergence failure.
- Architecture/function-size guardrail: pass; every new/modified function is at
  most 15 lines.
- Full Blender discovery: 473 pass, one reproducible Quick Fiber persistence
  error unrelated to V2.3 (the final unsafe/nonconverged preview does not publish
  `af_fiber_points_world`). This baseline workflow must be resolved separately;
  V2.3 has no runtime integration and cannot cause that V1 Quick Fiber path.
- Source benchmark files were opened read-only and never saved.

## Decision

Keep the V2.3 shared-world, topology memo, and array-capture work. They remove
real cold overhead without changing any curve. Do not enable V2 by default:
capture+cold still averages 247.60 ms, about 2.93x the direct V1 reference, and
seven of eight fixtures do not converge.

The next work should target fixed-point/contact correctness and successful
production convergence, not another cache layer. Native AOT capture/world build
is still valuable after that map is stable.

Implementation assumptions follow Blender's evaluated-ID contract
([Blender API](https://docs.blender.org/api/5.0/bpy.types.ID.html)) and NumPy's
contiguous array model
([NumPy documentation](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.flags.html)).
The packaged native boundary can be called without requiring an end-user compiler;
Python's FFI behavior is documented by
[`ctypes`](https://docs.python.org/3/library/ctypes.html).

## V2.4 C++ follow-up

The additive V2.4 experiment keeps V2.3 geometry exactly unchanged while
moving batch validation, topology classification, transforms, and collision
world construction behind one packaged C++ ABI. On the same eight production
fixtures, array-backed V2.3 totals 175.60 ms and V2.4 totals 143.44 ms on
average, an additional 18.31% cold reduction. See
[`fiber_v24_cpp_experiment.md`](fiber_v24_cpp_experiment.md) for the required
ablation, phase timings, visuals, and rollout decision.
