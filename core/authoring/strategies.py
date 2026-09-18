"""Versioned native construction strategies selected by the composition layer."""
from copy import deepcopy
from dataclasses import dataclass
from .errors import require
from .model import Registry
from .anchor_contract import defaults


@dataclass(frozen=True)
class ConstructionStrategy:
    topology: str

    def compile(self, recipe):
        result = deepcopy(recipe['construction'])
        require(result['kind'] == self.topology, 'STRATEGY_TOPOLOGY_MISMATCH')
        return defaults(result)


def construction_strategies():
    registry = Registry()
    for name in ('fusiform.v1', 'fan.v1', 'strap.v1'):
        registry.add(name, ConstructionStrategy('open_loft'))
    registry.add('loop.v1', ConstructionStrategy('closed_loft'))
    registry.add('branched_loft.v1', BranchedConstructionStrategy())
    return registry


class BranchedConstructionStrategy:
    def compile(self, recipe):
        require(recipe['construction']['kind'] == 'branched_loft', 'STRATEGY_TOPOLOGY_MISMATCH')
        return defaults(deepcopy(recipe['construction']['main']))
