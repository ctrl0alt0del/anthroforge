"""Render stored, planner, V2.4, and pin-smoothed paths left to right."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fiber_v25_branch2_render as render


def _materials():
    material = render.base._material
    return (material("COLLIDERS", (.08, .11, .15), alpha=.22),
            material("STORED_V1", (1.0, .31, .03), emission=.22),
            material("PLANNER", (.02, .78, 1.0), emission=.22),
            material("V2_4", (.80, .14, 1.0), emission=.22),
            material("BRIDGE_RECOVERY", (.12, .95, .32), emission=.22),
            material("PINS", (1.0, .92, .05), emission=.16))


def main():
    args = render._args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    render.base._reset_scene(); paths = render._paths(record); frame = render._frame(paths)
    names = "Stored V1", "Planner", "V2.4", "Bridge-aware recovery"
    materials = _materials()
    for index, (name, path) in enumerate(zip(names, paths)):
        render._tile(record, path, name, index, frame, materials)
    render._finish(output, args.blend_output)


if __name__ == "__main__":
    main()
