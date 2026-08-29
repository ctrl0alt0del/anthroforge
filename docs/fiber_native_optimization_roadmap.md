# Fiber native optimization roadmap

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

### 5. SIMD packet kernels

Add runtime-dispatched AVX2 packets for AABB and triangle tests with conservative double-precision
semantics. Do not use approximate reciprocal/square-root operations or fast-math in safety tests.

### 6. Compiler optimization

Benchmark `/GL`, `/LTCG`, and representative profile-guided optimization trained on the supplied
sphere, skull, skull-skin, and skeleton captures. Keep PGO and SIMD contributions independently
measurable.

### 7. Reduce CCD work without changing its reduction

Retain certified fat swept bounds per Fiber edge, share broad-phase traversal with contact
acquisition, and reuse containment per accepted-state generation. The persistent session already
fuses Python's pair batches while preserving the sequential safe-fraction order.

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
