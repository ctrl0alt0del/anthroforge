# Fiber V2.2 C++ migration and cold-start analysis

Date: 2026-08-17

## Conclusion

V2.2 has meaningful work that should move behind a larger C++ boundary, but the
banded structural solve is not that work. The highest-value native targets are:

1. one persistent per-SCP collision hierarchy shared by every affected Fiber;
2. one fused contact, candidate, CCD, merit, and acceptance session;
3. batched multi-Fiber collision work against that shared hierarchy.

Cold V2.2 is currently slow for two additional, directly demonstrated reasons:

- collider capture converts arrays into nested Python tuples and validates every
  scalar through frozen dataclass contracts;
- one solve constructs overlapping native acceleration structures three times
  per collider, including two collision worlds under inconsistent cache keys.

These are implementation problems. They are separate from V2.2's remaining
contact-direction, convergence, attachment-compatibility, and exact-count
handoff problems. C++ can make a correct iteration cheaper, but it cannot make a
blocked or incorrect search direction correct.

## Existing native boundary

Package 4.3 and Package 5.1 already place the geometric kernels in
`af_fiber_ccd.dll`:

- triangle and per-collider BVHs;
- nearest-point and fused contact queries;
- static edge validation;
- graph edge validation and lazy A* search;
- swept segment/triangle CCD.

Python still constructs query rows, owner intervals and candidates, calls those
kernels repeatedly, manages pair caches, evaluates merit, accepts or rejects
trials, and converts results back into Python records.

The recommended final boundary is a resumable native session:

```text
native_session.step(work_budget)
    refresh contact rows
    construct base and curved candidates
    reuse candidate pairs
    run CCD
    evaluate merit
    accept or reject
    update diagnostics
```

Python should retain Blender capture, request scheduling, provisional display,
token validation and final commit. NumPy officially supports direct C access to
contiguous ndarray storage, so a stable array ABI need not copy every value
through Python objects: <https://numpy.org/doc/stable/reference/c-api/array.html>.

## Fresh cold-profile method

`tools/fiber_v22_cold_profile.py` runs in a fresh Blender 5.0.1 background
process. It measures unprofiled capture and cold solve wall time, then repeats
the cold solve under `cProfile` for attribution. Before each cold solve it clears
the V2.2 route, triangle-snapshot, native-world and structural caches. Blender
and the DLL are already loaded, so the figures are cache-cold solver figures,
not application-launch figures.

Evaluated mesh data is intentionally captured through Blender's dependency
graph. Blender documents that final geometry must be obtained from an evaluated
object: <https://docs.blender.org/api/5.0/bpy.types.GeometrySet.html>.

Fresh raw records are stored in:

- `artifacts/fiber_v22_audit/cold_skull_f14.json`;
- `artifacts/fiber_v22_audit/cold_skull_f4.json`;
- `artifacts/fiber_v22_audit/cold_skeleton_f1.json`.

## Measured cold path

Times are milliseconds. `Capture` includes collider capture, anchors and request
construction. `Cold solve` is unprofiled. Individual build timings are isolated
measurements and overlap the cold solve; they must not be added to it again.

| Fixture | Capture | Cold solve | Isolated total | Combined snapshot | One collision world |
|---|---:|---:|---:|---:|---:|
| Skull/FIBER_14 | 140.74 | 245.11 | 385.85 | 65.38 | 53.51 |
| Skull/FIBER_4 | 169.40 | 333.84 | 503.23 | 73.12 | 61.14 |
| Skeleton/FIBER_1 | 319.92 | 426.88 | 746.80 | 76.96 | 77.74 |

These results agree with the broader audit: warm reuse is useful, while a real
geometry-generation change pays hundreds of milliseconds before publication or
downstream synchronization.

## Root cause 1: Python object capture dominates mesh extraction

`V2ColliderSnapshot` stores vertices and triangles as nested tuples. Its
`__post_init__` converts and validates every vertex component and triangle index,
then scans every triangle for bounds validity. The capture probe reports:

| Profiled capture component | Skull, 19 colliders | Skeleton, 32 colliders |
|---|---:|---:|
| `V2ColliderSnapshot.__post_init__` cumulative | 126.01 | 166.29 |
| Evaluated `_surface` extraction cumulative | 13.28 | 20.85 |
| Geometry digest | 1.65 | 2.35 |

The digest is not the bottleneck. Most measured capture time is Python tuple
boxing and scalar contract validation. The replacement should be immutable,
C-contiguous `float64` vertex and integer triangle buffers, validated with
vectorized shape, bounds and finiteness checks. The buffers can then be passed to
C++ without rebuilding nested Python objects.

