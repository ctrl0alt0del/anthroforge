"""Prepare a portable test environment without altering Blender's Python."""
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / '.artifacts' / 'cloud-venv'


def main():
    if not (3, 11) <= sys.version_info[:2] <= (3, 12):
        raise SystemExit('Use Python 3.11 or 3.12 for the pinned test dependencies.')
    venv.EnvBuilder(with_pip=True).create(ENV)
    python = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '-r',
                    str(ROOT / 'requirements-test.txt')], check=True)
    subprocess.run([str(python), str(ROOT / 'tools/cloud/check.py')], check=True, cwd=ROOT)


if __name__ == '__main__':
    main()
