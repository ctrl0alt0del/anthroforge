"""Native regression scenes using the established prototype input geometry."""
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "tests/blender"), str(ROOT / "tools")]
import anthroforge
from _helpers import ensure_addon_registered, reset_scene, root, scp_with_object
from test_soft_tissue_workflows import _quad, _curve, _create_rim, _create_point_tissue
from test_soft_tissue_muscle_attachment import _muscle_tissue
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.vcp.runtime_state import soft_tissue_solve_report, soft_tissue_diagnostic
from anthroforge.core.visualization.soft_tissue_sync import register_soft_tissue_sync
import prototype_soft_tissue_breast as breast
import prototype_soft_tissue_abdominal_fat as abdomen

OUTPUT = ROOT / "artifacts/soft_tissue_native_regression/v1"


def add_patch(name, patch, host, preset, module):
    base = module.make_mesh_object(name, patch.points, patch.faces, bpy.context.scene.collection)
    group = base.vertex_groups.new(name="AF_ST_INFLATION")
    for index, weight in enumerate(patch.weights):
        group.add([index], float(weight), "REPLACE")
    scene = bpy.context.scene
    scene.af_new_soft_tissue_preset = preset
    scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = base, host
    assert bpy.ops.af.add_soft_tissue_vcp() == {"FINISHED"}


def breasts():
    _root, _scp, host = breast.create_host(bpy.context.scene.collection)
    for side in ("LEFT", "RIGHT"):
        add_patch(f"{side} breast base", breast.root_patch(side, 7, 36), host, "POUCH", breast)


def abdominal():
    _root, _scp, host = abdomen.create_host(bpy.context.scene.collection)
    add_patch("Abdominal base", abdomen.patch_geometry(8, 48), host, "LAYER", abdomen)


def lips():
    host = _quad("Face support", 0)
    scp_with_object(root(), "Face support", host)
    for name, y in (("Upper lip", .12), ("Lower lip", -.12)):
        _create_rim(_curve(name, y), host)


def proxies():
    return [obj for obj in bpy.context.scene.objects if obj.get("af_soft_tissue_proxy")]


def snapshot():
    return {str(obj.get("af_soft_tissue_id")): [tuple(obj.matrix_world @ v.co) for v in obj.data.vertices] for obj in proxies()}


def camera(case):
    scene = bpy.context.scene
    vertices = [Vector(p) for values in snapshot().values() for p in values]
    center = sum(vertices, Vector()) / len(vertices)
    span = max((point-center).length for point in vertices)
    data = bpy.data.cameras.new("Regression camera")
    obj = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(obj)
    direction = Vector((1.4, -4, 1.4) if case == "breast_pouch" else (1.4, -3, 4))
    obj.location = center + direction.normalized()*span*4
    obj.rotation_euler = (center-obj.location).to_track_quat("-Z", "Y").to_euler()
    data.type, data.ortho_scale, scene.camera = "ORTHO", span*2.8, obj
    viewport(scene, obj, span, center)


def viewport(scene, camera_obj, span, center):
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light, scene.display.shading.color_type = "STUDIO", "OBJECT"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1000, 800, 100
    scene.world = scene.world or bpy.data.worlds.new("Regression world")
    scene.world.color = (.06, .06, .06)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                view = area.spaces.active.region_3d
                view.view_rotation, view.view_distance = camera_obj.rotation_euler.to_quaternion(), span*4
                view.view_location = center
    for obj in proxies():
        obj.color = (.65, .24, .19, 1)


def verify_reopened(before):
    after = snapshot()
    error = max((Vector(a)-Vector(b)).length for key in before for a, b in zip(before[key], after[key]))
    assert set(before) == set(after) and all(len(before[k]) == len(after[k]) for k in before)
    assert error <= 2.e-6, error
    fibers = [obj for obj in bpy.context.scene.objects if obj.get("af_fiber_proxy") or obj.get("af_fiber_mirror_proxy")]
    assert all(not o.hide_viewport and not o.hide_get() and not o.hide_render and o.display_type != "WIRE" for o in fibers)
    views = [s for screen in bpy.data.screens for area in screen.areas for s in area.spaces if s.type == "VIEW_3D"]
    assert all(s.shading.type == "SOLID" and s.shading.color_type == "OBJECT" for s in views)
    return dict(max_reopen_error=error, visible_fiber_count=len(fibers), tissue_count=len(after))


def build(case, builder):
    reset_scene()
    builder()
    camera(case)
    before = snapshot()
    path = OUTPUT / f"{case}.blend"
    StaticScene(root(), bpy.context.scene).save_debug_copy(path)
    bpy.ops.wm.open_mainfile(filepath=str(path))
    result = verify_reopened(before)
    result["solves"] = {t.id: soft_tissue_solve_report(t) for t in root().af_vcp_system.soft_tissues}
    result["recompute_ms"] = {t.id: soft_tissue_diagnostic(t)[0] for t in root().af_vcp_system.soft_tissues}
    assert all(t.evaluation_revision == 1 for t in root().af_vcp_system.soft_tissues)
    bpy.context.scene.render.filepath = str(OUTPUT / f"{case}.png")
    bpy.ops.render.render(write_still=True)
    return result


if __name__ == "__main__":
    ensure_addon_registered()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = {"lips": lips, "abdomen_layer": abdominal, "breast_pouch": breasts,
             "closed_bulk": _create_point_tissue, "muscle_attachment": lambda: _muscle_tissue("INFL")}
    results = {name: build(name, builder) for name, builder in cases.items()}
    (OUTPUT / "fixtures.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
