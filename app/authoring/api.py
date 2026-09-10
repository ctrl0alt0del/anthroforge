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
For a DSL route override, keep the intended region and copy anchor.surface as seed
and anchor.surface_binding as surface_binding, with offset=0.
Blocked/distant hits are unresolved and require a new guess; anatomical region
membership and the route between anchors still require separate authoring review.
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
