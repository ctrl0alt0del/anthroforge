# Fiber V2 subfiber-SQP experiment

## Status and verdict

SQP and subfiber-SQP are opt-in experiments. Production `solve_v2()` still calls
the collision core with `use_filter_sqp=False`; only the benchmark controllers
`SQP` and `SPAN_SQP` enable them.

Splitting at authored midpoints is mathematically valid because those points are
hard pins. With the shared pin values fixed, the structural/contact problem is a
set of independent span problems. The implementation advances their resumable
sessions round-robin, which is mathematical concurrency without threads.

The experiment is a partial quality success and a performance failure:

- it gives hard rerouter semantics to midpoints and removes curvature coupling
  across them;
- every measured stitched output is independently collision-valid;
- it does not make `sphere/FIBER_2` converge sooner;
- current Python/native orchestration is 1.36--1.79 times slower than whole-SQP
  on the multi-span cases;
- one-span controls are geometrically identical to whole-SQP, as required.

Do not promote `SPAN_SQP` to production in this form.

## Algorithm

1. Build DIRECT and the collision world once for the whole Fiber.
2. Run the optional planner once and exact-resample its result once.
3. Partition node indices at every authored hard anchor.
4. Convert each pair of adjacent hard anchors into a local endpoint pair.
5. Give each span its exact slice of the shared seed and node count.
6. Run one collision-core SQP session per span against the shared collider snapshot.
7. Advance unfinished sessions once per outer round.
8. Stitch spans while retaining each shared hard pin only once.
9. Aggregate validation and diagnostics; the whole result converges only when
   every span converges.

The structure can later become a batched block-diagonal native solve. The present
experiment deliberately retains separate native contact/CCD calls so its quality
effect can be measured before implementing that optimization.

Relevant approaches:

