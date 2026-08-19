"""Read-only diagnostic for rejected scalar-corridor coordinates."""

import bpy
import numpy as np

from anthroforge.core.vcp import v3_experiment as v3
from anthroforge.core.vcp.v2 import collision as collision
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _capture():
    root = common._root(); fiber = common._fiber(root, "FIBER_2")
    graph = bpy.context.evaluated_depsgraph_get(); colliders = common._colliders(bpy.context.scene, root, graph)
    snapshot = common.build_triangle_snapshot(colliders); anchors, _legacy = common._open_anchors(root, fiber, graph)
    request = common._request(root, fiber, anchors, colliders); corridor = v3.plan_v3_corridor(request, snapshot)
    return request, snapshot, corridor, v3.solve_v3_corridor(request, snapshot)


def _rows(values, keys, snapshot, threshold):
    output = []
    for distance, key in zip(values, keys):
        if distance >= threshold: continue
        node, face = key; output.append((node, snapshot.face_colliders[face], snapshot.face_owners[face], distance))
    return sorted(output, key=lambda row: row[-1])[:12]


def _probe(request, snapshot, corridor, result, node, value):
    direct, roadmap = np.asarray(corridor.direct), np.asarray(corridor.roadmap)
    alpha = np.asarray(result.alpha); alpha[node] = value; points = v3._corridor_points(direct, roadmap, alpha)
    threshold = v3._request_threshold(request); nodes = collision._node_rows(points, snapshot, corridor.contacts, threshold, None)
    edges = collision._edge_rows(points, v3._edges(len(points)), snapshot, corridor.contacts, threshold, None)
    checked = collision._static_result(nodes, edges, threshold, "probe")
    print("AF_COLLISION_PROBE", node, value, checked, flush=True)
    print("AF_NODE_BLOCKERS", _rows(nodes[0], nodes[1], snapshot, threshold), "contained", nodes[3], flush=True)
    print("AF_EDGE_BLOCKERS", _rows(edges[0], edges[1], snapshot, threshold), flush=True)


def main():
    captured = _capture()
    for node, value in ((23, 1.0), (23, 1.01), (23, 1.05), (23, 1.1),
                        (33, 1.01), (33, 1.05), (33, 1.1)):
        _probe(*captured, node, value)
    print("AF_CONTACTS", captured[2].contacts, flush=True)


main()
