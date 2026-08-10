import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_reserved_patches as reserved


def sparse_loops(first, second):
    return first, second


def main():
    reserved.patch_loops = sparse_loops
    reserved.main()


if __name__ == "__main__":
    main()
