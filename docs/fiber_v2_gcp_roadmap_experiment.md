# Fiber V2 GCP with ROADMAP Seed Experiment

## Question

Can a smooth Geometric Contact Potential (GCP), initialized from the validated
ROADMAP route, remove the stationary bump seen in `fiber_sphere.blend/FIBER_2`?
Would GCP replace the Fiber solver or only part of it?

## Straight answer

GCP replaces only the contact model: collision-set construction plus the
contact potential, gradient, and Hessian used by the optimizer. It does not
replace Fiber's length/curvature/fidelity objective, hard midpoint handling,
SQP/Newton coordination, planner, exact positive-clearance CCD, final static
validation, scheduling, publication, or migration.

The experiment fails the shape-quality gate. The initially monitored node-10
turn fell from 22.71 degrees to 7.14 degrees, but the bend was redistributed:
node 8 increased from 12.99 to 52.42 degrees and node 59 increased from 4.69 to
67.80 degrees. The result is independently collision-valid and full time fell
from 244.17 ms to 219.72 ms, but neither fact compensates for the new kinks.

## Controlled substitution

The comparison kept these parts unchanged:

- source file and `FIBER_2` authored anchors;
- exact-count ROADMAP seed and hard midpoint partition;
- corrected global-h span weights;
- structural fidelity, length, and curvature objective;
- localized endpoint-owner exemptions;
- Fiber's 0.002 world-space clearance;
- existing native conservative CCD for every accepted movement;
- existing independent static-clearance validator at the final result.

Only the current per-triangle augmented contact linearization was replaced by
IPC Toolkit 1.6's smooth GCP energy, gradient, and clamped-PSD Hessian. The GCP
package was loaded from the isolated ignored `.artifacts/gcp_deps` directory;
the Blender installation and production engine selector were not modified.

The GCP force scale was normalized when the first contact entered the smooth
activation distance. This is important: normalizing at the collision-free
ROADMAP seed produces a zero contact gradient and a meaningless huge weight.

## Results: normal 60-step work budget

All rows are collision-valid. Times are medians of three fresh solver calls and
include ROADMAP planning and final independent validation.

| Variant | Full time | Path length | Node 8 | Node 10 | Worst free-node turn | Accepted / rejected |
|---|---:|---:|---:|---:|---:|---:|
| Corrected span-SQP | 244.17 ms | 20.3925 | 12.99 deg | 22.71 deg | 22.71 deg at node 10 | 36 / 34 |
| GCP ratio 0.03 | 244.99 ms | 21.4200 | 94.89 deg | 2.14 deg | 94.89 deg at node 8 | 44 / 1 |
| GCP ratio 0.10 | 219.72 ms | 20.8715 | 52.42 deg | 7.14 deg | 67.80 deg at node 59 | 42 / 1 |
| GCP ratio 0.30 | 227.63 ms | 20.8200 | 26.13 deg | 14.34 deg | 67.80 deg at node 59 | 43 / 1 |
| GCP ratio 1.00 | 231.17 ms | 20.8600 | 28.58 deg | 15.20 deg | 67.80 deg at node 59 | 44 / 1 |

Every tested ratio is a failure. The 0.03 row moves the kink to node 8. The
other ratios reduce node 8 but create the same 67.80-degree kink at node 59.
Node-10 angle and the overall maximum (which is dominated by an authored hard
midpoint) hid these regressions. Future evaluation must report the complete
free-node turn profile and the worst free-node index.

The selected GCP row used 43 nonlinear iterations across the four spans
(`11, 4, 21, 7`), accepted 42, and rejected one. Its measured phases were:

| Phase | Time |
|---|---:|
| ROADMAP | 26.36 ms |
| GCP collision builds | 48.48 ms |
| GCP energy/gradient/Hessian | 9.49 ms |
| Sparse Newton solves | 7.93 ms |
| Existing exact CCD | 83.82 ms |
| Final independent validation | 2.72 ms |

