# Fiber V2 Package 4 — deterministic planner and exact-count handoff

## Outcome

Package 4 is implemented as an isolated, Blender-independent planner. It consumes
the immutable Package 1 request and Package 3 triangle snapshot and returns a
deterministic corridor, an exact-count reference `q`, hard-pin indices, localized
owner contacts, diagnostics, and a precise termination reason.

It is not connected to V1 editing, preview publication, persistence, or migration.
The supplied `.blend` files were opened read-only for capture and benchmarking.

## Algorithm

The planner evaluates branches in this order:

1. Strict direct visibility using the complete Package 3 collision policy.
2. For same-owner anchors, a deterministic lifted local-surface bridge followed by
   mesh A* when the local bridge is not valid.
3. A sparse compatibility shell around direct blockers. This preserves the useful
   obstacle samples of the existing planner while applying Package 3's stricter
   collider and owner-contact rules.
4. Deterministic Lazy PRM over k-nearest sparse/dense fallback graphs.
5. Collision-checked shortcutting.
6. Corridor-preserving exact-count subdivision. Corridor vertices are retained;
   the handoff never replaces a bend with an unchecked arc-resampling chord.
7. Independent Package 3 validation of the exact points and edges returned as `q`.

The same immutable collider snapshot, clearance radius, numerical slack, and local
owner-contact semantics are used throughout. Unrelated colliders are never removed.
An invalid exact-count handoff returns `NO_FEASIBLE_PATH`.

## Automated coverage

Focused Package 4/Package 3 tests cover:

- direct open and cyclic routes;
- exact node count and hard-pin ordering;
- unrelated closed blockers;
- deterministic replay;
- missing native backend;
- invalid/inside starts;
- localized endpoint-owner contact;
- segment-batch parity with individual Package 3 validation;
- the close-anchor sphere case that previously produced planner fanning.

The focused suite passes 31/31 and the function-size ratchet passes. Every new or
modified Python function is at most 15 lines.

The complete unit suite passes 375/375 (one expected failure). The complete Blender suite reaches 473/474 with
only the previously known Package 0 Quick Fiber persistence error
(`af_fiber_points_world` missing after asynchronous refinement). Package 4 is not
integrated into that workflow and introduces no new Blender-suite failure.

## Real Blender benchmark

Environment: Blender 5.0.1, Python 3.11.13, Windows x64, AMD Family 25 Model 97.
Each planner timing is the median of three calls against one already-built immutable
snapshot. Snapshot capture is reported separately because Package 5/11 will share it
across affected Fibers.

These rows intentionally exercise three different production Fibers. In particular,
`skull_muscles/FIBER_14` and `skull_muscles_skin/FIBER_1` are not a before/after
Draft Skin comparison. A controlled `FIBER_1` comparison proves Draft Skin is
excluded and produces the same Package 4 reference; see
`docs/fiber_v2_package4_profile.md`.

| Fixture | Triangles | Snapshot capture | V1 median | V1 strict result | Package 4 median | Branch | Package 4 result |
|---|---:|---:|---:|---|---:|---|---|
| `skull_muscles.blend/FIBER_14` | 30,544 | 205.86 ms | 146.33 ms | unsafe edge, residual 0.000925764 BU | 404.22 ms | ROADMAP | exact 64, valid |
| `skeleton_comb_base.blend/FIBER_1` | 39,180 | 404.15 ms | 116.05 ms | valid | 939.55 ms | ROADMAP | exact 64, valid |
| `skull_muscles_skin.blend/FIBER_1` | 30,544 | 243.45 ms | 39.94 ms | six unsafe edges, residual 0.001548551 BU | 443.43 ms | SURFACE | exact 64, valid |

Package 4 is deterministic in all recorded repeats. Its final node and edge
clearance residuals are zero under Package 3 validation.

The skeleton route is the important compatibility result: Package 4 reproduces the
four-point V1 corridor with a maximum corresponding-point delta of
`2.34e-7` BU and the same path length (`8.344900` BU), while validating the exact
64-point handoff. Earlier Package 4 prototypes took 8.27 seconds and escaped around
the global bounding box with a 20.85-BU route; the compatibility shell plus lazy
graph reduced that to 0.94 seconds and restored the intended rib-cage route.

