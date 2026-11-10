# mypy: disable-error-code="attr-defined,name-defined"
"""The few Win32 calls this project needs, kept apart so the rest stays testable anywhere.

Only imported on Windows. Everything else (what to run, what the exit codes mean) is in
``elevate.py`` and is tested with a fake in place of ``run_elevated``.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
ERROR_CANCELLED = 1223  # the user said no to the UAC prompt


class ElevationFailed(OSError):
    """The elevated process could not be started, or did not finish in time."""


class _ShellExecuteInfo(ctypes.Structure):  # pragma: no cover
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def short_path(path: str) -> str | None:  # pragma: no cover
    """The 8.3 name of an existing folder (``C:\\Users\\ANAMAR~1``), or ``None``."""
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer))
    return buffer.value if 0 < size < len(buffer) else None


def is_admin() -> bool:  # pragma: no cover
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def run_elevated(
    executable: str, parameters: str, timeout_seconds: float
) -> int:  # pragma: no cover
    """Run ``executable`` with the UAC prompt, hidden; wait for it and return its exit code."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb, info.lpFile, info.lpParameters, info.nShow = "runas", executable, parameters, 0
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ElevationFailed(ctypes.get_last_error(), "could not start the elevated process")
    if not info.hProcess:
        raise ElevationFailed(0, "Windows gave no handle to wait for the elevated process")
    try:
        waited = kernel32.WaitForSingleObject(info.hProcess, int(timeout_seconds * 1000))
        if waited == WAIT_TIMEOUT:
            kernel32.TerminateProcess(info.hProcess, 1)  # not left to write after we gave up
            raise ElevationFailed(WAIT_TIMEOUT, "the elevated process did not finish in time")
        if waited != WAIT_OBJECT_0:
            raise ElevationFailed(
                ctypes.get_last_error(), "waiting for the elevated process failed"
            )
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise ElevationFailed(ctypes.get_last_error(), "could not read the exit code")
        return int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)
