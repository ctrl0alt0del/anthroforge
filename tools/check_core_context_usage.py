import ast
import json
import sys
from pathlib import Path

BASELINE = Path(__file__).with_name("core_context_usage_baseline.json")


def repo_root():
    return Path(__file__).resolve().parents[1]


def iter_core_files(root):
    yield from sorted((root / "core").rglob("*.py"))


def _is_bpy_context(node):
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "context"
        and isinstance(node.value, ast.Name)
        and node.value.id == "bpy"
    )


def context_hits(path, root):
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    rel = str(path.relative_to(root)).replace("\\", "/")
    for node in ast.walk(tree):
        if _is_bpy_context(node):
            segment = ast.get_source_segment(source, node) or "bpy.context"
            yield rel, node.lineno, segment.strip()


def scan_hits(root=None):
    root = repo_root() if root is None else Path(root)
    hits = []
    for path in iter_core_files(root):
        hits.extend(context_hits(path, root))
    return sorted(hits)


def _key(item):
    return f"{item[0]}::{item[2]}"


def _counts(items):
    out = {}
    for item in items:
        out[_key(item)] = out.get(_key(item), 0) + 1
    return out


def _group_lines(items):
    out = {}
    for rel, lineno, segment in items:
        out.setdefault(f"{rel}::{segment}", []).append(lineno)
    return out


def load_baseline(path=BASELINE):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return {str(k): int(v) for k, v in json.loads(text).items()}


def write_baseline(hits, path=BASELINE):
    text = json.dumps(dict(sorted(_counts(hits).items())), indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def ratchet_status(root=None, baseline_path=BASELINE):
    hits = scan_hits(root)
    base = load_baseline(baseline_path)
    lines = _group_lines(hits)
    counts = _counts(hits)
    fresh = {key: lines[key] for key, count in counts.items() if count > base.get(key, 0)}
    legacy = {key: lines[key] for key, count in counts.items() if count <= base.get(key, 0)}
    fixed = sorted(key for key in base if key not in counts)
    return {"hits": hits, "new": fresh, "legacy": legacy, "fixed": fixed, "baseline": base}


def _print_hits(label, items, baseline):
    if not items:
        return
    print(f"{label}:")
    for key, lines in sorted(items.items()):
        current = len(lines)
        print(f"  {key} lines={sorted(lines)} allowed={baseline.get(key, 0)} current={current}")


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
        write_baseline(status["hits"])
        print(f"saved {len(status['baseline']) or len(_counts(status['hits']))} context entries to {BASELINE.name}")
        return 0
    _print_hits("new bpy.context usages in core", status["new"], status["baseline"])
    if status["new"]:
        print(f"legacy usages still tracked: {len(status['legacy'])}")
        return 1
    _print_fixed(status["fixed"])
    print(f"core bpy.context ratchet passed with {len(status['legacy'])} legacy entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