The remaining approximately 41 ms is Python orchestration, GCP mesh/filter
construction, initial seed validation, and uninstrumented setup. Current
span-SQP spent 116.57 ms in CCD and rejected 34 trials; the smoother GCP map
reduced that wasted work enough to offset GCP's more expensive contact builds.

Repeated executions agreed to a maximum point difference of
`1.91e-12`, so the measured shape change is deterministic at the declared
numerical scale.

## Higher-budget result

The 0.10 GCP ratio was also run with a 240-step ceiling. It stopped after 71
iterations (69 accepted, 2 rejected):

| Variant | Full time | Path length | Node-10 turn |
|---|---:|---:|---:|
| Corrected span-SQP | 254.96 ms | 20.3925 | 22.71 deg |
| GCP ratio 0.10 | 365.56 ms | 20.3834 | 14.74 deg |

Waiting longer lets the GCP curve tighten from 20.8715 to 20.3834, essentially
matching the baseline length. It does not establish acceptable shape quality:
the concentrated free-node kinks remain the disqualifying result. Production
convergence must evaluate the complete merit and free-node turn profile, not
stop at a visually favorable monitored node or total path length.

## Why the contact result improves

GCP does reduce feature-switching discontinuity and rejected trials, but the
experiment still uses external finite-radius CCD because public GCP has no
Fiber-radius offset. Structural Newton motion advances freely until CCD limits
it; when no correctly offset smooth contact is active, displacement accumulates
at the first limiting node. The bend is therefore concentrated at activation or
CCD boundaries instead of distributed smoothly along the span.

## Limitations found

1. IPC Toolkit's public `SmoothPotential` is a zero-distance barrier and does
   not expose Fiber's finite `dmin=collision_radius`. This experiment therefore
   keeps exact 0.002-clearance CCD outside GCP. A production integration needs a
   finite-offset GCP/capsule formulation or a justified hybrid.
2. Standard barrier GCP requires a feasible start. ROADMAP satisfies that for
   this test; it cannot replace V2's infeasible-DIRECT augmented-Lagrangian and
   filter logic.
3. Contact-force normalization is sensitive. Too little contact weight moved
   the artifact instead of solving it.
4. The experiment uses SciPy sparse Newton solves. Production should inject the
   smooth GCP blocks into the native block-banded Fiber system rather than ship
   this Python/SciPy orchestration unchanged.
5. Only `FIBER_2` was used to answer this isolated mechanism question. Rollout
   requires the full real-file suite and invalid-DIRECT fixtures.

## Recommended architecture

Do not integrate this experiment. If GCP is revisited, use a hybrid design only
after implementing finite-clearance contact inside the smooth objective:

1. Keep the existing planner as an optional accelerator.
2. Keep augmented-Lagrangian/filter feasibility for an intersecting DIRECT
   seed or an invalid ROADMAP handoff.
3. Once feasible, switch the contact portion of the same SQP loop to a
   finite-clearance smooth GCP formulation.
4. Assemble its local gradient/Hessian blocks into the existing native
   block-banded structural system.
5. Keep conservative CCD and independent final validation unchanged.

The experiment shows lower rejection count and potentially useful smooth
contact derivatives, but it does not yet show an acceptable Fiber path. Shape
quality must pass before its performance result has production value.

## Artifacts

- Benchmark: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_roadmap.json`
- Normal-budget render: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_roadmap.png`
- Inspectable normal-budget scene: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_roadmap_preview.blend`
- Higher-budget benchmark: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_roadmap_cap240.json`
- Higher-budget render: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_roadmap_cap240.png`
- Inspectable higher-budget scene: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_roadmap_cap240_preview.blend`
- Benchmark tool: `../tools/fiber_v2_gcp_roadmap_benchmark.py`
- Render tool: `../tools/fiber_v2_gcp_roadmap_render.py`

The source `.blend` remained byte-identical at SHA-256
`D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

## References

- IPC Toolkit GCP tutorial: <https://ipctk.xyz/tutorials/gcp.html>
- IPC paper and feasibility-preserving CCD context: <https://ipc-sim.github.io/>
