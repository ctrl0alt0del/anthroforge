# Fiber V1 vs accepted V2 packages — full-cycle qualification

## Decision

The accepted V2 work contains several strong components, but the cumulative
Package 6.1 pipeline is **not ready to replace V1**.

- Package 4.3 is a clear planner success: it returns the exact Package 4.1 route
  on all eight fixtures and is 6.70x faster in aggregate.
- Package 5.1 returns independently safe output on all eight fixtures.
- Package 6.1 correctly avoids unconditional Package 6 overhead and improves the
  dense skeleton case, reducing aggregate Package 5.1 solve time by 9.70%.
- The final P6.1 result is only faster than V1 on three of eight fixtures. Its
  aggregate warm solve time is 22.27% slower than V1.
- Only one of eight P6.1 runs terminates `CONVERGED`; six are `BLOCKED`, and the
  skeleton is `BUDGET_EXHAUSTED`.
- FIBER_4 retains visible contact rippling and Skeleton/FIBER_1 remains angular.
- Cold capture plus first P6.1 solve is 286.80–662.32 ms per isolated Fiber, so
  the current experiment does not meet live-edit latency.

The correct retained experimental baseline is therefore Package 4.3 + Package
5.1 + Package 6.1 dispatch. Rejected Package 4.2 grouping, unconditional Package
6, Packages 7.1/7.2, and Packages 8/8.1/8.2 must not enter production.

## What “accepted packages” means

| Package | Retained result | Comparison role |
|---|---|---|
| 1 | Immutable pure-data request/result contracts | Architecture component; no standalone curve |
| 2 | O(N) banded structural solve | Retained; global solve is 0.80–7.33 ms in the final runs |
| 3 | Packaged native collision backend and independent validator | Retained collision authority |
| 4.1 | Cached-metric Lazy A* | Exact route reference for planner parity |
| 4.2 | Persistent native BVH only | Grouped planner rejected; BVH retained by 4.3 |
| 4.3 | Native world, fused collision queries, native graph search | Accepted planner used by every later solver |
| 5.1 | Fused contact query, cached CCD pairs, final-only full validation | Accepted safe base solver experiment |
| 6.1 | Dynamic P5.1/P6 dispatcher | Accepted collision-policy experiment |

Packages 1–3 are components, and Package 4.x produces a planner reference rather
than a final optimized Fiber. The directly comparable final solvers are V1,
Package 5.1, and Package 6.1.

## Protocol

- Blender 5.0.1 background process per file/Fiber.
- Five timed warm repetitions after equal code-path priming.
- Cache-cleared first call recorded separately from warm shared-snapshot calls.
- V2 main-thread collider capture recorded separately.
- Eight real, nonblocking-pin fixtures: six skull Fibers, the matching skull-skin
  FIBER_1, and skeleton FIBER_1.
- Package 4.1, 4.3, 5.1, and 6.1 receive the same immutable request and triangle
  snapshot in each process.
- Every result is checked by the independent native static node/edge validator.
- Supplied `.blend` files are opened read-only and verified byte-identical.

