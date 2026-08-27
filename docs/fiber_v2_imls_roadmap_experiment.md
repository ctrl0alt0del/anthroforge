# Fiber V2 IMLS Contact Experiment

## Question

Can an Implicit Moving Least Squares (IMLS) surface remove the remaining
contact-induced bends in `fiber_sphere.blend/FIBER_2` while preserving Fiber's
exact clearance and hard midpoint routing?

## Straight answer

No. The controlled IMLS substitution is independently collision-valid, but it
produces a worse path and is much slower than corrected span-SQP. Its worst
free-node turn rises from 22.71 degrees to 59.87 degrees, its path is 10.5%
longer, and median full time rises from 246.28 ms to 1610.94 ms (6.54x).

This is not an early-stop, line-search, or rejection failure. The selected IMLS
run accepted all 41 iterations and rejected none. It smoothly converges to the
wrong equilibrium for this coarse polygonal SCP and its localized owner-contact
policy.

## Controlled substitution

The comparison kept these parts unchanged:

- source file, `FIBER_2` anchors, and exact-count ROADMAP seed;
- corrected hard-span split and global-h structural weights;
- length, curvature, and fidelity objective;
- exact hard pins and localized owner exemptions;
- 0.002 world-space Fiber collision radius;
- existing native conservative CCD for every movement;
- exact polygonal static-clearance validation before accepting the result.

Only the contact field and its optimizer derivatives changed. The experimental
IMLS field used the standard weighted oriented-plane form

\[
f(x)=\frac{\sum_j n_j^T(x-x_j)\phi_j(x)}{\sum_j\phi_j(x)}.
\]

The experiment sampled seven strictly interior points per triangle, retained
each face's outward normal, used a compact smooth radial weight and evaluated
three Fiber samples per edge. Its analytic gradient supplied Gauss-Newton
contact blocks to the same structural Newton system. Exact polygonal CCD and
validation remained authoritative; IMLS was not allowed to declare safety.

An initial vertex-normal prototype was discarded before comparison. Averaging
normals across the test's coarse box edges rounded the obstacle and was not a
valid representation of the authored SCP. The reported implementation preserves
sharp face normals and uses local support.

## Repeated benchmark

Times are medians of three complete isolated solver calls with the same
60-step work cap. Both results pass the independent exact clearance validator.

| Variant | Full time | Path length | Worst free-node turn | Accepted / rejected |
|---|---:|---:|---:|---:|
| Corrected span-SQP | 246.28 ms | 20.3925 | 22.71 deg at node 10 | 36 / 34 |
| IMLS, force 0.1, bandwidth 2.5 | 1610.94 ms | 22.5334 | 59.87 deg at node 59 | 41 / 0 |

The IMLS curve is 10.50% longer. At the previously monitored nodes it changes
node 8 from 12.99 to 18.58 degrees and node 10 from 22.71 to 18.73 degrees, but
it transfers the dominant defect to node 59, which rises from 4.69 to 59.87
degrees. Inspecting only node 10 would therefore give a false positive.

## IMLS phase breakdown

| Phase | Time |
|---|---:|
| Contact/sample queries | 144.45 ms |
| Contact assembly | 1066.64 ms |
| Sparse linear solve | 6.81 ms |
| Existing exact CCD | 79.25 ms |
| Final independent validation | 1.90 ms |

The run made 10,500 sample queries and assembled 3,144 active sample
contributions. Python sparse-matrix block insertion dominates the experimental
cost. A native block-banded implementation could reduce this time, but it would
only reach the same unacceptable shape faster, so native optimization is not
justified for this formulation.

## Parameter sweep

All tested rows remained collision-valid, but none passed shape quality.

| Force / bandwidth | Full time | Worst free-node turn |
|---|---:|---:|
| 0.03 / 2.5 | 1736.69 ms | 61.43 deg at node 59 |
| 0.10 / 2.5 | 1622.17 ms | 59.87 deg at node 59 |
| 0.30 / 2.5 | 2113.54 ms | 59.56 deg at node 59 |
| 1.00 / 2.5 | 2315.16 ms | 59.51 deg at node 59 |
| 0.10 / 0.75 | 2404.81 ms | 118.45 deg at node 8 |
| 0.10 / 1.25 | 2573.82 ms | 85.99 deg at node 59 |
| 0.10 / 4.00 | 882.71 ms | 67.80 deg at node 59 |

Narrow support is unstable at contact/feature transitions. Wider support is
faster but increases geometric bias and still concentrates the bend at node
59. Contact weight changes do not remove the failure. This rules out a simple
parameter-tuning explanation.

## Why IMLS fails here

IMLS is designed to replace a piecewise-linear mesh by a smooth implicit
surface, which can remove discontinuous tangential forces at triangle
boundaries. That benefit assumes that the smooth approximation is also the
desired contact geometry.

Fiber's feasible set is different: it is the exact finite-radius polygonal SCP
plus localized exclusions around authored owners. On this coarse, sharp test
geometry, IMLS rounds or biases the offset surface and its normals near face,
owner-exemption, and ROADMAP-span transitions. The length objective follows
that smooth but biased field. Curvature then accumulates where the implicit
field hands control back to exact CCD or to a different contact region.

The zero-rejection history is decisive: collision is not repeatedly fighting
and rolling back the solver. The solver is following the IMLS model successfully,
but that model does not encode the Fiber path we want.

## Decision

Reject IMLS for Fiber V2 production and remove no existing solver component.
Keep this implementation as an isolated benchmark only. Do not spend native
development time on it unless a future SCP representation supplies a genuinely
smooth authored limit surface that exactly defines Fiber clearance and owner
exemptions.

The result also narrows the remaining problem: merely smoothing contact normals
does not solve the kink. The next candidate must preserve exact finite-clearance
geometry while coordinating curvature across contact activation and routing-span
boundaries.

## Artifacts

- Repeated benchmark: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_imls_roadmap.json`
- Parameter sweep: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_imls_roadmap_sweep.json`
- Comparison render: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_imls_roadmap.png`
- Inspectable comparison scene: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_imls_roadmap_preview.blend`
- Benchmark tool: `../tools/fiber_v2_imls_roadmap_benchmark.py`
- Render tool: `../tools/fiber_v2_imls_roadmap_render.py`

The source `.blend` remained byte-identical at SHA-256
`D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

## References

- Madan and Levin, *Robust and Artefact-Free Deformable Contact with Smooth
  Surface Representations* (2024):
  <https://onlinelibrary.wiley.com/doi/10.1111/cgf.15187>
- Alexa et al., *Point Set Surfaces*:
  <https://www.sci.utah.edu/~shachar/pss/pss.htm>
