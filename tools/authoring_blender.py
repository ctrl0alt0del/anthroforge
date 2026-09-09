"""Headless entry: blender -b model.blend -P this.py -- request.json response.json [output.blend]."""
import json
import sys
from pathlib import Path
import bpy

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON.parent))
import anthroforge
from anthroforge.app.authoring.api import execute


def main():
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()
    args = sys.argv[sys.argv.index("--")+1:]
    request = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    root = bpy.data.objects.get(request["params"]["scene_id"])
    if root is None:
        raise ValueError("Requested AF_ROOT does not exist")
    response = execute(request, root, bpy.context.scene, Path(args[1]).parent / "journal")
    Path(args[1]).write_text(json.dumps(response, indent=2), encoding="utf-8")
    if len(args) > 2 and response["published"]:
        require_copy(args[2])
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args[2]).resolve()))


def require_copy(path):
    if Path(path).resolve() == Path(bpy.data.filepath).resolve():
        raise ValueError("Headless experiment output must be a copy")


if __name__ == "__main__":
    main()
