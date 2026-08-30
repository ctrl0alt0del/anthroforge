# Fiber native optimization roadmap

> Production update: the persistent native controller is the V3 default. Human visual review
> accepted its qualified FIBER_14 and skeleton/FIBER_1 paths. Set
> `AF_FIBER_V3_NATIVE_CONTROLLER=0` only for the retained Python diagnostic reference.
> See `fiber_v3_persistent_controller_production_trial.md`.

## Baseline

The accepted exact-parity OpenMP experiment used four worker threads for independent native
contact, nearest-point, and static-validation queries. It deliberately kept CCD serial because
parallel absolute-TOI reduction changed the nonlinear solver trajectory.

Measured production V3 runs on the current Ryzen 9 7900X3D workstation were:

| Fixture | Serial | Four workers | Improvement | Output parity |
| --- | ---: | ---: | ---: | --- |
| `skull_muscles/FIBER_14` | 361.88 ms | 320.46 ms | 11.4% | Bit-identical |
| `skeleton_comb_base/FIBER_1` | 1623.70 ms | 1460.27 ms | 10.1% | Bit-identical |

Each value is the median of four fresh Blender processes. All 64 coordinates matched byte for
byte between scalar and four-worker execution. Prior phase profiling showed CCD remained the
dominant serial phase, so further large gains must reduce CCD work or orchestration.

## LLVM OpenMP production backend

The Windows V3 backend now builds with Clang 19, precise floating-point semantics, and LLVM
OpenMP. The backend capability signature distinguishes this build from the retired MSVC/vcomp
binary, invalidating native-dependent caches when the backend changes.

The promotion A/B used `skull_muscles.blend/FIBER_14` at the final 180-step budget. Four
alternating fresh Blender processes measured 292.95 ms median for MSVC/vcomp and 287.32 ms for
Clang/libomp, a 1.9% reduction. All 64 coordinates were bit-identical. Both runs reported the
same safe `STALLED` state, 19 active contacts, zero penetration, and identical residuals.

The compiler change is accepted primarily to unlock modern OpenMP task scheduling. It is not
treated as a material solver optimization by itself. The locally installed Microsoft libomp
binary is suitable for development; release redistribution requires a separately approved
runtime provenance because Microsoft's `/openmp:llvm` documentation does not grant production
redistribution of that supplied DLL.

## Production threading contract

- Default to four native workers, capped by the available logical processor count.
- `AF_FIBER_NATIVE_THREADS` is read when the DLL is first loaded; use a fresh Blender process
  after changing it.
- Use deterministic static work assignment.
- Workers calculate independent indexed results only.
- Aggregate counters, minima, contacts, and output rows serially in original index order.
- Keep `af_mesh_pair_safe_step` and every CCD reduction serial.
- Include the parallel capability and selected worker count in backend identity and diagnostics.
- Preserve scalar execution for small batches where thread-team overhead is not recoverable.
- Missing OpenMP runtime makes V3 `BACKEND_UNAVAILABLE`; it never selects an unsafe fallback.

## Persistent fused native V3 session

`fiber-v3-production-2` now owns a persistent native session for each V3 span. It retains
edge/owner data, immutable triangle snapshots, contact rows, structural matrices and factors,
response workspaces, candidate-pair buffers, and CCD interval storage. Python still owns the
request token, round-robin scheduling, contact-group policy, SQP merit/regularization decisions,
cancellation, validation acceptance, and publication.

The production call boundary now fuses contact acquisition with independent validation, reuses
the native structural-response workspace, and constructs/filter/packs each feasible CCD job in
native code. CCD safe-fraction reduction remains serial and retains its original 128-pair batch
order, so the optimization trajectory is unchanged.

Six fresh Blender processes per mode, alternated reference/fused at the final 180-step cap,
measured:

| Fixture | Reference boundary | Persistent session | Improvement | Output parity |
| --- | ---: | ---: | ---: | --- |
| `skull_muscles/FIBER_14` | 279.63 ms | 252.26 ms | 9.8% / 1.11× | Bit-identical |
| `skeleton_comb_base/FIBER_1` | 1205.73 ms | 708.28 ms | 41.3% / 1.70× | Bit-identical |

Every comparison returned the same 64 coordinates. Both source `.blend` SHA-256 hashes remained
unchanged. `AF_FIBER_V3_NATIVE_SESSION=0` retains the old Python/native boundary as a temporary
internal reference; production defaults to the persistent session.

