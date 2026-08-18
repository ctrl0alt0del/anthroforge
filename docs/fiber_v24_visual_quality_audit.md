# Fiber V2.4 Visual Quality Audit

Date: 2026-08-17

Status: V2.4 is the retained performance baseline. This audit defines the next
quality work; it does not change production Fiber behavior.

## Visual legend and protocol

Every authored open Fiber in the three supplied production files was evaluated
through the isolated V2.4 solver using one immutable native collision snapshot
per file. Source files were opened read-only and remained byte-identical.

- orange: currently stored Fiber shape;
- cyan: validated V2.4 exact-count planner reference;
- purple: independently validated V2.4 final result;
- yellow: authored hard pins;
- dark transparent triangles: nearby V2 collision geometry.

The contact sheets include failures instead of silently omitting them. Editable
Blender reviews are stored beside each PNG.

| File | Fibers | Visual | Editable review |
|---|---:|---|---|
| Skull | 24 | `artifacts/fiber_v24_visual/skull_all.png` | `skull_all_review.blend` |
| Skull-skin | 25 | `artifacts/fiber_v24_visual/skull_skin_all.png` | `skull_skin_all_review.blend` |
| Skeleton | 1 | `artifacts/fiber_v24_visual/skeleton_all.png` | `skeleton_all_review.blend` |

## Result inventory

### Skull

| Result | Fibers | Interpretation |
|---|---|---|
| `CONVERGED`, validated | 13 | Clear direct case; current, planner, and final coincide. |
| `BLOCKED`, validated, surface | 1, 2, 3, 19, 22, 23 | Generally close to the stored result; the next structural move is collision-blocked. |
| `BLOCKED`, validated, roadmap | 4, 9, 10, 14, 25 | Planner has a large angular detour; solver only partially removes it. |
| `INVALID_ATTACHMENT` | 5, 6, 7, 8, 20, 21 | A hard authored anchor intersects unrelated collider `SCP_3:2`. |
| Missing parent | 15, 17, 18 | Saved attachment cannot be reconstructed. |
| `NO_FEASIBLE_PATH` | 11, 12, 24 | Route search runs, but exact-count handoff fails independent validation. |

All 12 returned skull curves are independently safe. Only one reaches the
current fixed-point criterion. Nine Fibers cannot start because their authored
configuration is invalid; three fail the planner-to-exact-count boundary.

### Skull-skin

The 24 shared Fibers have exactly the same termination and route classification
as the skull file. Eleven shared valid results differ by at most `8.15e-6`; the
remaining FIBER_4 differs by `0.00347`. Draft skin is not a V2 collider. The file
also contains FIBER_16 with a missing parent, giving ten invalid attachments.

### Skeleton

FIBER_1 returns a validated `BUDGET_EXHAUSTED` result, but its geometry is not
acceptable as a final anatomical result:

- planner length/current length: `2.965`;
- final length/current length: `2.646`;
- planner/final maximum separation: `0.5254` world units;
- current/final maximum separation: `3.4086` world units;
- final maximum corner: `119.5 degrees`;
- fixed-point residual: `0.069`;
- stationarity residual: `6.8e4`.

This is a combined planner-reference and contact-refinement failure, not an
iteration-cap-only problem.

## Defect class 1: roadmap shape

The roadmap results are visibly dominated by triangular spikes. The measured
planner geometry confirms that this is not a rendering impression:

| Fiber | Planner max corner | Final max corner | Planner/current length |
|---|---:|---:|---:|
| Skull/FIBER_4 | 118.5 deg | 37.1 deg | 1.245 |
| Skull/FIBER_9 | 108.8 deg | 38.0 deg | 1.210 |
| Skull/FIBER_10 | 118.8 deg | 72.1 deg | 1.145 |
| Skull/FIBER_14 | 88.8 deg | 12.9 deg | 1.328 |
| Skull/FIBER_25 | 141.4 deg | 29.5 deg | 1.697 |
| Skeleton/FIBER_1 | 129.8 deg | 119.5 deg | 2.965 |

The current planner uses A* over sampled free-space candidates, then
`_shortcut_route` keeps the furthest collision-clear chord. If a chord is not
clear, the remaining graph vertex becomes a hard polyline corner. The
exact-count handoff subsequently linearly subdivides those segments in
`_subdivide_routes`; it does not round or optimize the corner.

The roadmap is therefore a valid homotopy certificate, but a poor anatomical
fidelity target. Freezing this raw route was already shown by Package 7.1 to
produce loose arches. Accelerating the current map would converge faster toward
the wrong reference.

### Required close-surface planner correction

The current close-anchor branch accepts the first collision-clear lifted bridge
before computing the actual offset-surface route. The next experiment must
evaluate both, compare their lengths and lift, and prevent an unnecessarily
elevated local bridge from hiding a tighter valid route.

See `docs/fiber_close_surface_planner.md` for the exact cause, candidate policy,
local geodesic options, and torus-safe selection rule.

## Defect class 2: incoherent contact direction

The validated surface group is much closer to acceptable geometry:

