from dataclasses import dataclass, field


@dataclass
class ConflictContext:
    entity_type: str
    entity_id: str
    aspect: str
    source: str
    current: object
    incoming: object
    payload: dict = field(default_factory=dict)


_STRATEGIES = {}
_POLICIES = {}
_DEFAULT_POLICY = "last_write_wins"


def _norm_entity_type(entity_type):
    et = str(entity_type or "").strip().upper()
    return et if et else "*"


def _norm_aspect(aspect):
    a = str(aspect or "").strip().lower()
    return a if a else "*"


def _is_blender_source(source):
    s = str(source or "").strip().lower()
    return s.startswith("blender")


def register_conflict_strategy(name, resolver_fn, replace=False):
    key = str(name or "").strip().lower()
    if not key:
        raise ValueError("strategy name is required")
    if key in _STRATEGIES and not bool(replace):
        raise ValueError(f"conflict strategy already registered: {key}")
    if not callable(resolver_fn):
        raise TypeError("resolver_fn must be callable")
    _STRATEGIES[key] = resolver_fn


def list_conflict_strategies():
    return tuple(sorted(_STRATEGIES.keys()))


def set_conflict_policy(strategy, *, entity_type="*", aspect="*"):
    key = str(strategy or "").strip().lower()
    if key not in _STRATEGIES:
        raise KeyError(f"unknown conflict strategy: {key}")
    _POLICIES[(_norm_entity_type(entity_type), _norm_aspect(aspect))] = key


def clear_conflict_policies():
    _POLICIES.clear()


def get_conflict_policy(*, entity_type="*", aspect="*"):
    et = _norm_entity_type(entity_type)
    asp = _norm_aspect(aspect)
    for k in (
        (et, asp),
        (et, "*"),
        ("*", asp),
        ("*", "*"),
    ):
        if k in _POLICIES:
            return _POLICIES[k]
    return _DEFAULT_POLICY


def list_conflict_policies():
    out = []
    for (et, asp), strat in sorted(_POLICIES.items()):
        out.append({"entity_type": et, "aspect": asp, "strategy": strat})
    return out


def _resolve_by_name(strategy_name, ctx):
    fn = _STRATEGIES.get(str(strategy_name or "").strip().lower())
    if fn is None:
        fn = _STRATEGIES[_DEFAULT_POLICY]
    return fn(ctx)


def resolve_conflict(*, entity_type, entity_id, aspect, source, current, incoming, payload=None):
    ctx = ConflictContext(
        entity_type=_norm_entity_type(entity_type),
        entity_id=str(entity_id or ""),
        aspect=_norm_aspect(aspect),
        source=str(source or "unknown"),
        current=current,
        incoming=incoming,
        payload=dict(payload or {}),
    )
    policy = get_conflict_policy(entity_type=ctx.entity_type, aspect=ctx.aspect)
    return _resolve_by_name(policy, ctx)


def _strategy_last_write_wins(ctx):
    return ctx.incoming


def _strategy_prefer_domain(ctx):
    if _is_blender_source(ctx.source):
        return ctx.current if ctx.current is not None else ctx.incoming
    return ctx.incoming


def _strategy_prefer_blender(ctx):
    if _is_blender_source(ctx.source):
        return ctx.incoming
    return ctx.current if ctx.current is not None else ctx.incoming


def _strategy_merge_dict_shallow(ctx):
    cur = ctx.current
    inc = ctx.incoming
    if isinstance(cur, dict) and isinstance(inc, dict):
        out = dict(cur)
        out.update(dict(inc))
        return out
    if isinstance(inc, dict):
        return dict(inc)
    if inc is None:
        return cur
    return inc


register_conflict_strategy("last_write_wins", _strategy_last_write_wins, replace=True)
register_conflict_strategy("prefer_domain", _strategy_prefer_domain, replace=True)
register_conflict_strategy("prefer_blender", _strategy_prefer_blender, replace=True)
register_conflict_strategy("merge_dict_shallow", _strategy_merge_dict_shallow, replace=True)
set_conflict_policy("last_write_wins", entity_type="*", aspect="*")

