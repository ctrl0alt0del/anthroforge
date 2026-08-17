# Fiber V2.4 C++ Cold-Preparation Experiment

Date: 2026-08-17

Status: **retain as an opt-in structural optimization; do not roll V2 out**.

## Question and scope

V2.4 tests whether the cold collision-preparation work left in V2.3 benefits
from moving across one coarse native boundary. It does not change the planner,
candidate map, collision policy, CCD acceptance, validation, or convergence
rules. Consequently, V2.3 and V2.4 must return the same points exactly.

The packaged Windows DLL now accepts every immutable collider array in one
call. C++ validates indices and finite values, classifies open/closed topology,
applies transforms, and commits one native collision world. Python retains
Blender evaluated-mesh capture and owns the immutable request boundary.

End users do not install Visual Studio, a compiler, a C++ executable, or a
service. AnthroForge ships the 200,192-byte `af_fiber_ccd.dll`. A compiler is
needed only by developers rebuilding the binary.

## Implementation boundary

- `native/fiber_ccd/af_fiber_planner43.hpp` implements the batch C ABI and
  native topology classification.
- `core/vcp/v2/collision_native.py` binds the additive capability and fails
  closed when it is unavailable.
- `core/vcp/v2/contracts.py` adds an immutable, contiguous, array-backed
  collider contract.
- `core/vcp/v2/collision.py` builds a known-topology snapshot from the flags
  returned by the same native world.
- `core/vcp/v2/solver_v24.py` injects that world into the unchanged V2.3
  planner/solver pipeline and owns an independent route cache.

