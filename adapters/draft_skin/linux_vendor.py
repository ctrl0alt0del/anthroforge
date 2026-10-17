"""Linux host checks; Windows dependency validation remains unchanged."""
import sys
try:
    from ...core.linux_dependencies import ensure as packages
except ImportError:
    from core.linux_dependencies import ensure as packages


def ensure():
    bpy = sys.modules.get('bpy')
    if bpy is not None and tuple(bpy.app.version) != (5, 0, 1):
        raise RuntimeError('Linux geometry bundle requires Blender 5.0.1')
    import numpy
    if numpy.__version__ != '1.26.4':
        raise RuntimeError('Linux geometry bundle requires NumPy 1.26.4')
    return packages()
