"""LE and FAST use the existing selectable topology strategy boundary."""
from dataclasses import replace
from .reference import DeformationSettings
from .native import PreparedSolver
from ..warm_start.strategy_model import TopologyUpdateCandidate


class FinalSkinStrategy:
    version = 1

    def __init__(self, name):
        self.name = name

    def prepare(self, reference, strategy_settings, cancel_path):
        settings = replace(DeformationSettings(**strategy_settings), method=self.name)
        return PreparedSolver(reference, settings, cancel_path)

    def solve(self, context):
        reference = context.deformation_reference
        prepared = context.prepared_solver or self.prepare(reference, context.settings, context.cancel_path)
        try:
            positions, diagnostics, predicted = prepared.solve(context.anatomy_targets)
        finally:
            if context.prepared_solver is None: prepared.close()
        report = dict(iterations=int(diagnostics[0]), residual=float(diagnostics[1]),
            minimum_proxy_j=float(diagnostics[2]), outside_embeddings=int(diagnostics[3]),
            maximum_outside_normalized=float(diagnostics[4]), replay_error=float(diagnostics[5]),
            iteration_limit_reached=bool(self.name == "FAST" and diagnostics[0] >= 80))
        return TopologyUpdateCandidate(positions, reference.arrays["vertex_ids"], None, None,
                                       diagnostics=report)
