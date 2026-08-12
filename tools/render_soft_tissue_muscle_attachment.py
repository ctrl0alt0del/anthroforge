from pathlib import Path
import sys

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests" / "blender"
OUT = ROOT / "artifacts" / "soft_tissue_muscle_attachment"
for value in (str(ROOT), str(TESTS)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _helpers import find_flagged, reset_scene, select_only
from test_muscle_vcp_workflows import _muscle_setup, _surface_obj
from test_soft_tissue_workflows import _grid
from core.deps.dirty_hints import dirty_hints_for
from core.visualization.muscle_sync import register_muscle_sync
from core.visualization.soft_tissue_sync import register_soft_tissue_sync
from app.runtime_api import sync_scene


def build_case(feathered):
    reset_scene()
    root, first, second = _muscle_setup()
    select_only(first)
    second.select_set(True)
    bpy.ops.af.add_muscle_vcp()
    muscle = root.af_vcp_system.muscles[-1]
    _set_muscle_amount(root, muscle, 0.05)
    tissue = _create_tissue(root, muscle, feathered)
    return root, muscle, tissue


def _set_muscle_amount(root, muscle, amount):
    muscle.inflation_mode = "DISTRIBUTED"
    muscle.inflation_max_value = amount
    register_muscle_sync().sync_root_to_scene(root, bpy.context.scene, {muscle.id})


def _create_tissue(root, muscle, feathered):
    base = _grid("Feathered Base" if feathered else "Fixed Base", 11)
    base.location = (1.0, 0.5, 0.0)
    scene = bpy.context.scene
    scene.af_new_soft_tissue_preset = "POUCH"
    scene.af_new_soft_tissue_base_obj = base
    scene.af_new_soft_tissue_target_obj = _surface_obj(root, muscle, "INFL")
    bpy.ops.af.add_soft_tissue_vcp()
    tissue = root.af_vcp_system.soft_tissues[-1]
    _configure_attachment(tissue, feathered)
    register_soft_tissue_sync().sync_root_to_scene(root, scene, {tissue.id}, {tissue.id: "ALL"}, True)
    return tissue


def _configure_attachment(tissue, feathered):
    tissue.inflation_amount = 0.22
    tissue.sagginess = 0.25
    tissue.surface_slack = 0.1
    row = next(item for item in tissue.attachments if item.mask_attribute == "BOUNDARY")
    row.mode = "FIXED"
    row.strength = 0.85
    row.feather = 0.3 if feathered else 0.0


def render_case(label, feathered):
    root, muscle, tissue = build_case(feathered)
    _configure_scene(root, muscle, tissue)
    before = _world_points(_tissue_proxy(tissue.id))
    _render(label + "_before.png")
    _deform(root, muscle)
    after = _world_points(_tissue_proxy(tissue.id))
    _render(label + "_after.png")
    print(f"{label}: max displacement {_max_delta(before, after):.6f}")
    return root


def _deform(root, muscle):
    muscle.inflation_max_value = 0.2
    sync_scene(root, bpy.context.scene, dirty_hints_for("MUSCLE", {muscle.id}))


def _configure_scene(root, muscle, tissue):
    target = _surface_obj(root, muscle, "INFL")
    final = _tissue_proxy(tissue.id)
    for obj in bpy.context.scene.objects:
        obj.hide_render = obj not in {target, final}
    target.color = (0.95, 0.22, 0.06, 1.0)
    final.color = (0.08, 0.48, 1.0, 1.0)
    _configure_render()
    _create_camera()


def _configure_render():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "OBJECT"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = 900, 650
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"


def _create_camera():
    data = bpy.data.cameras.new("Visual Validation Camera")
    camera = bpy.data.objects.new("Visual Validation Camera", data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = (4.2, -5.2, 3.3)
    camera.rotation_euler = ((Vector((1.0, 0.5, 0.25)) - camera.location).to_track_quat("-Z", "Y").to_euler())
    data.lens = 58
    bpy.context.scene.camera = camera


def _render(filename):
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(OUT / filename)
    bpy.ops.render.render(write_still=True)


def _tissue_proxy(tissue_id):
    return find_flagged("af_soft_tissue_proxy", tissue_id, "af_soft_tissue_id")


def _world_points(obj):
    return tuple(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)


def _max_delta(first, second):
    return max((a - b).length for a, b in zip(first, second))


def main():
    render_case("fixed", False)
    root = render_case("feathered", True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "muscle_attachment_visual.blend"))
    print(f"Saved visual references for {root.name} to {OUT}")


main()
