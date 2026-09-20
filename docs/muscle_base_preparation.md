# Bounded completion of muscle bases

`anatomy.prepare_base` provides optional completion in the
[authoring flow](authoring_muscle_reconstruction.md), between **selecting the whole bone-facing
underside** and calculating fiber curves. The selected mesh is evidence to fit;
its holes, handles and disconnected scraps are not automatically the desired
muscle topology. Contact with SCPs does not crop the base.

## Anatomical approximation and smooth borders

User requirement, September 20, 2026: this stage must produce an approximate,
smooth anatomical underside suitable for sparse native reconstruction. Extracted
faces, projection contours and mathematical fits are evidence and construction
aids, not an outline that must be copied exactly. AI or human modeling decisions
define the intended shape. A small fitting residual or valid topology cannot
approve visibly kinked borders or a rippled interior.

Design each origin, insertion, side, cleft and seam from a small set of meaningful
anatomical landmarks. Use editable smooth curves to approximate noisy samples;
do not force the border through every source vertex or slice intersection. Keep
the broad belly width, complete attachment bands, head extents, taper and genuine
clefts. A deliberate cleft tip may change direction sharply; incidental notches,
zigzags and extraction artifacts must not propagate into native fibers.

Build or fair the interior to those designed borders and the broad underside
shape. Preserve suspended spans, thickness-side orientation and anatomical
concavities. Define a shared seam once and reuse its geometry and identity in both
patches; inspect tangent continuity where the anatomical surface is continuous.
Do not shrink away a belly, close a cleft, flatten the underside onto bone, or
use smooth shading to hide an unchanged jagged mesh.

Before handing off to fibers, review isolated borders, shaded and wire geometry,
and fixed-view cross-sections against the reference. Reject unexplained kinks,
ripples, folds and abrupt seam changes even when distance/topology checks pass.
Measurements constrain broad anatomical drift; they do not dictate a noisy
perimeter. Record boundary regularity separately from coverage and topology.

This is the construction and acceptance contract. The existing bounded
`prepare_base` implementation below resamples supplied arcs; it does not yet
guarantee these anatomical or smoothness criteria. A ready API result therefore
still needs this review and, where necessary, explicit boundary redesign.

## Input from AI or a human

Capture the repaired muscle mesh with `anatomy.transfer_sources`. The preparation
request includes its `source_object`, `topology_digest`, `geometry_digest`, current
`scene_id` and `expected_scene_revision`, plus:

- `heads`: explicit anatomical IDs and labels. Connected mesh components do not
  define these. A single geometric patch may serve multiple heads in a common belly.
- `arcs`: ordered mesh `vertex_ids`, an ID, sampling count (`segments`, default 12),
  and role: `origin`, `insertion`, `side`, `cleft`, `crop` or `seam`.
- `patches`: ID, participating `head_ids`, selected `source_triangles`, and an ordered
  closed `boundary` of `{arc, reverse}` references.
- Optional `settings`: `rings` (2–6), `iterations` (0–16), and positive
  `regularization` (up to 100). These control this experiment's surface fitting,
  not native fibers, their middle points, or muscle inflation.

Every ordinary boundary arc appears once. An explicit seam appears exactly twice,
in opposite directions. Both sides use **the same sampled coordinates and vertex
identities**. Cleft arcs cannot be used as seams. A patch must have a simple closed
perimeter and refer to known heads. All heads must participate in at least one patch.
The source indices must match the captured topology and geometry digests.

The declared graph can describe two heads merging into a common belly as three
patches, while still identifying **two anatomical heads**, not three muscles.
Origin/insertion and cleft labels are retained for subsequent curve layout; this
stage does not infer anatomical attachments from them or publish native branching.

## Reconstruction

1. Resample each supplied boundary arc once. Keep its endpoints and seam identities.
   The current implementation does not replace a jagged input with a designed
   smooth border; regular resampling alone is not sufficient acceptance.
2. Give each patch disk topology, which has one perimeter and no internal holes.
3. Initialize the interior by a harmonic extension of the fixed 3D boundary.
4. Fit interior vertices to area-weighted underside samples with a discrete fairing
   penalty. Regions lacking samples are completed through the smoothness term.
5. Assemble patches by declared seam identities. Preserve other boundaries,
   including clefts; do not infer a connection merely from spatial proximity.
6. Report topology, opposing orientations, degenerate triangles and nonadjacent
   Blender BVH overlap pairs separately. An unresolved result is still journaled for
   inspection, but is not ready for curve generation.

This is a bounded prototype using NumPy and existing Blender APIs. It changes no
solver, inflation model, SCP, skeleton or native muscle. It stores a content-addressed
preview asset and returns `base_surface`; no scene objects are published by this call.
Repeated requests recheck the source mesh, including geometry changes outside the
native skeleton revision.

## Verified and unresolved

The supplied two-head synthetic fixture has three missing interior areas. It becomes
one connected base with one outer boundary, no internal holes, exact shared seams,
and an open cleft. It has no detected nonadjacent BVH overlaps. Unit tests also reject
unknown heads, improper seam use and inconsistent seam orientation. Blender tests
verify scene immutability, journal output and stale-source rejection.

The real pectoral experiment remains **unresolved**: rebuilding disks removes its
topological holes, but fitting against the jagged/folded extracted perimeters creates
spatial folds. A low surface-distance residual does not override those failures.
The patch/component colors in that diagnostic are not head classification. Atlas
part labels are inherited provenance; meaningful chart boundaries and seams still
require explicit anatomical guidance. Automatic boundary/head discovery, a robust
general fit with no retries, full anatomical acceptance and automatic native curve
compilation of arbitrary head graphs are not implemented or claimed. The BVH check excludes adjacent/shared-vertex pairs
and is not an exhaustive intersection certificate.

Next curve layout must use the prepared base and the supplied attachment/merge graph,
preserve shared boundaries, and separately establish native snapping and route
feasibility. A hole-free surface alone is insufficient.

Implementation references: [libigl harmonic parameterization](https://libigl.github.io/tutorial/#harmonic-parametrization)
and [CGAL hole-filling and fairing](https://doc.cgal.org/latest/Polygon_mesh_processing/index.html#title29).

## Native reconstruction pilot

The archived pectoral feasibility experiment constructed native
Fiber Surfaces using explicit indexed attachment regions and the repaired underside
as a fitting target. This is a guided native feasibility experiment, not publication
of the rejected folded disk meshes or a new public authoring operation. The final
layout uses four major fibers, three minor fibers and one routing midpoint total,
with no inflation. Every authored pin is qualified on its existing SCP at zero
offset, including the midpoint; free curve nodes and loft interiors are not pins.

Native route clearance, hole-free topology and detected self-intersections are
checked separately from reference fit. The retained native surfaces pass these
mechanical checks, but their contours remain approximate, especially the minor's
unregistered coracoid transition. The native journal and saved scene must be used
together; completion remains a separate bounded method. Ready previews now expose
an ID consumable by `anatomy.define_base`; unresolved spatially folded previews
remain blocked. Disposable lab scripts were archived outside the addon; production
operations do not import them.
