"""Explicit portable smoke suite; not Blender/native production acceptance."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SUITES = (
    'test_issue_system', 'test_authoring_storage_policy', 'test_topology',
    'test_branch_flow', 'test_deformation_scheduling', 'test_deformation_reference',
)


def main():
    failures = []
    for name in SUITES:
        print('\nPortable suite: ' + name, flush=True)
        result = subprocess.run([sys.executable, '-m', 'unittest',
                                 'tests.unit.' + name], cwd=ROOT)
        if result.returncode:
            failures.append(name)
    print('Scope: portable contracts only; Blender/native/fixture acceptance is NOT covered.')
    if failures:
        raise SystemExit('Failed suites: ' + ', '.join(failures))


if __name__ == '__main__':
    main()
