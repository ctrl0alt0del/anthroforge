"""Composition root. Call execute(request, root, scene, journal_directory).

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
Blocked/distant hits are unresolved and require a new guess; anatomical region
membership and the route between anchors still require separate authoring review.

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
"""
from pathlib import Path
from .facade import AuthoringInterpreter
from ...core.authoring.storage import FileStore


def execute(request, root, scene, journal_directory=None):
    from ...adapters.authoring.native_scene import BlenderScene
    from ...adapters.authoring.solver import NativeFiberSolver
    from ...adapters.authoring.cached_solver import CachedFiberSolver
    directory = journal_directory or default_directory(root)
    store = FileStore(directory)
    return AuthoringInterpreter(BlenderScene(root, scene), CachedFiberSolver(NativeFiberSolver(), store), store).execute(request)


def default_directory(root):
    import bpy
    recovered = Path(bpy.data.filepath).with_suffix('.authoring') if bpy.data.filepath else None
    if recovered and recovered.is_dir():
        return recovered
    return root.get('af_authoring_journal') or Path.home()/'.anthroforge'/'authoring'