This change must preserve request immutability. The arrays should be owned by the
captured generation and marked read-only after validation.

## Root cause 2: duplicate native acceleration construction

A cold solve currently builds both:

1. a combined `NativeTriangleSnapshot` used by CCD/static validation;
2. a per-collider `NativeCollisionWorld` used by planning and contacts.

It then builds the collision world a second time. V2.2 `_wide_direct` requests a
world with `v22_snapshot_key(request)`, while planner and solver code request the
same colliders without that generation key. Those become different cache keys.

The profile proves the duplicate construction:

| Fixture | Native-world builds | `_closed_mesh` calls | `_closed_mesh` cumulative |
|---|---:|---:|---:|
| Skull/FIBER_14 | 2 | 57 = 19 × 3 | 109.49 |
| Skull/FIBER_4 | 2 | 57 = 19 × 3 | 105.56 |
| Skeleton/FIBER_1 | 2 | 96 = 32 × 3 | 140.43 |

The three topology passes are one combined snapshot plus two native worlds.
`_closed_mesh` constructs and sorts all mesh edges using `numpy.unique`; it is
repeated even though closedness is generation-invariant.

Immediate correction:

- create one solve-owned collision-world handle and pass it to wide-direct,
  planner, contact construction and validation;
- use one generation key everywhere;
- compute each collider's closed flag once during capture and retain it for that
  geometry generation.

The longer-term C++ correction is to make the persistent collision world provide
CCD candidate enumeration and static minimum distance as well. That removes the
second combined triangle snapshot, its 65-77 ms cold build, and Python's
segment/face pair materialization.

## Root cause 3: cold planning intentionally performs repeated work

V2.2 first runs a wide direct-path validation. If planning returns a ROADMAP, it
runs Package 4.3 planning once with the normal owner-contact factor and then a
second time with factor `8.0`. Fresh profiled cumulative `plan_reference_v43`
time is approximately:

| Fixture | Calls | Cumulative |
|---|---:|---:|
| Skull/FIBER_14 | 2 | 78.85 |
| Skull/FIBER_4 | 2 | 114.55 |
| Skeleton/FIBER_1 | 2 | 107.22 |

The second search was introduced as a correctness recovery, so it should not be
removed blindly. The desired replacement is one search whose owner corridor can
expand without rebuilding candidate geometry, graph storage or collision state.
Until that is implemented, route reuse only hides this cost after the first run.

## Root cause 4: collision work remains fixture-dependent

After cold construction, the same warm bottlenecks remain. The unprofiled cold
traces report CCD at roughly 22 ms for Skull/FIBER_14, 56 ms for Skull/FIBER_4,
and 109 ms for Skeleton/FIBER_1. Candidate/contact work is approximately 17, 31
and 42 ms respectively. Skeleton also spends substantially more time in repeated
accepted-step processing and exhausts its budget.

This explains why one global cold number is misleading: construction cost is
mostly scene-wide, while candidate pairs, CCD subdivisions, curved recovery and
accepted-step counts are Fiber-specific.

## Ranked implementation plan

### Safe structural improvements

1. Fix the collision-world cache-key mismatch and share one world per solve.
2. Store collider closedness once per geometry generation.
3. Replace tuple collider payloads with immutable contiguous array payloads.
4. Retain local-space per-SCP BLAS objects; update descendant transforms using
   native instance matrices and rebuild only a deformed SCP's BLAS.
5. Share that world across every Fiber affected by the same runtime request.

### Native consolidation after correctness is stable

6. Add CCD and minimum-distance operations directly to the persistent world,
   eliminating the combined triangle snapshot and Python pair arrays.
7. Fuse contact construction, candidate generation, curved recovery, CCD,
   merit, acceptance and diagnostics into a resumable native session.
8. Batch independent Fiber sessions against the shared world while keeping all
   Blender access and commits on the main thread.

### Low-value migrations

Do not prioritize moving these components:

- structural banded solve: about 2.60 ms warm average;
- independent final validation: about 3.28 ms and already native;
- compact signature: about 0.24 ms;
- P6.1 dispatch: about 0.50 ms;
- Blender event routing and commit logic.

The theoretical removable time is not equal to the sum of all profiled rows,
because cumulative measurements overlap. No final speedup should be promised
until each change is benchmarked in the complete event-to-commit cycle. The
current data does, however, prove that avoiding duplicate worlds, scalar tuple
capture and duplicate topology scans is a better cold-start investment than
rewriting the 2.60 ms structural solver.

