"""Read-only inventory of a skeleton's native SCPs for DSL readiness review."""
import json
import sys
from pathlib import Path
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import anthroforge
from anthroforge.adapters.authoring.capture import capture_mesh
from anthroforge.adapters.authoring.records import record, plain


def topology(mesh):
    edges = np.sort(np.concatenate([mesh.triangles[:, [0, 1]],
        mesh.triangles[:, [1, 2]], mesh.triangles[:, [2, 0]]]), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    points = mesh.vertices @ mesh.matrix[:3, :3].T + mesh.matrix[:3, 3]
    return dict(vertices=len(points), triangles=len(mesh.triangles),
        boundary_edges=int(sum(counts == 1)), nonmanifold_edges=int(sum(counts > 2)),
        bounds=[points.min(axis=0).tolist(), points.max(axis=0).tolist()],
        matrix=mesh.matrix.tolist(), concept=mesh.concept, side=mesh.side)


def scp_record(root, scp):
    mesh = capture_mesh(root, bpy.context.scene, scp)
    return dict(id=scp.id, name=scp.name, native=record(scp),
        custom={k: plain(scp[k]) for k in scp.keys() if k.startswith('af_')},
        geometry=topology(mesh) if mesh is not None else None)


def object_record(obj):
    custom = {k: plain(obj[k]) for k in obj.keys() if k != '_RNA_UI'}
    return dict(name=obj.name, type=obj.type, parent=obj.parent.name if obj.parent else None,
        dimensions=list(obj.dimensions), custom=custom,
        modifiers=[dict(name=m.name, type=m.type) for m in obj.modifiers])


def rig_record(obj):
    return dict(name=obj.name, bones=[dict(name=b.name,
        parent=b.parent.name if b.parent else None, head=list(b.head_local),
        tail=list(b.tail_local)) for b in obj.data.bones],
        pose=[dict(name=b.name, constraints=[dict(name=c.name, type=c.type)
        for c in b.constraints]) for b in obj.pose.bones])


def main():
    if not hasattr(bpy.types.Object, 'af_scp_system'):
        anthroforge.register()
    root = bpy.data.objects['AF_ROOT']
    units = bpy.context.scene.unit_settings
    result = dict(source=bpy.data.filepath, units=dict(system=units.system,
        scale_length=units.scale_length), root=record(root.af_scp_system),
        scps=[scp_record(root, scp) for scp in root.af_scp_system.scps],
        objects=[object_record(obj) for obj in bpy.context.scene.objects],
        rigs=[rig_record(obj) for obj in bpy.context.scene.objects if obj.type == 'ARMATURE'])
    Path(sys.argv[sys.argv.index('--') + 1]).write_text(json.dumps(result, indent=2, default=str))
    print('SCP_AUDIT_COMPLETE', len(result['scps']), flush=True)


if __name__ == '__main__':
    main()
