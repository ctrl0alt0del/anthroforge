# Fiber V2 OGC Trust-Filter Experiment

## Question

Does replacing GCP with Offset Geometric Contact (OGC) improve Fiber, either
with OGC's standard isotropic trust-region filter or with Planar-DAT?

## Straight answer

OGC and Planar-DAT are substantially better matched than GCP and Planar-DAT,
but neither OGC configuration beats the existing references.

- OGC with the standard isotropic filter is unacceptable: it remains visibly
  unfinished at a 50.04-degree worst free-node turn after the 240-step run.
- OGC with Planar-DAT is much better and collision-valid, reaching 24.23
  degrees, but span-SQP reaches 22.71 degrees and GCP reaches 22.98 degrees.
- OGC plus Planar-DAT takes 1158.44 ms, versus 449.52 ms for GCP and 248.12 ms
  for span-SQP.

Neither OGC variant should replace the current Fiber contact formulation.

## Controlled implementation

The experiment used IPC Toolkit 1.6's intended OGC components:

- `NormalCollisions.CollisionSetType.OGC`;
- the physical, area-weighted `BarrierPotential`;
- `ogc.TrustRegion.filter_step` for standard isotropic OGC;
- `ogc.TrustRegion.planar_filter_step` for OGC plus Planar-DAT.

GCP was absent from both OGC variants. GCP remained only as an independently
run reference row.

The following Fiber behavior stayed unchanged:

- `fiber_sphere.blend/FIBER_2`, authored anchors, and ROADMAP seed;
- hard midpoint span partition and corrected global-h structural weights;
- length, curvature, fidelity, and exact pin elimination;
- 0.002 world-space clearance and localized owner exemptions;
- final independent exact polygonal validation.

Exact Fiber CCD was used only as a safety audit. It never supplied an accepted
step fraction to either OGC optimizer.

## Codimensional Fiber mapping

OGC supports codimensional objects conceptually, but IPC Toolkit's exposed
surface collision set is based on vertex-face and edge-edge interactions. A
Fiber segment can move through a triangle interior without either endpoint
providing the necessary vertex-face event.

Each Fiber edge was therefore represented by eight linear proxy subdivisions.
The OGC proxy gradient and Hessian were mapped back to the original Fiber nodes
using

\[
g_x=W^Tg_p,\qquad H_x=W^TH_pW,
\]

where `W` is the fixed linear interpolation matrix. The proxies introduced no
additional optimizer degrees of freedom.

Trust-filtered proxy ratios were mapped conservatively to the incident Fiber
nodes. The trust neighborhood was inflated from the actual proposed Newton
movement before each update.

## Final repeated benchmark

The quality comparison uses a 240 accepted-step cap. Times are medians of three
complete isolated runs. All OGC rows pass independent final clearance
validation.

| Variant | Median time | Path length | Worst free-node turn |
|---|---:|---:|---:|
| Corrected span-SQP | 248.12 ms | 20.3925 | 22.71 deg at node 10 |
| GCP | 449.52 ms | 20.4074 | 22.98 deg at node 10 |
| OGC isotropic | 996.58 ms | 21.9757 | 50.04 deg at node 7 |
| OGC + Planar-DAT | 1158.44 ms | 20.5257 | 24.23 deg at node 9 |

OGC plus Planar-DAT is 2.58x slower than GCP and 4.67x slower than span-SQP.
Its worst free turn is 5.5% larger than GCP's. It is 0.58% longer than GCP.

## Parameter sweep

The 120-step sweep covered:

- OGC force ratios `0.03`, `0.1`, and `0.3`;
- activation radii `4r`, `8r`, and `16r`;
- trust relaxation `0.75` and `0.9`;
- both isotropic and Planar-DAT filters.

Every one of the 18 isotropic rows failed shape quality, with worst free turns
from 91.5 to 139.4 degrees. Planar-DAT rows ranged from 25.5 to 96.7 degrees.
The best Planar row was force ratio `0.03`, activation `16r`, and relaxation
`0.9`; this became the high-budget final configuration.

