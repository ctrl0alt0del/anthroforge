# Corrected span-SQP optimality verification: Fiber_2

## Conclusion

The corrected span-SQP result for `fiber_sphere.blend/FIBER_2` is **not a plateau** and is not
meaningfully unfinished. It is numerically converged immediately beside a strict constrained local
minimum of the objective that the implementation actually solves.

This does not establish global optimality. It establishes that additional ordinary SQP or GCP
iterations cannot remove the visible defect without leaving this attraction basin or changing the
objective.

## Verification

The read-only diagnostic reconstructs the exact sum of fixed-span objectives, eliminates all five
hard pins, independently reacquires the complete collision set, and checks the original nonlinear
segment/triangle distances.

Input SHA-256:
`D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

| Test | Result |
|---|---:|
| Objective finite-difference relative error | `1.19e-11` |
| Maximum active-contact Jacobian error | `4.23e-10` |
| Maximum contact-Hessian scale instability | `4.72e-6` |
| Independent active contacts | `8` |
| Positive-multiplier contacts | `8` |
| Active Jacobian rank | `8` |
| Independent KKT relative residual | `2.64e-5` |
| Reduced-Hessian dimension | `169` |
| Minimum reduced-Hessian eigenvalue | `+6.8685` |
| Eigenvalue classification tolerance | `0.1591` |
| Near-zero reduced modes | `0` |
| Feasible retracted eigenmode probes | `48 / 48` |
| Best eigenmode-probe energy change | `+3.89e-8` |

All contact multipliers are positive, the active constraint Jacobian has full row rank, and every
reduced-Hessian eigenvalue is positive. The minimum eigenvalue is about 43 times the classification
tolerance. These are the first- and second-order conditions for a strict constrained local minimum
under the verified smooth active contact manifold.

The stored result is not the exact floating-point KKT point: its remaining projected direction has
an optimum only `3.13e-7` world units away. That is `0.015` of the clearance slack and `0.000157`
of the collision radius. Following it reduces the `630.7918` objective by only `2.89e-9`, a relative
change of `4.58e-12`. This is numerical residue and cannot explain the visible shape.

Therefore the verified classification is:

`NUMERICALLY_CONVERGED_NEAR_STRICT_LOCAL_MINIMUM`

The complete machine-readable evidence is stored in `.artifacts/sqp_optimality/fiber2.json`.
