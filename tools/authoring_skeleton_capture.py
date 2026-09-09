"""Export a detached skeleton snapshot for repeatable DSL authoring experiments."""
import sys
import json
from pathlib import Path
import bpy

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON.parent))
import anthroforge
from anthroforge.adapters.authoring.native_scene import BlenderScene


def main():
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()
    root = bpy.data.objects["AF_ROOT"]
    snap = BlenderScene(root, bpy.context.scene).capture(root.name)
    value = dict(id=snap.id, revision=snap.revision, pose=snap.pose, meshes=[dict(id=m.id,
                 vertices=m.vertices.tolist(), triangles=m.triangles.tolist(), matrix=m.matrix.tolist(),
                 concept=m.concept, side=m.side) for m in snap.meshes])
    args = sys.argv[sys.argv.index("--")+1:]
    Path(args[0]).write_text(json.dumps(value), encoding="utf-8")
    print("CAPTURED", len(snap.meshes), flush=True)


if __name__ == "__main__":
    main()
