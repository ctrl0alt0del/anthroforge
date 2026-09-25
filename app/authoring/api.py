"""Composition root. Call execute(request, root, scene, journal_directory).

Adjacent base repair: anatomy.partition_base_surfaces takes two directed path
grids, facing sides and a local chart, returns a common local border, preserved
endpoints, bounded outline error and actual native mesh checks. Optional existing
branch roots are retained. smooth_base_preview can run this explicitly through
overlap_repairs before atomic publication. See docs/base_surface_partition.md.

Simplified reconstruction (DSL 0.4): transfer -> combined base/native Free fibers
-> inflation. anatomy.smooth_base_preview jointly fits directed underside patches
and shared boundaries to a sparse native-compatible ruled spline base, qualifies
pins and checks the actual retained loft. smooth_base_publish atomically creates
shared Free fibers, coordinated surfaces and uninflated muscles. No routing solver
or Python optimizer runs. See docs/smooth_native_base.md for the input contract,
material correspondence, editing, diagnostics and replay semantics.

Guided reconstruction (DSL 0.4): transfer_sources/transfer_preview/transfer_publish
adapt reference volumes to indexed skeletal correspondences. repair_volume creates
an audited Boolean-union copy. base_candidates supplies whole-underside evidence;
define_base records explicit head-aware disk patches (optionally using a ready
prepare_base completion). plan_base_fibers fits sparse native routes with qualified,
zero-offset SCP pins, up to eight middle points, and independent loft checks.
publish_base_fibers atomically creates editable fibers and uninflated Fiber Surfaces.
Anatomical review and inflation fitting remain separate. See
docs/authoring_muscle_reconstruction.md for parameters, limits and replay semantics.

Transfer collision correction (DSL 0.4): anatomy.transfer_collisions reports
penetration against selected evaluated SCP instances. transfer_correct_preview
fits a local displacement field with fixed vertex bands, qualified contact
bindings, optional influence masks and obstacle guards, then validates cleanup.
transfer_correct_publish publishes only a technically ready preview as a separate
reference object. Originals, SCPs and native fibers remain unchanged. Rebuild
downstream stages from the new reference. See docs/transfer_collision_correction.md.

Continuous attachments: transfer_attachment_preview replaces an explicit source
end cap with a complete indexed bone footprint and native solid transition.
transfer_attachment_publish requires footprint, topology and collision checks.
This remeshes the reference; rebind annotations and rebuild downstream stages.
See docs/continuous_attachment.md for inputs and approximation limits.

warnings.list (all protocol versions) reads the transient file-wide warning store.
It bypasses scene capture, solver and request replay. See docs/warnings.md for
filters, bounded pagination, check tokens and mutation/poll/correction examples.
All final authoring responses carry live warning state outside saved receipts.

Native recompute (DSL 0.4): fibers.recompute takes scene_id and
expected_scene_revision from anatomy.discover. Optional fiber_ids selects native
Fibers on this root; omission selects all. cold_start defaults to true and clears
runtime solver caches so the current planner runs again. Native settings, anchors,
and region definitions remain as authored. Resnap changed geometry before starting.
The operation enqueues ordinary FINAL native refinement and returns recompute.token.
Poll fibers.recompute_status with scene_id and token until recompute.done is true.
Progress includes pending, committed, failures and per-fiber statuses. A successful
start response means accepted work; completed failures yield status='unresolved'.
Only validated native results commit and update dependent surfaces/muscles/mirrors.
Polling and identical start-request replay read live progress without another solve.
Tokens are scoped to the loaded scene/root session and expire on reload/unregister.
In background Blender scripts, advance the ordinary refinement queue with
drain_fiber_refinements(max_slices=...) between polls; GUI timers do this normally.

Read-only point picker (DSL 0.4): use op='anatomy.snap_points', with params
scene_id, instance_id, expected_scene_revision, and points=[[world_x, y, z], ...].
Get instance IDs and the current revision from anatomy.discover; initialize IDs
with anatomy.initialize when needed. Optional max_distance and collision_radius
use scene units; the radius defaults to the native Fiber policy (0.002).
Only hits with valid=True contain an attachment {parent_id, attach_param} for
native endpoints/mid_touches (zero normal_offset), and an anchor publication record.
The attachment uses the native SCP ID; the anchor retains the authoring instance ID.
Retain these payloads instead of computing barycentrics again from the guess.
For a DSL route override, keep the intended region and copy anchor.surface_binding
as surface_binding; no seed is needed. Retained bindings select the same face.
An unbound route seed uses normalized owner-frame coordinates and snaps to the
nearest point on that SCP, bounded by the sampling projection's search_distance.
Explicit curve/patch sampling retains its directional projection. All results
must lie inside the chosen region. Offset defaults to zero; only open-fiber middle
touches allow an explicit offset. Endpoints and loop anchors require zero.
Snapping keeps a qualified nearest hit unchanged. Otherwise it searches the same
SCP for an exposed, collision-clear attachment with a usable local exit. Each hit's
snapping record reports mode, reason, displacement, tests and elapsed_ms. Failed
searches or hits beyond max_distance remain unresolved. This is not a complete
route guarantee; anatomical region membership and routing still require review.

anatomy.discover includes saved profile counts and journal location. anatomy.catalog
searches the current root's saved regions by document_id, profile, scp_id,
instance_id, side, text, or sampling_available, with offset/limit pagination.
It reports binding format, sampling readiness, and anatomical review separately.
anatomy.upgrade_regions takes document_id, expected_draft_revision and
expected_scene_revision. It upgrades legacy surface patches while their original
topology is available, preserving current review evidence for the unchanged area.
New visual patches store face_vidx, tri_vidx and barycentric polygon weights.
They follow vertex deformation and polygon retessellation; changes to polygon
connectivity or vertex indexing require rebinding. Procedural selectors retain
their declared frame-based semantics. Region definitions stay outside native
fiber/surface/muscle evaluation.

Read-only layout planner (DSL 0.4): anatomy.plan_fibers takes document_id,
expected_draft_revision, expected_scene_revision, region (a saved region reference),
boundary_landmarks, and tolerance (positive positional error in world scene units).
The area must be one connected disk on one SCP. Select four distinct vertices on
its boundary and use anatomy.snap_points to obtain their anchor.surface_binding.
Pass these bindings as boundary_landmarks={start_left: binding, start_right:
binding, end_right: binding, end_left: binding}, in that cyclic order. Fibers run
from the start boundary to the end boundary. Clipped patch boundary vertices may
use barycentric bindings; landmarks need not be original mesh vertices.
The tolerance is explicit: no anatomical percentage is assumed.

Optional candidate_count (default 17, max 65) controls the search grid.
samples_per_fiber (default 65, max 129) controls dense guide/solver samples, NOT
hard touch points. max_fibers (default 65) and max_points_per_fiber (default 4,
max 128, including both endpoints) are hard result limits. The user-approved
default is at most TWO middle points per fiber. Every route starts with none.
collision_radius applies to both the native picker and solver (default 0.002).
Only selected fibers are solved. max_solver_calls (default 32, max 256) and
solver_budget_ms (default 2000, max 10000) bound native work; the routing stage
also has a 30-second total budget. A stalled correction or exceeded limit is
unresolved; the planner never silently increases the hard-point budget.
At most 2,048 selected points are bound per request. Oversized or unsuitable
patches, crossed landmarks, impossible budgets and blocked anchors are unresolved.

The response plan contains fiber_count, point_count, middle_point_count,
max_sampled_error, region_area, bands, and ordered fibers. Each fiber has start,
end, middle_points and points in route order. Every point has anchor and attachment
payloads; middle offsets default to zero. solved_path contains dense native output,
while points contains only hard controls. routing_corrections records each touch's
measured before/after route error. A touch is added only after a native solve
deviates from the intended path, and must improve the error. Surface curvature
alone never produces a touch. Successful plans report native_solver_validated=True.
Its route_anchors are proposals for existing route overrides; recipe station count,
owners and region sampling requirements still apply. This operation does not patch
the recipe. assets includes an SVG of solved paths with sparse control markers.
No native fiber, surface or muscle is created, and the saved region is unchanged.

Example params (left_start etc. are surface_binding values from valid picker hits):
    dict(scene_id=root.name, document_id=document_id,
         expected_scene_revision=scene_revision, expected_draft_revision=1,
         region='/skeleton_profiles/default/regions/area', tolerance=0.02,
         boundary_landmarks=dict(start_left=left_start, start_right=right_start,
                                 end_right=right_end, end_left=left_end))
Use these in a normal version='0.4.0', message_type='request' envelope with a fresh
request_id and op='anatomy.plan_fibers', then call execute as above.

Selection minimizes count over fixed surface guide candidates under sampled,
pairwise ruled-strip tests. Then native solves start with endpoints, and a few
corrections may steer a demonstrated detour. The sampled envelope is rechecked
using the solved paths. A failed envelope requires revising the layout/tolerance;
it does not trigger dense touches. Route error uses sampled bidirectional distance
to polylines, so changed along-path node spacing alone does not add controls.
This does not certify area coverage or the minimum count of a solved/inflated
muscle. Loft triangulation, inflation and anatomical validation remain separate.
Indexed regions and retained bindings follow topology-preserving deformation;
request a fresh plan on the new scene revision to reassess its error. Stale scene
or draft revisions are rejected even when the request ID has a cached response.
Response version fiber_layout.v2 supersedes the rejected dense-control v1 planner;
old v1 request-cache entries are recomputed, not replayed.
"""
from pathlib import Path
from .facade import AuthoringInterpreter
from ...core.authoring.storage import FileStore


def execute(request, root, scene, journal_directory=None):
    from ...adapters.authoring.native_scene import BlenderScene
    from ...adapters.authoring.solver import NativeFiberSolver
    from ...adapters.authoring.cached_solver import CachedFiberSolver
    from ...adapters.authoring.warnings import BlenderWarnings
    directory = journal_directory or default_directory(root)
    store = FileStore(directory)
    service = AuthoringInterpreter(BlenderScene(root, scene), CachedFiberSolver(NativeFiberSolver(), store),
                                   store, warnings=BlenderWarnings(root, scene))
    return service.execute(request)


def default_directory(root):
    import bpy
    recovered = Path(bpy.data.filepath).with_suffix('.authoring') if bpy.data.filepath else None
    if recovered and recovered.is_dir():
        return recovered
    return root.get('af_authoring_journal') or Path.home()/'.anthroforge'/'authoring'
