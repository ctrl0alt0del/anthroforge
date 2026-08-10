from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector

from anthroforge.core.utils import get_af_root
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.soft_tissue_sync import register_soft_tissue_sync
from anthroforge.core.visualization.soft_tissue_build import _fixed_indices, build_rest_shape
from anthroforge.core.visualization.soft_tissue_source import sample_base
from anthroforge.app.use_cases.soft_tissue_create import _ensure_surface_field
from anthroforge.app.use_cases.soft_tissue_create import _assign_preset
from anthroforge.core.vcp.soft_tissue_presets import preset_values
from anthroforge.core.vcp.runtime_state import soft_tissue_diagnostic


def main():
    output, subdivide = _arguments()
    root = get_af_root(bpy.context.scene)
    tissue = _prepare_tissue(root, subdivide)
    proxy = _tagged("af_soft_tissue_proxy", tissue.id)
    if "--amount-comparison" in sys.argv:
        _run_amount_comparison(root, tissue, proxy, output)
        return
    _configure_scene(root.af_scp_system.scps[0].geometry_object_ref, proxy)
    before, after = _render_comparison(root, tissue, proxy, output, _prefix(subdivide))
    _print_stats(tissue)
    print("AF_SAG_VIS", {"max_delta": _max_delta(before, after),
          "centroid_delta": _centroid_delta(before, after), "output": str(output)})


def _prepare_tissue(root, subdivide):
    tissue = root.af_vcp_system.soft_tissues[0]
    if subdivide:
        _subdivide_base(root, tissue)
    if "--pouch-defaults" in sys.argv:
        _apply_defaults(root, tissue, "POUCH")
    if "--layer-defaults" in sys.argv:
        _apply_defaults(root, tissue, "LAYER")
    if "--reference-constraints" in sys.argv:
        _apply_reference_constraints(root, tissue)
    _apply_cli_overrides(tissue)
    return tissue


def _apply_cli_overrides(tissue):
    _apply_numeric_override(tissue, "--shape-retention", "shape_retention")
    _apply_numeric_override(tissue, "--volume-retention", "volume_retention")
    _apply_numeric_override(tissue, "--tolerance", "tolerance")
    _apply_numeric_override(tissue, "--amount", "inflation_amount")
    _apply_numeric_override(tissue, "--field-power", "field_power")
    _apply_numeric_override(tissue, "--sag-limit", "sag_limit")


def _run_amount_comparison(root, tissue, proxy, output):
    _set_amount_state(root, tissue, 4.0)
    _configure_scene(root.af_scp_system.scps[0].geometry_object_ref, proxy)
    metrics = [_render_amount(root, tissue, proxy, output, amount) for amount in (2.0, 4.0)]
    _print_stats(tissue)
    print("AF_AMOUNT_COMPARISON", metrics)


def _set_tissue_value(root, tissue, attribute, value):
    with suppress_vcp_prop_updates():
        setattr(tissue, attribute, float(value))
    register_soft_tissue_sync().sync_root_to_scene(root, bpy.context.scene, {tissue.id}, force=True)


def _render_amount(root, tissue, proxy, output, amount):
    _set_amount_state(root, tissue, amount)
    rest = _tagged("af_soft_tissue_rest_proxy", tissue.id)
    _show_rest_overlay(rest)
    rest_points, final_points = _world_vertices(rest), _world_vertices(proxy)
    tip = _tip_index(rest_points)
    bpy.context.scene.render.filepath = str(output / f"amount_{int(amount)}.png")
    bpy.ops.render.render(write_still=True)
    metrics = _tip_metrics(tissue, amount, tip, rest_points, final_points)
    metrics.update(_mask_metrics(tissue, rest_points, final_points))
    return metrics


def _show_rest_overlay(rest):
    if "--show-rest-overlay" not in sys.argv:
        return
    rest.hide_render = False
    rest.display_type = "WIRE"
    _style(rest, (0.95, 0.95, 0.95, 1.0), True)


def _set_amount_state(root, tissue, amount):
    with suppress_vcp_prop_updates():
        tissue.inflation_amount = float(amount)
        if "--scaled-gravity" in sys.argv:
            tissue.gravity = Vector(tissue.gravity).normalized() * (float(amount) / 0.62)
    register_soft_tissue_sync().sync_root_to_scene(root, bpy.context.scene, {tissue.id}, force=True)


