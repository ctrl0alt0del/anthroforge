# Fiber V2 composite-step feasible SQP + SOC ablation

## Verdict

The experiment is implemented and isolated from the default `BASE` span-SQP path.
The result is mixed and does **not** justify replacing BASE:

- Tangential-only is structurally incomplete. It cannot remove normal contact error and
  produces severe route artifacts.
- Normal-first composite stepping is robust in principle, but its trust allocation
  starves the tangential shortening step in dense contact. It stalls or consumes the
  full budget.
- Nonlinear second-order correction repairs that composite-step failure and restores
  convergence, but it does not improve the target `fiber_sphere/FIBER_2` shape. It
  reproduces BASE within 0.00000335 world units and costs 59% more warm time.
- SOC is useful as a convergence safeguard on some other Fibers. It changed
  `fiber_sphere/FIBER_1` from safe `STALLED` to `CONVERGED` and reduced warm time by
  24%, but did not materially change its already-good shape.

The correct conclusion is: keep the experiment available for diagnosis, do not enable
it in production, and do not expect composite-step SQP or SOC to solve the remaining
FIBER_2 tightness/bump defect. SOC changes how the optimizer reaches a constrained
stationary point; it does not change that stationary point's objective.

## Scientific basis

The experiment separates normal feasibility work from tangential objective work in the
style of feasible/trust-region SQP, then evaluates nonlinear constraints at the trial
point and adds a small correction for the linearization defect. This addresses the
Maratos-effect mechanism without bypassing Fiber's native CCD or final validation.

- Tenny and Wright, feasible trust-region SQP:
  <https://epubs.siam.org/doi/10.1137/S1052623402413227>
- Berahas, Bollapragada, and Shi, modified line-search SQP with second-order correction:
  <https://arxiv.org/abs/2406.11144>

This is an AnthroForge-specific implementation, not a verbatim implementation of either
paper.

## Controlled variants

All rows use the same captured request, ROADMAP seed, collider snapshot, hard pins,
accepted-step cap, native CCD, validation, and cameras.

1. `BASE`: unchanged corrected span-SQP.
2. `TANGENTIAL`: retain only the active-contact null-space component and fit it to the
   existing trust radius.
3. `COMPOSITE`: apply the normal component first, then admit the largest tangential
   fraction that still fits the trust radius.
4. `COMPOSITE_SOC`: evaluate nonlinear contact gaps at the composite proposal, solve a
   minimum-norm correction for negative nonlinear residuals, cap it to half the trust
   radius, then run the same CCD and independent validator as BASE.

The experiment records variant, normal/tangential fractions, SOC magnitude and time,
accepted/rejected steps, CCD limiter injections, contact state, geometry, and full
iteration traces.

## Mechanism tests

The intersecting-box unit fixture confirms that each component does something distinct:

| Variant | Accepted / rejected | Result | Interpretation |
|---|---:|---|---|
| BASE | 22 / 2 | `CONVERGED`, valid | Existing monolithic active-set result |
| TANGENTIAL | 5 / 10 | `STALLED`, valid | Cannot remove normal violation by itself |
| COMPOSITE | 11 / 9 | `STALLED`, valid | Feasibility priority alone does not resolve nonlinear contact switching |
| COMPOSITE + SOC | 15 / 2 | `CONVERGED`, valid | Nonlinear correction restores convergence |

Dedicated unit tests also verify that tangential-only does not fake feasibility, the
normal component reduces predicted violation, SOC cancels a constructed nonlinear gap,
pins remain exact, and every ablation passes through the same validating core.

## Real-file timing and geometry

Timings are medians in a read-only Blender 5.0.1 process. The table reports
`cold / warm` milliseconds, followed by accepted/rejected steps. Early-stalled variants
must not be interpreted as performance wins.

### `fiber_sphere.blend / FIBER_2`

