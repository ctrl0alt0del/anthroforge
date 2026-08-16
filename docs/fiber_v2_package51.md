# Fiber V2 Package 5.1 experiment

Package 5.1 is an isolated optimization of Package 5. It does not replace V1 or
enable V2 by default. Its public experiment entry point is `solve_package51`;
`solve_package5` remains the comparison baseline.

## Implemented scope

1. **Fused native contact construction.** One native edge query now performs
   world/local BVH traversal, exact segment/triangle closest-feature evaluation,
   containment, owner filtering, closest-factor extraction, blocker reporting,
   and contact-normal construction. The prior Python path sampled each active
   edge 17 times and repeatedly scanned triangle faces. Surface-only solves skip
   contact rows that Package 5 never consumes.
2. **Persistent CCD pair cache and curved feasible step.** The solve-local cache
   reuses an identical candidate set and remembers the last limiting edge/face
   pair, testing that pair first on later trials. Broad-phase discovery still
   runs whenever swept bounds change, so the cache cannot hide a new collider.
   Active roadmap contacts use four outward-bowed waypoints. Each leg is checked
   by the same CCD; no waypoint is accepted because of interpolation alone.
3. **Final-only full static validation.** A successful planner handoff is the
   initial valid state. CCD preserves validity between accepted states. Package
   5.1 therefore removes candidate and line-search static revalidation and runs
   the independent full node/edge validator once on the exact final output.

The native DLL ABI is `af_fiber_ccd-2.1023`. It remains an internal packaged
Windows binary; users do not install a compiler or external executable.

## Real Blender benchmark

Blender 5.0.1, three warm repetitions per solver, same captured colliders in each
process. Times are medians in milliseconds. Source `.blend` files were opened
read-only and their SHA-256 hashes remained unchanged.

| Fixture | V1 | Package 5 | Package 5.1 | P5→P5.1 |
|---|---:|---:|---:|---:|
| skull / FIBER_14 | 106.39 | 128.33 | 93.20 | -27.4% |
| skull / FIBER_1 | 40.80 | 130.54 | 87.15 | -33.2% |
| skeleton / FIBER_1 | 81.19 | 528.95 | 312.03 | -41.0% |
| skull-skin / FIBER_1 | 89.70 | 133.46 | 79.93 | -40.1% |

### Phase comparison

| Fixture | Candidate P5→P5.1 | CCD P5→P5.1 | Static validation P5→P5.1 |
|---|---:|---:|---:|
| skull / FIBER_14 | 24.51→13.28 | 32.99→52.85 | 46.29→2.50 |
| skull / FIBER_1 | 18.30→4.05 | 32.63→17.18 | 24.19→2.81 |
| skeleton / FIBER_1 | 85.08→28.33 | 305.40→225.17 | 98.81→6.00 |
| skull-skin / FIBER_1 | 18.08→5.90 | 31.71→21.31 | 22.07→4.10 |

Every Package 5.1 result passed the independent final node/edge clearance
validator. Path-length parity with Package 5 was within 0.08% for skull
FIBER_14, effectively exact for the two surface fixtures, and within 0.28% for
the skeleton fixture. All four runs still terminate `BLOCKED`, so this package
is a performance improvement and feasibility-preserving experiment, not a
convergence or rollout result.

The skeleton remains the limiting case: CCD is still 225 ms of its 312 ms total.
The curved path reduced trials from 12 to 7 and reused the limiting pair six
times, but native interval certification is still the next optimization target.

## Evidence

- JSON records and review blends: `artifacts/fiber_v2_package51/`
- Left-to-right renders: `skull_fiber14.png` and `skeleton_fiber1.png`
- Primary design references: [IPC](https://ipc-sim.github.io/file/IPC-paper-fullRes.pdf),
  [Rigid IPC curved trajectories](https://ipc-sim.github.io/rigid-ipc/), and
  [CGAL AABB tree distance queries](https://doc.cgal.org/latest/AABB_tree/index.html).
