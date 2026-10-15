"""Explicit strategy selection, including importable experimental native adapters."""
import importlib
import json
import math
from dataclasses import asdict
from .strategy_model import TopologyUpdateOptions


def update_options(payload=None):
    options = payload if isinstance(payload, TopologyUpdateOptions) else TopologyUpdateOptions(**(payload or {}))
    if options.failure_policy not in {"STOP", "REBUILD"}:
        raise ValueError("Topology failure policy must be STOP or REBUILD.")
    if not options.strategy or type(options.version) is not int or options.version < 1:
        raise ValueError("A topology strategy requires a name and positive integer version.")
    if not isinstance(options.settings, dict):
        raise ValueError("Topology strategy settings must be a JSON object.")
    if options.maximum_surface_error is not None and (not math.isfinite(options.maximum_surface_error)
                                                    or options.maximum_surface_error < 0):
        raise ValueError("Maximum surface error must be a finite, nonnegative scene distance.")
    json.dumps(asdict(options), allow_nan=False)
    return options


def resolve_strategy(options, injected=None):
    options = update_options(options)
    strategy = injected if injected is not None else _load(options)
    if strategy.name != options.strategy or strategy.version != options.version:
        raise ValueError("Topology strategy name/version does not match the requested implementation.")
    if not callable(getattr(strategy, "solve", None)):
        raise ValueError("Topology strategy must implement solve(context).")
    return strategy


def _load(options):
    if options.strategy in {"LE", "FAST"} and not options.module:
        from ..deformation.strategy import FinalSkinStrategy
        return FinalSkinStrategy(options.strategy)
    if options.strategy == "current" and not options.module:
        from .strategy_current import CurrentTopologyStrategy
        return CurrentTopologyStrategy()
    if options.module and options.strategy != "current":
        return importlib.import_module(options.module).STRATEGY
    raise ValueError(f"Topology strategy '{options.strategy}' is unavailable; no fallback was selected.")