- [Trajectory Splitting by ADMM](https://arxiv.org/abs/2111.01899) demonstrates
  parallel subproblem execution with coupling variables. Fiber does not need
  ADMM at exact authored pins because the boundary values are already fixed.
- [Batched pentadiagonal linear systems](https://arxiv.org/abs/1807.07382)
  supports the later implementation direction for solving independent Fiber
  spans as one native batch.

## Current-state benchmark

Blender 5.0.1, Windows workstation, cap 60, two timed warm repetitions, fresh
Blender process per fixture. Each process captures once and runs BASE, whole-SQP,
and span-SQP against the same immutable request and collider snapshot. Source
`.blend` files were opened read-only.

| Fixture | BASE | Whole SQP | Span SQP | Span/whole |
|---|---:|---:|---:|---:|
| `sphere/FIBER_2` | 2666.77 ms | 484.94 ms | 869.44 ms | 1.79x |
| `skull/FIBER_1` | 5092.69 ms | 239.92 ms | 326.83 ms | 1.36x |
| `skull/FIBER_14` | 2816.50 ms | 174.67 ms | 210.88 ms | 1.21x |
| `skeleton/FIBER_1` | 7834.61 ms | 852.18 ms | 859.20 ms | 1.01x |

The current BASE timings are not the historical 124--403 ms measurements. BASE
now reaches the trial guard with 467--478 rejected trials, so reusing the older
numbers would be misleading. This is a separate current-state BASE regression,
not a cost introduced by subfiber-SQP.

| Fixture/controller | Termination | Accepted/rejected | Valid |
|---|---|---:|---:|
| sphere BASE | `BUDGET_EXHAUSTED` | 13 / 467 | yes |
| sphere SQP | `BUDGET_EXHAUSTED` | 60 / 12 | yes |
| sphere span-SQP | `BUDGET_EXHAUSTED` | 184 / 14 | yes |
| skull F1 BASE | `BUDGET_EXHAUSTED` | 8 / 472 | yes |
| skull F1 SQP | `CONVERGED` | 12 / 11 | yes |
| skull F1 span-SQP | `STALLED` | 12 / 33 | yes |
| skull F14 SQP/span | `STALLED` | 7 / 18 each | yes |
| skeleton F1 SQP/span | `BUDGET_EXHAUSTED` | 60 / 5 each | yes |

## Per-span convergence

`sphere/FIBER_2` has five authored anchors and four independent spans:

| Span nodes | Cap-60 result | Accepted/rejected | Completion round |
|---|---|---:|---:|
| 0--12 | `BUDGET_EXHAUSTED` | 60 / 7 | 71 |
| 12--32 | `CONVERGED` | 4 / 2 | 10 |
| 32--56 | `BUDGET_EXHAUSTED` | 60 / 2 | 66 |
| 56--63 | `BUDGET_EXHAUSTED` | 60 / 3 | 67 |

At cap 200, span 12--32 still converges at step 4 and span 32--56 converges at
step 189. Spans 0--12 and 56--63 remain unfinished after 200 accepted steps.
The cap-200 wall time is 2556.06 ms. Its rendered curve is only marginally
different from cap 60. A cap-1000 attempt does not establish convergence: the
contact Schur system becomes too ill-conditioned for valid diagnostics. Waiting
longer is therefore not a valid quality strategy for this controller.

`skull/FIBER_1` has three spans. Span 0--29 converges at 7 accepted steps. Spans
29--46 and 46--63 stall after 1/10 and 4/19 accepted/rejected steps, with Schur
condition estimates of `1.65e16` and `4.49e16`. Splitting isolates the bad spans,
but does not cure their rank/conditioning problem.

## Geometry measurements

Turning angles exclude authored hard-pin nodes, because a kink is intentional at
a hard rerouter. Smaller unpinned angles are smoother.

| Fixture/controller | Path length | Worst unpinned turn | p95 unpinned turn |
|---|---:|---:|---:|
| sphere BASE | 32.627868 | 150.25° | 36.48° |
| sphere SQP | 20.703192 | 26.75° | 18.32° |
| sphere span-SQP | 21.141388 | 66.10° | 21.79° |
| skull F1 BASE | 0.703526 | 18.23° | 14.54° |
| skull F1 SQP | 0.704677 | 4.96° | 3.63° |
| skull F1 span-SQP | 0.699549 | 10.51° | 5.88° |

For sphere, the turns at the three hard midpoints are 9.78°/29.03°/7.25° under
whole-SQP and 38.01°/88.63°/42.54° under span-SQP. This confirms that splitting
actually removes the cross-midpoint smoothing stencil. It also exposes a 66.10°
unpinned turn inside the first span, so the subfiber result is not yet finished.

The one-span skull F14 and skeleton controls produce point-for-point equivalent
whole-SQP and span-SQP results. The wrapper itself does not change a Fiber that
has no midpoint partition.

## Artifacts

- `../.artifacts/fiber_v2_dynamic_step/sphere_f2_span_sqp.png`
- `../.artifacts/fiber_v2_dynamic_step/sphere_f2_span_sqp_cap200.png`
- `../.artifacts/fiber_v2_dynamic_step/skull_f1_span_sqp.png`
- `../.artifacts/fiber_v2_dynamic_step/skeleton_f1_span_sqp.png`
- `../.artifacts/fiber_v2_dynamic_step/sphere_f2_compare.json`
- `../.artifacts/fiber_v2_dynamic_step/skull_f1_compare.json`
- `../.artifacts/fiber_v2_dynamic_step/skull_f14_compare.json`
- `../.artifacts/fiber_v2_dynamic_step/skeleton_f1_compare.json`

## Verification

- 551 unit tests pass; six skipped and one expected failure.
- 57 focused V2 collision/contact/structural tests pass.
- Function-size ratchet passes with no new violations.
- Experiment modules and tools compile.
- Real Blender runs returned collision-valid outputs and did not save source files.

## Recommended next decision

Keep the partition semantics, not this execution strategy. If hard rerouter
midpoints are the contract, production should remove bend stencils across those
pins directly. For speed, use one fused native batched span solve and one batched
contact/CCD query, rather than independent Python sessions. Before that work,
fix the rank-deficient SQP contact system and the current BASE rejected-trial
regression; otherwise batching merely makes an unfinished algorithm cheaper.