Raising its cap from 120 to 240 improved the worst turn from 25.5 to 24.2
degrees. It did not surpass GCP or span-SQP, so the remaining difference is not
explained by the original 120-step ceiling.

## Why isotropic OGC fails

The isotropic filter limits each proxy node to a conservative sphere even when
its proposed movement is tangential or separating. In the selected row it
recorded:

| Diagnostic | OGC isotropic |
|---|---:|
| Accepted / rejected trials | 96 / 19 |
| Limited-node events | 855 |
| Minimum retained node step | 0.33% |
| Active collision contributions | 15,882 |
| Exact CCD audit failures | 0 |

It is conservative but excessively damped. Nodes needing to slide along the
obstacle repeatedly retain almost none of their proposed displacement. More
iterations shorten the path, but do not make this suitable for interactive
Fiber solving.

## Why Planar-DAT helps OGC

Planar-DAT restricts movement toward a collision division plane while allowing
more tangential and separating movement. Its selected row records only 162
limited-node events and retains at least 17.3% of a node's proposed step. This
is why it reaches a tight route while isotropic OGC remains visibly unfinished.

OGC's offset potential and Planar-DAT also share the same OGC contact
construction and minimum-distance semantics. This avoids the GCP/OGC trust
model mismatch from the preceding experiment. OGC plus Planar-DAT improves on
GCP plus Planar-DAT from 25.32 to 24.23 degrees and from 1504 to 1158 ms.

## Why it still loses

The globally coupled Fiber Newton direction remains the central mismatch.
Planar-DAT independently truncates proxy/node movement. Different node ratios
alter the combined length-curvature-contact direction and sometimes make it a
non-descent direction. The selected solve requires 38 trust contractions:

| Diagnostic | OGC + Planar-DAT |
|---|---:|
| Trial iterations | 123 |
| Accepted / rejected | 85 / 38 |
| Limited-node events | 162 |
| Exact CCD audit failures | 8 |
| Minimum retained node step | 17.3% |

The eight CCD audit failures mean the sampled proxy is not a formal
segment-triangle safety guarantee. A production implementation could not remove
the audit without first adding exact native segment-triangle OGC divisions.

Measured time is distributed as follows:

| Phase | OGC isotropic | OGC + Planar-DAT |
|---|---:|---:|
| OGC collision builds | 371.12 ms | 493.26 ms |
| Exact CCD audit | 248.45 ms | 272.44 ms |
| Trust updates | 140.47 ms | 145.91 ms |
| Barrier derivatives | 47.75 ms | 46.20 ms |
| Structural sparse solves | 16.73 ms | 15.18 ms |
| Trust filtering | 4.94 ms | 9.46 ms |

Even subtracting the complete CCD audit leaves OGC plus Planar-DAT at roughly
886 ms, almost twice GCP's measured 450 ms.

## Decision

Reject both OGC variants for Fiber V2 production:

- standard isotropic OGC fails both shape and latency;
- OGC plus Planar-DAT is the only viable OGC shape, but is still slower and
  slightly less smooth than GCP and span-SQP;
- the exposed toolkit primitives do not provide exact Fiber
  segment-triangle Planar-DAT safety.

No production engine code or selector was changed. A future OGC revisit would
require native segment-triangle offset contact and an energy-aware global
divide-and-project step, not another parameter change to the current filter.

## Artifacts

- Repeated final benchmark: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_ogc_dat_final.json`
- Parameter sweep: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_ogc_dat_sweep.json`
- Comparison render: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_ogc_dat_final.png`
- Inspectable render scene: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_ogc_dat_final_preview.blend`
- Benchmark tool: `../tools/fiber_v2_ogc_dat_benchmark.py`
- Render tool: `../tools/fiber_v2_ogc_dat_render.py`

The source `.blend` remained byte-identical at SHA-256
`D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

## References

- Chen et al., *Offset Geometric Contact*:
  <https://doi.org/10.1145/3731205>
- Official OGC and Planar-DAT integration tutorial:
  <https://ipctk.xyz/tutorials/ogc.html>
