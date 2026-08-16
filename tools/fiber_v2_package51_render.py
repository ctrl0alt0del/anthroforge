"""Render V1 / Package 4.3 / Package 5 / Package 5.1 comparison."""

import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_package5_update_render as renderer


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _optimized(record):
    output = copy.deepcopy(record)
    output["visual"]["package5"] = output["visual"]["package51"]
    return output


def main():
    args = _arguments(); source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    renderer._labels = lambda: ("V1", "PACKAGE 4.3", "PACKAGE 5", "PACKAGE 5.1")
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    renderer._build(source, _optimized(source), output, args.blend_output)


if __name__ == "__main__":
    main()
