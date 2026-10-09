"""Blender benchmark: retained native updates and collision reroutes at 10/100 Fibers."""
import json
import os
from pathlib import Path
import sys
from statistics import median
from time import perf_counter

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO.parent), str(REPO / 'tests/blender')]
os.environ['AF_FIBER_ENGINE'] = 'V3'
import bpy
from mathutils import Vector
from _helpers import reset_scene, scp_with_object, find_flagged
from test_muscle_parent_fibers import parent_fixture, arched_fiber
from anthroforge.core.vcp.fiber_node_attachment import capture_fiber_node_attachments
from anthroforge.core.visualization.muscle_fiber_attachment import apply_batch
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements, fiber_refinement_batch_stats


def fixture(count):
    os.environ['AF_FIBER_ENGINE'] = 'V1'
    reset_scene(); owner, _muscle, surface, parent = parent_fixture(); ids = []
    for _ in range(count):
        fiber, points = arched_fiber(owner, surface, parent)
        assert capture_fiber_node_attachments(owner, bpy.context.scene, fiber, points).ok
        ids.append(fiber.id)
    fibers = [f for f in owner.af_vcp_system.fibers if f.id in ids]
    os.environ['AF_FIBER_ENGINE'] = 'V3'
    return owner, surface, fibers, points


def deform(surface, distance):
    for vertex in surface.data.vertices: vertex.co.z += distance
    surface.data.update(); bpy.context.view_layer.update()


def measure(owner, fibers, reroute=False):
    started = perf_counter()
    apply_batch(register_fiber_sync(), owner, bpy.context.scene, fibers)
    if reroute: drain_fiber_refinements()
    elapsed = (perf_counter() - started) * 1000
    stale = [f.id for f in fibers if find_flagged('af_fiber_proxy', f.id, 'af_fiber_id').get('af_fiber_output_state') != 'CURRENT']
    assert not stale, stale
    return elapsed


def benchmark(count):
    owner, surface, fibers, points = fixture(count); warm = []
    bindings = [(f.a_attach_param, f.b_attach_param) for f in fibers]
    for distance in (.003, -.003, .003, -.003, .003, -.003):
        deform(surface, distance); warm.append(measure(owner, fibers))
    bpy.ops.mesh.primitive_cube_add(size=.06, location=points[3] + Vector((0, 0, .125)))
    scp_with_object(owner, 'Benchmark obstruction', bpy.context.object)
    deform(surface, .125); reroute = measure(owner, fibers, True)
    assert bindings == [(f.a_attach_param, f.b_attach_param) for f in fibers]
    return dict(fibers=count, warm_ms=warm, warm_median_ms=median(warm[2:]), reroute_ms=reroute,
                native_batches=fiber_refinement_batch_stats(), structural_bindings_unchanged=True)


def main():
    output = Path(sys.argv[sys.argv.index('--output') + 1])
    rows = [benchmark(count) for count in (10, 100)]
    output.write_text(json.dumps(rows, indent=2, default=str))
    print('MUSCLE_PARENT_BENCHMARK', json.dumps(rows, default=str), flush=True)


if __name__ == '__main__': main()
