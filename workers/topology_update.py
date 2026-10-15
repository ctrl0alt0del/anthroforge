"""Common worker boundary for selectable, connectivity-preserving updates."""
from dataclasses import asdict
from pathlib import Path
from core.warm_start.job import atomic_json
from core.warm_start.strategy_model import TopologyUpdateContext
from core.warm_start.strategy_pipeline import require_rebuild_allowed, run_topology_strategy
from core.warm_start.strategy_registry import resolve_strategy, update_options


def options_for(spec):
    return update_options(getattr(spec, "topology_update", None) if spec is not None else None)


def preflight(spec, decision):
    options = options_for(spec)
    resolve_strategy(options)
    if decision.topology_rebuild:
        require_rebuild_allowed(options)


def attempt_update(spec, capture, skin, old, decision, skin_type, before_skin=None, sources=()):
    options = options_for(spec)
    if decision.topology_rebuild or old is None:
        require_rebuild_allowed(options)
        return None
    context = _context(spec, capture, skin, old, skin_type, before_skin, sources)
    outcome = run_topology_strategy(context, options)
    record_outcome(spec, outcome.diagnostics)
    if outcome.result is None:
        require_rebuild_allowed(options, outcome.diagnostics)
    return outcome.result


def _context(spec, capture, skin, old, skin_type, before_skin, sources):
    from core.draft_skin.resources import worker_memory_limit
    cancelled = (lambda: Path(spec.cancel_path).exists()) if spec is not None else None
    return TopologyUpdateContext(old, before_skin, skin, capture, skin_type,
        after_sources=tuple(sources), memory_budget=worker_memory_limit(), cancelled=cancelled)


def record_outcome(spec, diagnostics):
    if spec is not None:
        atomic_json(Path(spec.job_dir) / "topology_strategy.json", diagnostics)


def augment_summary(spec, summary):
    import json
    path = Path(spec.job_dir) / "topology_strategy.json"
    from workers.stage_results import read
    summary["issues"] = [row for stage in read(spec).values() for row in stage.get("issues", ())]
    summary["topology_update_options"] = asdict(options_for(spec))
    if path.exists():
        summary["topology_strategy"] = json.loads(path.read_text(encoding="utf-8"))
        if summary["topology_strategy"]["status"] == "REJECTED":
            summary["fallback_diagnostic"] = summary["topology_strategy"]["message"]
    return summary


def annotate_rebuild(spec, result):
    metadata = augment_summary(spec, {}) if spec is not None else {}
    result.statistics["topology_update_options"] = metadata.get("topology_update_options", {})
    if "topology_strategy" in metadata:
        result.statistics["topology_strategy"] = metadata["topology_strategy"]
    return result
