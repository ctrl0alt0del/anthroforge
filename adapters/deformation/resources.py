"""OS-enforced memory ceiling for each native deformation service on Windows."""
import ctypes as C
from ...core.draft_skin.resources import available_memory


class Basic(C.Structure):
    _fields_ = [("process_time",C.c_int64),("job_time",C.c_int64),("flags",C.c_uint32),
        ("minimum",C.c_size_t),("maximum",C.c_size_t),("processes",C.c_uint32),
        ("affinity",C.c_size_t),("priority",C.c_uint32),("scheduling",C.c_uint32)]


class Limits(C.Structure):
    _fields_ = [("basic",Basic),("io",C.c_uint64*6),("process_memory",C.c_size_t),
        ("job_memory",C.c_size_t),("peak_process",C.c_size_t),("peak_job",C.c_size_t)]


def api():
    lib = C.WinDLL("kernel32",use_last_error=True)
    lib.CreateJobObjectW.argtypes = [C.c_void_p,C.c_wchar_p]; lib.CreateJobObjectW.restype = C.c_void_p
    lib.SetInformationJobObject.argtypes = [C.c_void_p,C.c_int,C.c_void_p,C.c_uint32]
    lib.AssignProcessToJobObject.argtypes = [C.c_void_p,C.c_void_p]
    lib.CloseHandle.argtypes = [C.c_void_p]
    return lib


def enforce(process):
    lib = api(); handle = lib.CreateJobObjectW(None,None)
    limits = Limits(); limits.basic.flags = 0x100|0x2000
    limits.process_memory = int(min(8*1024**3,(available_memory() or 8*1024**3)*.5))
    try:
        if not handle or not lib.SetInformationJobObject(handle,9,C.byref(limits),C.sizeof(limits)):
            raise C.WinError(C.get_last_error())
        if not lib.AssignProcessToJobObject(handle,int(process._handle)): raise C.WinError(C.get_last_error())
        process.deformation_job_handle = handle; process.deformation_memory_limit = limits.process_memory
    except Exception:
        if handle: lib.CloseHandle(handle)
        process.terminate(); raise


def release(process):
    handle = getattr(process,"deformation_job_handle",None)
    if handle: api().CloseHandle(handle); process.deformation_job_handle = None
