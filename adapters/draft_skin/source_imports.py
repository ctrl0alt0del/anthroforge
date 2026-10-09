"""Import verified bundle sources without reading or writing unverified bytecode."""

import sys
from importlib.machinery import (
    EXTENSION_SUFFIXES, SOURCE_SUFFIXES, ExtensionFileLoader, FileFinder, SourceFileLoader,
)
from pathlib import Path


class _SourceOnlyLoader(SourceFileLoader):
    def get_code(self, fullname):
        path = self.get_filename(fullname)
        return self.source_to_code(self.get_data(path), path)


class _BundleSourceHook:
    def __init__(self, root):
        self.bundle_source_root = Path(root).resolve()

    def contains(self, entry):
        return Path(entry).resolve().is_relative_to(self.bundle_source_root)

    def __call__(self, entry):
        if not self.contains(entry):
            raise ImportError(entry)
        return FileFinder(entry, (ExtensionFileLoader, EXTENSION_SUFFIXES),
                          (_SourceOnlyLoader, SOURCE_SUFFIXES))


def enable_source_imports(root):
    hook = _BundleSourceHook(root)
    if any(getattr(item, "bundle_source_root", None) == hook.bundle_source_root for item in sys.path_hooks):
        return
    sys.path_hooks.insert(0, hook)
    for entry in tuple(sys.path_importer_cache):
        if hook.contains(entry):
            sys.path_importer_cache.pop(entry, None)
