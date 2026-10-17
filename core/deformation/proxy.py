"""Maintained native tetrahedralization used only when constructing a reference."""
import importlib.util
import os
from pathlib import Path
import numpy as np

_DLL_DIRECTORY = None


def library():
    global _DLL_DIRECTORY
    if os.name != 'nt':
        return linux_library()
    folder = Path(__file__).resolve().parents[2]/"vendor/deformation"
    verify(folder)
    _DLL_DIRECTORY = os.add_dll_directory(str(folder/"pytetwild.libs"))
    spec = importlib.util.spec_from_file_location("PyfTetWildWrapper",folder/"pytetwild/PyfTetWildWrapper.pyd")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def linux_library():
    from ..linux_dependencies import ensure
    folder = ensure() / 'pytetwild'
    paths = list(folder.glob('PyfTetWildWrapper*.so'))
    if len(paths) != 1:
        raise RuntimeError('Linux PyTetWild extension is missing or ambiguous')
    spec = importlib.util.spec_from_file_location('PyfTetWildWrapper', paths[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(folder):
    import hashlib
    import json
    manifest = json.loads((folder/"manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Deformation dependency checksum mismatch; reinstall the matching package.")


def tetrahedralize(points, faces, resolution):
    native = library(); scale = float(np.ptp(points,axis=0).max())
    vertices, tets = native.tetrahedralize_mesh(np.asarray(points,np.float64),np.asarray(faces,np.uint32),
        True,False,.05,scale/resolution,1e-3,10.,False,4,40,3,False,False,False,
        np.empty((0,3)),np.empty((0,4),np.int32),np.empty(0))
    if not len(tets) or not np.isfinite(vertices).all(): raise ValueError("Native proxy preparation produced no usable volume.")
    return dict(vertices=vertices,tets=tets)
