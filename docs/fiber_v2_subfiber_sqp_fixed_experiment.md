# Fiber V2 corrected span-SQP experiment

## Decision

Keep `SPAN_SQP_FIXED` as an opt-in experiment. The correction succeeds at its
primary purpose: it removes the severe non-midpoint zigzag on
`fiber_sphere/FIBER_2`, preserves intentional hard-midpoint hinges, produces a
slightly shorter path than whole-SQP, and uses less wall time on that fixture.

It is not ready for production. Two sphere spans still consume the shared budget
without meeting the residual tolerance, and `skull/FIBER_1` stalls where
whole-SQP converges.

Production `solve_v2()` remains unchanged.

## Corrected formulation

For a full Fiber with `N` nodes and a span with `n` nodes, the old experiment
recomputed `h=1/(n-1)`. That weakened the first sphere span's curvature by about
145 times and its last span's curvature by about 729 times.

The corrected span request rescales stored weights by

\[
w_{L,s}=w_L\frac{N-1}{n-1},\qquad
w_{B,s}=w_B\left(\frac{N-1}{n-1}\right)^3.
\]

Consequently, every local `wL/h` and `wB/h^3` coefficient exactly matches the
full Fiber. Algebraic tests verify that the assembled free-node matrix equals the
whole-Fiber matrix with only the single `D2` row crossing each hard midpoint
removed.

The corrected controller also:

- synchronizes one owner-contact interval across every span each outer round;
- shares the immutable collider world and planner seed;
- advances spans round-robin;
- applies one aggregate accepted-step cap instead of one cap per span;
- independently validates every span before stitching.

This is consistent with fourth-order domain-decomposition work, where interface
conditions and the strongly `h`-dependent interface system must be handled
explicitly:

- [Domain Decomposition for Fourth-Order Problems](https://doi.org/10.1137/0730021)
- [Domain decomposition interface preconditioners for fourth-order elliptic problems](https://doi.org/10.1016/0168-9274(91)90072-8)

## Same-process performance comparison

Blender 5.0.1, accepted-step cap 60, two warm repetitions. Every controller in a
row used the same captured request and collider snapshot in one Blender process.

| Fixture | BASE | Whole SQP | Old span-SQP | Corrected span-SQP |
|---|---:|---:|---:|---:|
| `sphere/FIBER_2` | 3244.75 ms | 609.80 ms | 1035.26 ms | **427.44 ms** |
| `skull/FIBER_1` | 5820.86 ms | **219.45 ms** | 324.72 ms | 308.74 ms |

On the sphere, corrected span-SQP is 29.9% faster than whole-SQP and 58.7%
faster than the old span experiment. On skull F1 it remains 40.7% slower than
whole-SQP, though it is 4.9% faster than the old span experiment.

Single-span controls produce exactly the same points as whole-SQP:

| Fixture | Whole SQP | Corrected span-SQP | Maximum point delta |
|---|---:|---:|---:|
| `skull/FIBER_14` | 175.80 ms | 206.91 ms | 0 |
| `skeleton/FIBER_1` | 945.25 ms | 929.80 ms | 0 |

The timing differences on single-span controls are run variance and wrapper
overhead; geometrically the controller is a no-op when there is no midpoint.

## Geometry

Turning-angle measurements exclude authored hard midpoint nodes.

| Sphere controller | Path length | Worst interior turn | p95 interior turn |
|---|---:|---:|---:|
| Whole SQP | 20.703192 | 26.75° | 18.32° |
| Old span-SQP | 21.141388 | 66.10° | 21.79° |
| Corrected span-SQP | **20.674072** | **33.67°** | **18.22°** |
| Corrected, cap 240 | **20.580856** | **31.69°** | **16.13°** |

The original unwanted node-9 turn falls from 66.10° to 33.67°. The three
authored midpoint turns remain intentionally free: corrected span-SQP gives
31.65° / 86.60° / 55.08°, compared with whole-SQP's smoothed
9.78° / 29.03° / 7.25°.

For skull F1, corrected span-SQP nearly restores whole-SQP's within-span
smoothness:

| Controller | Path length | Worst interior turn | p95 interior turn |
|---|---:|---:|---:|
| Whole SQP | 0.704677 | 4.96° | 3.63° |
| Old span-SQP | 0.699549 | 10.51° | 5.88° |
| Corrected span-SQP | 0.703463 | 5.04° | 3.68° |

## Convergence

Sphere at one shared cap of 60:

| Span | Termination | Accepted/rejected |
|---|---|---:|
| 0--12 | budget exhausted | 17 / 6 |
| 12--32 | converged | 4 / 2 |
| 32--56 | budget exhausted | 19 / 4 |
| 56--63 | budget exhausted | 20 / 3 |

At shared cap 240, span 32--56 converges at accepted step 25. Spans 0--12 and
56--63 remain unfinished after 104 and 107 accepted steps. Their residuals stop
near `2.69e-5` and `2.44e-5`; more budget still does not provide a proper stop.

Skull F1 improves from two stalled spans under the old experiment to two
converged spans under the corrected controller. Span 0--29 still stalls after
4 accepted and 13 rejected steps, so the stitched result truthfully remains
`STALLED`. Whole-SQP remains superior on this fixture because its cross-midpoint
system converges globally.

## Visual artifacts

- `../.artifacts/fiber_v2_dynamic_step/sphere_f2_span_sqp_fixed.png`
- `../.artifacts/fiber_v2_dynamic_step/sphere_f2_span_sqp_fixed_cap240.png`
- `../.artifacts/fiber_v2_dynamic_step/skull_f1_span_sqp_fixed.png`
- inspectable `.blend` files with the same basenames;
- `../.artifacts/fiber_v2_dynamic_step/sphere_f2_fixed_compare.json`;
- `../.artifacts/fiber_v2_dynamic_step/skull_f1_fixed_compare.json`.

All source `.blend` hashes remain unchanged.

## Verification

- Corrected global coefficient equivalence test passes.
- Free-node matrix differs from whole-SQP only by the intended cross-pin `D2` row.
- Shared accepted-step cap test passes.
- 60 focused V2 collision/contact/structural tests pass.
- Function-size ratchet passes with no new violation.
- Real Blender outputs are finite, exact-count, and independently collision-valid.

## Next technical blocker

The scaling bug is fixed. The remaining defect is no longer the midpoint split:
some individually safe spans accept many steps while their fixed-point residual
stays nearly constant. The next experiment should correct SQP progress and
termination inside a span, not add more curvature or planner patches.