Fresh processes follow Blender's documented
[`--background`](https://docs.blender.org/manual/ja/5.0/advanced/command_line/arguments.html)
workflow. Timing uses `perf_counter`, consistent with Blender's
[Python performance guidance](https://docs.blender.org/api/dev/info_best_practice.html).

## Warm shared-snapshot benchmark

Times are medians in milliseconds. P4.1 and P4.3 are planner-only columns; V1,
P5.1, and P6.1 are complete solve columns including final validation.

| Fixture | V1 | P4.1 plan | P4.3 plan | P5.1 | P6.1 | P6.1 / V1 |
|---|---:|---:|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 95.56 | 428.92 | 23.78 | 295.88 | 203.50 | 2.13x |
| Skull/FIBER_1 | 39.15 | 160.50 | 48.44 | 74.24 | 79.09 | 2.02x |
| Skull/FIBER_13 | 140.41 | 131.88 | 14.05 | 26.46 | 30.94 | **0.22x** |
| Skull/FIBER_14 | 113.20 | 198.43 | 11.96 | 104.49 | 91.02 | **0.80x** |
| Skull/FIBER_22 | 114.14 | 37.17 | 9.78 | 31.48 | 31.28 | **0.27x** |
| Skull/FIBER_4 | 43.52 | 170.43 | 32.14 | 155.78 | 157.18 | 3.61x |
| Skull/FIBER_9 | 51.34 | 127.83 | 18.69 | 153.36 | 153.63 | 2.99x |
| Skull-skin/FIBER_1 | 85.09 | 186.70 | 56.47 | 82.27 | 87.75 | 1.03x |
| **Aggregate** | **682.41** | **1441.85** | **215.30** | **923.97** | **834.38** | **1.22x** |

Package 4.3's aggregate planner time is 85.1% lower than Package 4.1. Package
6.1 is 9.70% faster than Package 5.1 overall, almost entirely because it selects
the trust/certificate branch for the skeleton. All other fixtures select the
exact Package 5.1 path.

## Cold full-cycle cost

`V2 full` is main-thread collider/request capture plus a cache-cleared first P6.1
call. Capture can be shared among Fibers affected by one runtime request, so these
rows are intentionally the pessimistic isolated-Fiber case.

| Fixture | V1 cold | V2 capture | P6.1 cold | V2 full | V2 full / V1 |
|---|---:|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 89.03 | 374.92 | 287.40 | 662.32 | 7.44x |
| Skull/FIBER_1 | 40.95 | 206.89 | 200.43 | 407.31 | 9.95x |
| Skull/FIBER_13 | 147.43 | 229.87 | 110.73 | 340.60 | 2.31x |
| Skull/FIBER_14 | 144.05 | 214.96 | 164.00 | 378.96 | 2.63x |
| Skull/FIBER_22 | 137.13 | 196.26 | 90.55 | 286.80 | 2.09x |
| Skull/FIBER_4 | 47.07 | 218.85 | 227.78 | 446.63 | 9.49x |
| Skull/FIBER_9 | 51.01 | 211.94 | 213.53 | 425.47 | 8.34x |
| Skull-skin/FIBER_1 | 118.99 | 199.25 | 196.54 | 395.78 | 3.33x |

The accepted native BVH/world work is useful only when it persists and is shared.
The current isolated benchmark still flattens/captures Blender collider geometry,
which dominates the cold path.

## Package 6.1 phase attribution

| Fixture | Planner | Candidate/contact | CCD | Final validation | Structural solve | Trials | Mode |
|---|---:|---:|---:|---:|---:|---:|---|
| Skeleton/FIBER_1 | 31.98 | 39.51 | 116.17 | 5.30 | 7.33 | 12 | P61 trust |
| Skull/FIBER_1 | 53.81 | 4.49 | 15.90 | 3.21 | 1.56 | 3 | P5.1 |
| Skull/FIBER_13 | 20.81 | 3.21 | 7.13 | 4.55 | 0.80 | 1 | P5.1 |
| Skull/FIBER_14 | 24.52 | 15.86 | 50.48 | 2.85 | 2.51 | 5 | P5.1 |
| Skull/FIBER_22 | 9.26 | 1.68 | 14.14 | 3.51 | 1.62 | 3 | P5.1 |
| Skull/FIBER_4 | 54.42 | 35.31 | 59.26 | 3.60 | 3.10 | 5 | P5.1 |
| Skull/FIBER_9 | 33.61 | 60.41 | 61.26 | 3.47 | 4.15 | 7 | P5.1 |
| Skull-skin/FIBER_1 | 53.84 | 4.63 | 17.42 | 2.65 | 1.86 | 3 | P5.1 |

The structural factor/solve is confirmed not to be the bottleneck. Remaining
time is route construction, repeated contact construction, and CCD. The P6.1
dispatcher is doing its job: it activates only for the one workload where the
certificate/trust path saves substantial time.

## Correctness, termination, and visual result

- Package 4.1 and Package 4.3 references have maximum point delta `0.0` on all
  eight fixtures.
- P5.1 and P6.1 independently validate as collision-safe on all eight fixtures.
- Under the same strict V2 validator, only Skeleton/FIBER_1's V1 output passes;
  the other seven V1 outputs violate the requested node/edge clearance policy.
- P6.1 terminates `CONVERGED` only on Skull/FIBER_13. Skeleton/FIBER_1 is
  `BUDGET_EXHAUSTED`; the other six are `BLOCKED`.
- P6.1 equals P5.1 point-for-point on seven fixtures. Skeleton/FIBER_1 is the
  only dynamically activated Package 6 path.
- Skull and skull-skin FIBER_1 have identical P6.1 points (`max delta = 0.0`),
  identical 30,544-triangle collider inputs, and close timings. Draft Skin does
  not enter planning or collision.
- Skull/FIBER_14 and Skull/FIBER_22 are the strongest combined speed/shape
  results. Skull/FIBER_13 is the only fully converged result.
- Skull/FIBER_4 still has visible contact ripple. Skeleton/FIBER_1 remains a
  visibly angular three-sided route and is slower than V1.

The strict V1 failures mean V1 and V2 timing are not quality-equivalent: V1 is
often faster because it returns geometry the V2 validator rejects. That does not
make P6.1 production-ready; safe output also needs stable convergence, acceptable
anatomical shape, and live latency.

## Artifacts

All artifacts are in `artifacts/fiber_v2_accepted_full/`:

- `accepted_timing.png` — planner, warm solver, and cold full-cycle charts;
- eight `*.json` benchmark records with exact points, phase traces, diagnostics,
  validation, and source hashes;
- eight `*.png` true Blender side-by-side renders;
- eight `*_review.blend` self-contained viewport review files.

Each render is left-to-right: V1, Package 4.3 planner, Package 5.1, Package 6.1.

Source hashes after qualification:

- `skull_muscles.blend` — `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
- `skull_muscles_skin.blend` — `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`
- `skeleton_comb_base.blend` — `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`

Verification: 445 unit tests pass, with six expected native-bridge skips and one
pre-existing expected warm/cold convergence failure. Function-size ratchet,
Python compilation, and diff check pass.

## V1/V2 hybrid performance analysis

### What V1 genuinely does better

V1 has three useful performance properties that can be retained without making
V2 less strict:

1. **Local work.** Its collision correction visits the currently active
   colliders and affected nodes/segments. It does not rebuild an exact contact
   representation for every chain edge before every trial.
2. **Coarse-to-fine budgeting.** V1 distributes one authored iteration budget
   across progressive node counts. It does not spend the full cap at every
   level.
3. **Warm geometric continuity.** V1 can seed the next edit from the prior
   curve. Small edits therefore begin in the previous route corridor instead
   of treating planning as a new global problem.

V1 also appears faster for reasons that cannot be retained in a production V2:

- segment collision is optional during its inner iterations;
- segment penetration uses sparse samples and ray tests rather than the native
  static-distance and continuous-motion authority;
- a failed roadmap can return a straight `LOCAL_FALLBACK`;
- local rollback only prevents a newly introduced sampled collision;
- raw V1 solve results can be finite and visually plausible while failing V2's
  requested node/edge clearance.

That distinction explains the benchmark. V1 beats P6.1 by 2.0–3.6x on
Skull/FIBER_1, FIBER_4, and FIBER_9, but all three V1 outputs fail strict V2
validation. Conversely, V2 already beats V1 by 4.5x on the clear FIBER_13 and
by 3.6x on surface FIBER_22. A dispatcher must therefore select safe work
patterns, not select the V1 result based on Fiber identity.

### What V2 should always keep

- Package 2's banded structural solve: it costs only 0.80–7.33 ms and is not a
  performance problem.
- Package 4.3's native Lazy A* planner when a global route is actually needed.
- One immutable collider/owner policy for planning, contacts, CCD, and final
  validation.
- Exact pins, native continuous acceptance, and one independent final static
  validation.
- Package 6.1's workload dispatcher. Its probe cost is small and it correctly
  selects the dense trust/certificate branch only for Skeleton/FIBER_1.

### Avoidable V2 work proved by the traces

| Avoidable work | Evidence | Safe replacement |
|---|---|---|
| Replanning an unchanged corridor | Planner is 53.8 ms on both skull FIBER_1 variants; 54.4 ms on FIBER_4 | Re-pin and validate the previous V2 corridor; run P4.3 only if that fails |
| Two full ROADMAP plans in Package 5.1 | `_package5_planner` first runs normal P4.3, then reruns it with the final owner span | Plan once with the final owner policy, or rerun only after an owner-span validation failure |
| Querying all chain edges each trial | Candidate/contact is 35.3 ms on FIBER_4 and 60.4 ms on FIBER_9 | Persist per-edge clearance/contact certificates; refresh only dirty or expired edges |
| Four-leg curved CCD for every active trial | FIBER_14 executes 12 waypoints and spends 50.5 ms in CCD | Try one certified linear step first; construct curved waypoints only when a limiting pair blocks it |
| Per-Fiber cold collider capture | Isolated capture costs 196–375 ms | Share one persistent instanced collision world per runtime request and rebuild only deformed SCP BLAS data |
| Exact CCD on provably separated pairs | Skeleton still spends 116.2 ms in CCD after P6.1 reduction | Use conservative distance-versus-motion bounds; exact CCD only for ambiguous pairs |

Final validation is only 2.65–5.30 ms and must not be removed. Structural solve
is also too small to justify replacement. The remaining optimization target is
collision orchestration around those two phases.

### Proposed hybrid dispatcher

The dispatcher should be a strict cascade. Every fast path either proves its
preconditions or falls through to a more general V2 path.

| Mode | Activation rule | Work performed |
|---|---|---|
| `REUSE_REPAIR` | Prior output is `CURRENT`; topology and collider topology match; only anchors or transforms changed | Re-pin the old corridor, update only its dirty window, validate changed edges, then use CCD for their motion |
| `DIRECT_CLEAR` | Strict direct exact-count route is safe; first structural candidate has no active contacts; swept-distance certificate covers all pairs | One banded solve, one certified step, final validator |
| `SURFACE_INTERACTIVE` | P4.3 returns a safe surface corridor | Publish the safe corridor immediately; defer optional structural refinement until quiet/final quality |
| `P51_LIGHT` | Reuse/direct proof fails and first-candidate pair count or density is below the P6.1 thresholds | Current P5.1, but linear CCD first and curved waypoints only on a blocking limiting pair |
| `P61_DENSE` | At least 256 candidate pairs, density at least four per edge, at least 50% bounded compression, and at least 70% certified exclusion | Current Package 6.1 trust/certificate path |
| `FULL_REPLAN` | Collider topology changed, route validation failed, or the changed anchor leaves the prior corridor | Full Package 4.3 plus the appropriate light/dense solver path |

For viewport responsiveness, V1-style local deformation can be used only as a
`STALE` provisional preview. It must never become `CURRENT`, update persistent
point JSON, or reach downstream consumers without the same V2 final validator.

### Required persistent collision state

The largest full-cycle gain needs a persistent, hierarchical native world:

- one local-space BLAS per SCP geometry;
- instance transforms in a shared top-level structure;
- a parent transform update refits that parent and descendant instances;
- only a real mesh deformation rebuilds that SCP's BLAS;
- every Fiber snapshots stable geometry/transform generations rather than
  flattening all triangles again;
- per-edge pair, distance, and contact certificates are keyed by those
  generations and invalidated only for moved edges or changed collider
  instances.

This matches the SCP hierarchy: a parent deformation can move descendants by
transform, but it does not deform their meshes. It therefore avoids paying the
196–375 ms isolated capture cost for every affected Fiber.

### Expected benefit by production fixture

- **FIBER_13:** `DIRECT_CLEAR`; current 30.94 ms should approach the 14.05 ms
  planner cost plus one small structural/validation pass.
- **FIBER_22:** `SURFACE_INTERACTIVE`; a validated visible corridor is available
  near the 9.78 ms P4.3 time, while the 31.28 ms final refinement can remain
  asynchronous.
- **Skull and skull-skin FIBER_1:** corridor reuse removes their approximately
  54 ms planner phase on compatible edits.
- **FIBER_14:** eliminating the duplicate ROADMAP pass can save roughly 10–15
  ms; linear-first CCD and dirty-edge contact refresh target most of the
  remaining 66 ms candidate/CCD cost.
- **FIBER_4 and FIBER_9:** planner reuse alone is insufficient. Their 95–122 ms
  combined contact/CCD phases require incremental edge certificates and
  limiting-pair-driven curved recovery.
- **Skeleton/FIBER_1:** retain P6.1 dense dispatch. Persistent distance
  certificates and instanced collision data are required to reduce its 116 ms
  CCD phase; the light path must not be selected.

These are optimization targets, not claimed benchmark results. Each mode needs
an A/B benchmark and point/clearance parity check before acceptance.

### Recommended implementation order

1. Remove the unconditional second ROADMAP plan and add strict route parity
   tests.
2. Add validated previous-corridor reuse for handle and property edits.
3. Add linear-first CCD with limiting-pair-triggered curved recovery.
4. Persist per-edge clearance/contact certificates and refresh dirty edges.
5. Integrate the persistent instanced collision world into multi-Fiber SCP
   requests.
6. Re-run the eight-fixture matrix after every step; retain a mode only when it
   is strict-safe, visibly acceptable, and faster on its activation class.

This ordering follows the LazySP principle of postponing expensive collision
evaluation until it can affect the selected path, while preserving the common
global-plan/local-optimization structure used by CHOMP and TrajOpt. Exact CCD
remains the fail-closed authority for ambiguous swept pairs.
