# Fiber V2 Structural-Metric CCD Projection

## Outcome

The replacement experiment is collision-safe and removes most outer-loop CCD
rejections on sparse collision worlds. It does **not** improve the `FIBER_2` bump.

The experiment remains opt-in through `V2ContactExperiment`; production/default
behavior is unchanged.

## What changed

When CCD discovers a limiting pair, the experiment does not locally project the hit
edge and does not return immediately to contact refresh. It:

1. injects the limiting constraint into the current active set;
2. re-solves the full span in the existing structural length/curvature metric;
3. runs CCD on the new globally distributed direction;
4. repeats until the full proposal is certified or the bounded attempt aborts.

The inner loop is capped at six structural re-solves. Two consecutive unresolved
attempts disable it for that span. It is not activated when the CCD broad phase reports
more than 256 candidate pairs, because repeated CCD dominates in dense worlds.

This follows the same constrained-direction principle used by active-set SQP and the
feasibility-preserving CCD acceptance model used by IPC. Unlike the rejected local
surface projection, correction is distributed by the Fiber structural inverse.

## Synthetic result

The intersecting DIRECT-through-box fixture remains independently valid and converged:

| Variant | Accepted | Rejected | Projection solves |
|---|---:|---:|---:|
| Base | 22 | 2 | 0 |
| Structural CCD | 22 | 0 | 2 |

## Real Blender results

All timings are full solver timings after one shared immutable capture. Sphere timings
use multiple cold and warm repetitions. Every result passed independent static
collision validation.

| File / Fiber | Base warm | Projection warm | Delta | Base steps A/R | Projection steps A/R | Shape delta |
|---|---:|---:|---:|---:|---:|---:|
| `fiber_sphere/FIBER_2` | 247.27 ms | 240.76 ms | -2.63% | 36 / 34 | 37 / 1 | max 3.35e-6 |
| `fiber_sphere/FIBER_1` | 239.65 ms | 207.00 ms | -13.62% | 23 / 41 | 19 / 16 | max 7.11e-7 |
| `skeleton_comb_base/FIBER_1` | 1357.78 ms | 1383.22 ms | +1.87% | 57 / 48 | 57 / 48 | exactly zero |

Cold timing changes were -3.30%, -14.09%, and +1.08%, respectively.

On the dense skeleton case, the activation rule skipped all 48 limiting events. There
were zero projection solves and point-identical output. The small timing difference is
therefore process/run noise plus the constant-time candidate-count check, not numeric
work from the experiment.

## FIBER_2 quality

The measured internal turn is unchanged:

- Base node-10 turn: 22.70948 degrees.
- Structural-CCD node-10 turn: 22.70919 degrees.
- Maximum point displacement: 0.00000335 world units.

The overlay is visually coincident. The new scheduling reaches essentially the same
constrained stationary point with fewer rejected outer proposals. This proves that the
bump is not caused by loss of the CCD limiter alone. With the present objective and
linearized contact model, it is the solver's chosen constrained solution.

## Decision

This is a useful sparse-case convergence/performance technique, but it is not a shape
fix. It should not be promoted as the answer to the unevenness problem. A real shape
change requires changing the local contact model or the objective around the obstacle;
reordering the same structural/contact solve cannot produce a materially different
stationary path.

## Artifacts

- `.artifacts/fiber_v2_dynamic_step/sphere_f2_structural_ccd_bounded.json`
- `.artifacts/fiber_v2_dynamic_step/sphere_f2_structural_ccd_bounded.png`
- `.artifacts/fiber_v2_dynamic_step/sphere_f2_structural_ccd_bounded.blend`
- `.artifacts/fiber_v2_dynamic_step/sphere_f1_structural_ccd_bounded.json`
- `.artifacts/fiber_v2_dynamic_step/skeleton_f1_structural_ccd_sparse_gate.json`
