"""Dump evaluated Package 4 inputs from a loaded Blender file without saving it."""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import build_triangle_snapshot
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _manifest(colliders, anchors, snapshot):
    return {"file": bpy.data.filepath, "colliders": [_collider(row) for row in colliders],
            "anchors": [_anchor(row) for row in anchors], "triangles": len(snapshot.triangles),
            "scene_meshes": [_mesh(row) for row in bpy.context.scene.objects if row.type == "MESH"]}


def _collider(row):
    return {"id": row.collider_id, "owner": row.owner_id,
            "vertices": len(row.vertices), "triangles": len(row.triangles)}


def _anchor(row):
    return {"point": list(row.point), "owner": row.owner_id,
            "role": row.role.value, "authored_index": row.authored_index}


def _mesh(obj):
    return {"name": obj.name, "scp_id": str(obj.get("af_scp_id", "")),
            "geometry_role": str(obj.get("af_geometry_role", ""))}


def _write(output, manifest, snapshot):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    np.savez_compressed(output.with_suffix(".npz"), vertices=snapshot.vertices,
                        triangles=snapshot.triangles)


def main():
    args = _arguments(); root = bench._root(); fiber = bench._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    anchors, _legacy = bench._open_anchors(root, fiber, depsgraph); snapshot = build_triangle_snapshot(colliders)
    _write(Path(args.output), _manifest(colliders, anchors, snapshot), snapshot)


if __name__ == "__main__":
    main()
