# Guided muscle reconstruction in authoring 0.4

**Transfer reference volumes → define the retained bone-facing underside → preview
SCP-bound native fibers → publish native Fiber Surfaces → configure inflation.**
Guarded native inflation controls are described in [Section Profile and legacy
authoring](section_profile.md); automated volume fitting is not part of these
operations. Anatomical correspondences, head identities, attachment bands and
review remain explicit inputs; successful execution does not certify anatomical
accuracy.

For an already reviewed path, [Controlled and Free fibers](free_fibers.md)
describes direct sampled/Bézier creation, editing the current deformed path,
shared structural tags and solver-free attachment updates. The planning
operations below retain their existing Controlled behavior.

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

The modeling target is an **approximate smooth anatomical underside**. Design
clean borders from meaningful landmarks and broad shape evidence; do not trace
every extracted vertex, projection kink or sampling artifact. Preserve complete
attachment bands, belly width, all heads and intentional clefts. Inspect actual
border/interior smoothness independently of residuals, topology and spatial
checks before native fibers. See the [smooth-border construction and acceptance
contract](muscle_base_preparation.md#anatomical-approximation-and-smooth-borders).
The current API's geometry checks do not automatically certify that contract.

Choose the modeled extent at this stage. Thin tendrils and tendon-like areas
that add no useful inflated muscle volume may be omitted (user direction,
September 20, 2026). Record excluded parts and the crop boundary with the base,
then carry that same extent through native surfaces, inflation, measurements,
mirroring and saved-scene regeneration. Preserve substantial heads, belly width
and their shared structure; small thickness alone is not an automatic cutoff.
A cropped edge is a modeling boundary, not an anatomical attachment. Qualified
curves outside the retained extent may remain as visible construction controls,
but must not regenerate excluded muscle tissue. Compare against the retained
reference extent and disclose the omissions rather than claim a full-volume fit.

For an end crop, persist the native muscle extent with `muscles.domain_configure`
after defining the cropped base. `muscles.domain_inspect` takes `muscle_id` and
returns the current `output_domain` and `base_revision`. Configuration requires
`muscle_id`, `expected_scene_revision`, `expected_base_revision`, and:

```json
{
  "configuration": {
    "mode": "plane", "space": "root_local",
    "origin": [0, 0, 0], "normal": [0, 0, 1], "keep_positive": true
  }
}
```

These coordinates illustrate the API, not an anatomical cut. The plane follows
the avatar root. It selects retained material on the evaluated base and uses the
same edge-interpolation weights on the inflated surface. Inflation is evaluated
before cropping, so the cut does not create a new zero-depth perimeter pinch.
The complete branched assembly is cropped once, preserving shared edge identity;
mirrors use the cropped geometry. Source bindings, shared-point identities and
qualified construction curves are unchanged. `{"mode":"full"}` restores the
complete evaluated muscle. Invalid or wholly empty authoring cuts are rejected
without publication. The edit panel exposes the same muscle-extent controls.

The current native extent supports one plane per muscle. Omit separate fine
continuation parts at the base/family level and remove their native dependents;
do not keep their generated tissue merely hidden. A plane crop is not a general
automatic detector for tendons or noninflating anatomy.

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
Zero-area fragments from region clipping are ignored during nearest-point
selection. If the closest region guess fails native qualification, the picker
tries at most eight nearby interior triangle guesses. Each must still satisfy
the original region, facing, distance and zero-offset constraints. This bounded
search can remain unresolved; it is not a global nearest-qualified-point proof.

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

The [Section Profile controls and native API](section_profile.md) provide an
optional open-loft inflation workflow: inspect and preview a current surface,
then create a muscle with an atomic initial configuration using
`muscles.create_from_surface`. The same controls remain editable in Blender.

Receipts make publication idempotent. Manual edits to published records or paths
cause a conflict; a changed reference/support requires replanning. Keep the matching
journal when saving/reloading. Repeated preview requests revalidate live inputs
before reusing numerical work. Previews never mutate the Blender scene.

Use `StaticScene.save_debug_copy` (also used by the command-line runner). Reopen
normally to verify source/mirrored fibers visible as normal curves and native SCP
colors in Solid/Object mode. Report anatomical review, sampled base fit, native
route clearance, base topology/spatial checks, persistence and visibility separately.
A ready base does not certify muscle-surface collision clearance or inflation fit.
See [draft volume-fitting practices](muscle_volume_fitting.md) for separate
transfer, base-width, thickness-fit and visual review checks.

For a previously qualified pick at a sharp SCP crease, `points.edit` can retain
the selected native face exactly: provide `attachment: {parent_id, attach_param}`
instead of `position`/`scp_id`, with an optional native `offset`. The raw attachment
must name an actual evaluated `surface_param_v2` triangle with valid barycentrics.
Both the underlying zero-offset point and final offset must qualify without
replacement of the supplied binding; an occluded face or a changed fallback pick
is rejected atomically. Indexed region membership, facing and bounded source
distance still require the caller's anatomical qualification evidence. Existing
world-point edits retain their normal snapping behavior. Ordinary endpoints stay
at zero offset; shared-point changes invalidate all incident native geometry.
