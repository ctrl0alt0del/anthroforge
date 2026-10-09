import hashlib
import importlib
import json
import os
import py_compile
import sys
import tempfile
import unittest
from contextlib import ExitStack
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

from adapters.draft_skin import vendor
from tests.unit.test_draft_skin_vendor_package import tiny_bundle
from tools import build_draft_skin_vendor as builder


def add_sources(bundle):
    package = bundle / "af_vendor_fixture"
    package.mkdir()
    (package / "__init__.py").write_text("from .child import VALUE\n")
    (package / "child.py").write_text("VALUE = 'source'\n")
    payload = json.loads((bundle / "bundle.json").read_text())
    for path in package.glob("*.py"):
        payload["files"].append(dict(path=path.relative_to(bundle).as_posix(),
                                    size=path.stat().st_size, sha256=builder.digest(path.read_bytes())))
    data = builder.canonical(payload)
    (bundle / "bundle.json").write_bytes(data)
    manifest = bundle.parents[1] / "manifest.json"
    values = json.loads(manifest.read_text())
    manifest.write_text(json.dumps(dict(values, bundle_lock_sha256=builder.digest(data))))


def poisoned_cache(source):
    source.write_text("VALUE = 'cached'\n")
    timestamp = source.stat()
    cache = Path(py_compile.compile(str(source), doraise=True))
    source.write_text("VALUE = 'source'\n")
    os.utime(source, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    return cache


def fingerprints(bundle):
    return {p.relative_to(bundle).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in bundle.rglob("*") if p.is_file()}


class BytecodeTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.bundle = tiny_bundle(self.root)
        add_sources(self.bundle)
        self.stack.enter_context(mock.patch.multiple(vendor, VENDOR_ROOT=self.root,
                                 MANIFEST_PATH=self.root / "manifest.json"))
        for name in ("_runtime", "_preloaded"):
            self.stack.enter_context(mock.patch.object(vendor, name))
        self.stack.enter_context(mock.patch.object(sys, "path_hooks", list(sys.path_hooks)))
        self.stack.enter_context(mock.patch.object(sys, "path", list(sys.path)))
        self.stack.enter_context(mock.patch.object(sys, "dont_write_bytecode", False))
        self.stack.enter_context(mock.patch.object(sys, "pycache_prefix", None))
        self.stack.enter_context(mock.patch.dict(sys.path_importer_cache))
        self.stack.enter_context(mock.patch.dict(sys.modules))

    def cache(self, name, data=b"untrusted cache"):
        path = self.bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_generated_cache_variants_are_read_only_and_repeatable(self):
        for suffix in ("cpython-311", "cpython-311.opt-1", "cpython-311.opt-2", "cpython-312"):
            self.cache(f"af_vendor_fixture/__pycache__/child.{suffix}.pyc")
        before = fingerprints(self.bundle)
        hooks = len(sys.path_hooks)
        vendor.ensure_worker_dependencies()
        vendor.ensure_worker_dependencies()
        self.assertEqual(len(sys.path_hooks), hooks + 1)
        self.assertEqual(importlib.import_module("af_vendor_fixture").VALUE, "source")
        self.assertEqual(before, fingerprints(self.bundle))

    def test_valid_but_unverified_bytecode_is_never_executed(self):
        source = self.bundle / "af_vendor_fixture/child.py"
        poisoned_cache(source)
        namespace = {}
        exec(SourceFileLoader("probe", str(source)).get_code("probe"), namespace)
        self.assertEqual(namespace["VALUE"], "cached")
        before = fingerprints(self.bundle)
        vendor.ensure_worker_dependencies()
        self.assertEqual(importlib.import_module("af_vendor_fixture").VALUE, "source")
        self.assertEqual(before, fingerprints(self.bundle))

    def test_orphan_cache_and_unexpected_executables_are_rejected(self):
        for name in ("ghost.cpython-311.pyc", "child.py", "child.pyd", "child.pyc"):
            with self.subTest(name=name):
                path = self.cache("af_vendor_fixture/__pycache__/" + name)
                before = list(sys.path)
                with self.assertRaisesRegex(RuntimeError, "unexpected files.*" + name):
                    vendor.ensure_worker_dependencies()
                self.assertEqual(sys.path, before)
                path.unlink()

    def test_cache_cannot_mask_missing_source(self):
        self.cache("af_vendor_fixture/__pycache__/child.cpython-311.pyc")
        (self.bundle / "af_vendor_fixture/child.py").unlink()
        with self.assertRaisesRegex(RuntimeError, r"missing files \(1\): af_vendor_fixture/child.py"):
            vendor.ensure_worker_dependencies()

    def test_cache_cannot_mask_altered_source(self):
        self.cache("af_vendor_fixture/__pycache__/child.cpython-311.pyc")
        (self.bundle / "af_vendor_fixture/child.py").write_text("VALUE = 'damage'\n")
        with self.assertRaisesRegex(RuntimeError, "checksum failed: af_vendor_fixture/child.py"):
            vendor.ensure_worker_dependencies()

    def test_linked_cache_is_rejected(self):
        path = self.cache("af_vendor_fixture/__pycache__/child.cpython-311.pyc")
        path.unlink()
        path.symlink_to(self.bundle / "native.pyd")
        with self.assertRaisesRegex(RuntimeError, "linked bundle path"):
            vendor.ensure_worker_dependencies()

    def test_source_hook_does_not_intercept_other_packages(self):
        vendor.ensure_worker_dependencies()
        with self.assertRaises(ImportError):
            sys.path_hooks[0](str(self.root / "outside"))


if __name__ == "__main__":
    unittest.main()