## Multi-Fiber resource coordinator

Production V3 now has one cooperative coordinator over isolated per-Fiber sessions. Blender
capture, validation of request identity, preview application, commit, and downstream dispatch
remain on the main thread. Only immutable native CCD jobs from distinct sessions may enter the
OpenMP executor; two jobs with the same session handle are rejected. Hard-midpoint spans within
one Fiber remain sequential, preserving the accepted global-budget trajectory.

The scheduling boundary uses injected policy and executor objects. Selected Fibers have priority
over other visible Fibers, visible Fibers have priority over background work, and bounded aging
prevents starvation. Cancellation unregisters the job and closes every retained native span
session. Successful commits from one coordinator turn are combined into one
`FIBER_SOLVE_READY` event per root. A batch exception fails closed and retains last-good output.

Cross-session work is dynamically dispatched. A two-batch qualification measures whether the
native jobs recover the OpenMP team cost. Jobs below 0.25 ms use the serial native call path;
parallel execution remains available for qualified work. Automatic multi-session scheduling is
enabled for four or more simultaneous small Fibers or a Fiber with at least 256 nodes. The
internal `AF_FIBER_V3_BATCH=0/1` overrides exist for reference/qualification only; `AUTO` is the
production default.

The supplied skull fixture showed why the dynamic gate is required. `FIBER_1` and `FIBER_14`
used only about 31 ms of actual CCD time across 366 sweeps. Three fresh-process runs measured
1270.21 ms median for the serial dispatcher and 1270.56 ms for forced batching (0.03% difference),
with identical point hashes, terminations, accepted/rejected counts, and source-file hashes.
Accordingly, production `AUTO` does not batch that two-Fiber workload. A four-Fiber run also
retained all four exact point hashes and measured 2290.03 ms serial versus 2291.63 ms coordinated
in the qualification samples; the adaptive executor disabled parallel CCD after it measured the
jobs below threshold.

The coordinator integration also removed two unrelated runtime amplifiers exposed by profiling:
V3 numeric iterations no longer masquerade as Blender display-level changes, and full collider
stamp scans are limited to the 50 ms publication cadence while depsgraph invalidation remains
immediate and final commit forces a full check. On `skull_muscles.blend/FIBER_1,FIBER_14`, three
fresh-process legacy-runtime runs measured 1896.47 ms median versus 1270.21 ms after the fix, a
33.0% full-cycle reduction. Outputs were bit-identical.

This is a resource-coordinator foundation, not a claim that complete Fiber solves now run in
parallel. Contact grouping, SQP policy, active-set decisions, and acceptance still execute in
Python. Actual CCD is much smaller than the old diagnostic suggested because that timer included
time waiting between progressive slices; per-job native timing now reports the true kernel cost.
The next material cross-Fiber gain requires exposing contact/structural work as resumable native
jobs or moving the accepted numeric iteration fully behind the persistent native-session API.

## Full-session worker-pool experiment

An isolated experiment tested whether the existing pure-data V3 sessions could be scheduled as
whole resumable jobs before moving more policy into C++. Blender captured and primed every request
on the main thread, then a short-lived `ThreadPoolExecutor` repeatedly assigned fixed quanta from
independent sessions to any free worker. The pool was always joined before Blender resumed, no
worker accessed RNA or the depsgraph, and one session was never advanced concurrently by two jobs.

The experiment is intentionally unreachable from production. It lives in
`core/vcp/v3/session_pool_experiment.py` and is driven read-only by
`tools/fiber_v3_session_pool_benchmark.py`.

Three fresh-process runs on `skull_muscles.blend/FIBER_1,FIBER_14` measured:

| Configuration | Median solve | Median capture + setup + solve | Relative full time |
| --- | ---: | ---: | ---: |
| Serial sessions, four native workers | 1007.07 ms | 1215.81 ms | reference |
| Two session workers, one native worker each | 1107.73 ms | 1326.46 ms | 9.1% slower |
| Two session workers, two native workers each | 1083.50 ms | 1287.67 ms | 5.9% slower |
| Two session workers, four native workers each | 1101.10 ms | 1330.02 ms | 9.4% slower |

Every run produced bit-identical coordinates, terminations, accepted/rejected counts, and source
file hashes. A four-Fiber qualification sample was also exact, but four session workers with four
native workers increased solver time from 1894.55 ms to 2418.00 ms (27.6%).

