# Transferred-reference collision correction

Production authoring protocol 0.4 exposes three operations:

| Operation | Result |
| --- | --- |
| `anatomy.transfer_collisions` | Read-only source/SCP quality and localized collision reports. |
| `anatomy.transfer_correct_preview` | Journaled candidate geometry, fitting report, before/after collision and protection checks. Does not publish scene objects. |
| `anatomy.transfer_correct_publish` | Separate reference mesh, only when the candidate passes technical checks. Source objects, SCPs, discovery and native fibers are unchanged. |

These operations implement a bounded local repair, not anatomical registration,
global muscle packing or automatic anatomical acceptance. They require Blender and
its bundled NumPy only. No SciPy/libigl installation or external worker is required.

## Inputs and intended use

Use `anatomy.transfer_sources` to capture the evaluated source mesh and its
`topology_digest` and `geometry_digest`. Get SCP **instance IDs**, including the
correct side, from `anatomy.discover`. All positions, radii, distances and areas use
world scene units; the API does not infer millimetres.

Every operation takes the normal `scene_id` and `expected_scene_revision` guards.
Both diagnostic and preview requests additionally require:

```python
params = dict(
    scene_id=scene_id, expected_scene_revision=scene_revision,
    source_object=source_name, topology_digest=topology_digest,
    geometry_digest=geometry_digest,
    obstacle_instance_ids=[humerus_instance_id],
    settings=dict(tolerance=0.0001),
)
```

For a correction, add a scale-appropriate influence radius and maximum movement:

```python
params['settings'].update(influence_radius=0.55, max_displacement=0.6,
                          max_iterations=100, max_seconds=180)
params['protected_bands'] = [dict(id='distal_fixed', vertex_indices=fixed_vertices)]
params['guard_instance_ids'] = [radius_instance_id, ulna_instance_id]
params['contacts'] = [dict(
    id='humeral_attachment', source_binding=source_binding,
    obstacle_instance_id=humerus_instance_id, target_binding=target_binding,
)]
```

The numbers above are the FCU case scale, **not universal defaults**.

- `protected_bands` contain evaluated **source-muscle vertex indices**. All
  selected vertices receive exactly zero displacement in the field. The influence
  fades smoothly near them. Post-cleanup validation tests those vertices and the
  centroids of triangles wholly inside each protected selection against the output.
  Bands are explicit modeling inputs, not automatically inferred anatomy.
- `contacts` constrain actual barycentric source-triangle points to barycentric
  points on selected target/guard SCP geometry. Both bindings use `tri_vidx` and
  `tri_weights`; retain qualified target bindings from `anatomy.snap_points`.
  The constraints use interpolation of **deformed mesh vertices**, not evaluation
  of the nonlinear field at a triangle's original centroid. A contact can relocate
  onto bone; a fixed band cannot. Conflicting constraints are rejected. Supply a
  band or enough contact constraints for the intended attachment region: one
  landmark does not protect an entire anatomical attachment.
- `obstacle_instance_ids` must be cleared within tolerance. Optional, disjoint
  `guard_instance_ids` allow pre-existing penetration but may not increase its
  measured maximum depth, centroid-estimated penetrating area or reverse-containment depth. During fitting,
  corresponding source samples also receive a non-worsening distance penalty.
  This is a sampled guard, not a proof that no small new intersection exists.
- `settings.influences` optionally contains `{center: [x,y,z], radius: r}` spheres.
  Their smoothly blended envelope is zero outside their union. Without them,
  Gaussian influence decays with distance; it is not a hard spatial cutoff.

The caller selects all relevant neighboring bones. Unlisted geometry is not checked.
The API neither invents attachment anatomy nor silently resnaps invalid contacts.

## Calculation and cleanup

The fit selects deterministic farthest-point centers around detected penetration
and declared contacts. A Gaussian displacement basis is masked by fixed bands and
optional influence spheres. Linear equality constraints are eliminated with an SVD
null space. Adaptive damped least squares balances forward and reverse containment, signed
volume, deformation magnitude and differences between neighboring vertex displacements; bounded line search limits
movement. Every evaluation samples the actual displaced vertices and face centroids.

Default `cleanup='exact'` applies an Exact self-union and target-bone difference on
disposable meshes. Guards are not Boolean-subtracted. Numerical welding uses one
percent of the requested tolerance. Touching sheets are separated by subdividing
shared edges and splitting vertex fans without changing the represented surface.
`cleanup='none'` validates the deformed mesh directly. An already-clear, unconstrained
source takes the no-op path. Cleanup can change topology: recapture the published
reference before selecting its underside or defining new indexed muscle selections.

