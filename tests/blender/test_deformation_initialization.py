"""Prepare, publish, remove temporary draft, save and reopen the actual torso."""
import sys
import time
from pathlib import Path
import bpy
ROOT = Path(__file__).resolve().parents[2]; sys.path[:0] = [str(ROOT.parent),str(ROOT),str(ROOT/"tests")]
import anthroforge
from anthroforge.adapters.deformation import runtime, request, storage
from fixtures.deformation_scene import load_fixture, debug_visibility
from anthroforge.adapters.authoring.scene import StaticScene
BASE = Path("E:/development/WIP_models/rib_rig_experiment")


def wait(root):
    deadline = time.monotonic()+1200
    while time.monotonic()<deadline:
        runtime.tick()
        if not runtime.jobs.ACTIVE and not runtime.QUEUE.slots: break
        time.sleep(.1)
    assert root.get("af_deformation_status") == "Reference ready",root.get("af_deformation_status")


def run():
    anthroforge.register(); root,obj = load_fixture(BASE/"20261014_v21_large_diff/change_0/source_debug.blend")
    before = obj.data.as_pointer(); runtime.initialize(root,bpy.context.scene); wait(root)
    assert obj.data.as_pointer() == before
    assert not any(o.get("af_draft_skin") for o in bpy.context.scene.objects)
    reference = storage.load(root,obj)
    path = BASE/"20261015_v32_production_deformation/initialized_debug.blend"
    StaticScene(root,bpy.context.scene).save_debug_copy(path); bpy.ops.wm.open_mainfile(filepath=str(path))
    root = bpy.data.objects["AF_ROOT"]; obj = request.topology(root,bpy.context.scene)
    assert storage.load(root,obj).signature == reference.signature
    print("INITIALIZATION_PASS",debug_visibility(root),flush=True)


if __name__ == "__main__":
    try: run()
    finally: runtime.shutdown()
