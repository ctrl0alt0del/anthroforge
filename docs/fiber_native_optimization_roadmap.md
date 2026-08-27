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

## Proposed next improvements

### 1. Persistent fused native V3 session

Keep points, contacts, multipliers, factor buffers, candidate pairs, CCD certificates, and
containment state in one native session. Expose bounded `begin`, `step`, and `finish` calls so
Python retains scheduling and publication but stops repacking every numerical phase.

### 2. Topology-shared worlds and batched transform refit

Separate topology, deformation, and transform generations. Reuse triangle BVHs when only an SCP
transform changes, submit all descendant transforms together, and refit the world BVH once.
Rebuild only the geometry of an actually deformed collider.

### 3. Allocation-free native workspaces

Reuse traversal stacks, candidate arrays, contact rows, block matrices, factors, RHS vectors,
and CCD interval queues. Remove per-edge `vector`, per-point `priority_queue`, and per-solve
factor allocations from hot paths.

### 4. Better BVH construction and traversal

Use compact cache-line-sized nodes, binned SAH construction for stable geometry, iterative
near-first traversal, deterministic per-edge emission, and refitting for unchanged topology.
Avoid global contact sorting when deterministic traversal can already produce canonical order.

### 5. Precomputed transformed geometry

On each collider transform, cache world vertices, triangle edges, normals, bounds, and inverse
padding scale once. Reuse them across contact, nearest, CCD broad phase, and static validation.

### 6. SIMD packet kernels

Add runtime-dispatched AVX2 packets for AABB and triangle tests with conservative double-precision
semantics. Do not use approximate reciprocal/square-root operations or fast-math in safety tests.

### 7. Compiler optimization

Benchmark `/GL`, `/LTCG`, and representative profile-guided optimization trained on the supplied
sphere, skull, skull-skin, and skeleton captures. Keep PGO and SIMD contributions independently
measurable.

### 8. Reduce CCD work without changing its reduction

Retain certified fat swept bounds per Fiber edge, share broad-phase traversal with contact
acquisition, reuse containment per state generation, and fuse Python's pair batches into one
persistent native job while preserving the current sequential safe-fraction order.

### 9. Versioned CCD replacement

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
