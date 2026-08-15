# Fiber V2 Package 4.2 — grouped routes and persistent native collision BVH

## Status and scope

Package 4.2 is an opt-in experimental planner entry point. It does not change V1,
saved Fiber data, migration, UI defaults, or downstream publication. It combines:

- a shared surface/roadmap candidate space for consecutive anchors on one owner;
- a persistent, generation-keyed collision snapshot cache;
- a native deterministic BVH retained by each snapshot;
- snapshot-native broad phase, exact segment/triangle distances, and closed-mesh
  containment without rebuilding or copying triangle geometry per query.

The experiment answers two separate questions: whether independent route segments
caused the Maxilla/FIBER_21 rollback, and whether persistent prebuilt collision data
reduces Package 4 collision cost.

## Grouped planner

Package 4.2 detects runs of at least three consecutive anchors with the same owner.
It first searches one offset owner-mesh graph for the entire run, preserving one
surface side and one validated topology. If no surface-chain route exists, it uses
one deduplicated candidate pool shared by every segment in the run. Ordinary pairs
and cyclic Fibers retain Package 4.1 behavior.

This removes accidental candidate-space independence, but hard authored anchors
remain exact. Grouping is not allowed to hide an invalid anchor or ignore an
unrelated collider.

## Persistent native collision snapshot

The packaged Windows native backend now reports `af_fiber_ccd-1.31`. A snapshot
owns immutable vertices, triangle indices, face bounds, and a deterministic
median-split BVH. The same handle serves:

1. swept/static edge AABB candidate queries;
2. exact segment/triangle distances by face index;
3. closed-mesh containment over a collider's contiguous face range.

`V2CollisionSnapshotCache` retains at most eight snapshots by an explicit geometry
generation key. A hierarchy edit creates one new cold snapshot; every affected
Fiber can reuse it. Callers must include parent deformation and descendant transform
generations in that key. Empty keys fail rather than risk stale geometry.

This package does not yet implement per-SCP local-space BLAS plus a refittable TLAS.
Therefore a changed hierarchy still requires one world-space rebuild. The measured
benefit comes from sharing that rebuild and from faster BVH/native queries, not from
pretending transformed child geometry is unchanged.

## Real Maxilla/FIBER_21 qualification

Source: `skull_muscles.blend`, SHA-256
`A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`.
The source remained byte-identical. The benchmark changed **Maxilla Top Radius**
from its stored value to `0.2` in memory, settled the evaluated hierarchy, and
captured 30,544 triangles.

### Rollback verdict

Package 4.2 does **not** fix this Fiber's rollback. It terminates
`NO_FEASIBLE_PATH`, as do Packages 4 and 4.1. The decisive evidence is at the hard
anchors, before route search:

- anchors 4 and 5 are owned by Lateral Cartilage (`SCP_10`);
- both are already within the requested clearance of Nasal (`SCP_4`);
- Nasal is an ancestor through `SCP_10 → SCP_11 → SCP_4`;
- neither anchor is inside a closed collider, but both violate the 0.002 clearance;
- hard pins cannot be displaced by the planner or solver.

The direct anchor segments 3–5 are blocked by both Lateral Cartilage and Nasal.
All ten tested owner-surface variants (five offsets, both normal signs) find the
first SCP_10 subsegment but fail the next two. This disproves the hypothesis that
pairwise side selection alone caused the rollback.

The correct next feature is an authored, hierarchy-aware **local contact set**:
an attachment on a descendant may locally contact explicitly related ancestor
surfaces, while those same surfaces remain colliders everywhere outside the bounded
attachment interval. Globally excluding Nasal, relaxing clearance, or moving hard
pins would hide a real policy error and is rejected.

## Performance result

Fresh Blender 5.0.1 processes on the current Windows workstation; the old column
uses the sorted-AABB native snapshot and the new column uses the persistent BVH.
Planner medians use the same evaluated scene and collision semantics.

| Planner | Pre-BVH baseline | Persistent native BVH | Reduction | Result |
|---|---:|---:|---:|---|
| Package 4 | 2510.35 ms | 2063.29 ms | 17.8% | `NO_FEASIBLE_PATH` |
| Package 4.1 | 989.98 ms | 728.49 ms | 26.4% | `NO_FEASIBLE_PATH` |
| Package 4.2 | 2183.87 ms | 1841.66 ms | 15.7% | `NO_FEASIBLE_PATH` |