| Group | Count | Median time | Median planner/final delta | Median final/current length |
|---|---:|---:|---:|---:|
| Surface | 6 | 44.71 ms | 0.01082 | 1.007 |
| Roadmap | 5 | 152.41 ms | 0.14000 | 1.029 |
| Direct | 1 | 12.22 ms | 0.00000 | 1.000 |

Nevertheless, every surface case reports `BLOCKED`. Four end with a zero CCD
fraction. Code inspection explains why:

- `_base_candidate` calls the structural solver with the current iterate as
  its fidelity reference, so every iteration applies another shortening step;
- `_merit` and `_stationarity` also evaluate against the current points,
  removing the documented fixed anatomical reference;
- collision response is a post-solve local normal projection;
- the `SURFACE` path retracts toward its common owner surface, but unrelated
  blockers are handled only by CCD rejection rather than by a tangential global
  direction;
- one rejected step with an unchanged contact set maps directly to `BLOCKED`.

This map repeatedly proposes motion through the obstacle. CCD is correctly
rejecting that motion; more iterations do not create a better direction.

### Required solver improvement

After the roadmap reference is improved, implement the coherent contact system
specified but not achieved by Package 7:

1. Freeze the refined, independently safe corridor as `q`.
2. Preallocate node and edge-sample contact slots.
3. In the local step, update closest-point targets and contact normals.
4. In the global step, include those targets in the same banded objective and
   solve for normal clearance and tangential smoothing together.
5. Evaluate fidelity, length, curvature, contact, merit, and stationarity
   against that one fixed objective.
6. Accept only a merit-improving, CCD-certified state.
7. Use bounded damping/trust recovery before declaring a stable zero-step
   contact `BLOCKED`.

Package 7.2 already proved that a controller around the existing post-solve
projection is insufficient. The contact targets must participate in the global
system. Safeguarded Anderson acceleration is appropriate only after this base
map is coherent and energy-decreasing; otherwise it accelerates the same bad
fixed point ([Anderson acceleration paper](https://arxiv.org/abs/1805.05715)).

## Defect class 3: exact-count handoff

FIBER_11, FIBER_12, and FIBER_24 find candidate routes but fail after linear
exact-count conversion. This should be addressed in the planner-corridor work,
not labeled a general route-search failure:

- preserve every authored pin and route corner in allocation;
- validate each resampled edge incrementally;
- if an allocated chord is unsafe, locally refine the corridor representation
  and redistribute the fixed final-node budget;
- return `INVALID_CONFIGURATION` if required safe support points exceed the
  authored count, otherwise reserve `NO_FEASIBLE_PATH` for exhausted search.

## Defect class 4: authored attachment conflicts

Six skull Fibers have a hard pin inside unrelated `SCP_3:2`. No collision solver
can simultaneously keep such a pin exact and keep it outside that collider.
This requires an authoring repair workflow:

- highlight the pin and conflicting SCP in the viewport;
- name the collider and measured penetration in the Fiber panel;
- offer a non-destructive nearest feasible relocation preview;
- commit relocation only with user confirmation;
- never broaden owner exemption to hide the unrelated collision.

Missing-parent Fibers require relinking or explicit removal; numerical solving
cannot reconstruct their intended anchors.

## Publication policy

`validated` and `converged` must remain separate facts. Eleven skull V2.4 curves
are independently collision-safe but terminate `BLOCKED`; several are visually
close to the stored curve. The runtime should retain the best validated result
as a visible `VALIDATED_INCOMPLETE`/failed preview instead of snapping back.
Whether such a result becomes downstream-current should be an explicit product
policy, but it must never be described as converged.

## Recommended implementation order

1. **Close-surface route-selection experiment.** Target the reproduced close
   sphere anchors and same-surface production Fibers without changing V2.4
   dispatch.
2. **Contact slots in the banded global solve.** Target the six surface Fibers
   only after the planner experiment supplies qualified routes.
3. **Truthful adaptive termination and best validated preview.** Remove
   one-rejection-to-`BLOCKED`; preserve safe incomplete output visibly.
4. **Acceleration only after base-map qualification.** Compare safeguarded
   Anderson `m=4` against the unaccelerated coherent map.
5. **Attachment repair UI** can proceed independently because the six pin
   conflicts are authored-data problems.

Minimum gates before acceleration:

- roadmap maximum corners below 45 degrees unless obstacle geometry requires a
  sharper turn;
- no planner route more than 15% longer than the shortest independently safe
  refined corridor without a reported reason;
- FIBER_11, 12, and 24 either receive safe exact-count paths or a precise
  insufficient-node/no-route reason;
- at least four of six surface cases converge without changing route branch;
- Skeleton/FIBER_1 final length is no more than 10% above its independently
  valid anatomical reference and has no corner above 45 degrees;
- every returned curve remains independently valid.

## Artifacts

- Machine-readable per-Fiber records:
  `artifacts/fiber_v24_visual/{skull,skull_skin,skeleton}.json`.
- Full contact sheets and editable scenes:
  `artifacts/fiber_v24_visual/*_all.png` and `*_all_review.blend`.
- Detailed examples:
  `skull_f1`, `skull_f9`, `skull_f14`, and `skull_f25`, each as PNG and
  editable review `.blend`.