Closed but overlapping obstacles are evaluated through a detached Exact union;
original SCPs/modifiers stay untouched. Open or unresolved obstacles block the
calculation. Quality before and after this normalization is reported.

Detached Boolean calculations are centered and quantized at the cleanup epsilon
(one percent of the requested collision tolerance) before Blender mesh creation.
This reduces float32 sensitivity to world translation. Obstacle normalization
permits one additional union only when the first result fails quality; every
result is rechecked. Further unchecked unions can worsen topology. The FCU
humerus and its translated fixture are covered by the Blender regression tests.

## Settings and budgets

| Setting | Default / bound |
| --- | --- |
| `tolerance` | Required, positive distance. |
| `influence_radius`, `max_displacement` | Required for correction, positive distances. |
| `protection_blend` | 0.3 × influence radius. |
| `centers` | 16; range 4–48. |
| `smoothness` | 3; range 0–100. |
| `fit_clearance` | 0; optional nonnegative fitting target, not an acceptance guarantee or mandatory gap at contacts. |
| `max_iterations` | 60; range 1–150. |
| `max_seconds` | 60; range 1–180. Soft fitting budget checked between iterations; reporting/cleanup are additional. |
| `max_volume_change` | 0.15; relative change in signed surface integral, not occupied union volume. |
| `validation_samples` | 4,096; range 64–60,000, in addition to all vertices and face centroids. |
| `cleanup` | `exact` or `none`. |

Each input mesh is limited to 30,000 vertices / 60,000 triangles. At most 16 target
and 16 guard instances, 128 contacts, 64 bands and 16 influence spheres are allowed.
A separate 20-million-Jacobian-element budget prevents an oversized solve. Oversized,
inconsistent or invalid inputs return diagnostics rather than partial publication.

## Reports, acceptance and persistence

`response.transfer` contains the summary; `response.assets` links the full immutable
candidate record with world vertices, triangles, request definition, field,
pre-cleanup quality, before/after reports and fitting stop reason. Fit stationarity
or a budget stop is not a convergence certificate. Final technical acceptance is
independent of that stop reason.

Collision reports include penetrating vertex/triangle indices, bounds, a mean exit
vector, maximum sampled depth, centroid-estimated area, sample counts and triangle
overlap pairs, and a reverse-containment check for bones enclosed by the muscle.
Overlap pairs include valid surface contact. Inside/outside uses
three ray directions with winding-number fallback for disagreement. Geometry
quality uses double-precision narrow-phase checks; intersections whose measured
extent is below tolerance remain explicitly counted as
`subtolerance_intersection_pairs`. No report claims an exact clearance certificate.

Publication is blocked by unresolved collisions, unacceptable topology, protection
loss, excessive displacement or volume change. Protection checks have a
double-precision fallback for thin triangles that Blender BVH can miss. Reports
distinguish `anatomical_review='required'` from numerical readiness.

Publish with `preview_id`, current scene ID and revision. Live source/SCP digests
are rechecked even on replay. An identical request reuses its receipt; a changed
payload cannot reuse its request ID. Publication creates a separately owned review
collection, verifies any existing output before reuse and rolls back new objects if
the operation receipt cannot be written. The matching authoring journal and manifest
persist source provenance, calculation settings and validation. Save deliverables
with `StaticScene.save_debug_copy`.

`downstream_rebuild_required=['base', 'fibers', 'inflation']` explicitly marks what
must be regenerated from the corrected reference. Existing native geometry remains
unchanged; publication is not a claim to have repaired it.

## Validation

Maintained tests: `tests/unit/test_correction_field.py` and
`tests/blender/test_authoring_collision_correction.py`, plus the existing transfer
integration suite. They cover fixed bands, barycentric contacts, incompatible
constraints, topology separation, collision detection, source preservation, stale
requests, replay, cleanup ownership, publication rollback, thin-triangle distance
checks and save/reload.

The production FCU run is recorded under
`E:/development/WIP_models/muscle_reconstruction_workflow/runs/2026-09-19-fcu-complete-8ecb3eff/review/collision_api_v001`.
It tests a humerus correction with radius/ulna guards, two contact constraints and a
fixed distal region. This is case evidence, not a universal anatomical guarantee.
