import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path
import tempfile
import numpy as np
from core.topology.model import TopologyResult
from core.warm_start.strategy_model import TopologyUpdateContext, TopologyUpdateOptions
from core.warm_start.strategy_pipeline import run_topology_strategy
from core.warm_start.strategy_registry import resolve_strategy
from tests.unit.test_deformation_reference import reference


def context():
    ref = reference(); a = ref.arrays
    old = TopologyResult(a["vertices"],a["quads"],np.zeros(1,np.int32),np.full(1,-1,np.int32))
    return TopologyUpdateContext(old,None,None,None,"deformed",deformation_reference=ref,
        anatomy_targets=a["samples"]+.1,contact_projection=lambda ctx,result:result)


class FinalDeformationPipelineTests(unittest.TestCase):
    def test_final_strategy_requires_neither_draft_nor_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            ctx = replace(context(),cancel_path=str(Path(folder)/"cancel"))
            with patch("core.deformation.pipeline.check_result",side_effect=lambda result,cancel:result):
                outcome = run_topology_strategy(ctx,TopologyUpdateOptions(strategy="LE",failure_policy="STOP"))
        self.assertIsNotNone(outcome.result,outcome.diagnostics)
        np.testing.assert_allclose(outcome.result.vertices,ctx.anatomy_targets,atol=1e-8)
        np.testing.assert_array_equal(outcome.result.quads,ctx.topology.quads)
        self.assertIsNone(outcome.result.skin_binding)

    def test_no_rebuild_and_no_missing_contact_substitution(self):
        outcome = run_topology_strategy(context(),TopologyUpdateOptions(strategy="LE"))
        self.assertIsNone(outcome.result)
        self.assertIn("rebuilding is forbidden",outcome.diagnostics["message"])
        ctx = replace(context(),contact_projection=None)
        outcome = run_topology_strategy(ctx,TopologyUpdateOptions(strategy="LE",failure_policy="STOP"))
        self.assertIsNone(outcome.result)
        self.assertIn("contact preparation",outcome.diagnostics["message"])

    def test_explicit_native_strategy_selection(self):
        for method in ("LE","FAST"):
            self.assertEqual(resolve_strategy(TopologyUpdateOptions(strategy=method)).name,method)
