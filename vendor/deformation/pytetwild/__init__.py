"""Wrapper for fTetWild."""


# start delvewheel patch
def _delvewheel_patch_1_13_0():
    import os
    if os.path.isdir(libs_dir := os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'pytetwild.libs'))):
        os.add_dll_directory(libs_dir)


_delvewheel_patch_1_13_0()
del _delvewheel_patch_1_13_0
# end delvewheel patch

from . import _accessor as _accessor
from .pytetwild import tetrahedralize, tetrahedralize_csg, tetrahedralize_pv  # noqa: F401

try:
    # Written by setuptools-scm at build time
    from ._version import version as __version__
except ImportError:  # pragma: no cover
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("pytetwild")
    except PackageNotFoundError:
        __version__ = "unknown"