The result rejects Python-level full-session threading as a production optimization. The accepted
solver still spends substantial work in Python contact grouping, objective construction, active-set
policy, acceptance, and diagnostics, so the GIL serializes much of the supposedly parallel work.
Nested per-session OpenMP teams also contend for cache and memory bandwidth, while unequal Fiber
durations leave fixed per-session allocations underused. A useful option-B implementation therefore
needs one native task graph and one OpenMP team, with Python limited to capture, cancellation,
scheduling priorities, and publication. Merely placing existing `session.step()` calls on Python
threads is not sufficient.

## Heterogeneous native-operation executor experiment

The follow-up isolated experiment replaced fixed Fiber-to-worker ownership with a native OpenMP
executor accepting heterogeneous contact-measure, structural-response, and CCD jobs. Lightweight
Python control drivers pause at the exact native call; the broker submits immutable descriptors;
workers claim whichever job is ready. A worker therefore has no Fiber identity and can execute
work for different Fibers in consecutive waves. The production DLL and V3 selector remain
unchanged; the experiment uses `af_fiber_ccd_v3_ops_experiment.dll`.

The allocator gives a single ready job the complete native team. It enables outer operation-level
parallelism only when at least four independent jobs are ready for four workers, and bypasses the
broker when one Fiber remains. This avoids deliberately idling cores merely to preserve the
experiment.

Three alternating fresh-process runs on `skull_muscles.blend` measured:

| Workload | Direct V3 median | Operation executor median | Difference | Exact parity |
| --- | ---: | ---: | ---: | --- |
| `FIBER_1,FIBER_14`, solve only | 1007.39 ms | 1179.86 ms | 17.1% slower | Yes |
| `FIBER_1,FIBER_14`, capture + setup + solve | 1206.28 ms | 1397.13 ms | 15.8% slower | Yes |
| Four Fibers, solve only | 2186.34 ms | 2988.07 ms | 36.7% slower | Yes |

Every Fiber retained its exact point hash, termination, accepted/rejected counts, validation state,
and point count. The source hash stayed `a7c4033ab2eb7479eaec4a069cb1d7ddf9fecc5d5c43037863b02a9f9bb7ef06`.
The four-Fiber set includes the pre-existing unsafe `FIBER_21`; both paths returned the same unsafe
result, so it proves scheduler parity but is not a correctness qualification for that Fiber.

The two-Fiber workload generated roughly 523 brokered jobs in 264 waves but never had four ready
at once, so it correctly retained inner-kernel parallelism. The four-Fiber workload generated about
2492 jobs in 1136 waves and did reach four workers, yet remained slower. The experiment therefore
rejects whole contact/structural/CCD calls as the shared-pool job granularity:

- each Python condition/event handoff adds overhead hundreds or thousands of times per solve;
- four ready high-level jobs turn four internally parallel kernels into four single-worker kernels;
- Fiber phases do not stay aligned, so the ready queue is commonly smaller than the worker count;
- job costs differ sharply, and the long Fiber tail cannot overlap completed Fibers;
- the block recurrence and Python acceptance/controller work remain serial.

The useful next version must keep the coordinator and solver iteration wholly native and expose
range jobs inside contact traversal and CCD, for example 16--64 Fiber edges or 64--128 candidate
pairs. Indexed outputs and stable serial reductions can preserve exact results. Python should see
only `begin`, bounded `step(deadline)`, cancellation, diagnostics, and final publication—not one
round trip per numeric operation. The isolated executor is evidence and scaffolding, not a
production optimization.

## Persistent C++ task coordinator experiment

The next isolated backend moves ownership of native operation streams and their cursors into C++.
It exposes `create`, bounded `step(deadline)`, and `destroy`; a step opens one OpenMP team and lets
workers claim range jobs without returning to Python between numerical operations. The production
DLL remains unchanged. The experiment is capability-versioned separately and lives in
`af_fiber_ccd_v3_ops_experiment.dll`.

The implemented work graph uses:

- 32-edge contact and validation jobs;
- 32-edge CCD broad-phase jobs and 128-pair narrow-phase jobs;
- serial block factorization and forward/backward structural recurrence;
- per-edge/per-pair indexed writes followed by stable index-order reduction;
- persistent per-span native sessions and C++-owned stream cursors across bounded steps.