def _world_vertices(obj):
    return tuple(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)


def _tip_index(rest_points):
    count = len(rest_points) // 2
    return max(range(count), key=lambda index: (rest_points[index] - rest_points[count + index]).length)


def _tip_metrics(tissue, amount, tip, rest_points, final_points):
    gravity = Vector(tissue.gravity).normalized()
    delta = final_points[tip] - rest_points[tip]
    count = len(rest_points) // 2
    outer = min(range(count), key=lambda index: final_points[index].x)
    return {"amount": amount, "tip_index": tip, "rest_tip": tuple(rest_points[tip]),
            "final_tip": tuple(final_points[tip]), "delta": tuple(delta),
            "gravity_drop": delta.dot(gravity), "total_displacement": delta.length,
            "outer_index": outer, "outer_point": tuple(final_points[outer])}


def _mask_metrics(tissue, rest_points, final_points):
    sample = sample_base(tissue.base_object_ref, tissue, scene=bpy.context.scene)
    shape = build_rest_shape(tissue, sample)
    fixed, count = set(_fixed_indices(tissue, shape)), len(shape.groups.get("BACKING", ()))
    gravity = Vector(tissue.gravity).normalized()
    drops = tuple((final_points[i] - rest_points[i]).dot(gravity) for i in range(len(rest_points)))
    return {"attachments": [(row.mode, row.mask_attribute, row.strength) for row in tissue.attachments],
            "front": _drop_summary(drops, range(count)), "backing": _drop_summary(drops, range(count, count * 2)),
            "fixed": _drop_summary(drops, fixed), "free": _drop_summary(drops, set(range(len(drops))) - fixed)}


def _drop_summary(drops, indices):
    values = [drops[index] for index in indices]
    return {"count": len(values), "min": min(values), "mean": sum(values) / len(values), "max": max(values)}


def _apply_numeric_override(tissue, option, attribute):
    if option not in sys.argv:
        return
    with suppress_vcp_prop_updates():
        setattr(tissue, attribute, float(sys.argv[sys.argv.index(option) + 1]))


def _render_comparison(root, tissue, proxy, output, prefix):
    before = _render_state(root, tissue, proxy, output, prefix, 0.0)
    after = _render_state(root, tissue, proxy, output, prefix, 1.0)
    return before, after


def _arguments():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ()
    output = Path(args[0] if args else "artifacts/debug_soft_tissue_sag").resolve()
    output.mkdir(parents=True, exist_ok=True)
    return output, "--subdivide" in args


def _subdivide_base(root, tissue):
    obj, mesh = tissue.base_object_ref, tissue.base_object_ref.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.subdivide_edges(bm, edges=tuple(bm.edges), cuts=14, use_grid_fill=True)
    bm.to_mesh(mesh)
    bm.free()
    group = obj.vertex_groups.get(tissue.field_attribute)
    None if group is None else obj.vertex_groups.remove(group)
    _ensure_surface_field(obj, tissue.field_attribute)
    register_soft_tissue_sync().sync_root_to_scene(root, bpy.context.scene, {tissue.id}, {tissue.id}, True)


def _apply_defaults(root, tissue, preset):
    with suppress_vcp_prop_updates():
        _assign_preset(tissue, preset, preset_values(preset))
    register_soft_tissue_sync().sync_root_to_scene(root, bpy.context.scene, {tissue.id}, {tissue.id}, True)


def _apply_reference_constraints(root, tissue):
    with suppress_vcp_prop_updates():
        for row in tissue.attachments:
            if row.mask_attribute == "BACKING":
                row.mode, row.strength = "FIXED", 1.0
            elif row.mask_attribute == "SUSPENSION":
                row.mode, row.strength = "SOFT", 0.015
    register_soft_tissue_sync().sync_root_to_scene(root, bpy.context.scene, {tissue.id}, {tissue.id}, True)


def _prefix(subdivide):
    if "--reference-constraints" in sys.argv:
        return "reference_constraints"
    if "--layer-defaults" in sys.argv:
        return "layer_defaults"
    base = "pouch_defaults" if "--pouch-defaults" in sys.argv else ("subdivided" if subdivide else "broken")
    return base + _override_suffix()


