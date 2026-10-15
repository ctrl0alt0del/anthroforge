"""Real saved torso: shared service, direct final mesh, no draft dependencies."""
import sys
import time
from pathlib import Path
import bpy
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent),str(ROOT)]
import anthroforge
from anthroforge.adapters.deformation import runtime, storage, request
from anthroforge.core.deformation.contact import prepare_contact


def wait(root):
    deadline = time.monotonic()+600
    while time.monotonic()<deadline:
        runtime.tick()
        if not runtime.QUEUE.slots and not runtime.jobs.ACTIVE: break
        time.sleep(.1)
    print("WORKER_RESULT",root.get("af_deformation_status"),flush=True)
    assert root.get("af_deformation_status") == "Updated",root.get("af_deformation_status")


def run(path):
    anthroforge.register(); bpy.ops.wm.open_mainfile(filepath=str(path))
    root = bpy.data.objects["AF_ROOT"]; obj = request.topology(root,bpy.context.scene)
    reference = prepare_contact(storage.load(root,obj),normal=(0,1,0)); storage.store(root,obj,reference)
    pointer = obj.data.as_pointer(); root.af_topology_settings.deformation_method = "LE"
    runtime.enqueue(root,bpy.context.scene,True); wait(root)
    assert obj.data.as_pointer() == pointer
    assert not any(o.get("af_draft_skin") for o in bpy.context.scene.objects)
    runtime.enqueue(root,bpy.context.scene,True); wait(root)
    runtime.shutdown()
    print("DEFORMATION_WORKER_PASS",flush=True)


if __name__ == "__main__": run(Path(sys.argv[sys.argv.index("--")+1]))
