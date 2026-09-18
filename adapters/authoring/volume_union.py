"""Evaluate an Exact Boolean on disposable copies; never alter SCPs or sources."""
import bpy
import numpy as np
from ...core.authoring.base_patch import topology
from ...core.authoring.errors import require
from ...core.authoring.transfer_meshes import world
from .base_quality import inspect


def combine(rows):
    vertices, faces = [], []
    for row in rows.values():
        points = world(row['geometry']); triangles = np.asarray(row['geometry']['triangles'], int)
        if np.linalg.det(np.asarray(row['geometry']['matrix'])[:3, :3]) < 0:
            triangles = triangles[:, ::-1]
        faces.extend((triangles+len(vertices)).tolist()); vertices.extend(points.tolist())
    return vertices, faces


def evaluate(scene, rows):
    vertices, faces = combine(rows); mesh = bpy.data.meshes.new('Temporary volume union')
    obj, collection = None, None
    try:
        mesh.from_pydata(vertices, [], faces); mesh.update()
        obj = bpy.data.objects.new('Temporary volume union', mesh); scene.collection.objects.link(obj)
        collection = bpy.data.collections.new('Temporary union operand')
        modifier = obj.modifiers.new('Resolve overlapping volumes', 'BOOLEAN')
        modifier.operation, modifier.solver, modifier.operand_type = 'UNION', 'EXACT', 'COLLECTION'
        modifier.collection, modifier.use_self, modifier.use_hole_tolerant = collection, True, True
        return evaluated_mesh(obj)
    finally:
        cleanup(obj, mesh, collection)


def evaluated_mesh(obj):
    bpy.context.view_layer.update(); evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles(); vertices = np.array([tuple(v.co) for v in mesh.vertices])
        triangles = np.array([tuple(t.vertices) for t in mesh.loop_triangles], int)
        require(len(triangles) > 0, 'BASE_UNION_EMPTY')
        report = topology(triangles); report.update(inspect(vertices, triangles))
        report['ready'] = not any(report[k] for k in ('boundary_edges', 'nonmanifold_edges', 'nonadjacent_bvh_overlap_pairs', 'degenerate_triangles'))
        return dict(vertices=vertices.tolist(), triangles=triangles.tolist(), quality=report)
    finally:
        evaluated.to_mesh_clear()


def cleanup(obj, mesh, collection):
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    if collection is not None:
        bpy.data.collections.remove(collection)
