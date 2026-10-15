import ctypes
import os


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("load", ctypes.c_ulong),
        ("total_phys", ctypes.c_ulonglong),
        ("avail_phys", ctypes.c_ulonglong),
        ("total_page", ctypes.c_ulonglong),
        ("avail_page", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("avail_virtual", ctypes.c_ulonglong),
        ("avail_extended", ctypes.c_ulonglong),
    ]


def available_memory():
    if os.name == "nt":
        return _windows_available()
    return _posix_available()


def _windows_available():
    status = _MemoryStatus()
    status.length = ctypes.sizeof(status)
    return int(status.avail_phys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0


def _posix_available():
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, ValueError, OSError):
        return 4 * 1024**3


def worker_memory_limit():
    available = available_memory() or (4 * 1024**3)
    return int(min(4 * 1024**3, available * 0.35))


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_ulong), ('page_faults', ctypes.c_ulong)]
    _fields_ += [(name, ctypes.c_size_t) for name in ('peak_resident', 'resident', 'peak_paged_pool',
        'paged_pool', 'peak_nonpaged_pool', 'nonpaged_pool', 'private', 'peak_private')]


def memory_metrics():
    if os.name != 'nt':
        return {}
    counters = _ProcessMemoryCounters(); counters.cb = ctypes.sizeof(counters)
    process = ctypes.WinDLL('kernel32').GetCurrentProcess; process.restype = ctypes.c_void_p
    query = ctypes.WinDLL('psapi').GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessMemoryCounters), ctypes.c_ulong]
    if not query(process(), ctypes.byref(counters), counters.cb):
        raise OSError('Cannot read draft-skin worker memory usage.')
    return {'worker_peak_resident_bytes': int(counters.peak_resident),
            'worker_resident_bytes': int(counters.resident), 'worker_peak_private_bytes': int(counters.peak_private)}