Trace replay removes Python from the measured numerical chain without claiming that the remaining
SQP controller has already been ported. On `skull_muscles/FIBER_1,FIBER_14`, the three-run median
for replaying about 522 recorded native operations was 58.46 ms with four workers. A paired
one-worker/four-worker run measured 108.53/52.00 ms, a 2.09x kernel-graph speedup. The ordinary
full V3 solve remained 1112.96 ms median; these boundaries are deliberately not conflated.

The long-tail `skeleton_comb_base/FIBER_1` trace contained 1954 native operations, 992 contact
jobs, 992 validation jobs, 729 serial structural jobs, 1458 CCD broad-phase jobs, and 4315 CCD
pair jobs. One worker required 994.97 ms; four workers required 601.63 ms, a 39.5% reduction or
1.65x speedup. All source file hashes remained unchanged.

Contact/validation rows and structural outputs matched exactly in every unit and real-file trace.
The indexed absolute-TOI CCD reduction intentionally differs from the old order-dependent product:
on skull, four sweeps became at most `1.53e-5` more permissive; on skeleton, three became at most
`3.37e-4` more permissive. Valid/invalid decisions did not change, and independent static-check
failure counts were identical before and after replay. Raw CCD diagnostic hashes differ because
the parallel implementation computes certificates for a whole range before stable reduction.

A live-controller qualification proved the numerical consequence cannot be hidden. All final
Fibers remained independently validated, but skull accepted/rejected counts and point hashes
changed, and skeleton/FIBER_1 changed from 486/243 accepted/rejected trials to 407/168. Calling the
coordinator once per old Python wave was also slower on skull (1492.76 ms versus the 1112.96 ms
direct median), because it still launches hundreds of teams and retains Python control flow.

Therefore the native task/resource architecture is accepted as a promising experiment, but the
absolute-TOI reduction and live result are not production-approved. Production integration needs
two explicit decisions: port the accepted SQP controller so one bounded native step covers several
iterations, and either retain the legacy serial CCD trajectory or version and visually approve the
order-independent CCD trajectory. Silent result drift is not acceptable.

## Native SQP/controller experiment

The next isolated backend ports the finite-work span loop behind one C++ call. It keeps one OpenMP
team alive while C++ performs true-length IRLS assembly, active-set response solves, trust limiting,
adaptive regularization, contact retention, limiting-pair injection, CCD, filter acceptance,
multiplier updates, convergence checks, and round-robin shared-budget span scheduling. Python now
performs capture, planner/seed initialization, independent stitched validation, and reporting only.
The experiment DLL is `af_fiber_ccd_v3_sqp_experiment.dll`; production remains unchanged.

Two CCD policies run under the same native controller:

- `LEGACY` retains the serial 128-pair multiplicative safe-step trajectory;
- `INDEXED` evaluates stable indexed edge/pair jobs and performs a deterministic absolute-minimum
  reduction.

One fresh-process qualification sample per real Fiber measured the native controller boundary:

| Fixture | Legacy CCD | Indexed CCD | Indexed change | Max final-point delta | Decisions |
| --- | ---: | ---: | ---: | ---: | --- |
| `fiber_sphere/FIBER_2` | 51.26 ms | 55.41 ms | 8.1% slower | `6.80e-6` | 288/288 identical |
| `skeleton_comb_base/FIBER_1` | 762.46 ms | 612.07 ms | 19.7% faster / 1.25x | `1.73e-9` | 1053/1053 identical |
| `skull_muscles/FIBER_1` | 75.81 ms | 83.06 ms | 9.6% slower | `1.70e-10` | 236/236 identical |
| `skull_muscles/FIBER_14` | 37.58 ms | 38.53 ms | 2.5% slower | `2.69e-7` | 110/110 identical |

Every legacy and indexed result passed independent stitched static validation. Accepted/rejected
counts and every accept/reject/inject decision matched for all four Fibers. Safe fractions can
differ because the reductions have different semantics, but contact retention and limiter
migration prevent those differences from changing the measured controller trajectory. All source
`.blend` hashes remained unchanged.

The indexed policy is therefore useful only on a sufficiently large CCD workload. It loses on
the three light Fibers because OpenMP task creation exceeds the saved pair work, while the long
skeleton Fiber recovers that overhead. Any production form needs a per-sweep dynamic activation
gate based on edge/pair job counts, not a global always-on switch.

