# Skeleton-driven anatomy transfer

Use the optional `shape_preservation` block on `anatomy.transfer_preview` for the
joint family shape-preservation and bone-clearance fit. See
[shape_preserving_transfer.md](shape_preserving_transfer.md) for indexed bands,
controls, final-surface reports and publication semantics. Without that block the
original shared-field behavior described below is unchanged.

Authoring 0.4 exposes `skeleton_transfer.v1` (with the former experimental alias). It fits **one spatial
deformation from paired skeletal landmarks**, then applies that same field to all
selected reference muscle meshes and optional annotations. Muscle names have no
effect on the algorithm. A target skin is not required.

This implements the reference-volume stage of the
[guided reconstruction flow](authoring_muscle_reconstruction.md). Transfer itself
does not fit native fibers, lofts or inflation. It also does not infer source
bone identity or source-to-target anatomical correspondence. Existing target
discovery provides permitted regions; a caller must choose homologous source and
target landmarks within them once for the group being transferred.

## Operations and workflow

Use `app.authoring.api.execute(request, root, scene, journal_directory)`, or the
existing `tools/authoring_blender.py` JSON runner. Import the reference bone and
muscle meshes into the working scene first. Work in a copy for experiments.

1. `anatomy.discover` supplies the current scene revision, SCP instance IDs and
   discovery catalogue. Initialize stable identities if needed. The discover
   inventory asset contains evaluated target geometry. Use a retained discovery
   draft; no muscle recipe is required.
2. `anatomy.transfer_sources` with `source_objects` and `expected_scene_revision`
   exports evaluated reference geometry, topology signatures and geometry digests.
   Include the reference bones whose surfaces will carry correspondence landmarks.
3. `anatomy.transfer_preview` fits the field and writes a journal asset containing
   the mapped meshes, the reusable field coefficients, correspondences and quality
   diagnostics. It creates **no Blender objects**. The response gives `preview_id`.
4. `anatomy.transfer_publish` takes `preview_id` and `expected_scene_revision` and
   creates independent meshes in `AF_TRANSFER_REVIEW_<id>`. It preserves the original
   references, SCPs, discovery and native muscles/fibers. Replaying publication
   reuses the same objects and rejects a manually edited review collection.

All operations use the existing protocol envelope:

```json
{
  "version": "0.4.0",
  "message_type": "request",
  "request_id": "unique-request-id",
  "op": "anatomy.transfer_preview",
  "params": {
    "scene_id": "AF_ROOT",
    "expected_scene_revision": "revision-from-discover",
    "source_objects": ["AtlasMuscleA", "AtlasMuscleB"],
    "correspondences": [],
    "settings": {"max_landmark_error": 0.001}
  }
}
```

Populate `correspondences` with **4–256 distinct, noncoplanar source landmarks**.
The empty array above is a placeholder, not an executable request. Each row is:

```json
{
  "id": "named-skeletal-landmark",
  "source": {
    "object": "AtlasBone",
    "topology_digest": "signature-from-transfer_sources",
    "surface_binding": {"tri_vidx": [12, 18, 19], "tri_weights": [0.2, 0.3, 0.5]}
  },
  "target": {
    "document_id": "saved-discovery-document",
    "expected_draft_revision": 1,
    "region": "/skeleton_profiles/body/regions/named_region",
    "topology_digest": "signature-of-evaluated-SCP-topology",
    "surface_binding": {"tri_vidx": [41, 53, 55], "tri_weights": [0.4, 0.2, 0.4]}
  }
}
```

The indices and weights above are illustrative; obtain real bindings from the
captured geometry. `anatomy.snap_points` can supply qualified **target** bindings
after anatomical neighborhood selection. Transfer verifies that each resolved
target point lies in its named discovery region; it does not replace that choice
with the region centroid or an unconstrained nearest point.

Bindings use evaluated triangle vertex IDs and barycentric weights, plus an
indexed topology signature. Coordinate deformation updates their world positions
without rebuilding regions. A removed/retessellated binding triangle or changed
connectivity requires rebinding. Discovery polygon patches themselves retain their
existing retessellation support. Dataset vertex indices are never copied to the
different target SCP topology.

