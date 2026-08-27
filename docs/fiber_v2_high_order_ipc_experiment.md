# Fiber V2 High-Order IPC Representation Experiment

## Decision

Reject the high-order representation for Fiber V2 production.

The experiment proves that the representation can be made collision-valid, but
it does not materially improve the difficult `fiber_sphere/FIBER_2` result. The
best valid reduced representation lowers the worst non-midpoint turn from
22.71 degrees to 22.32 degrees, while making the complete warm-started cycle
about 3.0 times slower and lengthening the path by 0.39%. A cold ROADMAP start
either remains infeasible or preserves the ROADMAP's severe turns.

Production V2 and its selector remain unchanged.

## Representation tested

Every hard-midpoint-delimited Fiber span is a clamped cubic B-spline:

- hard midpoint positions are exact shared controls;
- adjacent spans share position only, so authored midpoint kinks remain legal;
- each span is internally C2;
- the 64 published Fiber nodes are `x = W_o c`;
- a 253-point dense collision proxy is `p = W_p c`;
- the dense proxy and exact 64-node output chain both participate in contact.

The quadratic Fiber objective is pulled back into control space:

\[
A_c=W_o^T A_x W_o,\qquad b_c=W_o^T b_x.
\]

Standard IPC barrier derivatives are transferred in the High-Order IPC form:

\[
g_c=W_p^Tg_p,\qquad H_c=W_p^TH_pW_p.
\]

The experiment uses IPC Toolkit's standard IPC collision set and barrier, the
existing world-space owner policy, and exact native Fiber CCD. Its initial
feasibility projection acts in cubic-control space. It cannot publish or alter
production Fiber data.

## Why both collision representations are necessary

A dense cubic proxy can be collision-valid while the chord between two of the
64 published points cuts through the collider. Conversely, validating only the
64-node polyline does not prove that the represented cubic curve is safe.

The final experiment therefore places two disconnected dynamic chains in the
same IPC collision system:

1. the dense approximation of the cubic curve;
2. the exact polyline that Fiber would publish.

Every accepted movement is also CCD-limited against both chains. This removed
the false result in which the cubic proxy passed but published Fiber geometry
failed independent validation.

## Real Blender benchmark

Fixture: `E:/development/WIP_models/fiber_sphere.blend/FIBER_2`, Blender 5.0.1,
120-step cap. Timings are medians of three isolated runs. High-order timings do
not include the upstream span-SQP solve when `SPAN_SQP` is the seed.

| Variant | Controls | Median | Valid | Length | Worst free turn |
|---|---:|---:|:---:|---:|---:|
| Corrected span-SQP | 64 nodes | 235.74 ms | yes | 20.392520 | 22.709 deg |
| High-order, ROADMAP, full | 64 | 422.89 ms | no | 40.175584 | 157.623 deg |
| High-order, ROADMAP, reduced | 48 | 308.17 ms | yes | 38.363893 | 141.875 deg |
| High-order, span-SQP seed, full | 64 | 263.53 ms | yes | 20.397566 | 22.550 deg |
| High-order, span-SQP seed, reduced | 48 | 484.71 ms | yes | 20.471185 | 22.320 deg |

The actual warm-started full cycles are:

- 499.28 ms for span-SQP plus the 64-control high-order refinement;
- 720.45 ms for span-SQP plus the 48-control high-order refinement.

The 48-control result improves the worst turn by only 0.39 degrees (1.72%) and
is 0.078665 units longer (0.39%). The curves are visually almost identical.

## Control-density sweep

The sweep tested 64, 60, 54, 52, 48, 44, 38, and 33 controls. The 64, 60, 54,
and 48-control representations produced valid results. The other tested bases
could not consistently represent a safe curve inside this narrow collision
corridor. Feasibility is not monotonic in the raw control count because knot
placement changes separately in each authored span.

The 48-control variant required 19 feasibility updates before ordinary IPC
optimization. The full 64-control variant required five. Both then accepted
four optimizer steps and rejected the next nonlinear step.

## Why High-Order IPC does not help this Fiber

1. High-order bases improve representation accuracy; they do not choose a
   better route. The ROADMAP's free-node artifacts remain part of the initial
   curve and are not removed by changing basis.
2. The valid route occupies a narrow corridor. Removing controls reduces the
   curve's ability to satisfy hard midpoints, clearance, and shortening at the
   same time.
3. Corrected span-SQP already imposes strong within-span curvature. Replacing
   those nodes with a cubic basis changes the final shape only slightly.
4. Collision work increases. The optimizer handles 253 dense proxy points plus
   the 64-node output chain instead of one 64-node chain.
5. A useful cold high-order solve would still need the collision-constrained
   optimizer to remove the ROADMAP's route artifacts. The representation does
   not replace that missing global progress mechanism.

High-Order IPC is effective when a coarse high-order physical discretization
replaces a much denser low-order physical mesh. Here, collision geometry rather
than the structural factor is already the expensive part, and FIBER_2 cannot be
reduced far enough for the smaller structural system to compensate.

## Verification

- Four high-order basis and pulled-back-gradient unit tests pass.
- Forty focused high-order, contact-core, and structural tests pass.
- All new and modified functions are at most 15 lines.
- Python compilation and diff checks pass.
- Both valid high-order results pass independent dense-proxy and exact-output
  static validation.
- The source `.blend` remained byte-identical at SHA-256
  `D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

## Artifacts

- Final benchmark: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_high_order_ipc_final.json`
- Control-density sweep: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_high_order_ipc_density.json`
- Comparison render: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_high_order_ipc_final.png`
- Inspectable scene: `../.artifacts/fiber_v2_dynamic_step/sphere_f2_high_order_ipc_final_preview.blend`
- Basis implementation: `../tools/fiber_v2_high_order_basis.py`
- Benchmark: `../tools/fiber_v2_high_order_ipc_benchmark.py`
- Renderer: `../tools/fiber_v2_high_order_ipc_render.py`

## References

- Ferguson et al., *High-Order Incremental Potential Contact for Elastodynamic
  Simulation on Curved Meshes*: <https://zferg.us/research/high-order-ipc/>
- IPC Toolkit getting-started guide: <https://ipctk.xyz/tutorials/getting_started.html>
