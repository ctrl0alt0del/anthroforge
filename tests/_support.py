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

    def copy(self):
        return FakeVector(self)


class FakeMatrix(tuple):
    def __new__(cls, values=()):
        return super().__new__(cls, tuple(values))

    def __matmul__(self, other):
        return other

    def copy(self):
        return FakeMatrix(self)

    def inverted(self):
        return self

    def to_3x3(self):
        return self

    def to_quaternion(self):
        return FakeQuaternion()

    def to_scale(self):
        return FakeVector((1.0, 1.0, 1.0))

    def normalized(self):
        return self

    @staticmethod
    def Diagonal(values):
        return FakeMatrix(values)

    @staticmethod
    def Translation(values):
        return FakeMatrix(values)

    @staticmethod
    def LocRotScale(location, rotation, scale):
        return FakeMatrix((location, rotation, scale))


class FakeQuaternion(tuple):
    def __new__(cls, axis=(0.0, 0.0, 1.0), angle=0.0):
        return super().__new__(cls, (axis, angle))

    def __matmul__(self, other):
        return other

    def to_matrix(self):
        return FakeMatrix()


def install_fake_mathutils():
    if "mathutils" not in sys.modules:
        mathutils = types.ModuleType("mathutils")
        mathutils.Vector = FakeVector
        mathutils.Matrix = FakeMatrix
        mathutils.Quaternion = FakeQuaternion
        bvhtree = types.ModuleType("mathutils.bvhtree")
        bvhtree.BVHTree = type("BVHTree", (), {})
        mathutils.bvhtree = bvhtree
        sys.modules["mathutils"] = mathutils
        sys.modules["mathutils.bvhtree"] = bvhtree


def install_fake_bpy():
    if "bpy" in sys.modules:
        return sys.modules["bpy"]
    bpy = types.ModuleType("bpy")
    bpy.data = types.SimpleNamespace(objects={})
    bpy.context = types.SimpleNamespace(scene=None)
    handlers = types.ModuleType("bpy.app.handlers")
    handlers.load_post, handlers.depsgraph_update_post = [], []
    handlers.load_pre, handlers.undo_pre, handlers.redo_pre = [], [], []
    handlers.persistent = lambda fn: fn
    app = types.ModuleType("bpy.app")
    app.handlers = handlers
    app.timers = types.SimpleNamespace(register=lambda *a, **k: None, is_registered=lambda fn: False, unregister=lambda fn: None)
    bpy.app = app
    sys.modules["bpy"] = bpy
    sys.modules["bpy.app"] = app
    sys.modules["bpy.app.handlers"] = handlers
    return bpy


def install_fake_modules():
    install_fake_mathutils()
    install_fake_bmesh()
    install_fake_bpy_extras()
    return install_fake_bpy()


def install_fake_bmesh():
    if "bmesh" in sys.modules:
        return sys.modules["bmesh"]
    module = types.ModuleType("bmesh")
    module.types = types.SimpleNamespace(BMVert=type("BMVert", (), {}))
    module.from_edit_mesh = lambda data: types.SimpleNamespace(verts=[], select_history=[], verts_ensure_lookup_table=lambda: None)
    sys.modules["bmesh"] = module
    return module


def install_fake_bpy_extras():
    if "bpy_extras" in sys.modules:
        return sys.modules["bpy_extras"]
    module = types.ModuleType("bpy_extras")
    module.view3d_utils = types.SimpleNamespace(
        location_3d_to_region_2d=lambda *args, **kwargs: None,
        region_2d_to_location_3d=lambda *args, **kwargs: FakeVector(),
    )
    io_utils = types.ModuleType("bpy_extras.io_utils")
    io_utils.ImportHelper = type("ImportHelper", (), {})
    module.io_utils = io_utils
    sys.modules["bpy_extras"] = module
    sys.modules["bpy_extras.io_utils"] = io_utils
    return module
