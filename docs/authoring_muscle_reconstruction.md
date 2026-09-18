# Guided muscle reconstruction in authoring 0.4

**Transfer reference volumes → define the whole bone-facing underside → preview
SCP-bound native fibers → publish native Fiber Surfaces.** Inflation fitting is
deferred. Anatomical correspondences, head identities, attachment bands and review
remain explicit inputs; successful execution does not certify anatomical accuracy.

Use `app.authoring.api.execute(request, root, scene, journal_directory)` or
`tools/authoring_blender.py`. `anatomy.discover` advertises `skeleton_transfer.v1`,
`muscle_base.v1`, and `native_base.v1`; old experimental names remain compatibility
aliases. All calls use the 0.4 envelope with a unique `request_id`, `scene_id` and
current `expected_scene_revision`. Indices refer to evaluated capture assets.

## Transfer and repair

`anatomy.transfer_sources`, `transfer_preview`, and `transfer_publish` capture
reference meshes, fit one shared field from indexed skeletal correspondences,
and publish independent review objects. Different source/target topology is
supported; homologous landmarks are supplied, not inferred or copied by index.
See [the transfer contract](anatomy_transfer.md).

`anatomy.repair_volume` takes `sources`, each with `source_object`,
`topology_digest`, and `geometry_digest`. It evaluates Blender Exact self-union
on disposable copies. Only results without open/nonmanifold edges, degenerate
triangles or detected nonadjacent overlaps become separate review objects.
Failures return an unresolved diagnostic asset. No source or SCP is modified.
Capture the repaired object again; Boolean repair invalidates its old face IDs.
Exact Boolean is not guaranteed to resolve every source; there is no silent
voxel or approximate repair fallback.

## Define the whole underside and heads

`anatomy.base_candidates` takes the three source fields above plus
`support_instances` (SCP authoring IDs). It returns per-face nearest-bone normal,
facing, visibility and distance evidence. There is **no contact-distance cutoff**:
suspended underside spans remain candidates. Evidence can contain holes/fragments;
components are not interpreted as anatomical heads.

`anatomy.define_base` takes the source fields and:

```json
{
  "anatomical_note": "Describe whole underside, heads and attachment proxies.",
  "heads": [{"id": "main", "label": "Anatomical identity"}],
  "patches": [{
    "id": "belly", "head_ids": ["main"],
    "source_triangles": [0, 1],
    "boundary_vertex_ids": [0, 1, 2, 3]
  }]
}
```

These example indices illustrate fields, not anatomical selections. Each patch
must be a connected disk with one boundary, no holes, and no detected spatial
overlap. Four distinct boundary vertices, ordered **start-left, start-right,
end-right, end-left**, establish direction and across-fiber ordering. All named
heads must participate; patch triangle selections cannot overlap.

Optional `anatomy.prepare_base` completes incomplete evidence with explicitly
declared boundaries and seams. It returns `base_surface.id` and an assembled mesh
asset. Only a `geometry_candidate` can feed `define_base`: supply
`prepared_base_id` instead of the three source fields, keep its head definitions,
and use triangle/vertex indices from its assembled mesh. Spatial folds remain
blocked even when topological holes have disappeared. See
[completion constraints and known failures](muscle_base_preparation.md).

Source geometry and topology digests guard selections. Source deformation requires
refitting; it does not rebuild the skeleton's indexed regions. Mesh work is bounded;
oversized/complex selections require manageable explicit patches or completion.

## Preview native fibers

`anatomy.plan_base_fibers` takes `base_id`, a positive scene-unit `tolerance`, and
one `parts` entry per patch: `{patch_id, bindings}`. Every binding has:

- `role`: `origin`, `insertion`, or `route`.
- `document_id`, `expected_draft_revision`, `region`: existing discovery data.
- `across`: inclusive interval from 0 to 1 across the patch.
- `max_distance`: maximum underside-guess-to-pin displacement in scene units.
- Optional `along`: inclusive route interval along the reference curve.
- Optional `facing`, `minimum_facing_dot`: the required outward anatomical side.

Bands may cover different SCPs. Where they overlap, the closest valid qualified
candidate wins. Use facing constraints when a region also contains the opposite
bone surface; collision qualification alone cannot identify anatomical side.

The implementation parameterizes the disk, samples longitudinal underside curves,
and selects a sparse set from fixed candidates using measured strip error. Native
V3 routes start with two endpoints; measured deviations justify sparse corrections.
**Every authored pin has zero offset and retained triangle vertex indices and
barycentric weights.** Solver nodes and loft interior vertices are not pins.

Defaults: 17 candidates, 65 samples/curve, maximum 8 fibers/patch, 2 middle points,
64 solver calls, 2 seconds/solve and a 30-second numerical budget. Set
`max_middle_points` up to **8**. Dense samples are measurement data, not pins.
`candidate_count`, `samples_per_fiber`, `max_fibers`, `collision_radius`,
`max_solver_calls` and `solver_budget_ms` are explicit bounded options.

The plan asset records source guesses, bindings, native routes, correction reasons,
actual loft geometry, fit error, topology and spatial checks. Unresolved plans cannot
publish. Change constraints explicitly; the planner does not silently add unsupported
pins or increase budgets. The count is sparse within fixed candidates, not a global
minimum. Separate head patches become coordinated parts; no shared branch junctions
or arbitrary connector graph is invented by this operation.

## Publish, resume and export

`anatomy.publish_base_fibers` takes `plan_id` and current scene revision. It rechecks
source geometry, supports and discovery revisions, then atomically appends native
fibers and LOFT Fiber Surfaces with head associations. It creates no inflated
muscles. The native Create Muscle from Fiber Surface action remains available for
subsequent manual inflation configuration.

Receipts make publication idempotent. Manual edits to published records or paths
cause a conflict; a changed reference/support requires replanning. Keep the matching
journal when saving/reloading. Repeated preview requests revalidate live inputs
before reusing numerical work. Previews never mutate the Blender scene.

Use `StaticScene.save_debug_copy` (also used by the command-line runner). Reopen
normally to verify source/mirrored fibers visible as normal curves and native SCP
colors in Solid/Object mode. Report anatomical review, sampled base fit, native
route clearance, base topology/spatial checks, persistence and visibility separately.
A ready base does not certify muscle-surface collision clearance or inflation fit.
