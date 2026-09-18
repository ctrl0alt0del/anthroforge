"""Whole bone-facing underside evidence, without a bone-contact distance crop."""
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from ...core.authoring.errors import require
from ...core.authoring.transfer_meshes import world


def tree(geometry):
    vertices = world(geometry); faces = np.asarray(geometry['triangles'], int)
    if np.linalg.det(np.asarray(geometry['matrix'])[:3, :3]) < 0:
        faces = faces[:, ::-1]
    return BVHTree.FromPolygons(vertices.tolist(), faces.tolist(), all_triangles=True), vertices, faces


def candidates(row, supports):
    muscle, vertices, faces = tree(row['geometry']); require(len(faces) <= 100000, 'BASE_EVIDENCE_BUDGET')
    bones = [(owner, tree(geometry)[0]) for owner, geometry in supports.items()]
    require(bones, 'BASE_SUPPORTS_EMPTY')
    triangles = vertices[faces]; cross = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    lengths = np.linalg.norm(cross, axis=1); epsilon = max(1e-9, np.linalg.norm(np.ptp(vertices, axis=0))*1e-6)
    require(np.all(lengths > epsilon*epsilon*1e-3), 'BASE_DEGENERATE_SOURCE')
    rows = [evidence(center, normal, muscle, bones, epsilon) for center, normal in zip(triangles.mean(1), cross/lengths[:, None])]
    return dict(version='underside_evidence.v1', faces=rows, source_triangles=[i for i, r in enumerate(rows) if r['score'] > 0],
                anatomical_review='required', limitations=['No distance cutoff: noncontact underside spans remain candidates.',
                'Face evidence can contain holes or fragments; supply explicit head-aware disk patches before native planning.',
                'Nearest-bone normals and occlusion are evidence, not automatic attachment or anatomical classification.'])


def evidence(center, normal, muscle, bones, epsilon):
    owner, hit = min(((owner, bone.find_nearest(Vector(center))) for owner, bone in bones), key=lambda pair: pair[1][3])
    point, bone_normal, triangle, distance = hit; delta = np.asarray(point)-center
    direction = delta/max(distance, epsilon); signed = float(np.dot(-delta, bone_normal))
    visible = distance <= epsilon or muscle.ray_cast(Vector(center+normal*epsilon), Vector(direction), max(distance-epsilon*4, epsilon))[0] is None
    score = float(-np.dot(normal, bone_normal) if signed < -epsilon*4 or distance <= epsilon else np.dot(normal, direction))
    if not visible and signed >= -epsilon*4:
        score = min(score, -.75)
    return dict(owner=owner, support_triangle=int(triangle), distance=float(distance), signed_distance=signed,
                visible=visible, score=score)
