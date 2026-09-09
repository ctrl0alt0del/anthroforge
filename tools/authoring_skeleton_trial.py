"""Build representative documents on a skeleton copy and retain diagnostics."""
import json
import sys
from pathlib import Path
import bpy
from time import perf_counter
from uuid import uuid4

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON.parent))
import anthroforge
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.native_scene import BlenderScene


def trial(root, path, folder):
    document = json.loads(path.read_text())
    scene = bpy.context.scene
    revision = BlenderScene(root, scene).capture(root.name).revision
    request = dict(dsl="anthroforge.authoring.protocol", version=document["version"], message_type="request", op="build",
        request_id=path.stem+"_trial_"+uuid4().hex[:8], params=dict(scene_id=root.name, expected_scene_revision=revision,
            transaction="document_atomic", document=document))
    print("BUILDING", path.name, flush=True)
    started = perf_counter()
    result = execute(request, root, scene, folder / "journal")
    return save_trial(folder,path,result,started)


def save_trial(folder, path, result, started):
    result["cost"]["elapsed"] = dict(value=(perf_counter()-started)*1000,unit="ms")
    (folder / (path.stem+"_response.json")).write_text(json.dumps(result, indent=2))
    print("RESULT", path.stem, result["status"], result["diagnostics"], flush=True)
    return result


def main():
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()
    folder = Path(sys.argv[sys.argv.index("--")+1])
    root = bpy.data.objects["AF_ROOT"]
    results = [trial(root, path, folder) for path in sorted(folder.glob("muscle_*_dsl.json"))]
    if any(r["published"] for r in results):
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / "skeleton_dsl_test.blend"))


if __name__ == "__main__":
    main()
