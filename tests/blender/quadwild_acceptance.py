"""Run the complete production topology/reference/publication path on real fixtures."""
import sys
import time
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT/'tests')]
import bpy
import numpy as np
import anthroforge
from anthroforge.adapters.topology.vendor import ensure_worker_dependencies
ensure_worker_dependencies()
from anthroforge.adapters.deformation import runtime
from anthroforge.adapters.topology.capture import capture_topology_surface, capture_topology
from anthroforge.adapters.topology.solver import solve_capture
from anthroforge.core.topology.protocol import write_capture, read_capture, write_result
from anthroforge.adapters.authoring.scene import StaticScene
from fixtures.deformation_scene import debug_visibility
from types import SimpleNamespace

BASE = Path('E:/development/WIP_models/rib_rig_experiment')
OUT = BASE/'20261016_v35_quadwild_production'


def capture(label):
    source = BASE/'20261015_v31_production_foundation/torso_reference_debug.blend'
    if label == 'skull': source = Path('E:/development/WIP_models/skull_muscles_skin_sparse_topology.blend')
    bpy.ops.wm.open_mainfile(filepath=str(source)); runtime.shutdown(); root = bpy.data.objects['AF_ROOT']
    root.af_topology_settings.backend = 'QUADWILD'; root.af_topology_settings.symmetry_mode = 'X' if label == 'skull' else 'Y'
    root.af_topology_settings.target_quad_count = 8100
    if label == 'skull': return root, capture_topology(root, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
    data = np.load(BASE/'20261014_v19_issue_system/before_skin.npz')
    return root, capture_topology_surface(root, bpy.context.scene, bpy.context.evaluated_depsgraph_get(), data['vertices'], data['triangles'])


def publish(root, result, source, folder):
    from workers.deformation_construction import attempt
    from anthroforge.adapters.deformation.construction import publish as commit
    spec = SimpleNamespace(root_name=root.name, job_dir=str(folder), cancel_path=str(folder/'cancel'))
    attempt(spec, result, source); write_result(folder/'result.npz', result)
    obj = commit(bpy.context.scene, root, result, folder)
    save_verified(root, obj, folder)


def save_verified(root, obj, folder):
    for collection in tuple(bpy.data.collections):
        if collection.name.startswith('AF_TOPOLOGY_WORK'):
            for item in tuple(collection.objects): bpy.data.objects.remove(item, do_unlink=True)
            bpy.data.collections.remove(collection)
    name = obj.name; path = folder/'production_debug.blend'; StaticScene(root,bpy.context.scene).save_debug_copy(path)
    bpy.ops.wm.open_mainfile(filepath=str(path)); runtime.shutdown()
    report = debug_visibility(bpy.data.objects['AF_ROOT']); report['faces'] = len(bpy.data.objects[name].data.polygons)
    (folder/'reopen.json').write_text(json.dumps(report, indent=2))


def publish_interrupted_skull():
    from anthroforge.core.topology.protocol import read_result
    from anthroforge.adapters.deformation.construction import publish as commit
    root, source = capture('skull'); folder = OUT/'skull'; result = read_result(folder/'result.npz')
    error = 'Reference preparation interrupted after more than 15 minutes inside native LE preparation. No new deformation reference is available.'
    result.statistics['deformation_preparation_error'] = error
    result.statistics.setdefault('warnings', []).append(error); write_result(folder/'result.npz', result)
    obj = commit(bpy.context.scene, root, result, folder); save_verified(root, obj, folder)
    (folder/'receipt.json').write_text(json.dumps(dict(reference_ready=False, statistics=result.statistics), indent=2))


def run(label):
    folder = OUT/label; folder.mkdir(parents=True, exist_ok=True); started = time.perf_counter()
    root, source = capture(label); write_capture(folder/'capture.npz', source); loaded = read_capture(folder/'capture.npz')
    assert loaded.input_hash == source.input_hash and len(loaded.flow_guides) == len(source.flow_guides)
    print('CAPTURE', label, len(source.flow_samples), len(source.flow_guides), flush=True)
    from anthroforge.adapters.topology.vendor import ensure_worker_dependencies
    result = solve_capture(loaded, ensure_worker_dependencies(), lambda *args: print(*args, flush=True))
    write_result(folder/'result.npz', result); publish(root, result, source, folder)
    (folder/'receipt.json').write_text(json.dumps(dict(seconds=time.perf_counter()-started, statistics=result.statistics), indent=2))


if __name__ == '__main__':
    anthroforge.register(); runtime.shutdown(); label = sys.argv[sys.argv.index('--')+1]
    if label == 'skull-publication': publish_interrupted_skull()
    else: run(label)
