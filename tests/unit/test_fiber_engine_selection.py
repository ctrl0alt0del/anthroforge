import unittest

from core.vcp.fiber_engine_selection import (FiberEngineKind, resolve_fiber_engine,
                                             select_fiber_engine)


class FiberEngineSelectionTests(unittest.TestCase):
    def test_default_requests_v3(self):
        value = resolve_fiber_engine(environ={})
        self.assertEqual((value.requested, value.actual, value.source),
                         (FiberEngineKind.V3, FiberEngineKind.V3, "DEFAULT"))

    def test_environment_selects_exact_engines(self):
        for raw, expected in (("V1", FiberEngineKind.V1), ("V2", FiberEngineKind.V2),
                              ("V3", FiberEngineKind.V3)):
            with self.subTest(raw=raw):
                value = resolve_fiber_engine(environ={"AF_FIBER_ENGINE": raw})
                self.assertEqual((value.requested, value.actual, value.source),
                                 (expected, expected, "ENVIRONMENT"))

    def test_explicit_selection_has_precedence(self):
        value = resolve_fiber_engine("V2", {"AF_FIBER_ENGINE": "V1"})
        self.assertEqual((value.actual, value.source), (FiberEngineKind.V2, "EXPLICIT"))

    def test_invalid_value_fails_closed(self):
        value = resolve_fiber_engine(environ={"AF_FIBER_ENGINE": "AUTO"})
        self.assertFalse(value.valid)
        self.assertIn("expected V1, V2, or V3", value.error)

    def test_selector_values_are_exact(self):
        for raw in ("v2", " V2", "V2 "):
            self.assertFalse(resolve_fiber_engine(environ={"AF_FIBER_ENGINE": raw}).valid)

    def test_loop_uses_explicit_compatibility_fallback(self):
        value = select_fiber_engine("CYCLIC", environ={})
        self.assertEqual((value.requested, value.actual, value.fallback_reason),
                         (FiberEngineKind.V3, FiberEngineKind.V1,
                          "V3_TOPOLOGY_COMPATIBILITY"))

    def test_v1_override_is_global(self):
        value = select_fiber_engine("CYCLIC", environ={"AF_FIBER_ENGINE": "V1"})
        self.assertEqual((value.actual, value.fallback_reason), (FiberEngineKind.V1, ""))

    def test_v3_loop_uses_explicit_compatibility_fallback(self):
        value = select_fiber_engine("CYCLIC", environ={"AF_FIBER_ENGINE": "V3"})
        self.assertEqual((value.actual, value.fallback_reason),
                         (FiberEngineKind.V1, "V3_TOPOLOGY_COMPATIBILITY"))
