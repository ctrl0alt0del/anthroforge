# Fiber V3 transverse-corridor experiment

Status: isolated negative experiment, not imported by production, measured 2026-08-19.

## Hypothesis

The scalar V3 first pass constrains each node to the `DIRECT[i]--ROADMAP[i]` line. The proposed second pass adds the missing perpendicular direction:

- `C[i]`: independently valid first-pass result;
- `Z[i]`: tangent of `C`;
- `X[i]`: projected `DIRECT[i]--ROADMAP[i]` direction;
- `Y[i] = Z[i] × X[i]`;
- `S[i] = C[i] + beta[i] Y[i]`.

Degenerate frames at hard pins are filled by rotation-minimizing parallel transport. This avoids the Frenet-frame singularity and unnecessary normal-plane rotation described by [rotation-minimizing/Bishop frames](https://onlinelibrary.wiley.com/doi/abs/10.1111/sapm.12275).

For each free node, the experiment samples the connected collision-free interval containing `beta=0`:

`beta_min[i] <= beta[i] <= beta_max[i]`.

It constructs lower, upper, and smoothed middle curves from those intervals. The second layered search spans the complete interval, includes the first-pass point and middle target explicitly, applies the existing length/curvature objective plus a midpoint preference, and uses the same native collision world, CCD acceptance, owner contacts, and independent final validator as pass one. Hard-pin intervals are exactly zero.

This follows the general safe-corridor pattern of separating a collision-free corridor from the trajectory optimized inside it. Safe-corridor methods use connected convex regions for this reason; independently safe samples are not sufficient to certify connecting edges. See [Safe Flight Corridor constrained optimization](https://www.sciencedirect.com/science/article/pii/S1000936124003078).

## Result

The hypothesis fails on the target `fiber_sphere/FIBER_2` kink.

The transverse interval exists and every reported candidate passes independent validation. However, the useful smoothing direction for the problematic turn lies primarily back in the `D--R` surface. Moving only along `Y` either leaves the curve unchanged or distributes the original sharp turn over neighboring nodes.

The smoothed middle curve demonstrates the limit clearly:

- free maximum turn improves from 137.40 to 77.70 degrees;
- free p95 turn remains 33.22 degrees;
- length grows from 23.0162 to 23.5823, or 2.46%;
- it creates visible transverse envelope excursions.

The actual optimized candidate remains much closer to the first-pass curve because its structural objective correctly rejects those distributed bends.

## Midpoint-weight sweep

| Midpoint weight | Free maximum turn | Free p95 turn | Interpretation |
|---:|---:|---:|---|
| 1 | 137.40 deg | 33.22 deg | effectively unchanged |
| 50 | 136.64 deg | 33.22 deg | negligible local reduction |
| 500 | 136.25 deg | 39.56 deg | spreads the kink and worsens overall quality |

The retained experimental weight is 50 because it is the strongest tested value that does not regress p95. Its result still fails the quality acceptance rule and therefore preserves pass one.

## Real-file timing

Blender 5.0.1, `fiber_sphere.blend/FIBER_2`, 64 nodes, five pass-two repetitions. Source remained byte-identical with SHA-256 `D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

| Path | Time | Free max turn | Free p95 turn | Accepted |
|---|---:|---:|---:|---|
| V2 cold | 108.04 ms | 117.45 deg | 9.65 deg | independently valid |
| V3 pass one cold | 146.93 ms | 137.40 deg | 33.22 deg | independently valid |
| Pass two full | 105.05 ms median | 136.64 deg | 33.22 deg | no |
| Pass two windowed | 118.94 ms median | 137.40 deg | 33.22 deg | no |

Full two-pass latency is about 251.98 ms. The full pass spends approximately 17.97 ms constructing intervals, 71.51 ms on its layered seed, 14.41 ms refining, and 2.55 ms validating. The windowed pass is not faster overall because its selected candidate triggers more continuous refinement trials.

## Conclusion

Do not integrate this second pass into V3 production. It adds roughly 105 ms without fixing the target kink.

The experiment also disproves the assumption that the missing `Y` coordinate alone explains the kink. The next representation, if pursued, must allow coupled changes of the in-surface `alpha` and transverse `beta` coordinates. Running separate fixed-alpha and fixed-beta passes cannot reach that coupled solution. A dense two-dimensional grid would be too expensive; a future experiment would need continuous two-coordinate optimization or alternating updates with a monotonic joint merit and the same CCD validator.

## Artifacts

- Implementation: `core/vcp/v3_transverse_experiment.py`
- Benchmark: `tools/fiber_v3_transverse_experiment.py`
- Renderer: `tools/fiber_v3_transverse_render.py`
- Tests: `tests/unit/test_fiber_v3_transverse_experiment.py`
- Data: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_transverse.json`
- Comparison: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_transverse.png`
- Inspectable blend: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_transverse.blend`

The production selector, solver, cache, UI, and publication paths remain unchanged.
