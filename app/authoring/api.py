"""Composition root. Call execute(request, root, scene, journal_directory)."""
from pathlib import Path
from .facade import AuthoringInterpreter
from ...core.authoring.storage import FileStore


def execute(request, root, scene, journal_directory=None):
    from ...adapters.authoring.native_scene import BlenderScene
    from ...adapters.authoring.solver import NativeFiberSolver
    from ...adapters.authoring.cached_solver import CachedFiberSolver
    directory = journal_directory or default_directory(root)
    store = FileStore(directory)
    return AuthoringInterpreter(BlenderScene(root, scene), CachedFiberSolver(NativeFiberSolver(), store), store).execute(request)


def default_directory(root):
    import bpy
    recovered = Path(bpy.data.filepath).with_suffix('.authoring') if bpy.data.filepath else None
    if recovered and recovered.is_dir():
        return recovered
    return root.get('af_authoring_journal') or Path.home()/'.anthroforge'/'authoring'
