import base64
import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from adapters.draft_skin import vendor
from tools import build_draft_skin_vendor as builder
from workers import draft_skin_worker


def record_row(name, data):
    code = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return [name, "sha256=" + code, str(len(data))]


def fake_wheel(path, corrupt=False):
    files = {"toy.cp311-win_amd64.pyd": b"native", "toy-1.dist-info/METADATA": b"License: MIT",
             "toy-1.dist-info/WHEEL": b"Wheel-Version: 1.0\nTag: cp311-cp311-win_amd64\n"}
    rows = [record_row(name, data) for name, data in files.items()]
    if corrupt:
        rows[0][1] = "sha256=wrong"
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows + [["toy-1.dist-info/RECORD", "", ""]])
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("toy-1.dist-info/RECORD", output.getvalue())


def tiny_bundle(root):
    bundle = root / "bundles" / "win64-cp311-v2"
    bundle.mkdir(parents=True)
    (bundle / "native.pyd").write_bytes(b"native")
    payload = {"schema": 1, "bundle": "win64-cp311-v2", "wheels": [],
               "files": [{"path": "native.pyd", "size": 6,
                          "sha256": hashlib.sha256(b"native").hexdigest()}]}
    data = builder.canonical(payload)
    (bundle / "bundle.json").write_bytes(data)
    (root / "manifest.json").write_text(json.dumps({"bundle": "win64-cp311-v2",
                                        "bundle_lock_sha256": builder.digest(data), "wheels": []}))
    return bundle


