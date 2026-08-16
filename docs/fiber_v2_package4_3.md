# Fiber V2 Package 4.3 — fused native planning experiment

## Status and scope

Package 4.3 is one opt-in experiment combining every remaining Package 4 native
optimization. It does not change V1, saved Fiber data, UI defaults, migration, or
downstream publication. Package 4, 4.1, and 4.2 remain callable references.

The experiment contains four inseparable but independently timed native features:

1. hard-anchor collision preflight before candidate or graph construction;
2. fused polyline/edge validation, including owner trimming and containment;
3. persistent per-collider bottom-level BVHs with a refittable top-level hierarchy;
4. native cached-metric Lazy A* coupled directly to native edge validation.

Surface branches use the same native collision world and graph kernel. Candidate
policy and anatomical route ranking remain deterministic Python policy so Package
4.3 can be compared against Package 4.1 without simultaneously changing intent.

## Native collision world

Each SCP collider owns immutable local vertices, triangles, closed/open topology,
owner token, and a local BVH. A top-level BVH contains transformed collider bounds.
Transform-only hierarchy changes refit the top level without rebuilding child mesh
BVHs. Geometry changes replace only the affected collider BVH and then refit the
top level. Exact segment/triangle distances are evaluated in world space, so affine
and nonuniform transforms do not reinterpret the requested clearance.

The Python adapter may construct identity instances from the existing world-space
Package 1 request. Blender benchmark capture additionally exercises real local
meshes and transforms to measure descendant-transform refits.

## Fused validation

One native call receives nodes, edges, endpoint owner tokens, contact span,
clearance threshold, and the collision-world handle. It performs hierarchy broad
phase, local owner-interval subtraction, exact distance, and closed-mesh endpoint
containment. It returns per-edge state, blocker identity, minimum distance, and
candidate/tested counts. No per-pair Python materialization or result scattering is
allowed on the Package 4.3 path.

Hard anchors are submitted as degenerate edges with exact owner exemptions. Any
unrelated collision terminates `INVALID_ATTACHMENT` before graph construction.

## Native Lazy A*

Candidate generation and stable neighbor ordering are inherited from Package 4.1.
The native call receives coordinates plus a CSR graph. It builds the Euclidean
metric once, repeatedly runs deterministic A*, validates only unknown selected-path
edges through the fused validator, rejects invalid edges, and returns the first
fully validated path or no path. Search, validation, and pair counters are returned
for parity and profiling.

## Correctness gates

- Package 4.3 routes, exact references, pins, contacts, and termination match
  Package 4.1 on every existing deterministic fixture unless hard-anchor preflight
  replaces wasted `NO_FEASIBLE_PATH` work with `INVALID_ATTACHMENT`.
- Native fused edge states match Package 3 reference validation for open, closed,
  nonmanifold, transformed, owner-contact, and containment fixtures.
- Identity instances match the existing world-space snapshot bit-for-bit.
- Transform refit matches a clean rebuilt world for every query.
- Hard-anchor preflight identifies the authored index and blocking collider.
- The native backend fails closed when missing, stale, or incompatible.
- Every new or modified function is at most 15 lines.

## Real Blender benchmark matrix

Fresh Blender processes and immutable source hashes are required for:

- `skull_muscles.blend/FIBER_14`;
- `skull_muscles.blend/FIBER_1`;
- `skeleton_comb_base.blend/FIBER_1`;
- `skull_muscles_skin.blend/FIBER_1`;
- Maxilla Top Radius `0.2` / `FIBER_21` with original invalid hard pins;
- the controlled repaired-pin `FIBER_21` request;
- one Maxilla hierarchy edit shared by all affected Fibers.

Report Package 4, 4.1, 4.2, and 4.3 medians, snapshot build/refit, graph search,
collision validation, candidate/tested pairs, termination, and independent final
validation. Produce true Blender side-by-side route renders and a review `.blend`.

## Qualification decision

Package 4.3 is successful only if it preserves safety and route identity while
materially reducing both roadmap and surface workloads. A faster zigzag or an
incorrectly exempted hard anchor fails qualification. The grouped Package 4.2
planner remains disabled unless a feasible production fixture proves a visible
route-quality advantage.