The native controller is not bitwise Python-parity. Against the Python reference, maximum final
point differences were `1.3193`, `0.16224`, `0.00698`, and `0.02258` world units for sphere,
skeleton, skull/FIBER_1, and skull/FIBER_14 respectively. Timing comparisons against production
were originally not treated as speedup claims. The remaining semantic difference is in the higher-level collision
manifold policy: coherent side selection for ambiguous contact groups, exact production limiter
feature migration, and the production contact/stationarity termination details. Until those are
ported and numerical parity passes. Human visual qualification subsequently accepted the safe
native paths, so production-5 versions this behavior rather than claiming bitwise equivalence.

The benchmark JSON contains complete per-trial CCD fractions, model ratios, violations, limiter
identities, and decisions. Matching Blender comparison copies and trajectory plots are stored in
the task visualization output; they are generated from source files without saving the sources.

## Proposed next improvements

### 1. Topology-shared worlds and batched transform refit

Separate topology, deformation, and transform generations. Reuse triangle BVHs when only an SCP
transform changes, submit all descendant transforms together, and refit the world BVH once.
Rebuild only the geometry of an actually deformed collider.

### 2. Allocation-free native workspaces

Reuse traversal stacks, candidate arrays, contact rows, block matrices, factors, RHS vectors,
and CCD interval queues. Remove per-edge `vector`, per-point `priority_queue`, and per-solve
factor allocations from hot paths.

### 3. Better BVH construction and traversal

Use compact cache-line-sized nodes, binned SAH construction for stable geometry, iterative
near-first traversal, deterministic per-edge emission, and refitting for unchanged topology.
Avoid global contact sorting when deterministic traversal can already produce canonical order.

### 4. Precomputed transformed geometry

On each collider transform, cache world vertices, triangle edges, normals, bounds, and inverse
padding scale once. Reuse them across contact, nearest, CCD broad phase, and static validation.

**Partial implementation tested 2026-08-30 — rejected, concept still open.** Contiguous triangle
vertices/normals inside each native snapshot preserved exact results but made skull `FIBER_1`
11.9% slower. The native world persisted, but V3 rebuilt its flattened CCD snapshot for every new
solve session, so this did not test a fully persistent cross-recompute triangle cache.

### 5. SIMD packet kernels

Add runtime-dispatched AVX2 packets for AABB and triangle tests with conservative double-precision
semantics. Do not use approximate reciprocal/square-root operations or fast-math in safety tests.

**Tested 2026-08-30 — rejected.** Global AVX2 changed the numerical trajectory. Function-local
`avx2,no-fma` preserved exact results but was neutral on skull and 5.6% slower on skeleton.

### 6. Compiler optimization

Benchmark `/GL`, `/LTCG`, and representative profile-guided optimization trained on the supplied
sphere, skull, skull-skin, and skeleton captures. Keep PGO and SIMD contributions independently
measurable.

**Tested 2026-08-30 — rejected.** LTO regressed the heavy skeleton fixture. PGO preserved exact
results but its fresh-process full-cycle gain was inconsistent and remained within run variance.

### 7. Reduce CCD work without changing its reduction

Retain certified fat swept bounds per Fiber edge, share broad-phase traversal with contact
acquisition, and reuse containment per accepted-state generation. The persistent session already
fuses Python's pair batches while preserving the sequential safe-fraction order.

**Tested 2026-08-30 — accepted narrowly.** Production retains exact fat-bound reuse only after a
previous sweep contains at least 512 pairs. It reduced dense skeleton CCD time by 8.8% and full
solve time by about 1%; sparse skull sweeps stay on the original BVH path.

### 8. Versioned CCD replacement

Only after exact-parity work is exhausted, evaluate independent absolute-TOI queries with a
deterministic global minimum. This is a numerical algorithm change, not transparent threading;
it requires a new backend version, adversarial safety qualification, and visual approval.

## Required validation for every native optimization

- Scalar and optimized coordinates, terminations, counts, and diagnostics must match exactly
  unless the change is explicitly versioned as numerical.
- Test cold and warm runs in fresh Blender processes.
- Record full request-to-validated-package time and native phase timings separately.
- Preserve all source `.blend` hashes.
- Run native reference/adversarial collision suites, unit/Blender suites, compilation, dependency
  inspection, and the function-size ratchet.