The first 30,544-triangle cached snapshot build costs 63.32 ms. Five same-generation
lookups have a 0.0011 ms median, with one miss and five hits. Full Blender evaluated
collider capture plus cold BVH build is 178.56 ms, essentially unchanged from the
old 182.17 ms capture; persistence therefore matters only when one captured
snapshot is shared across affected Fibers.

Package 4.2 itself is slower than Package 4.1 on this failing fixture because its
surface-chain qualification adds 20 graph builds before the fallback search. It is
not a rollout candidate in its current form. The native BVH improvement is useful
independently and should be retained for the next hierarchy-contact experiment.
The Package 4 and 4.1 rows are clean unchanged-planner comparisons. The Package 4.2
baseline predates the final offset-mesh chain search, so its 15.7% reduction is an
end-to-end package comparison rather than a pure BVH A/B.

### Controlled repaired-pin retry

The planner comparison was repeated after replacing only invalid anchors 4 and 5
in memory. Each remained an exact `SCP_10` hard pin and was moved to the nearest
distinct collision-valid sample on the evaluated `SCP_10` surface. Displacements
were 0.0123841 and 0.0124103 world units. The source blend was never saved and its
SHA-256 remained unchanged.

| Planner | Original pins | Repaired pins | Repaired validation |
|---|---:|---:|---|
| Package 4.1 | 894.48 ms, `NO_FEASIBLE_PATH` | 84.68 ms, `CONVERGED` | valid |
| Package 4.2 | 2107.17 ms, `NO_FEASIBLE_PATH` | 95.36 ms, `CONVERGED` | valid |

Both repaired planners returned the same 64-node reference bit-for-bit. Package
4.2 tested fewer collision pairs (775 versus 937), but remained 12.6% slower because
it performed eight graph-metric builds and sixteen graph searches versus two and
nine for Package 4.1. The invalid pins therefore caused most of the catastrophic
4.2 slowdown, but grouping still provides no result-quality benefit on this route.
It should remain experimental until a coupled route fixture demonstrates a benefit.

## Tests and artifacts

- 381 unit tests pass, with one pre-existing expected failure.
- Focused collision tests: 24/24 pass.
- Focused planner tests: 13/13 pass.
- Full Blender discovery: 473/474 pass. The sole failure is the explicitly skipped
  Stage-0 Quick Fiber persistence case (`af_fiber_points_world` is absent after
  refinement); it reproduces alone and Package 4.2 is not active on that V1 path.
- Native/reference primitive, containment, CCD, and transformed-world tests pass.
- Function-size ratchet passes; every new or modified function is at most 15 lines.
- `git diff --check` reports no whitespace errors.

Artifacts:

- `artifacts/fiber_v2_package42/maxilla_bvh_repeats3.json` — benchmark and cache data;
- `artifacts/fiber_v2_package42/maxilla_anchor_clearance.json` — hard-pin and blocker diagnostics;
- `artifacts/fiber_v2_package42/maxilla_package42_comparison.png` — true Blender render;
- `artifacts/fiber_v2_package42/maxilla_bvh_benchmark.png` — timing comparison.
- `artifacts/fiber_v2_package42/maxilla_fixed_pins_retry.json` — controlled repaired-pin retry;
- `artifacts/fiber_v2_package42/maxilla_fixed_pins_retry.png` — repaired 4.1/4.2 Blender render.

## Research basis

The persistent multi-query structure follows the preprocessing/reuse principle in
[Bekris et al., *Multiple Query Probabilistic Roadmap Planning using Single Query
Planning Primitives*](https://www.cse.lehigh.edu/~chen/papers/pdfs/bekris2003prt-multiple-single-query.pdf).
Lazy edge validation follows the motivation in
[Sánchez and Latombe, *On Delaying Collision Checking in PRM
Planning*](https://journals.sagepub.com/doi/10.1177/027836402320556458): collision
tests dominate and should be postponed until a candidate path needs them. The
retained BVH separates reusable spatial indexing from dynamic queries. Reuse is
generation-guarded because stale collision data is never an acceptable optimization.
