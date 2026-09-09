"""Verify saved skeleton publication against its persisted evaluated geometry."""
import sys
from pathlib import Path
import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import anthroforge
from anthroforge.adapters.authoring.native_scene import BlenderScene, root_documents
from anthroforge.adapters.authoring.publication import verify


def main():
    if not hasattr(bpy.types.Object,"af_scp_system"):
        anthroforge.register()
    root = bpy.data.objects["AF_ROOT"]
    port = BlenderScene(root,bpy.context.scene)
    count = 0
    for value in root_documents(root).values():
        record = value["record"]
        port.refresh(record["native_ids"])
        verify(port,record["native_ids"],record["results"])
        count += len(record["results"])
    assert count, "No authoring publication in this file"
    finish(count)


def finish(count):
    print("SAVED_AUTHORING_GEOMETRY_PASS",count,flush=True)
    if "--" in sys.argv:
        target = Path(sys.argv[sys.argv.index("--")+1]).resolve()
        assert target != Path(bpy.data.filepath).resolve(), "Use a separate verified output copy"
        bpy.ops.wm.save_as_mainfile(filepath=str(target))


if __name__ == "__main__":
    main()
