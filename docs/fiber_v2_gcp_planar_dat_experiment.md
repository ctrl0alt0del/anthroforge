# Fiber V2 GCP plus Planar-DAT Experiment

## Question

Can Planar Divide-and-Truncate (Planar-DAT) preserve useful tangential Fiber
motion around contact and thereby improve the remaining GCP kinks in
`fiber_sphere.blend/FIBER_2`?

## Straight answer

Not in the tested Fiber formulation. The combination is collision-valid and
eventually approaches the same overall route, but it is slower and slightly
less smooth than both corrected span-SQP and GCP alone.

At the 240-step quality budget, median full time rises from 380.05 ms for GCP
to 1504.39 ms for GCP plus Planar-DAT. Worst free-node turn rises from 22.96
degrees to 25.32 degrees. Planar-DAT therefore does not pass either the shape
or performance gate.

## Controlled implementation

The experiment used IPC Toolkit 1.6's official
`ogc.TrustRegion.planar_filter_step`; it did not recreate Planar-DAT in Python.
The following remained unchanged:

- source file, authored anchors, ROADMAP seed, and hard-span partition;
- GCP contact potential, gradient, clamped-PSD Hessian, and force scaling;
- length, curvature, fidelity, and exact hard pins;
- 0.002 world-space clearance and localized owner policy;
- independent exact static-clearance validation.

Planar-DAT replaced global CCD fraction scaling as the movement limiter. The
existing exact native CCD was retained as a measurement-only audit. An audit
failure rejected the proposal; its fraction was never used to shorten and
accept the step.

## Fiber-specific adaptations required

The stock filter did not directly cover Fiber's collision primitive. Standard
surface contact is represented by vertex-face and edge-edge pairs, while a
codimensional Fiber segment can sweep through a triangle interior without an
endpoint-face or obstacle-edge event. The first exact CCD audit exposed this
immediately.

For a fair experiment, each Fiber edge was represented by eight proxy
subdivisions for Planar-DAT. A proxy limitation conservatively scaled both
original endpoints. The exact Fiber points remained the optimizer variables;
the proxy existed only for the Planar-DAT filter.

The trust-region neighborhood was also rebuilt using the actual proposed
Newton displacement. Without this dynamic inflation, the toolkit's simulation
default query radius sent most proxy points through its isotropic fallback and
discarded 92--97% of otherwise useful movement.

Finally, a failed filtered direction contracted the trust radius and retried up
to eight times. Stopping on the first non-descent filtered direction produced
an unfinished ROADMAP-like result and was not used for the final comparison.

## Final repeated benchmark

Times are medians of three complete isolated calls. The GCP and GCP plus
Planar-DAT rows both pass independent exact clearance validation.

| Variant | Full time | Path length | Worst free-node turn |
|---|---:|---:|---:|
| Corrected span-SQP | 242.58 ms | 20.3925 | 22.71 deg at node 10 |
| GCP | 380.05 ms | 20.6349 | 22.96 deg at node 10 |
| GCP + Planar-DAT | 1504.39 ms | 20.5870 | 25.32 deg at node 8 |

Planar-DAT makes the GCP result 3.96x slower while worsening its largest free
turn by 10.3%. It shortens the GCP result by only 0.23%, which is not a useful
quality trade.

## Solver evidence

| Diagnostic | GCP | GCP + Planar-DAT |
|---|---:|---:|
| Trial iterations | 72 | 177 |
| Accepted | 70 | 93 |
| Rejected / contracted | 2 | 84 |
| Exact CCD audit failures | n/a | 8 |
| Limited node events | n/a | 304 |
| Minimum retained node step | n/a | 10.0% |

The combination does not fail because its iteration cap is too low. Raising
the accepted-step budget from 120 to 240 improved the selected row from roughly
28.4 to 25.3 degrees, but still did not reach either reference. The path length
had already converged to the same region.

The eight exact CCD audit failures also matter: proxy sampling does not provide
a formal segment-triangle guarantee. Removing the audit would make this
experiment faster but unsafe. A production implementation would require a
native Planar-DAT division for the actual segment-triangle primitive.

## Time breakdown

| Phase | Time |
|---|---:|
| Repeated GCP collision builds | 610.77 ms |
| Exact CCD safety audit | 382.08 ms |
| Planar-DAT neighborhood updates | 205.02 ms |
| GCP derivatives | 49.03 ms |
| Structural sparse solves | 19.00 ms |
| Planar-DAT filtering itself | 13.76 ms |

The Planar-DAT kernel is inexpensive. The slowdown comes from the additional
contact-set rebuilds and from 84 trust contractions, each of which repeats GCP
energy/contact work. Even excluding the exact CCD audit entirely leaves about
1122 ms, 2.95x slower than GCP alone.

## Why it does not help this solver

Planar-DAT is well matched to local per-vertex simulation updates: it can limit
one vertex's movement toward a division plane without damping tangential motion
elsewhere. Fiber uses one globally coupled Newton direction. Length, curvature,
node distribution, and contact determine that direction together.

Scaling different Fiber nodes by different Planar-DAT fractions changes the
relative components of that global direction. Although each individual node
keeps its ray direction, the combined Fiber direction can stop being a descent
direction for the structural-contact objective. The line search then cannot
repair it merely by multiplying the whole result by a smaller scalar; the trust
region must be contracted and the filtered direction reconstructed.

That is exactly what the diagnostics show: GCP alone rejects two trials, while
GCP plus Planar-DAT requires 84 contractions. The method preserves local
tangential freedom but disrupts the coordinated tangential redistribution that
the complete Fiber span needs.

## Decision

Reject GCP plus Planar-DAT for Fiber V2 production. No production source or
engine selector was changed.

The broader direction is not disproven, but a viable successor would be a
different algorithm: native exact segment-triangle division constraints
assembled into an energy-aware constrained global step (the paper's
divide-and-project direction), rather than per-node post-filtering of the Fiber
Newton direction. That would need a new experiment and cannot be treated as a
small Planar-DAT integration.

## Artifacts

- Repeated final benchmark: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_planar_dat_final.json`
- Parameter sweep: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_planar_dat_contract_sweep.json`
- Comparison render: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_planar_dat_final.png`
- Inspectable render scene: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_gcp_planar_dat_final_preview.blend`
- Benchmark tool: `../tools/fiber_v2_gcp_planar_dat_benchmark.py`
- Render tool: `../tools/fiber_v2_gcp_planar_dat_render.py`

The source `.blend` remained byte-identical at SHA-256
`D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

## References

- Chen et al., *Divide and Truncate: A Penetration and Inversion Free Framework
  for Coupled Multi-physics Systems*: <https://arxiv.org/abs/2604.15513>
- IPC Toolkit Planar-DAT tutorial and API:
  <https://ipctk.xyz/tutorials/ogc.html#planar-dat-divide-and-truncate>
