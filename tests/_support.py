from pathlib import Path
import sys
import types


def addon_root():
    return Path(__file__).resolve().parents[1]


def import_root():
    return addon_root().parent


def package_name():
    return addon_root().name


def ensure_import_path():
    root = str(import_root())
    if root not in sys.path:
        sys.path.insert(0, root)


class FakeVector(tuple):
    def __new__(cls, values=(0.0, 0.0, 0.0)):
        return super().__new__(cls, tuple(values))


def install_fake_mathutils():
    if "mathutils" not in sys.modules:
        sys.modules["mathutils"] = types.SimpleNamespace(Vector=FakeVector)


def install_fake_bpy():
    if "bpy" in sys.modules:
        return sys.modules["bpy"]
    bpy = types.SimpleNamespace()
    bpy.data = types.SimpleNamespace(objects={})
    bpy.context = types.SimpleNamespace(scene=None)
    sys.modules["bpy"] = bpy
    return bpy


def install_fake_modules():
    install_fake_mathutils()
    return install_fake_bpy()
