# Fiber V3 scalar-corridor experiment

Status: isolated experiment, not imported by production, measured 2026-08-19.

## Question and result

V3 restricts a Fiber to paired cross-sections between two exact-count references:

- `D[i]`: the piecewise-direct path through authored pins;
- `R[i]`: the independently validated ROADMAP path;
- `X[i] = D[i] + alpha[i] * (R[i] - D[i])`, where `0 <= alpha[i] <= 1`.

The first exact implementation was unnecessarily slow because it discarded accepted V2 infrastructure. After reusing that infrastructure, `fiber_sphere/FIBER_2` cold time fell from 761.0 ms to 124.1 ms and unchanged-geometry exact replay takes 6.2 ms. The remaining production blocker is geometry quality: V3 is slightly shorter than V2 on this fixture, but its free-node p95 turn is 33.22 degrees versus V2's 9.65 degrees.

The experiment therefore validates the scalar corridor as a fast global seed/recovery mechanism, not yet as the sole production Fiber representation. It is related to [Elastic Bands](https://9p.io/who/seanq/icra93.pdf), [CHOMP](https://personalrobotics.cs.washington.edu/publications/ratliff2009chomp.pdf), and lazy collision evaluation in [LazySP](https://personalrobotics.cs.washington.edu/publications/haghtalab2018laziness.pdf) and [Lazy PRM](https://www.kavrakilab.org/publications/bohlin-kavraki2000path-planning-using.html).

## Implemented pipeline

1. Reuse V2.1 exact planner-route caching and linear-first dispatch.
2. Reuse V2.2 compact generation signatures and immutable snapshot identity.
3. Reuse V2.3 persistent collision-world caching and V2.4 batch-world construction.
4. Construct exact-count `D` and `R` with identical authored hard pins.
5. Dynamically select the global workload: 33 levels only for a small graph; otherwise solve 9 coarse levels and one 9-level local refinement.
6. Validate 10,206 adjacent transitions on the difficult 64-node fixture instead of 68,607.
7. Run deterministic second-order dynamic programming over length and 3D curvature.
8. Reuse P5.1 behavior: one CCD query establishes a safe prefix, energy trials remain inside that prefix, and a fully rejected search terminates instead of repeating it.
9. Independently validate the result before commit or exact-cache replay.

The graph reduction is 6.72x. FIBER_2 continuous refinement now uses two CCD calls cold and one geometrically warm, instead of 97 and 88 respectively. Owner-contact intervals and collider identity are identical for planning, transitions, continuous refinement, and validation.

This is a practical form of lazy/adaptive collision evaluation: expensive edge checks are concentrated near the winning alpha corridor rather than performed at full resolution everywhere. It follows the same broad principle as LazySP and Lazy PRM, while the layered scalar graph remains specific to AnthroForge.

## Cold, exact, and geometric warm paths

Cold solving is deterministic and global within the sampled scalar corridor. It generates `D/R`, searches the hierarchical alpha graph, refines the scalar field, and validates the exact result.

Exact-result replay uses the full V2.2 request/snapshot signature. A bounded cache hit still undergoes independent static validation; an invalid hit is evicted. This path takes about 6 ms in the measured file.

Geometric warm start projects prior points onto unchanged cross-sections:

`alpha[i] = clamp(dot(W[i] - D[i], R[i] - D[i]) / ||R[i] - D[i]||^2, 0, 1)`.

The projected curve is independently validated. It cannot change the corridor, pins, collision policy, or objective. The benchmark disables exact replay when measuring this path, so its 15-17 ms result is genuine warm optimization rather than a cache hit.

## Real-file benchmark

Blender 5.0.1, Windows workstation, 64 nodes, 64 accepted-step cap, seven repeated exact/warm runs. Source remained byte-identical with SHA-256 `D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`.

| Fiber | Engine/path | Time | Valid | Length | Free-node p95 turn | Result |
|---|---:|---:|---:|---:|---:|---|
| FIBER_2 | V2 production | 85.66 ms | yes | 23.14647 | 9.65 deg | `BLOCKED` |
| FIBER_2 | V3 cold | 124.14 ms | yes | 23.01618 | 33.22 deg | `STALLED` |
| FIBER_2 | V3 exact replay | 6.24 ms median | yes | 23.01618 | 33.22 deg | cached |
| FIBER_2 | V3 geometric warm | 15.85 ms median | yes | 23.01618 | 33.22 deg | `STALLED` |
| FIBER_1 | V2 production | 38.23 ms | yes | 6.57561 | 10.79 deg | `STALLED` |
| FIBER_1 | V3 cold | 116.48 ms | yes | 6.56783 | 9.04 deg | `STALLED` |
| FIBER_1 | V3 exact replay | 6.00 ms median | yes | 6.56783 | 9.04 deg | cached |
| FIBER_1 | V3 geometric warm | 17.30 ms median | yes | 6.56783 | 9.04 deg | `STALLED` |

### Optimization effect

| FIBER_2 V3 path | Before V2 reuse | After V2 reuse | Improvement |
|---|---:|---:|---:|
| Cold | 761.0 ms | 124.14 ms | 6.13x |
| Geometric warm | 374.2 ms | 15.85 ms | 23.60x |
| Exact replay | not implemented | 6.24 ms | new path |

FIBER_2 cold remains 1.45x slower than V2 rather than the previous 7.2x. FIBER_1 cold remains 3.05x slower because its simple V2 solve costs only 38 ms while V3 unconditionally constructs and searches a dual-path corridor. A production dispatcher should activate the V3 corridor only for ROADMAP cases that need global recovery; it should not tax already-simple Fibers.

## Where cold time remains

For FIBER_2, the 124.14 ms cold run contains 54.24 ms of planning and 54.34 ms of corridor seed construction. Seed construction is 45.24 ms collision work and 8.98 ms dynamic programming. For FIBER_1, seed construction is 76.33 ms: 67.05 ms collision work and 9.15 ms search.

The dynamic program is not the bottleneck. A further native API is useful only if it fuses transition construction, persistent pair filtering, and collision tests in native memory. Moving A* or the small dynamic program alone would not materially help.

## Mathematical and quality limit

The desired obstacle-aware shortest path does not necessarily intersect every paired segment `D[i]--R[i]`. The restriction is useful only while the desired route remains inside that paired corridor and every cross-section has a connected feasible interval.

FIBER_2 exposes the failure. At a hard pin, `D` and `R` coincide, but adjacent cross-sections diverge sharply. Feasible alpha intervals jump, forcing angular geometry even though a smoother 3D path exists outside the scalar lines. More iterations cannot repair a path excluded by the representation.

The sound next quality experiment is to use the scalar solution as a seed, then release free nodes into a narrow 3D tube around it. Exact pins remain eliminated. This must be evaluated against V2 before any production integration.

## Artifacts and code

- Experiment: `core/vcp/v3_experiment.py`
- Read-only benchmark: `tools/fiber_v3_corridor_experiment.py`
- Comparison renderer: `tools/fiber_v3_corridor_render.py`
- Focused tests: `tests/unit/test_fiber_v3_experiment.py`
- FIBER_2 data: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_optimized.json`
- FIBER_2 comparison: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_optimized_compare.png`
- Inspectable blend: `artifacts/fiber_v3_corridor/fiber_sphere_FIBER_2_optimized_compare.blend`

No production selector, solver, UI, cache, or publication path imports this experiment.
