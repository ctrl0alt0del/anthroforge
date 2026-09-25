"""Exact repair on temporary geometry; no source/SCP or selection mutation."""
import bpy
import bmesh
import numpy as np
from ...core.authoring.errors import require
from ...core.authoring.correction_topology import split


def create(collection, vertices, faces):
    mesh = bpy.data.meshes.new('Collision calculation'); obj = None
    try:
        mesh.from_pydata(vertices.tolist(), [], faces.tolist()); mesh.update()
        obj = bpy.data.objects.new('Collision calculation', mesh); collection.objects.link(obj)
        return obj
    except BaseException:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise


def modifier(obj, operation, other=None, collection=None):
    mod = obj.modifiers.new('Collision calculation', 'BOOLEAN'); mod.operation = operation
    mod.solver = 'EXACT'; mod.use_self = True; mod.use_hole_tolerant = True
    if other is not None:
        mod.object = other
    else:
        mod.operand_type = 'COLLECTION'; mod.collection = collection


def compact(mesh, epsilon):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh); bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=epsilon)
        bmesh.ops.dissolve_degenerate(bm, dist=epsilon, edges=[e for e in bm.edges if e.calc_length() <= epsilon])
        bmesh.ops.triangulate(bm, faces=list(bm.faces)); bm.verts.index_update()
        vertices = np.array([tuple(v.co) for v in bm.verts]); faces = np.array([[v.index for v in f.verts] for f in bm.faces], dtype=int)
        require(len(faces) > 0, 'CORRECTION_CLEANUP_EMPTY')
        return split(vertices, faces)
    finally:
        bm.free()


def extract(obj, epsilon):
    bpy.context.view_layer.update(); ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); mesh = ev.to_mesh()
    try:
        return compact(mesh, epsilon)
    finally:
        ev.to_mesh_clear()


def remove(collection):
    for obj in list(collection.objects):
        mesh = obj.data; bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(collection)


def clean(scene, vertices, faces, obstacles=(), epsilon=1e-7):
    collection = bpy.data.collections.new('Temporary collision calculation'); empty = bpy.data.collections.new('Empty collision operand')
    origin = np.asarray(vertices, dtype=float).mean(axis=0)
    try:
        scene.collection.children.link(collection); obj = create(collection, np.rint((vertices-origin)/epsilon)*epsilon, faces)
        modifier(obj, 'UNION', collection=empty)
        for obstacle in obstacles:
            bone = create(collection, np.rint((obstacle.vertices-origin)/epsilon)*epsilon, obstacle.faces); modifier(obj, 'DIFFERENCE', other=bone)
        output, triangles = extract(obj, epsilon)
        return output+origin, triangles
    finally:
        remove(collection); bpy.data.collections.remove(empty)
