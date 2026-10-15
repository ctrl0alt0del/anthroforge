"""Transport fixture: a distinct strategy identity delegating unchanged numerics."""
from dataclasses import replace
from core.warm_start.strategy_current import CurrentTopologyStrategy


class TransportStrategy:
    name, version = "transport_fixture", 1

    def solve(self, context):
        candidate = CurrentTopologyStrategy().solve(context)
        return replace(candidate, diagnostics={**candidate.diagnostics,
            "transport_fixture": True, "received_before_skin": context.before_skin is not None})


STRATEGY = TransportStrategy()
