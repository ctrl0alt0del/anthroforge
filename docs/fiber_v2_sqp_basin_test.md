# FIBER_2 corrected span-SQP basin test

## Answer

No alternative converged basin was found for the current corrected span-SQP objective. Anti-local-
minimum machinery is therefore not justified as the next fix for the visible bump.

This is a multi-start test, not a proof that no other basin exists anywhere. It does show that the
meaningful collision-valid alternatives already available to Fiber do not reach a better minimum.
Planner and V1 starts converge to the same strict local minimum, and whole-SQP returns to the same
neighborhood. This is the behavior expected from multistart/local-minimization tests used to expose
separate attraction basins ([basin-hopping reference](https://arxiv.org/abs/cond-mat/9803344)).

## Fixture and contract

- File: `E:\development\WIP_models\fiber_sphere.blend`
- Fiber: `FIBER_2`
- Input SHA-256: `D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`
- Objective: exact sum of the four corrected fixed-span objectives.
- All five authored pins are eliminated exactly.
- Every seed is aligned and resampled through the same V2 pin indices.
- Every relaxation uses the same contact semantics and accepted-step cap of 180.
- Two runs per seed were bitwise deterministic.

## Results

| Seed | Seed valid | Result | Validated | Objective | Max distance from planner | Interpretation |
|---|---:|---|---:|---:|---:|---|
| Planner ROADMAP | yes | `CONVERGED` | yes | `630.7917826415` | `0` | Verified strict local minimum |
| V1 | yes | `CONVERGED` | yes | `630.7917829305` | `3.35e-6` | Same basin |
| Whole-SQP | yes | `STALLED` | yes | `630.7917034965` | `1.13e-5` | Same geometric neighborhood, unfinished |
| V2 BASE | yes | `STALLED` | yes | `630.7882772847` | `1.16e-4` | Not a minimum; consumes collision slack |
| Stored proxy | no | `NO_FEASIBLE_PATH` | no | `644.9364365304` | n/a | Cannot establish a basin |
| DIRECT | no | result-construction error | no | n/a | n/a | Exposes nonfinite-condition diagnostic bug |

Planner and V1 differ by only `3.35e-6` world units at the worst node, far below the
`1.0335e-4` basin-separation threshold. Their objective difference is `2.89e-7`.

The apparent V2 BASE improvement is not a second minimum:

- independent classification: `NOT_STATIONARY_DESCENT_CONFIRMED`;
- relative KKT stationarity residual: `9.02e-4`;
- confirmed feasible descent step: `1.03e-5` world units;
- exact contact gap: `-6.57e-6`, consuming 31.8% of the permitted clearance slack;
- energy advantage over the planner minimum: only `0.003505`, or `0.000556%`;
- worst free turn is slightly worse: `22.7194°` versus `22.7095°`.

The V2 BASE curve is therefore an unfinished, tolerance-shifted point—not evidence that an
anti-local-minimum search found a better path.

## Visual conclusion

The four valid results are visually coincident in the real Blender render. The overlay does not
show removal of the bump. The small V2 BASE displacement is numerically measurable but not a useful
shape improvement.

- Render: `.artifacts/sqp_basin/fiber2_comparison.png`
- Inspectable Blender copy: `.artifacts/sqp_basin/fiber2_comparison.blend`
- Full multistart data: `.artifacts/sqp_basin/fiber2.json`
- V2 BASE optimality data: `.artifacts/sqp_basin/fiber2_v2base_optimality.json`

## Decision

Do not add basin hopping, random restarts, or large perturbations yet. They would add planner-like
branching cost without evidence that the current objective contains a visually better minimum.

The next investigation should change or ablate the objective itself. In particular, the current
solver is not pure minimum length: it balances fidelity, length, and curvature. The bump can be the
correct minimum of that balance. Test fidelity and curvature behavior at active contact while
holding the collision core and exact pins fixed.
