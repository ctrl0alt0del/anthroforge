"""Run import snapshots against the same checkout as the Blender test runner."""

from pathlib import Path
import importlib.util
import sys

import bpy


def snapshot_command(filepath, outpath):
    return [bpy.app.binary_path, "--factory-startup", "-b", filepath, "--python-exit-code", "1",
            "--python", str(Path(__file__).resolve()), "--", outpath]


def _load_addon():
    path = Path(__file__).resolve().parent.parent / "__init__.py"
    spec = importlib.util.spec_from_file_location("anthroforge", path,
                                                submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["anthroforge"] = module
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == path, "Snapshot loaded the wrong checkout"
    module.register()


if __name__ == "__main__":
    _load_addon()
    from anthroforge.core.importing.extract import write_snapshot_json
    write_snapshot_json(sys.argv[sys.argv.index("--") + 1])
