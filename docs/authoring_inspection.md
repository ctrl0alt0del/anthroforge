# Contextual geometry inspection

`anatomy.views` now includes nearby evaluated geometry automatically when
`context_ids` is omitted. `neighbor_distance` is a world scene-unit distance;
its default is 15% of the subject's world bounding-box diagonal. Selection uses
conservative world AABB separation, including overlapping boxes. It can include
extra objects and does not claim that meshes intersect or share anatomical roles.
No neighbor is silently discarded by a top-N limit.

Pass either an SCP `instance_id` or a mesh `source_object` name as the subject.
Mesh inspection also discovers nearby native inflated muscles and other visible
meshes, using evaluated world bounds before capture. Hidden source-reference meshes
can be included explicitly through `context_objects`; native muscle neighbors are
included regardless of their viewport hiding. These mesh snapshots stay separate
from SCP discovery. Saved views recapture them and reject stale geometry edits.

Explicit `context_ids`, including `[]` for isolation, preserve caller control.
Set `automatic_context=true` to combine explicit and automatically selected
objects. `anatomy.view` supports the same options when changing a saved view.
Omitting all context options there preserves the saved context.

Both operations return `inspection` plus an `inspection_measurements` JSON asset:
snapshot/revision identity, neighborhood settings and inclusion reasons, owner IDs,
object names, persistent labels, world bounds/extents, surface centroid and area,
mesh counts, object axes, matrices, and geometry digests. Distances use scene units;
areas use squared scene units. Object axes do not assert anatomical directions.
Bounds are not oriented anatomical width/depth measurements or collision reports.

Images label visible objects with stable O-prefixed identifiers; each view's
`legend` and the measurement packet resolve them to names and full geometry IDs. HTML
galleries include the legend. Point highlights use distinct persistent P-prefixed
labels returned with each projection. Hidden points remain marked `occluded` in
the response and are not painted onto an unrelated visible surface. Display
`labels=false` disables object text for a custom view. Image labels do not change
native object colors, visibility, geometry, or saved Blender presentation.

These operations inspect existing geometry and discovery. They neither create
anatomical regions nor certify correspondence, transfer, or muscle reconstruction.
