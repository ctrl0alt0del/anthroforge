"""Launch the pinned headless Blender with writable user/cache directories."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def environment():
    result = dict(os.environ)
    for key, directory in [('BLENDER_USER_CONFIG', 'blender-config'), ('XDG_CACHE_HOME', 'cache')]:
        path = ROOT / '.artifacts/cloud-runtime' / directory
        path.mkdir(parents=True, exist_ok=True)
        result[key] = str(path)
    return result


def main():
    binary = ROOT / '.artifacts/blender-5.0.1-linux-x64/blender'
    if not binary.is_file():
        raise SystemExit('Run python3.11 tools/cloud/geometry_setup.py first')
    raise SystemExit(subprocess.call([str(binary), *sys.argv[1:]], env=environment()))


if __name__ == '__main__':
    main()
