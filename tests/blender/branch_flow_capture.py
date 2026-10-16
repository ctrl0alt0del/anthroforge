"""Capture real torso branch guidance and seam evidence without editing the fixture."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT)]
import bpy
import numpy as np
import anthroforge
from anthroforge.adapters.topology.vendor import ensure_worker_dependencies
ensure_worker_dependencies()
from anthroforge.adapters.deformation import runtime
from anthroforge.adapters.topology.flow_capture import capture_flow, muscle_roles
from anthroforge.adapters.topology.muscle_flow import material_patches
from anthroforge.core.topology.model import TopologySettings
from anthroforge.core.topology.flow_native import select_paths
OUT = Path('E:/development/WIP_models/rib_rig_experiment/20261016_v36_branch_flow')
BASE = OUT.parent/'20261016_v35_quadwild_production'


def capture():
    anthroforge.register(); runtime.shutdown()
    bpy.ops.wm.open_mainfile(filepath=str(BASE/'torso/production_debug.blend')); runtime.shutdown()
    root = bpy.data.objects['AF_ROOT']; regions = []
    samples, paths, warnings = capture_flow(root, bpy.context.scene, bpy.context.evaluated_depsgraph_get(), TopologySettings(), regions)
    owners = [r['owner'] for r in regions if r['branched']]
    mask = np.isin(samples[:, 9], owners)
    np.savez(OUT/'samples.npz', all=samples, branches=samples[mask], regular=samples[~mask])
    (OUT/'capture.json').write_text(json.dumps(dict(regions=regions, warnings=warnings), indent=2))
    save_patches(root)
    prepare_inputs(samples, mask)
    print('CAPTURE', len(samples), 'BRANCH SAMPLES', mask.sum(), 'WARNINGS', warnings, flush=True)


def save_patches(root):
    data, metadata = {}, []
    for muscle in root.af_vcp_system.muscles:
        for role in muscle_roles(root, muscle):
            patches, branched = material_patches(root, bpy.context.scene, muscle, role)
            if not branched: continue
            for key, grid, flip, seam in patches:
                name = f'p{len(metadata)}'; data[name] = grid
                metadata.append(dict(key=name, muscle=muscle.id, name=muscle.name, role=role, patch=key, flip=flip, seam=seam))
    np.savez(OUT/'patches.npz', **data)
    (OUT/'patches.json').write_text(json.dumps(metadata, indent=2))


def prepare_inputs(samples, mask):
    receipt = json.loads((BASE/'torso/receipt.json').read_text())
    folder = Path(receipt['statistics']['diagnostic_path']).parent
    with np.load(folder/'input.npz') as d: arrays = dict(d)
    points, offsets = arrays['flow_points'], arrays['flow_offsets']
    paths = select_paths(arrays['vertices'], [points[a:b] for a,b in zip(offsets[:-1], offsets[1:])])
    arrays.update(flow_points=np.vstack(paths), flow_offsets=np.r_[0,np.cumsum([len(p) for p in paths])])
    for name, field in [('without', samples[~mask]), ('with', samples)]:
        target = OUT/name; target.mkdir(exist_ok=True)
        np.savez(target/'input.npz', **dict(arrays, flow_samples=field))


if __name__ == '__main__': capture()
