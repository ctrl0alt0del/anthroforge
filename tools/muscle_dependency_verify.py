"""Graph, cold/warm decode and reopened geometry/debug verification on a copy."""
import json
import sys
import time
from pathlib import Path
import bpy
sys.path.insert(0, str(Path(__file__).parent))
import muscle_dependency_probe as probe


def canonical(data):
    graph, entities, adjacency, indices, sizes = data
    components = {frozenset(k for k, value in indices.items() if value == index) for index in sizes}
    return graph.ports, graph.edges, entities, dict(adjacency), components


def capture(owner):
    from anthroforge.core.deps import runtime_context_build as build
    probe.COUNTERS.clear(); started = time.perf_counter()
    data = build._cached_graph_data(owner)
    return data, dict(milliseconds=(time.perf_counter()-started)*1000, counters=dict(probe.COUNTERS))


def graph_checks():
    from anthroforge.core.deps import runtime_context_build as build
    owner = probe.root(); build.clear_runtime_context_cache(); probe.codec_instrumentation()
    cold, cold_record = capture(owner); warm, warm_record = capture(owner)
    uncached = build._graph_data(owner)
    assert cold is warm and canonical(warm) == canonical(uncached)
    assert all(warm[0].downstream_entities({key}) == uncached[0].downstream_entities({key}) for key in warm[2])
    return dict(cold=cold_record, warm=warm_record, ports=len(warm[0].ports), edges=len(warm[0].edges),
                entities={key: len(values) for key, values in warm[1].items()}, parity=True)


def debug_checks():
    owner = probe.root(); objects = tuple(bpy.context.scene.objects)
    fibers = [obj for obj in objects if obj.get('af_root_name') == owner.name and obj.get('af_fiber_proxy')]
    invalid = [obj.name for obj in fibers if obj.hide_get() or obj.hide_viewport or obj.hide_render or obj.display_type == 'WIRE']
    views = [(s.shading.type, s.shading.color_type) for screen in bpy.data.screens for area in screen.areas
             for s in area.spaces if s.type == 'VIEW_3D']
    scps = [obj for obj in objects if obj.get('af_root_name') == owner.name and obj.get('af_scp_geometry')]
    return dict(fibers=len(fibers), hidden_or_wire=invalid, views=views, scp_colors={obj.name: list(obj.color) for obj in scps})


def screenshot():
    if bpy.app.background: return
    selected = [o for o in bpy.context.scene.objects if o.get('af_muscle_id') == probe.STATE['args'].muscle and o.type == 'MESH']
    if not selected: return
    for obj in bpy.context.selected_objects: obj.select_set(False)
    for obj in selected: obj.select_set(True)
    bpy.context.view_layer.objects.active = selected[0]
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.view3d.view_axis(type='FRONT'); bpy.ops.view3d.view_selected()
    probe.viewport_snapshot(probe.STATE['args'].output + '.png')


def verify():
    result = probe.STATE['result']; result['geometry'] = probe.geometry()
    result['graph'] = graph_checks(); result['debug'] = debug_checks()
    bpy.context.view_layer.update(); result['geometry_after_update'] = probe.geometry()
    screenshot(); probe.save(); bpy.ops.wm.quit_blender()


def main():
    probe.STATE['args'] = probe.args(); addon = probe.load_checkout()
    if not hasattr(bpy.types.Object, 'af_scp_system'): addon.register()
    bpy.ops.wm.open_mainfile(filepath=probe.STATE['args'].file)
    probe.STATE['result'] = probe.metadata()
    if bpy.app.background: verify()
    else: bpy.app.timers.register(verify, first_interval=3)


if __name__ == '__main__':
    main()
