# Simplified base and native Free fibers

For neighboring heads with overlapping facing borders, use explicit
`overlap_repairs` or the standalone `anatomy.partition_base_surfaces` operation.
See [local shared-border repair](base_surface_partition.md) for its chart inputs,
limits, persistence semantics and biceps evidence. No adjacency is inferred.

The reconstruction workflow has three operational stages: **transfer → simplified
base with native Free fibers → inflation**. `anatomy.smooth_base_preview` and
`anatomy.smooth_base_publish` implement the combined middle stage in authoring 0.4,
advertised as `smooth_native_base.v1`. They do not depend on experimental scripts.

The caller supplies the retained underside, anatomical heads, sparse fiber count,
attachment neighborhoods and explicit shared sides. C++ fits smooth longitudinal
curves jointly, preserving broad shape instead of tracing every mesh crease.
The fitted base uses the same piecewise ruled strips as the native loft. The API
evaluates the actual native surface before allowing publication. It does not
automatically discover heads, choose the anatomical underside, or fix bone collisions.
Those remain transfer/modeling responsibilities.

## Request

Call `app.authoring.api.execute(request, root, scene, journal_directory)` with the
ordinary `version="0.4.0"`, `message_type="request"`, `request_id` and `op` envelope.
Preview parameters:

| Parameter | Meaning |
| --- | --- |
| `scene_id`, `expected_scene_revision` | Current `anatomy.discover` identity/revision |
| `source_object`, `topology_digest`, `geometry_digest` | Evaluated mesh captured by `anatomy.transfer_sources` |
| `family` | Anatomical family name retained on native muscles |
| `heads` | Unique `{id, label}` records; every head must belong to a patch |
| `patches` | One to eight directed disk patches described below |
| `seams` | Explicit shared longitudinal sides; use `[]` for one patch |
| `settings` | Fit controls and explicit world-unit error bounds |
| `anatomical_note` | Scope, approximations and retained/omitted anatomy |

A patch has `id`, `head_ids`, and two to eight `endpoints` pairs. Each pair is one
future fiber, ordered across the patch. Each `{start, end}` pin specifies
`instance_id`, world `position`, and `max_distance`. Pins use native qualified
nearest-surface snapping, not raw closest-triangle projection. Rejection remains
unresolved. They define attachment neighborhoods, not automatic anatomical truth.

Choose one indexed shape input:

- `grid_vertex_ids`: rectangular indices, **across × along**, each dimension 4–129.
  They select samples from the captured source; they are not native routing pins.
- `source_triangles` with four `boundary_vertex_ids`: start-left, start-right,
  end-right, end-left around one disk. A bounded native harmonic solve establishes
  correspondence and a 17×49 sampling grid. Holes, disconnected selections,
  folded charts and invalid boundary landmarks are rejected.

Total input fit samples cannot exceed 40,000. Triangle selection is limited to
8,192 triangles and harmonic charts to 8,192 vertices after chart preparation.
For both forms, source geometry and topology guards must match the capture.

Optional patch `output_domain` uses the existing muscle output-domain schema:
`{"mode":"full"}` or a plane in `root_local` space. A modeling cut is not a physical
attachment. Pin `mode="extend"` preserves the fitted body edge and adds a fixed
cubic construction extension to its qualified bone pin. Default `mode="fit"`
locks the fitted edge to that pin. Paired paths must use matching parameter extents;
prefer the same extension modes within a patch. Retained geometry is checked after
the declared cut; excluded construction fibers remain visible for debugging.

Example seam:

```json
{"id":"common-belly",
 "first":{"patch_id":"main","side":1},
 "second":{"patch_id":"head","side":0}}
```

Side `0` is the first fiber, side `1` the last. Both sides must have identical
endpoint definitions and the same longitudinal direction. The entire boundary is
one shared curve, and publication uses **one native fiber identity in both surfaces**.
This is a coordinated-parts representation, not an arbitrary branched-loft wrapper.
A side cannot join multiple seams. Partial branches, reversed seams and nested
graphs must be designed with existing explicit branch tools or another decomposition.

Physical endpoints have zero normal offset. A seam endpoint may supply
`normal_offset` and a nonempty `purpose`: it is a shared structural junction, not
a claimed bone insertion. Its offset attachment is requalified without changing
the retained binding. Conflicting duplicate endpoint definitions are rejected.

## Settings and fitting