On the two skull fixtures, V1 is faster because it accepts planner routes that fail
the unified Package 3 edge-clearance validator. Package 4 takes a longer safe route:
`1.560151` versus `1.014068` BU for FIBER_14, and `0.809525` versus `0.724949` BU for
the surface Fiber. Package 5 is responsible for optimizing these safe references;
Package 4 deliberately does not trade clearance correctness for path length.

## Visual artifacts

- `artifacts/fiber_v2_package4/real_file_planner_preview.png` overlays V1 and
  Package 4 routes on nearby evaluated collision triangles.
- `artifacts/fiber_v2_package4/planner_benchmark_comparison.png` compares median
  wall time.
- The adjacent JSON files contain routes, exact references, collider counts,
  pair counts, validation results, environment data, and source hashes.

## Performance analysis

The simple synthetic blocker remains within the 150 ms interactive unit budget.
Production time is currently dominated by strict containment and edge validation:

- skeleton: 223 speculative edges and 33,941 tested edge/triangle pairs;
- skull FIBER_14: 83 edges and 8,680 tested pairs;
- skull-skin surface Fiber: 665 edge checks but only 3,076 tested pairs, with mesh
  surface-path candidates dominating instead.

Solve-local containment caching prevents reclassifying the same roadmap point on
every lazy edge. Eager complete graphs and validation-deferral experiments were
rejected: they either exceeded 8 seconds on the skeleton or performed more exact
candidate retries while providing no safety benefit.

Package 4 passes the binary clearance check but fails qualification as the V2
planner. It is neither fast enough nor consistently anatomically useful enough to
become Package 5's fixed reference `q`. The strict validator remains reusable, but
Package 5 must not be asked to repair a poor planner corridor.

## Blender render qualification

The following artifacts are true Blender 5.0 Eevee renders. They reconstruct the
captured evaluated production collision meshes and routes in one scene with the
same camera, lighting, transforms, and diagnostic materials. Only the divider and
text labels are added afterward. Left is V1; right is Package 4.

- `artifacts/fiber_v2_package4/skull_fiber14_blender_side_by_side.png`: failed.
  Package 4 is safe but takes a large, visibly implausible triangular detour.
- `artifacts/fiber_v2_package4/skeleton_fiber1_blender_side_by_side.png`: route
  quality passes and visually matches V1, but 939.55 ms versus 116.05 ms fails the
  live-editing requirement.
- `artifacts/fiber_v2_package4/skull_skin_fiber1_blender_side_by_side.png`: the
  Package 4 route is safe but visibly more angular and costs 443.43 ms versus
  39.94 ms. It is only a candidate seed, not a qualified anatomical corridor.

The quality failure occurs because exact collision validity is the only hard route
criterion after sparse sampling. The search has no bound on detour ratio, corridor
deviation, maximum turn, or distance from a locally repaired route. When nearby
samples cannot repair an unsafe V1-like edge, the graph may choose a globally safe
shell vertex and still call the resulting route successful.

Required redesign: retain the unified collision snapshot and final validator, but
search in tiers: direct route, local repair around only the blocking triangles,
surface corridor, regional roadmap, and global fallback only for final-quality
work. Rank valid candidates by detour ratio, maximum corridor deviation, curvature,
and then length. An implausible global detour must be rejected or reported as no
acceptable corridor rather than silently supplied to Package 5.

## Immutable benchmark hashes

- `skull_muscles.blend`: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
- `skeleton_comb_base.blend`: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`
- `skull_muscles_skin.blend`: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`

## Research basis

The roadmap branch follows the deterministic application of probabilistic roadmap
ideas and lazy collision evaluation: build reusable obstacle-space samples, search
geometrically, and validate only candidate edges. Collision-checked shortcutting is
used only after a valid corridor exists. Package 4 keeps deterministic samples and
tie-breaking because V2 requires reproducible cold results.
