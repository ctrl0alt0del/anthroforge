"""Versioned maintained native boundary; no Python numerical solver fallback."""
import ctypes as C
from pathlib import Path
from ..native_platform import library_path
import numpy as np

P = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
I = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")


def library():
    path = library_path("native/deformation/af_deformation_v1.dll")
    if not path.is_file():
        raise RuntimeError("Final-skin native library is missing; install the matching AnthroForge package.")
    lib = C.CDLL(str(path))
    if lib.af_ad_version() != 1:
        raise RuntimeError("Incompatible final-skin native capability.")
    declarations(lib)
    return lib


def declarations(lib):
    lib.af_ad_error.restype = C.c_char_p
    lib.af_ad_create.argtypes = [P,C.c_int,I,C.c_int,P,C.c_int,P,C.c_int,P,C.c_int,C.c_int,C.c_double,C.c_char_p]
    lib.af_ad_create.restype = C.c_void_p
    lib.af_ad_destroy.argtypes = [C.c_void_p]
    lib.af_ad_destroy.restype = None
    lib.af_ad_cancel_path.argtypes = [C.c_void_p,C.c_char_p]
    lib.af_ad_solve.argtypes = [C.c_void_p,P,P,P,P]
    lib.af_ad_embedding.argtypes = [C.c_void_p,I,P]
    lib.af_ad_areas.argtypes = [P,C.c_int,I,C.c_int,C.c_int,P]
    lib.af_ad_areas.restype = None


def array(value, integer=False):
    return np.ascontiguousarray(value, np.int32 if integer else np.float64)


class PreparedSolver:
    def __init__(self, reference, settings, cancel_path):
        from .validation import validate_settings
        validate_settings(settings)
        self.lib = library(); self.handle = None; self.reference = reference
        self.settings = settings; self.cancel_path = str(cancel_path)
        self.center = (reference.arrays["vertices"].max(0)+reference.arrays["vertices"].min(0))*.5
        self.scale = float(np.ptp(reference.arrays["vertices"], axis=0).max())
        if self.scale <= 0: raise ValueError("Reference has zero extent.")
        self._prepare()

    def _prepare(self):
        from .disk_cache import restore, retain
        folder = Path(self.cancel_path).parent
        if self.settings.method == "FAST": restore(folder)
        a = self.reference.arrays; settings = self.settings
        v, t = self.normalized(a["proxy_vertices"]), array(a["proxy_tets"], True)
        points, samples = self.normalized(a["vertices"]), self.normalized(a["samples"])
        self.handle = self.lib.af_ad_create(v,len(v),t,len(t),points,len(points),samples,len(samples),
            array(a["sample_weights"]), {"LE":0,"FAST":2}[settings.method], settings.fast_handles,
            settings.constraint_strength, self.cancel_path.encode())
        if not self.handle: raise RuntimeError(self.lib.af_ad_error().decode())
        if settings.method == "FAST": retain(folder)

    def normalized(self, value):
        return array((value-self.center)/self.scale)

    def set_cancel_path(self, path):
        self.cancel_path = str(path)
        self.lib.af_ad_cancel_path(self.handle,self.cancel_path.encode())

    def solve(self, targets):
        targets = self.normalized(targets)
        if targets.shape != self.reference.arrays["samples"].shape or not np.isfinite(targets).all():
            raise ValueError("Invalid current anatomy samples.")
        if not self.handle: raise RuntimeError("Native solver is closed.")
        output = np.empty_like(self.reference.arrays["vertices"], dtype=np.float64)
        predicted = np.empty_like(targets); diagnostics = np.zeros(6)
        if not self.lib.af_ad_solve(self.handle,targets,output,diagnostics,predicted):
            raise RuntimeError(self.lib.af_ad_error().decode())
        if not np.isfinite(output).all(): raise RuntimeError("Nonfinite deformation result.")
        self.last_prediction = predicted*self.scale+self.center
        return output*self.scale+self.center, diagnostics, predicted*self.scale+self.center

    def embedding(self):
        count = len(self.reference.arrays["vertices"])
        ids = np.empty((count,4), np.int32); weights = np.empty((count,4))
        if not self.handle: raise RuntimeError("Native solver is closed.")
        if not self.lib.af_ad_embedding(self.handle,ids,weights):
            raise RuntimeError(self.lib.af_ad_error().decode())
        return ids, weights

    def close(self):
        if self.handle:
            self.lib.af_ad_destroy(self.handle); self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
