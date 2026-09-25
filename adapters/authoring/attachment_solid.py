"""Native Blender solid construction; original scene objects are never operands."""
import bpy
import bmesh
import numpy as np
from .collision_cleanup import create, modifier, extract, remove
from ...core.authoring.errors import require


def capture(bm):
    bmesh.ops.triangulate(bm, faces=list(bm.faces)); bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces)); bm.verts.index_update()
    return np.array([list(v.co) for v in bm.verts]), np.array([[v.index for v in f.verts] for f in bm.faces])


def hull(points):
    bm = bmesh.new()
    try:
        result = bmesh.ops.convex_hull(bm, input=[bm.verts.new(p) for p in points], use_existing_faces=False)
        bmesh.ops.delete(bm, geom=list(set(result['geom_unused']+result['geom_interior'])), context='VERTS')
        return capture(bm)
    finally:
        bm.free()


def cap_cut(retained):
    vertices, faces, loop = retained; center = vertices[loop].mean(0); index = len(vertices)
    faces = np.array(list(faces)+[[int(a), int(b), index] for a, b in zip(loop, np.roll(loop, -1))])
    return repaired(np.vstack([vertices, center]), faces, fill=False)


def repaired(vertices, faces, fill=True):
    mesh = bpy.data.meshes.new('Attachment topology'); bm = bmesh.new()
    try:
        mesh.from_pydata(vertices, [], faces); bm.from_mesh(mesh)
        if fill:
            bmesh.ops.dissolve_degenerate(bm, dist=1e-7, edges=list(bm.edges))
        edges = [e for e in bm.edges if e.is_boundary]
        require(not edges or not fill or len(edges) <= 3, 'ATTACHMENT_UNEXPECTED_OPEN_OUTPUT')
        if fill and edges:
            require(max(e.calc_length() for e in edges) <= np.ptp(vertices, axis=0).max()*.02, 'ATTACHMENT_LARGE_OPEN_OUTPUT')
            bmesh.ops.holes_fill(bm, edges=edges, sides=3)
        return capture(bm)
    finally:
        bm.free(); bpy.data.meshes.remove(mesh)


def union(scene, first, second):
    collection = bpy.data.collections.new('Temporary attachment union'); scene.collection.children.link(collection)
    try:
        a = create(collection, *first); b = create(collection, *second); modifier(a, 'UNION', other=b)
        return extract(a, 1e-7)
    finally:
        remove(collection)