The ABI uses fixed-width C-compatible arrays and explicit counts. This follows
Microsoft's exported-DLL guidance and NumPy's contiguous-array C boundary:
[Microsoft DLL exports](https://learn.microsoft.com/en-us/cpp/build/reference/export-exports-a-function?view=msvc-170),
[Microsoft DLL walkthrough](https://learn.microsoft.com/en-us/cpp/build/walkthrough-creating-and-using-a-dynamic-link-library-cpp?view=msvc-170),
and [NumPy C API](https://numpy.org/doc/stable/user/c-info.how-to-extend.html).

## Benchmark protocol

- Blender 5.0.1, Windows x64, fresh `--background --factory-startup` process.
- The add-on is explicitly registered after each read-only production file is
  opened so cold measurements do not inherit file-load hydration caches.
- Five cold and five warm repetitions per V2 variant.
- `V1 direct` is the first direct legacy solver call after registration. It is
  a latency reference, not a quality-equivalent result and is currently one
  observation rather than a five-run median.
- `Total` means request capture plus isolated cold solve. It excludes the
  125 ms quiet window, viewport scheduling, commit, and downstream drivers.
- `V2.3 array` is the required ablation: the V2.3 solver receives the same
  array-backed request as V2.4 but does not use the new C++ batch entry point.

Benchmark inputs remained byte-identical:

| File | SHA-256 |
|---|---|
| `skull_muscles.blend` | `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06` |
| `skull_muscles_skin.blend` | `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96` |
| `skeleton_comb_base.blend` | `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42` |
| packaged DLL | `37BB9003171DB73F67701393466E0A61A7B84B2A0292DEE90ED5580A541B1617` |

## Full cold benchmark

All values are milliseconds.

| Fixture | V1 direct | V2.3 tuple total | V2.3 array total | V2.4 C++ total |
|---|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 163.66 | 419.96 | 270.30 | 234.15 |
| Skull-skin/FIBER_1 | 182.29 | 381.89 | 190.29 | 147.31 |
| Skull/FIBER_1 | 141.98 | 332.55 | 169.71 | 141.27 |
| Skull/FIBER_13 | 214.12 | 244.52 | 101.48 | 68.85 |
| Skull/FIBER_14 | 185.04 | 267.57 | 137.48 | 105.94 |
| Skull/FIBER_22 | 216.72 | 251.79 | 119.18 | 89.14 |
| Skull/FIBER_4 | 155.93 | 338.02 | 201.81 | 176.56 |
| Skull/FIBER_9 | 142.87 | 340.53 | 214.59 | 184.28 |
| **Mean** | **175.33** | **322.10** | **175.60** | **143.44** |

V2.4 reduces mean capture-plus-cold time by **55.47%** relative to tuple-based
V2.3. The ablation attributes that result as follows:

- tuple capture to array capture: `129.09 -> 21.20 ms`, **83.58% lower**;
- V2.3 tuple cold solve to V2.3 array cold solve: `193.01 -> 154.41 ms`,
  **20.00% lower**;
- V2.3 array total to V2.4 native total: `175.60 -> 143.44 ms`,
  **18.31% lower**;
- V2.3 array cold solve to V2.4 native cold solve: `154.41 -> 122.24 ms`,
  **20.83% lower**.

The C++ contribution is therefore real but smaller than the array-boundary
contribution. It is not valid to attribute the entire 55.47% to C++.

Against the factory-cold V1 direct reference, V2.4 is 18.19% lower on the
eight-fixture mean. That is not a universal win: V2.4 is slower on
Skeleton/FIBER_1, Skull/FIBER_4, and Skull/FIBER_9. It also excludes the live
runtime work listed above, so it must not be described as a faster complete
product cycle.

## Where the time changed

These are representative phase observations from the final cold samples, not
medians. Nested phase timers can overlap.

| Phase | V2.3 tuple | V2.3 array | V2.4 C++ |
|---|---:|---:|---:|
| Snapshot/topology | 73.55 | 61.15 | 18.70 |
| Native world | 25.57 | 13.45 | 20.50 |
| Planner | 30.24 | 21.59 | 21.78 |
| Candidate/contact | 22.50 | 23.68 | 21.84 |
| CCD | 34.92 | 35.43 | 33.88 |
| Independent validation | 3.35 | 3.13 | 3.25 |

Native classification plus known-topology snapshot assembly cuts the remaining
array snapshot phase by 69.42%, saving about 42.45 ms. The native-world row is
7.05 ms higher than the array V2.3 row because V2.4 performs topology validation
inside the batch call while V2.3 consumes an already memoized Python result.
The net cold gain remains about 32 ms.

Planner, candidate/contact, CCD, and independent validation are intentionally
unchanged. V2.4 is therefore a cold preparation experiment, not a solver-map
optimization.

Warm solve time changes only `56.92 -> 55.94 ms` (**1.72%**), confirming that
V2.3 already cached the work moved into C++.

## Correctness and visual comparison

Across all eight production fixtures:

- maximum V2.3/V2.4 coordinate delta is exactly `0.0`;
- route, termination reason, and validation state are identical;
- V2.4 uses one native batch-world construction per solve;
- collider arrays are immutable and generation-keyed.

The left-to-right review renders show V1 in orange, V2.3 in green, and V2.4 in
purple. Green and purple overlap exactly; any visible V1 difference predates
V2.4.

- `artifacts/fiber_v24/skull_f14.png` and `skull_f14_review.blend`;
- `artifacts/fiber_v24/skull_f4.png` and `skull_f4_review.blend`;
- `artifacts/fiber_v24/skeleton_f1.png` and `skeleton_f1_review.blend`;
- `artifacts/fiber_v24/skin_f1.png` and `skin_f1_review.blend`.

Termination remains unchanged: only Skull/FIBER_13 converges;
Skeleton/FIBER_1 exhausts its budget; the other six fixtures are blocked. Every
listed result passes the existing independent validator. C++ does not repair
the fixed-point/contact direction, compatibility, or anatomical-shape issues.

## Qualification

- Focused V2.4/V2.3/collision suite: 50/50 passed.
- Complete unit suite: 476 tests passed, six optional-native skips, one known
  expected warm/cold fixed-point failure.
- Function-size and architecture guardrail: passed; no new or modified Python
  function exceeds 15 lines.
- Full Blender discovery: 473/474 passed. The sole error is the pre-existing,
  reproducible Quick Fiber persistence case where an unsafe/nonconverged
  preview does not write `af_fiber_points_world`. V2.4 has no production
  runtime caller and did not introduce that failure.
- Source `.blend` hashes are unchanged.

## Decision

Retain the array-backed immutable contract and the native batch/topology API.
They are credible infrastructure for V2 and remove measurable cold overhead
without changing a curve. Keep V2.4 isolated and opt-in.

Do not roll out V2 on this result. The next priority is not more native capture
work; it is the fixed-point/contact direction and exact-count compatibility.
Once those produce acceptable, converged paths, integrate the retained native
boundary into one complete live event-to-commit benchmark. Blender geometry
must still be captured from evaluated dependency-graph state on the main thread
([Blender evaluated ID API](https://docs.blender.org/api/5.0/bpy.types.ID.html)).