def _override_suffix():
    values = []
    options = (("--shape-retention", "shape"), ("--volume-retention", "volume"),
               ("--tolerance", "tolerance"), ("--amount", "amount"),
               ("--field-power", "field"), ("--sag-limit", "limit"))
    for option, label in options:
        if option in sys.argv:
            values.append(f"_{label}_{float(sys.argv[sys.argv.index(option) + 1]):.2f}")
    return "".join(values)


def _tagged(key, tissue_id):
    return next(obj for obj in bpy.context.scene.objects
                if obj.get(key) and obj.get("af_soft_tissue_id") == tissue_id)


def _configure_scene(host, proxy):
    scene = bpy.context.scene
    bpy.context.view_layer.update()
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.display.shading.light, scene.display.shading.color_type = "STUDIO", "OBJECT"
    _isolate(host, proxy)
    _style(host, (0.16, 0.22, 0.32, 1.0), False)
    _style(proxy, (0.95, 0.25, 0.08, 1.0), True)
    _camera_for((host, proxy))


def _isolate(host, proxy):
    for obj in bpy.context.scene.objects:
        obj.hide_render = obj not in {host, proxy}


def _style(obj, color, wire):
    obj.color = color
    obj.show_wire = bool(wire)
    obj.show_all_edges = bool(wire)


def _camera_for(objects):
    scene = bpy.context.scene
    low, high = _bounds(objects)
    center, span = (low + high) * 0.5, high - low
    camera = bpy.data.objects.new("AF_Sag_Debug_Camera", bpy.data.cameras.new("AF_Sag_Debug_Camera"))
    scene.collection.objects.link(camera)
    camera.data.type, camera.data.ortho_scale = "ORTHO", max(span.x, span.z) * 1.3
    camera.location = center + Vector((0.0, -max(5.0, span.y * 3.0), span.z * 0.08))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera


def _bounds(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    return Vector(tuple(min(point[i] for point in points) for i in range(3))), Vector(tuple(max(point[i] for point in points) for i in range(3)))


def _render_state(root, tissue, proxy, output, prefix, sagginess):
    with suppress_vcp_prop_updates():
        tissue.sagginess = float(sagginess)
    register_soft_tissue_sync().sync_root_to_scene(root, bpy.context.scene, {tissue.id}, force=True)
    points = tuple(tuple(proxy.matrix_world @ vertex.co) for vertex in proxy.data.vertices)
    rest = _tagged("af_soft_tissue_rest_proxy", tissue.id)
    rest_points = tuple(tuple(rest.matrix_world @ vertex.co) for vertex in rest.data.vertices)
    print("AF_SAG_STATE", {"sagginess": sagginess, "diagnostic": soft_tissue_diagnostic(tissue),
          "final_rest_delta": _max_delta(points, rest_points)})
    bpy.context.scene.render.filepath = str(output / f"{prefix}_sag_{int(sagginess)}.png")
    bpy.ops.render.render(write_still=True)
    return points


def _max_delta(first, second):
    return max((Vector(a) - Vector(b)).length for a, b in zip(first, second))


def _centroid_delta(first, second):
    before = sum((Vector(value) for value in first), Vector()) / len(first)
    after = sum((Vector(value) for value in second), Vector()) / len(second)
    return tuple(after - before)


def _print_stats(tissue):
    sample = sample_base(tissue.base_object_ref, tissue, scene=bpy.context.scene)
    rest = build_rest_shape(tissue, sample)
    count = len(sample.points)
    thickness = tuple((Vector(rest.vertices[i]) - Vector(rest.vertices[count + i])).length for i in range(count))
    print("AF_SAG_STATS", {"base_vertices": count, "boundary_edges": len(sample.boundary_edges),
          "weight_range": (min(sample.weights), max(sample.weights)), "thickness_range": (min(thickness), max(thickness)),
          "fixed": len(_fixed_indices(tissue, rest)), "relaxation": tissue.relaxation_mode,
          "preset": tissue.preset, "field_power": tissue.field_power,
          "shape_retention": tissue.shape_retention, "volume_retention": tissue.volume_retention,
          "sagginess": tissue.sagginess, "sag_limit": tissue.sag_limit, "tolerance": tissue.tolerance,
          "gravity": tuple(tissue.gravity)})


if __name__ == "__main__":
    main()
