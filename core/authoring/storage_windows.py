"""Optional transparent NTFS compression; logical file contents never change."""
import ctypes
import os
from ctypes import wintypes
from functools import lru_cache


@lru_cache(maxsize=1)
def kernel():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetCompressedFileSizeW.restype = wintypes.DWORD
    return api


def compressed_size(path):
    if os.name != 'nt':
        return path.stat().st_size
    api, high = kernel(), wintypes.DWORD()
    ctypes.set_last_error(0)
    low = api.GetCompressedFileSizeW(str(path), ctypes.byref(high))
    if low == 0xffffffff and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    return (high.value << 32) | low


def compress(path, force=False):
    if os.name != 'nt' or (path.stat().st_file_attributes & 0x800 and not force):
        return False
    api = kernel()
    handle = api.CreateFileW(str(path), 0xc0000000, 7, None, 3, 0x02000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if force: set_compression(api, handle, 0)
        set_compression(api, handle)
    finally:
        api.CloseHandle(handle)
    return True


def set_compression(api, handle, value=1):
    mode, returned = ctypes.c_ushort(value), wintypes.DWORD()
    if not api.DeviceIoControl(handle, 0x9c040, ctypes.byref(mode), 2,
                               None, 0, ctypes.byref(returned), None):
        raise ctypes.WinError(ctypes.get_last_error())
