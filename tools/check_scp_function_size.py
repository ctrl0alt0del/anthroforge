import ast
import sys
from pathlib import Path

LIMIT = 15
TARGETS = [
    'operators/add_scp.py',
    'properties/scp_properties.py',
    'ui/scene_props.py',
    'ui/panels/create_panel.py',
    'ui/panels/scp_create_sections.py',
    'core/visualization/sync.py',
    'core/visualization/sync_runtime.py',
    'core/visualization/scp_attachment_runtime.py',
    'core/scp_runtime',
]


def iter_target_files(root):
    for rel in TARGETS:
        path = root / rel
        if path.is_dir():
            yield from sorted(path.glob('*.py'))
        elif path.exists():
            yield path


def code_line_count(node, lines):
    if not node.body:
        return 0
    start = node.body[0].lineno
    end = node.body[-1].end_lineno
    body = lines[start - 1 : end]
    return sum(1 for line in body if line.strip() and not line.strip().startswith('#'))


def function_violations(path):
    source = path.read_text(encoding='utf-8-sig')
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            size = code_line_count(node, lines)
            if size > LIMIT:
                yield size, node.name, node.lineno


def main():
    root = Path(__file__).resolve().parents[1]
    violations = []
    for path in iter_target_files(root):
        for size, name, lineno in function_violations(path):
            violations.append((str(path.relative_to(root)), lineno, name, size))
    if not violations:
        print('SCP function size check passed.')
        return 0
    for rel, lineno, name, size in sorted(violations):
        print(f'{rel}:{lineno} {name} has {size} code lines')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