| Setting | Default / bounds |
| --- | --- |
| `longitudinal_controls` | 6; 4–8 cubic spline controls per fiber |
| `fairness` | 0.0001; 1e-8–1 |
| `junction_smoothness` | 0.001; 0–1; soft transverse tangent penalty |
| `samples_per_fiber` | 33; 9–65; tessellation, not modeling controls |
| `max_shape_error` | Required positive world-unit distance to supplied shape samples |
| `max_native_error` | Required positive world-unit bidirectional holdout distance |
| `max_width_change` | 0.15; fraction at five interior stations |
| `collision_radius` | 0.002; qualified attachment selection only |

The fit normalizes scene scale, combines shape and boundary samples with sparse
fairness terms, locks qualified endpoints and enforces shared-curve equality.
Sampled transverse ordering constraints discourage collapsed/crossed strips and
opposing seam sides. The bounded constraint iteration can return
`BASE_ORDER_UNRESOLVED`; it is not a global topology or optimality proof. Actual
native geometry is independently inspected. No Python optimizer or routing solver
runs. All iterative fitting and harmonic solving use packaged `af_fiber_ccd_v3_18`.

This low-dimensional representation suppresses local bumps. It does not promise
globally smooth transverse derivatives: ruled strips can have derivative changes
at fibers, and shared seams are exactly positional with softly regularized tangents.
Increasing controls to chase raw anatomy defeats the simplified modeling target.

## Preview and publication

Preview is read-only for Blender objects. The content-addressed journal asset
contains source definitions, sparse spline controls, complete Free paths, explicit
material stations, fitted and native meshes, retained-domain meshes and checks.
The response has `base_surface.id`, `quality`, `unique_fibers`, parts and diagnostics.
`status="unresolved"` retains diagnostic geometry but blocks publication.

Checks include maximum/RMS shape change, five width changes, bidirectional native
holdout distance, degenerate triangles and triangle crossings within and between
retained parts. Shared coincident seam vertices are treated as adjacency. This is
not an exhaustive intersection certificate; visual review remains necessary.
No global bone-clearance or anatomical acceptance is inferred from readiness.

Publish with `scene_id`, current `expected_scene_revision`, and `preview_id`.
The source/support guards and preview readiness are rechecked before mutation.
Publication is transactional: it creates Free fibers, coordinated Fiber Surfaces
and uninflated native muscles, checks the regenerated geometry against the preview,
then saves the receipt. Failures, including journal writes, restore native data.
Keep the journal beside the `.blend` and export through `StaticScene.save_debug_copy`.

Repeating publication returns the same native identities if their saved native
configuration is unchanged. It does not create duplicates or refit evaluated
geometry. `geometry_revalidated=false` distinguishes this receipt lookup from a
fresh geometry certification. Changed paths/settings reject replay with
`BASE_EXTERNAL_EDIT`. Before first publication, changed source/supports require
a fresh preview.

## Correspondence, editing and inflation

Authored surfaces retain `af_authoring_free_surface_stations`. Unlike normalized
arc length, these material stations preserve where neighboring curves correspond
even when their lengths differ. Existing surfaces without this metadata retain
their existing behavior. Native inflation receives this same prepared base.

Moving samples while keeping identities preserves stations exactly. Explicit Free
Edit Path/resampling retains surviving sample anchors and interpolates material
stations by normalized span length for new samples. Changing endpoint identities
or reversing their order is rejected rather than silently twisting the loft.
After intentional edits, review shape again; the old fit acceptance no longer applies.
Attachment deformation and Free recomputation preserve the sampled-path contract
without invoking a routing solver. Material correspondence currently requires
ordinary open Free lofts; it does not imply support for closed or mirrored-row
expansion modes.

Control Point, Distributed and Section Profile inflation remain separate existing
operations. A shared boundary does not automatically blend inflated derivatives;
evaluate the resulting head assembly when fitting depth. Base checks never claim
that an inflation fit has been completed.

A clear transferred reference does not establish clearance of the smoothed native
base. The September 22 FCU run measured new penetration into the humerus and ulna
after fitting, despite a clear corrected reference. Check actual retained native
triangles against the relevant SCPs after fitting and after inflation. Localize
such failures to the combined base stage when the reference remains clear;
inflation cannot repair its fixed perimeter. API readiness is not bone clearance.

Method references: [Stanford surface fitting](https://graphics.stanford.edu/papers/surfacefitting/)
and [PCL B-spline fitting](https://pointclouds.org/documentation/tutorials/bspline_fitting.html).
These inform the low-dimensional approximation; the native-compatible ruled basis,
qualified pins and native publication checks are AnthroForge-specific.
