"""Resolve the selected loft's inflation control without creating extra muscles."""
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from .branched_surface_capture import capture_assembly


def branch_surface(root, muscle):
    if getattr(muscle, 'surface_source_mode', '') != 'FIBER_SURFACE':
        return None
    surface = next((s for s in root.af_vcp_system.fiber_surfaces if s.id == muscle.fiber_surface_id), None)
    return surface if surface is not None and surface.construction_mode == 'BRANCHED_LOFT' else None


def selected_part(root, muscle):
    surface = branch_surface(root, muscle)
    index = -1 if surface is None else surface.active_branch_index
    connection = surface.branches[index] if surface is not None and 0 <= index < len(surface.branches) else None
    return (muscle, '', 0) if connection is None else (connection.settings, connection.id, index+1)


def control_part(root, muscle, obj):
    key = str(obj.get('af_muscle_branch_id', ''))
    surface = branch_surface(root, muscle)
    settings = muscle if not key else next((c.settings for c in surface.branches if c.id == key), None) if surface else None
    return settings.inflation_secondary if settings is not None and obj.get('af_inflation_side') == 'B' else settings


def snapped_control(root, scene, muscle, obj, target):
    surface = branch_surface(root, muscle)
    if surface is None:
        return None
    assembly = capture_assembly(root, scene, surface)
    key = str(obj.get('af_muscle_branch_id', ''))
    grid = assembly.main if not key else next(b.grid for b in assembly.branches if b.connection.id == key)
    rows, columns = grid.shape[:2]
    faces = [(r*columns+c, (r+1)*columns+c, (r+1)*columns+c+1, r*columns+c+1)
             for r in range(rows-1) for c in range(columns-1)]
    tree = BVHTree.FromPolygons([Vector(p) for p in grid.reshape((-1, 3))], faces)
    return tree.find_nearest(target)[0]
