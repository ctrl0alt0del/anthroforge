import ast
import json
import sys
from pathlib import Path

LIMIT = 15
BASELINE = Path(__file__).with_name("function_size_baseline.json")
EXCLUDED = {"backup", "tests", "__pycache__", ".git", ".codex", ".agents",
            "artifacts", ".artifacts", "dist", "build", "venv", ".env", ".worktrees"}


def repo_root():
    return Path(__file__).resolve().parents[1]


def iter_target_files(root):
    for path in root.rglob("*.py"):
        if not EXCLUDED.intersection(path.parts):
            yield path


def iter_defs(tree, parents=()):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            trail = parents + (node.name,)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node, ".".join(trail)
            yield from iter_defs(node, trail)


def code_line_count(node, lines):
    if not getattr(node, "body", None):
        return 0
    body = lines[node.body[0].lineno - 1 : node.body[-1].end_lineno]
    return sum(1 for line in body if line.strip() and not line.strip().startswith("#"))


def function_violations(path, root):
    source = path.read_text(encoding="utf-8-sig")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    rel = str(path.relative_to(root)).replace("\\", "/")
    for node, name in iter_defs(tree):
        size = code_line_count(node, lines)
        if size > LIMIT:
            yield rel, node.lineno, name, size


def scan_violations(root=None):
    root = repo_root() if root is None else Path(root)
    hits = []
    for path in iter_target_files(root):
        hits.extend(function_violations(path, root))
    return sorted(hits)


def _key(item):
    return f"{item[0]}::{item[2]}"


def load_baseline(path=BASELINE):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return {str(k): int(v) for k, v in json.loads(text).items()}


def write_baseline(violations, path=BASELINE):
    data = {_key(item): item[3] for item in violations}
    text = json.dumps(dict(sorted(data.items())), indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def ratchet_status(root=None, baseline_path=BASELINE):
    hits = scan_violations(root)
    base = load_baseline(baseline_path)
    keys = {_key(item) for item in hits}
    fresh = [item for item in hits if _key(item) not in base]
    grown = [item for item in hits if base.get(_key(item), item[3]) < item[3]]
    legacy = [item for item in hits if _key(item) in base and item[3] <= base[_key(item)]]
    fixed = sorted(key for key in base if key not in keys)
    return {"violations": hits, "new": fresh, "grown": grown, "legacy": legacy, "fixed": fixed}


def _print_items(label, items):
    if not items:
        return
    print(f"{label}:")
    for rel, lineno, name, size in items:
        print(f"  {rel}:{lineno} {name} has {size} code lines")


def _print_fixed(items):
    if not items:
        return
    print("resolved since baseline:")
    for key in items:
        print(f"  {key}")


def main(argv=None):
    args = set(sys.argv[1:] if argv is None else argv)
    status = ratchet_status()
    if "--update-baseline" in args:
        write_baseline(status["violations"])
        print(f"saved {len(status['violations'])} function-size violations to {BASELINE.name}")
        return 0
    _print_items("new violations", status["new"])
    _print_items("grown violations", status["grown"])
    if status["new"] or status["grown"]:
        print(f"legacy violations still tracked: {len(status['legacy'])}")
        return 1
    _print_fixed(status["fixed"])
    print(f"function-size ratchet passed with {len(status['legacy'])} legacy violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
