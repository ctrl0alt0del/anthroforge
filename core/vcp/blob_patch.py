from dataclasses import dataclass
from mathutils import Vector, kdtree
import bpy


@dataclass
class BlobPatch:
    vertex_indices: list
    weights: list
    world_positions: list
    target_object_name: str = ""


class BlobPatchQuery:
    def __init__(self, positions, weights):
        self.positions = positions or []
        self.weights = weights or []
        self.tree = None

        if self.positions:
            kd = kdtree.KDTree(len(self.positions))
            for i, p in enumerate(self.positions):
                kd.insert(p, i)
            kd.balance()
            self.tree = kd

    def nearest(self, world_point):
        if self.tree is None:
            return None, 0.0
        co, idx, _dist = self.tree.find(world_point)
        if idx < 0:
            return None, 0.0
        return co.copy(), float(self.weights[idx])


def _smoothstep01(x):
    t = max(0.0, min(1.0, float(x)))
    return t * t * (3.0 - 2.0 * t)


def _blob_sdf_world(blob, p_world):
    d = p_world - blob.center_world

    if blob.shape == "ELLIPSOID":
        ax = max(1e-8, blob.radius * blob.axis_scale.x)
        ay = max(1e-8, blob.radius * blob.axis_scale.y)
        az = max(1e-8, blob.radius * blob.axis_scale.z)
        q = Vector((d.x / ax, d.y / ay, d.z / az))
        # Dimensionless distance converted back to world units by min axis.
        return (q.length - 1.0) * min(ax, ay, az)

    # Sphere
    return d.length - blob.radius


def _target_vertices_world(target_obj):
    if target_obj is None or target_obj.type != "MESH":
        return None, None

    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = target_obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()
    if mesh_eval is None:
        return None, None

    mw = target_obj.matrix_world
    verts = [(i, mw @ v.co) for i, v in enumerate(mesh_eval.vertices)]
    return verts, obj_eval


def compute_dynamic_patch(
    blob,
    target_obj,
    prev_patch=None,
    contact_margin=0.02,
    penetration_max=0.04,
    exit_scale=0.5,
    max_patch_vertices=256,
):
    if target_obj is None or target_obj.type != "MESH":
        return BlobPatch([], [], [], "")

    verts_data, obj_eval = _target_vertices_world(target_obj)
    if verts_data is None:
        return BlobPatch([], [], [], target_obj.name)

    try:
        prev_set = set(prev_patch.vertex_indices) if prev_patch else set()
        enter_th = max(1e-8, float(contact_margin))
        exit_th = enter_th * max(0.0, float(exit_scale))
        pen_max = max(1e-8, float(penetration_max))

        candidates = []
        for vidx, p in verts_data:
            sd = _blob_sdf_world(blob, p)
            is_prev = vidx in prev_set
            in_patch = (sd < exit_th) if is_prev else (sd < enter_th)
            if not in_patch:
                continue

            penetration = max(0.0, -sd)
            w = _smoothstep01(penetration / pen_max)
            w *= max(0.0, min(1.0, float(blob.attach_strength)))
            if w <= 1e-8:
                continue

            candidates.append((vidx, p, w))

        # Downsample to strongest anchors, deterministic tie-break by vertex index.
        lim = max(1, int(max_patch_vertices))
        if len(candidates) > lim:
            candidates.sort(key=lambda it: (-it[2], it[0]))
            candidates = candidates[:lim]

        vertex_indices = [it[0] for it in candidates]
        world_positions = [it[1].copy() for it in candidates]
        weights = [float(it[2]) for it in candidates]

        return BlobPatch(
            vertex_indices=vertex_indices,
            weights=weights,
            world_positions=world_positions,
            target_object_name=target_obj.name,
        )
    finally:
        obj_eval.to_mesh_clear()


def build_patch_query(patch):
    if patch is None:
        return BlobPatchQuery([], [])
    return BlobPatchQuery(patch.world_positions, patch.weights)
