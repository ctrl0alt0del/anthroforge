import argparse
import sys
from pathlib import Path


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from adapters.topology.instant_api import remesh_file


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--target-vertices", type=int, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    remesh_file(args.input, args.output, args.vendor, args.target_vertices)


if __name__ == "__main__":
    main()
