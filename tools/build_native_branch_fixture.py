"""Build a standalone native cube example; opening it needs only the regular addon."""
from pathlib import Path
import sys
import bpy

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON.parent))
sys.path.insert(0, str(ADDON/'tests/blender'))
sys.path.insert(0, str(ADDON))
import anthroforge
from _branch_fixture import create_fixture
from anthroforge.core.visualization.fiber_surface_sync import register_fiber_surface_sync
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.adapters.authoring.scene import StaticScene


def configure_view():
    from mathutils import Quaternion
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                view = area.spaces.active
                view.shading.color_type = 'OBJECT'
                view.region_3d.view_location = (0, 0, 0)
                view.region_3d.view_distance = 11
                view.region_3d.view_rotation = Quaternion((.89, .35, .14, .25)).normalized()


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    anthroforge.register()
    root, muscle, connection, fibers = create_fixture()
    register_fiber_surface_sync().sync_root_to_scene(root, bpy.context.scene)
    register_muscle_sync().sync_root_to_scene(root, bpy.context.scene)
    root.af_vcp_system.active_vcp_type, root.af_vcp_system.active_vcp_id = 'MUSCLE', muscle.id
    configure_view()
    destination = Path('E:/development/WIP_models/native_branching_20260917.blend')
    StaticScene(root, bpy.context.scene).save_debug_copy(destination)
    print('NATIVE_BRANCH_FIXTURE', destination, 'muscle', muscle.id, 'connection', connection.id, flush=True)


if __name__ == '__main__':
    main()