| Variant | Cold / warm | Status | Steps | Length | Worst free turn | Max delta from BASE |
|---|---:|---|---:|---:|---:|---:|
| BASE | 341.33 / 347.59 ms | `CONVERGED` | 36 / 34 | 20.392520 | 22.709° | 0 |
| TANGENTIAL | 412.90 / 423.28 ms | `STALLED` | 30 / 64 | 21.781278 | 112.631° | 1.272462 |
| COMPOSITE | 1302.55 / 1292.54 ms | `BUDGET_EXHAUSTED` | 120 / 114 | 20.400929 | 23.535° | 0.379735 |
| COMPOSITE + SOC | 572.28 / 552.67 ms | `CONVERGED` | 57 / 49 | 20.392522 | 22.709° | 0.00000335 |

Composite's median admitted tangential fraction fell to `0.099`; it caused 107 limiting
contact injections and spent the full global budget. SOC raised the median admitted
tangential fraction to `0.482`, applied a nonzero correction 60 times, and restored
convergence. The final result nevertheless returned to BASE's constrained stationary
point, so the visible bump/tightness did not improve.

### `fiber_sphere.blend / FIBER_1` control

| Variant | Cold / warm | Status | Steps | Length | Worst free turn | Max delta from BASE |
|---|---:|---|---:|---:|---:|---:|
| BASE | 341.26 / 330.72 ms | `STALLED` | 23 / 41 | 6.569446 | 2.338° | 0 |
| TANGENTIAL | 591.98 / 583.64 ms | `STALLED` | 41 / 87 | 7.249837 | 62.764° | 0.812767 |
| COMPOSITE | 435.82 / 444.97 ms | `STALLED` | 27 / 39 | 6.569446 | 2.338° | 0.00000087 |
| COMPOSITE + SOC | 280.17 / 250.18 ms | `CONVERGED` | 29 / 5 | 6.569443 | 2.338° | 0.00038985 |

Here SOC is genuinely helpful as a convergence safeguard: it removes most rejections
and reaches the same good geometry faster.

### `skeleton_comb_base.blend / FIBER_1` complex control

| Variant | Cold / warm | Status | Steps | Length | Worst free turn | Max delta from BASE |
|---|---:|---|---:|---:|---:|---:|
| BASE | 2210.45 / 2132.62 ms | `CONVERGED` | 57 / 48 | 6.625980 | 20.027° | 0 |
| TANGENTIAL | 864.26 / 781.44 ms | `STALLED` | 8 / 29 | 6.690990 | 47.722° | 0.450177 |
| COMPOSITE | 569.77 / 528.10 ms | `STALLED` | 7 / 18 | 7.601882 | 121.847° | 1.106682 |
| COMPOSITE + SOC | 2266.19 / 2251.78 ms | `CONVERGED` | 57 / 42 | 6.617051 | 19.366° | 0.150929 |

Composite alone appears fast only because it stops after producing an unacceptable
angular path. SOC restores a valid converged route, shortens it by 0.135%, reduces the
single worst free turn by 3.3%, and costs 5.6% more warm time. Its free-turn p95 is
slightly worse, so this is not an unqualified geometry improvement.

## Reproducibility

- `fiber_sphere.blend` SHA-256:
  `D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`
- `skeleton_comb_base.blend` SHA-256:
  `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`
- Both use 64 nodes. The sphere capture contains 972 triangles; the skeleton capture
  contains 39,180 triangles.
- Source `.blend` files were never saved.

Artifacts:

- `artifacts/fiber_v2_composite_sqp/fiber_sphere_fiber2.json`
- `artifacts/fiber_v2_composite_sqp/fiber_sphere_fiber2.png`
- `artifacts/fiber_v2_composite_sqp/fiber_sphere_fiber2_visual.blend`
- `artifacts/fiber_v2_composite_sqp/fiber_sphere_fiber1.json`
- `artifacts/fiber_v2_composite_sqp/skeleton_fiber1.json`
- `artifacts/fiber_v2_composite_sqp/skeleton_fiber1.png`
- `artifacts/fiber_v2_composite_sqp/skeleton_fiber1_visual.blend`

## Verification

- `python -m unittest tests.unit.test_fiber_v2_composite_sqp tests.unit.test_fiber_v2_contact_core`:
  30 tests passed.
- `python -m unittest discover -s tests/unit -p 'test_fiber_v2_*.py'`:
  164 tests passed.
- New and modified functions remain at or below 15 lines.
- The default `V2ContactExperiment()` selects `BASE`; no production engine selector or
  UI behavior changed.