Source and target do **not** need equal vertex counts, face connectivity or matching
indices. Each topology signature validates that mesh's own stored binding; the two
signatures are never required to match. The field receives paired world positions,
not paired mesh vertices. The original visual demo used copied support meshes for
convenient landmark selection, so it did not demonstrate this distinction. A separate
Blender regression now previews and publishes two reference volumes using a cube
source and an independently generated UV-sphere target with different connectivity,
surface bindings and vertex counts. This checks topology independence, not anatomical
correspondence or whole-surface registration.

Optional `annotations` entries contain `id`, `label` and `source` using the same
source-binding structure. Their transferred positions use the **same field** as
the meshes. They are review annotations, not persisted native attachment pins.

## Method and settings

The prototype uses a cubic radial-basis field with an affine tail, solved with
Blender's bundled NumPy. No SciPy installation is needed. For normalized source
landmarks `X`, the kernel is `K[i,j] = ||X[i] - X[j]||^3`, and the polynomial columns
are `[1,x,y,z]`. Solve the standard constrained block system for weights and affine
coefficients, then evaluate it in world coordinates for every mesh vertex.

This is an implementation of the shared-field concept, not an embedded-deformation
graph or a muscle-specific registration procedure. The standard RBF formulation
is documented in [SciPy's RBFInterpolator reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html).
Bone-landmark-driven morphing has precedent in
[AnyBody's scaling workflow](https://anyscript.org/anybody-tutorial/Scaling/lesson3.html);
that precedent does not certify this implementation's anatomical results.

| Setting | Meaning |
|---|---|
| `max_landmark_error` | Required positive error tolerance in **target scene units**. No automatic unit conversion. |
| `smoothing` | Defaults to `0` for landmark interpolation; `0..1` regularization in normalized source coordinates. Nonzero values allow landmark error. |
| `allow_reflection` | Defaults to `false`. Explicit opt-in for a globally mirrored correspondence; sampled local inversions still produce errors. |
| `max_axis_ratio` | Defaults to `10`. Warn above this sampled local anisotropic stretch ratio. |
| `samples_per_mesh` | Defaults to `2048`; range `32..4096`. Samples vertices and triangle centers for Jacobian checks. |

Limits: 128 selected output meshes, 384 total captured objects including landmark
owners, 500,000 total evaluated vertices, and 1,024 optional annotations. The
landmark solve is cubic in landmark count; mesh evaluation is proportional to
vertex count × landmark count. Evaluation is chunked to bound temporary arrays.

## Review and persistence

`transfer.landmarks` reports per-landmark, maximum and RMS error. Per-mesh reports
include sampled Jacobian orientation/collapse, principal stretches, axis ratio,
collapsed output triangles, degenerate source triangles and the fraction of
samples outside the landmark **axis-aligned bounds**. This last check is not a
convex-hull test. Source object transforms are baked into output world vertices;
reflected transforms and explicit field reflections preserve triangle winding.
With reflection enabled, expected handedness comes from a least-squares affine
fit to the mapped skeletal landmarks, shared across every transferred mesh.
The RBF polynomial tail alone is not the complete deformation and may have the
opposite handedness. Local Jacobians are still checked against that common
reference; a mesh with the opposite sign or a collapsed region remains unresolved.

A fold/collapse or excessive landmark error returns `status: unresolved`.
Publishing an unresolved preview is allowed **for inspection**, retaining its
diagnostics; `published: true` means review objects exist, not anatomical acceptance.
Even `status: success` explicitly records:

```json
{
  "anatomy": "not_evaluated",
  "collisions": "not_evaluated",
  "native_fibers": "not_created",
  "deformation": "sampled_only"
}
```

Finite samples cannot prove a globally invertible field or a collision-free mesh.
Landmark agreement does not establish full bone-surface correspondence. Sparse
constraints can bend or distort surrounding volumes, particularly beyond the
landmark coverage and at large pose changes. The method has no volume-preservation,
muscle architecture, skin-envelope or bone-collision constraints. Review these
properties separately before using a transferred volume as a native-fitting target.

Preview/publication rechecks scene revision, discovery draft revision, topology,
resolved target landmarks and evaluated source geometry. After changing the SCPs,
issue a **new preview request** with the current scene revision; still-valid indexed
bindings may be reused. This is not a live deformer attached to the original meshes.

The matching journal holds inputs and mapped geometry. Published review collections
embed field/definition/annotation/validation metadata; the geometry survives normal
save/reload without reading the journal. Further authoring operations still need
their matching journal. Mesh materials, UVs, shape keys, rigging and arbitrary
attributes are not transferred; these are geometric review copies.

Save exports with `StaticScene.save_debug_copy` to retain the normal visible native
curves and native SCP colors. Publication itself does not change existing visibility.

## Collision reports and local correction

The production operations `anatomy.transfer_collisions`,
`anatomy.transfer_correct_preview` and `anatomy.transfer_correct_publish` implement
the requested diagnostics and calculated local correction. See
[transfer_collision_correction.md](transfer_collision_correction.md) for parameters,
protected bands, contact bindings, guard bones, budgets, acceptance and replay.
They create a separately owned corrected reference; the original skeleton and
native muscles remain unchanged. After accepting it, regenerate affected downstream
stages. Collision readiness is distinct from anatomical acceptance.

## Validation

Disposable demo scripts are archived outside the addon. The maintained tests below
exercise the transfer API; native reconstruction has separate integration tests in
`test_authoring_native_base.py`, without imports from those demo scripts.

Targeted checks:

```powershell
python -m unittest discover -s tests/unit -p test_anatomy_transfer.py
& 'C:/Program Files/Blender Foundation/Blender 5.0/blender.exe' --background --factory-startup --python-exit-code 1 --python tests/blender_runner.py -- --pattern=test_authoring_transfer.py
```

The tests cover affine/nonlinear mapping, analytic Jacobians, reflection/collapse,
world transforms, indexed-region membership, stale inputs, separate/idempotent
publication, rollback on receipt failure, save/reload and reuse of bindings after
a topology-preserving SCP deformation. Anatomical suitability on the production
skeleton requires anatomical review. Native loft publication is supported by the
guided reconstruction flow; automatic inflation fitting is deferred.


### FCU collision experiment, September 21, 2026

Evidence: `E:/development/WIP_models/muscle_reconstruction_workflow/runs/2026-09-19-fcu-complete-8ecb3eff/review/collision_comparison_v001`. This is a transfer-reference experiment, not a production repair API or a rebuilt native FCU. The source reference already penetrates SCP13; the native output inherits an upper collision. A manually chosen smoothly faded translation clears SCP13 but separates the selected humeral contact by 0.38524 scene units and is rejected for attachment preservation.

A smooth RBF displacement fit with two explicit head-contact constraints, distal locking, bone-distance penalties and displacement-gradient regularization clears the tested upper collision after self-intersection union cleanup and a residual bone difference. Test the actual deformed triangles: evaluating a nonlinear field at undeformed triangle centroids is not equivalent. The fit reached its 150-evaluation budget, so this is not evidence of convergence or a universal optimum. Only two declared contact landmarks are constrained; full attachment bands remain unvalidated. Exact cleanup is part of the measured result, not an omitted implementation detail.

At 1e-4 scene-unit tolerance, final vertices/centroids and 60,000 additional area-weighted samples find no SCP13 penetration. Selected contact distances are below 1.2e-7 scene units; signed surface integral changes about -1.9%, which is not an occupied-volume certificate. Ulna penetration remains (about 0.107 vs 0.260 originally). Clearance does not certify simplified shape quality, complete attachment anatomy, or downstream native reconstruction. Preserve failed/manual variants, actual-mesh checks, cleanup and reopen evidence with the successful local correction.
