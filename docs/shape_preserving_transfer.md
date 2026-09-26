# Shape-preserving transfer with bone clearance

Production authoring protocol 0.4 supports `shape_preservation` on
`anatomy.transfer_preview`. Publish with the existing `anatomy.transfer_publish`.
Omitting the block retains the original shared cubic RBF transfer unchanged.
The calculation uses the current packaged native library `af_fiber_ccd_v3_19.dll`; restart
Blender after updating an already loaded addon/native library.

Use `shape_preservation.constraints` (`transfer_constraints.v1`) for a dynamic
list of local attachment, protection, shape, guide and clearance records. See
[the production constraint API](transfer_constraints.md). The settings below
describe the legacy mode used when that field is absent.

## Input and workflow

Select **all heads of one anatomical family** in `source_objects`. Their existing
indexed skeletal correspondences first create the original RBF guide. Supply
attachment-band vertex indices for **every selected head**; obtain their
evaluated topology and geometry digests from `anatomy.transfer_sources`.
Legacy `protected_bands` retain their original RBF-transferred positions exactly.
Explicit `attachment_bands` instead hold qualified target positions on an indexed
SCP region. The API does not infer anatomical bands or certify their selection.
Use separate requests for unrelated muscle families.

Add this block to the ordinary transfer preview request:

```json
{
  "shape_preservation": {
    "family_id": "deltoid.L",
    "protected_bands": [
      {
        "source_object": "Atlas clavicular head",
        "topology_digest": "<captured topology digest>",
        "geometry_digest": "<captured geometry digest>",
        "vertex_indices": [12, 13, 14]
      }
    ],
    "obstacle_instance_ids": ["<scapula instance>", "<acromion instance>", "<clavicle instance>", "<humerus instance>"],
    "tolerance": 0.01,
    "validation_samples": 512,
    "settings": {
      "shape_strength": 18,
      "collision_strength": 60,
      "clearance": 0.002,
      "radius_fraction": 0.3,
      "cluster_radius_fraction": 0.2,
      "far_influence": 0.08,
      "bridge_fraction": 0.015,
      "max_iterations": 240,
      "convergence": 0.00001
    }
  }
}
```

The example illustrates one band; include additional rows for the other selected
heads and their full attachment areas. Index lists are evaluated-source indices,
not coordinates. Capture them again after topology or evaluated geometry changes.
Obstacle IDs are inventory **instance IDs**, including the intended mirror side,
not SCP labels. Include all relevant neighboring bones, not just attachment owners.
The existing detached obstacle normalization repairs overlapping bone components
for queries without changing the actual SCPs, modifiers or indexed discovery.
Open or unresolved obstacle meshes fail explicitly.

## Explicit attachment targets

Capability `transfer_attachment_bands.v1` adds `shape_preservation.attachment_bands`.
Use it for an origin or insertion that must reach a particular existing region,
instead of freezing the initial field's guess. Set `protected_bands` to `[]` when
all attachments use explicit targets. Every selected source still needs a band.
Bands must have unique IDs and disjoint source vertices, including legacy bands.

```json
{
  "id": "index_origin",
  "source_object": "Atlas first dorsal interosseous",
  "topology_digest": "<source evaluated topology>",
  "geometry_digest": "<source evaluated geometry>",
  "vertex_indices": [20, 21, 22],
  "target": {
    "document_id": "skeleton_direct_scp_18",
    "expected_draft_revision": 1,
    "region": "/skeleton_profiles/scp_18/regions/metacarpal_L",
    "topology_digest": "<target evaluated topology>"
  },
  "mapping": {
    "source_frame": [[0, 0, 0], [0, 0, 1], [1, 0, 0]],
    "target_frame": [[2, 0, 0], [2, 0, 2], [3, 0, 0]],
    "max_distance": 0.1
  }
}
```

Each frame contains three **world-space points**: proximal axis origin, distal
axis end, and a point establishing the homologous transverse side. The mapping
rotates and uniformly scales by the target/source axis-length ratio, then uses
one batched native nearest query against the region polygons. `max_distance`
limits the movement from this mapped guess to the region, in world units.
Degenerate frames, stale source geometry, changed target topology/draft, targets
outside the obstacle set, and exceeded projection budgets fail explicitly.
Choose the correct local side/region; nearest projection does not infer anatomy.
Frame coordinates describe the current evaluation, not live deformation bindings.

Alternatively replace `mapping` with `target_bindings`, containing one existing
`{ "tri_vidx": [i,j,k], "tri_weights": [a,b,c] }` binding per source index.
These indexed targets must resolve inside the declared region. The two methods
are mutually exclusive. Bindings preserve target correspondence through
topology-preserving deformation; rerun preview/publication to update the reference.

