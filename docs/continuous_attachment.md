# Continuous transferred-muscle attachments

`anatomy.transfer_attachment_preview` and `anatomy.transfer_attachment_publish`
are protocol 0.4 operations for replacing a transferred reference's penetrating
end cap with a complete bone-conforming contact patch. They do not infer anatomy,
create native fibers, or change SCP geometry. The original transfer remains intact.

## Inputs

Supply the current scene revision, source object and its topology/geometry digests,
`obstacle_instance_ids`, and `attachment_instance_id` included among those obstacles.
`footprint` contains `{tri_vidx: [i,j,k], polygon: [[b0,b1,b2],...]}` records:
convex barycentric polygons on actual evaluated SCP triangles. Their union must
have one manifold boundary. Shared points are welded by indexed barycentric
identity, not rounded world coordinates. Duplicate triangles are removed.

`source_cut_values` is one scalar per source mesh vertex. Values no greater than
`settings.cut_value` are retained; the discarded end must contain the entire
attachment needing replacement. `overlap_cut_value` is smaller and defines an
interior overlap ring. Both cuts must produce one boundary. This field may use
source anatomical coordinates; it need not be a world-space plane.

Settings also require `departure_direction`, `escape_distance`, and two axes
each for `attachment_axes` and `retained_axes`. These establish corresponding
material sides of the two boundaries. They are essential for avoiding a deep-side
to superficial-side twist. `tolerance` specifies the bone-penetration review
threshold in scene units. `validation_samples` defaults to 4096.

## Construction and acceptance

C++ computes cyclic boundary correspondence and blended cubic envelope guides.
Native Blender convex-hull and Exact Boolean operations form a solid proximal
transition, unite it with the retained belly, and subtract selected bones.
This is a local shape approximation: the transition is convex before subtraction
and does not preserve arbitrary concavities or multiple end branches. It changes
topology. Use one appropriate head/end at a time and review its shape with neighbors.
There is no Python optimization loop or solver fallback.

The final candidate is checked for manifold closure, degeneracy, self-crossings,
bone penetration and reverse containment. Complete footprint triangle-area
coverage is measured, in addition to vertex/centroid distances. Publication
requires at least 99.99% area coverage and distance at most
`max(1e-4, tolerance*0.01)`. Bone checks use all vertices, all face centroids and
seeded area samples; they are not a mathematical clearance certificate.
Anatomical acceptance always remains a separate visual decision.

Self-crossing checks treat vertices within the Boolean cleanup precision
(`max(1e-7, bounding-box diagonal * 1e-8)`) as adjacent seam contacts.
This avoids intermittent false crossings from float32 Boolean roundoff without
welding the published mesh or relaxing bone-clearance and manifold checks.

Preview is read-only. Publish rejects stale source/support geometry or a failed
preview; repeated publication reuses the existing object and detects manual edits.
The saved manifest records the indexed footprint, construction and validation.
After SCP deformation rerun this operation: this reference mesh has no live
attachment-deformation hook. Rebind old annotations after remeshing and regenerate
base, fibers and inflation; old barycentric muscle bindings are invalid.

## Deltoid evidence, September 24

The clavicular-head candidate uses a qualified front/upper portion of the existing
`lateral_anterior_envelope_L` region. It replaces the complete proximal cap and
retains the distal belly. Earlier independent boundary interpolation created a
rolled cuff or self-crossing transition and was rejected. The solid transition
passed the real deltoid geometry checks; its shape remains subject to user review.
The other two deltoid heads were not reconstructed by this operation.