class BuildTests(unittest.TestCase):
    def test_wheel_record_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "toy-1-cp311-cp311-win_amd64.whl"
            fake_wheel(wheel)
            builder.extract_wheel(wheel, Path(directory) / "ok", set())
            fake_wheel(wheel, corrupt=True)
            with self.assertRaisesRegex(ValueError, "RECORD hash"):
                builder.extract_wheel(wheel, Path(directory) / "bad", set())

    def test_unsafe_names(self):
        for name in ("../escape", "/absolute", "C:/drive", "bad\\path", "a//b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                builder.safe_name(name)

    def test_source_wheel_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "vendor/draft_skin/wheels/toy-1-cp311-cp311-win_amd64.whl"
            path.parent.mkdir(parents=True)
            fake_wheel(path)
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                builder.verify_wheel_source(root, {"file": path.name, "sha256": "0" * 64})

    def test_refresh_requires_version_bump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tiny_bundle(root)
            source = root / "vendor/draft_skin"
            source.mkdir(parents=True)
            (source / "manifest.json").write_bytes((root / "manifest.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "Bump bundle version"):
                builder.build_bundle(root, root / "new", refresh_lock=True, previous_bundle="v1")


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.bytecode = sys.dont_write_bytecode
        self.root = Path(self.temporary.name)
        self.bundle = tiny_bundle(self.root)
        self.enterContext(mock.patch.object(sys, "path_hooks", list(sys.path_hooks)))
        self.enterContext(mock.patch.dict(sys.path_importer_cache))
        self.vendor_patch = mock.patch.multiple(vendor, VENDOR_ROOT=self.root,
                                                MANIFEST_PATH=self.root / "manifest.json")
        self.vendor_patch.start()
        self._mock_import_checks()

    def _mock_import_checks(self):
        self.runtime_fn = vendor._runtime
        self.runtime_patch = mock.patch.object(vendor, "_runtime")
        self.runtime_patch.start()
        self.preloaded_fn = vendor._preloaded
        self.preloaded_patch = mock.patch.object(vendor, "_preloaded")
        self.preloaded_patch.start()

    def tearDown(self):
        sys.path[:] = [item for item in sys.path if item != str(self.bundle)]
        sys.dont_write_bytecode = self.bytecode
        self.preloaded_patch.stop()
        self.runtime_patch.stop()
        self.vendor_patch.stop()
        self.temporary.cleanup()

    def test_success_is_read_only_and_idempotent(self):
        before = sys.dont_write_bytecode
        try:
            self.assertEqual(vendor.ensure_worker_dependencies(), self.bundle)
            self.assertEqual(vendor.ensure_worker_dependencies(), self.bundle)
            self.assertEqual(sys.path.count(str(self.bundle)), 1)
            self.assertTrue(sys.dont_write_bytecode)
            self.assertEqual({p.name for p in self.bundle.iterdir()}, {"native.pyd", "bundle.json"})
        finally:
            sys.dont_write_bytecode = before

    def test_missing_corrupt_extra_leave_path_unchanged(self):
        before = list(sys.path)
        (self.bundle / "native.pyd").write_bytes(b"damage")
        with self.assertRaisesRegex(RuntimeError, "checksum failed"):
            vendor.ensure_worker_dependencies()
        self.assertEqual(sys.path, before)
        (self.bundle / "native.pyd").write_bytes(b"native")
        (self.bundle / "extra").write_text("x")
        with self.assertRaisesRegex(RuntimeError, "unexpected files"):
            vendor.ensure_worker_dependencies()
        self.assertEqual(sys.path, before)

    def test_legacy_cache_is_irrelevant(self):
        with mock.patch("tempfile.gettempdir", side_effect=AssertionError("TEMP consulted")):
            self.assertEqual(vendor.ensure_worker_dependencies(), self.bundle)

    def test_missing_bundle_and_manifest_do_not_change_path(self):
        before = list(sys.path)
        with mock.patch.object(vendor, "VENDOR_ROOT", self.root / "absent"):
            with self.assertRaisesRegex(RuntimeError, "bundle is missing"):
                vendor.ensure_worker_dependencies()
        (self.bundle / "bundle.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "manifest checksum failed"):
            vendor.ensure_worker_dependencies()
        self.assertEqual(sys.path, before)

    def test_linked_bundle_file_is_rejected(self):
        source = self.bundle / "native.pyd"
        target = self.root / "external.pyd"
        target.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "linked bundle path"):
            vendor.ensure_worker_dependencies()

    def test_incompatible_runtime_is_rejected(self):
        with mock.patch.object(vendor, "_runtime", wraps=self.runtime_fn):
            with mock.patch.object(vendor.platform, "system", return_value="Linux"):
                with self.assertRaisesRegex(RuntimeError, "Windows x64 bundle"):
                    vendor.ensure_worker_dependencies()

    def test_schema_and_python_abi_are_rejected(self):
        payload = {"schema": 1, "bundle": "win64-cp311-v2", "platform": "win64",
                   "python": [3, 10]}
        source = {"bundle": "win64-cp311-v2"}
        with mock.patch.object(vendor.platform, "system", return_value="Windows"):
            with mock.patch.object(vendor.platform, "machine", return_value="AMD64"):
                with mock.patch.object(vendor, "_host_versions"):
                    with self.assertRaisesRegex(RuntimeError, "CPython 3.11"):
                        self.runtime_fn(source, payload)
                    with self.assertRaisesRegex(RuntimeError, "schema or version"):
                        self.runtime_fn(source, {**payload, "schema": 2})

    def test_host_numpy_mismatch_is_rejected(self):
        bpy = mock.Mock(app=mock.Mock(version=(5, 0, 1)))
        numpy = mock.Mock(__version__="2.0.0")
        with mock.patch.dict(sys.modules, {"bpy": bpy, "numpy": numpy}):
            with self.assertRaisesRegex(RuntimeError, "NumPy version"):
                vendor._host_versions({"blender": [5, 0, 1], "numpy": "1.26.4"})

    def test_preloaded_foreign_package_is_rejected(self):
        alien = mock.Mock(__file__=str(self.root / "alien.py"))
        with mock.patch.object(vendor, "_preloaded", wraps=self.preloaded_fn):
            with mock.patch.dict(sys.modules, {"scipy": alien}):
                with self.assertRaisesRegex(RuntimeError, "conflicting preloaded package"):
                    vendor.ensure_worker_dependencies()

    @unittest.skipUnless(sys.platform == "win32", "Windows path syntax")
    def test_extended_local_bundle_is_idempotent_and_readable(self):
        extended = vendor._io_root(self.bundle)
        self.assertEqual(vendor._io_root(extended), extended)
        self.assertTrue(extended.is_dir())
        self.assertEqual(vendor._actual_files(extended), {"native.pyd", "bundle.json"})
        payload = json.loads((self.bundle / "bundle.json").read_text())
        vendor._verify_files(extended, payload)
        package = mock.Mock(__file__=str(self.bundle / "scipy/__init__.py"))
        with mock.patch.object(vendor, "_preloaded", wraps=self.preloaded_fn):
            with mock.patch.object(vendor, "PACKAGE_ROOTS", ("scipy",)):
                with mock.patch.dict(sys.modules, {"scipy": package}):
                    vendor._preloaded(extended)

    @unittest.skipUnless(sys.platform == "win32", "Windows path syntax")
    def test_unc_bundle_gets_required_extended_unc_prefix(self):
        ordinary = Path(r"\\server\share\anthroforge\vendor")
        extended = Path(r"\\?\UNC\server\share\anthroforge\vendor")
        self.assertEqual(vendor._io_root(ordinary), extended)
        self.assertEqual(vendor._io_root(extended), extended)


class WorkerTests(unittest.TestCase):
    def test_dependency_failure_precedes_bake(self):
        with mock.patch.object(draft_skin_worker, "read_job", return_value=object()):
            with mock.patch.object(draft_skin_worker, "status_writer", return_value=lambda *x: None):
                with mock.patch.object(draft_skin_worker, "ensure_worker_dependencies", side_effect=RuntimeError("missing")):
                    with mock.patch.object(draft_skin_worker, "_bake_and_capture") as bake:
                        with self.assertRaisesRegex(RuntimeError, "missing"):
                            draft_skin_worker.run_job(Path("unused"))
                        bake.assert_not_called()


if __name__ == "__main__":
    unittest.main()
