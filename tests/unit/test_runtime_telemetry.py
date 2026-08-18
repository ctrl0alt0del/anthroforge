from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ADDON_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ADDON_ROOT / "core" / "deps" / "runtime_trace.py"
SPEC = importlib.util.spec_from_file_location("runtime_trace_test", MODULE_PATH)
runtime_trace = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime_trace
SPEC.loader.exec_module(runtime_trace)


def request():
    return SimpleNamespace(source="property", event_type="FIBER_UPDATE", quality="INTERACTIVE",
                           full=False, dirty_aspects={"FIBER": {"SOLVER"}}, payload={"cause": "slider"})


class RuntimeTelemetryTests(unittest.TestCase):
    def setUp(self):
        runtime_trace.clear_request_telemetry()

    def test_request_record_collects_bounded_metrics(self):
        with patch.object(runtime_trace, "trace_enabled", return_value=True), \
                patch.object(runtime_trace, "_cache_bytes", side_effect=(8, 13)):
            record = runtime_trace.begin_request_telemetry(request(), 12.5)
            runtime_trace.record_request_phases(build=1.0, sync=2.0)
            runtime_trace.telemetry_count("fiber_solves", 1)
            runtime_trace.telemetry_count("fiber_iterations", 7)
            runtime_trace.telemetry_count("fiber_collision_queries", 9)
            runtime_trace.telemetry_count("fiber_writes", 2)
            runtime_trace.telemetry_timing("fiber_curve_update", 0.4)
            runtime_trace.telemetry_slice(13.0, "LOCAL_STEP")
            runtime_trace.finish_request_telemetry(record, 4.0)
        saved = runtime_trace.request_telemetry()[0]
        self.assertEqual((saved["cause"], saved["aspects"]), ("slider", {"FIBER": ["SOLVER"]}))
        self.assertEqual((saved["solves"], saved["iterations"], saved["collision_queries"], saved["writes"]), (1, 7, 9, 2))
        self.assertEqual((saved["cache_delta_bytes"], saved["progressive_slices"]["histogram"]), (5, {"<=16": 1}))

    def test_records_are_disabled_and_bounded(self):
        with patch.object(runtime_trace, "trace_enabled", return_value=False):
            self.assertIsNone(runtime_trace.begin_request_telemetry(request()))
        with patch.object(runtime_trace, "trace_enabled", return_value=True), \
                patch.object(runtime_trace, "_cache_bytes", return_value=0):
            for index in range(runtime_trace._TELEMETRY_MAX_RECORDS + 3):
                record = runtime_trace.begin_request_telemetry(request(), index)
                runtime_trace.finish_request_telemetry(record)
        records = runtime_trace.request_telemetry()
        self.assertEqual((len(records), records[0]["queue_ms"]), (runtime_trace._TELEMETRY_MAX_RECORDS, 3.0))

    def test_finished_record_accepts_detached_progressive_metrics(self):
        with patch.object(runtime_trace, "telemetry_enabled", return_value=True), \
                patch.object(runtime_trace, "_cache_bytes", return_value=0):
            record = runtime_trace.begin_request_telemetry(request())
            runtime_trace.finish_request_telemetry(record)
            previous = runtime_trace.activate_request_telemetry(record)
            runtime_trace.telemetry_count("fiber_iterations", 3)
            runtime_trace.telemetry_collision_query(4)
            runtime_trace.telemetry_slice(18.0, "ACCEPT")
            runtime_trace.restore_request_telemetry(previous)
        saved = runtime_trace.request_telemetry()[0]
        self.assertEqual((saved["iterations"], saved["collision_queries"], saved["progressive_slices"]["count"]), (3, 4, 1))

    def test_engine_telemetry_records_production_and_backend_versions(self):
        selection = SimpleNamespace(requested="V2", actual="V2", source="DEFAULT",
                                    fallback_reason="", error="")
        record = {}
        runtime_trace.telemetry_fiber_engine(selection, 1, record, "prod-1", "native-1")
        row = record["fiber_engines"][0]
        self.assertEqual((row["engine_version"], row["backend_version"]), ("prod-1", "native-1"))


if __name__ == "__main__":
    unittest.main()