The existing C++ fitter holds these targets exactly. Its report includes band
identity, target owner/region, mapped positions, projection distance, initial
target error, and final target error. It explicitly does **not** certify whole
attachment-area coverage or intervening triangles. Fully constrained triangles
collapsed by the target mapping are listed before fitting, to distinguish bad
target geometry from distortion introduced by the optimizer. Overly broad or poorly mapped
hard bands can flatten or fold tissue even with zero final target error: inspect
the selected source contact side, faces, span, and surrounding belly. This API
does not perform the remeshed end-cap construction in `continuous_attachment.md`.

Explicit bands replace the corresponding fixed target vertices; movable vertices
still use the original RBF result as a soft guide. A large band correction can
therefore conflict with the inherited belly guide. The FDI diagnostic restored
contact but remained distorted, and increasing shape weight changed that bow.
Do not interpret that weight ablation as a general repair or automatic rebinding
of the whole deformation field. It remains a separate transfer acceptance check.

Publication and replay revalidate the attachment region as well as existing
skeletal correspondences. Changed drafts require a fresh request; old receipts
are not permission to reuse stale attachment targets.

## Controls

| Setting | Default | Meaning |
| --- | --- | --- |
| `shape_strength` | 18 | Resistance to distortion of overlapping source-shape clusters. |
| `collision_strength` | 60 | Relative weight of exit targets for vertices inside bones; zero disables the fitting penalty, but final reports still run. |
| `clearance` | 0.002 | World-unit offset beyond the nearest bone exit for penetrating vertices; not a guaranteed surface margin. |
| `radius_fraction` | 0.30 | Attachment influence falloff distance, relative to maximum target axis extent, using source-mesh graph distances in similarity placement. |
| `far_influence` | 0.08 | Remaining guide influence far from fixed bands. |
| `cluster_radius_fraction` | 0.20 | Radius of overlapping rigid shape neighborhoods relative to maximum source axis extent. |
| `bridge_fraction` | 0.015 | Maximum proximity for up to three local graph links per vertex; zero disables proximity links. |
| `max_iterations` | 240 | Native iteration budget, 1–1000. |
| `convergence` | 0.00001 | World-unit RMS step threshold; small updates do not certify a correct result. |

`tolerance` is required and controls collision review/obstacle normalization;
it does not soften protected attachments. `validation_samples` defaults to 512
seeded area samples, **in addition to every vertex and face centroid**.
World-unit controls must be chosen for the scene's scale.

## Calculation and output semantics

The native implementation fits one proper or reflected similarity placement for
the complete selected family, using the orientation inferred from the skeletal
correspondences and the existing `allow_reflection` setting. It blends between
that placement and the original RBF result using attachment distance, then jointly
fits overlapping rigid clusters and bone-exit penalties. Fixed bands remain exact.
All graph preparation, cluster construction, iterations and iterative collision
queries run in C++; Python marshals arrays and performs final independent review.
There is no Python optimizer fallback, skin boundary or muscle-specific formula.

The preview result's method is `shared_cubic_rbf_shape_clearance.v1`.
`shape_preservation` includes settings, stop reason, elapsed native time, obstacle
normalization, before/after collision reports and separate fixed/movable vertex
penetrations. `source_order` and `vertex_offsets` map family-wide report indices
back to individual heads. Per-mesh `attachment_influence` supports heatmap views.

Original RBF quality and diagnostics are retained as `initial_field_quality` and
`initial_field_diagnostics`, rather than being reported as measurements of the
final surface. The stored RBF `field` is **only the initial skeletal guide**.
Annotations remain mapped by that initial field and are labeled accordingly;
they are not final fitted muscle-surface attachment coordinates.

Remaining collisions, worsened penetration or collapsed triangles mark a preview
`unresolved`. As with ordinary transfer, it can still be published as a separate
review copy with that status preserved. Publication is not anatomical acceptance.
The iteration limit is a warning, not a false claim of convergence. Check complete
head layout and broad form visually before continuing to base/native fibers.

This is approximate local shape preservation, not exact curvature/volume
preservation, an injective deformation, or guaranteed clearance. Fixed bands can
retain inherited bone penetration; triangle interiors can collide even if the
vertex penalty improves the boundary. Multi-ray final reports also check face
centroids, area samples and reverse bone containment. No collision certificate is
issued. Source creases remain for the later simplified base stage.

## Validation

The production native implementation was compared with the user-reviewed
September 23 pectoral, deltoid and FCU experiment using identical frozen inputs.
Maximum coordinate differences were 0, less than `7e-14`, and 0 scene units.
Those fixtures retain their known unresolved penetrations; matching them verifies
implementation fidelity, not general anatomical or collision acceptance.

Maintained tests cover proper/reflected similarity, scale, hard bands,
determinism, collision response, malformed arrays, budgets, protocol validation,
preview replay, stale inputs, transactional publication, rollback and normal
save/reopen. The original transfer remains covered independently.
