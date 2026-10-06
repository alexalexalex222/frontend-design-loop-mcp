"""Standalone Windows invocation host; run by file path with Python -I -S.

Only this process holds the anonymous Job handle. It joins the Job before
creating the target, so even a target that exits immediately cannot orphan its
children. The handle stays open until host exit (closing it kills the host too).
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys

_DWORD = ctypes.c_uint32
_HANDLE = ctypes.c_void_p
_SIZE_T = ctypes.c_size_t
_KILL_ON_JOB_CLOSE = 0x00002000
_EXTENDED_LIMIT_INFORMATION = 9
_HOST_FAILURE = 125


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", _DWORD),
        ("MinimumWorkingSetSize", _SIZE_T),
        ("MaximumWorkingSetSize", _SIZE_T),
        ("ActiveProcessLimit", _DWORD),
        ("Affinity", _SIZE_T),
        ("PriorityClass", _DWORD),
        ("SchedulingClass", _DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", _SIZE_T),
        ("JobMemoryLimit", _SIZE_T),
        ("PeakProcessMemoryUsed", _SIZE_T),
        ("PeakJobMemoryUsed", _SIZE_T),
    ]


def _kernel32():
    if os.name != "nt":
        raise OSError("Windows Job ownership requires Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, ctypes.c_wchar_p], _HANDLE),
        "SetInformationJobObject": ([_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD], ctypes.c_int),
        "AssignProcessToJobObject": ([_HANDLE, _HANDLE], ctypes.c_int),
        "GetCurrentProcess": ([], _HANDLE),
        "CloseHandle": ([_HANDLE], ctypes.c_int),
        "PeekNamedPipe": (
            [
                _HANDLE,
                ctypes.c_void_p,
                _DWORD,
                ctypes.c_void_p,
                ctypes.POINTER(_DWORD),
                ctypes.c_void_p,
            ],
            ctypes.c_int,
        ),
        "ExitProcess": ([_DWORD], None),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes = args
        function.restype = result
    return api


def _job_error(operation: str) -> OSError:
    error = ctypes.get_last_error()
    return OSError(error, f"Windows Job ownership: {operation} failed (WinError {error})")


def _own_invocation(api) -> int:
    # NULL security attributes make the handle non-inheritable; NULL name means
    # other invocations cannot open this Job by a shared name.
    job = api.CreateJobObjectW(None, None)
    if not job:
        raise _job_error("CreateJobObjectW")
    try:
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(
            job, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise _job_error("SetInformationJobObject")
        # No breakaway flag is enabled. Incompatible enclosing Jobs fail here,
        # before Popen; silently launching without ownership is never allowed.
        if not api.AssignProcessToJobObject(job, api.GetCurrentProcess()):
            raise _job_error("AssignProcessToJobObject")
    except BaseException:
        api.CloseHandle(job)
        raise
    return job


def _send_status(fd: int, payload: dict) -> None:
    data = (json.dumps(payload, ensure_ascii=True) + "\n").encode("ascii")
    while data:
        data = data[os.write(fd, data) :]


def _host(command: list[str] | str, *, shell: bool, status_fd: int, api) -> int:
    try:
        _own_invocation(api)
        # The status channel belongs only to the host, never the requested
        # process. Caller stdio is inherited directly, with no text conversion.
        os.set_inheritable(status_fd, False)
        # Explicit stdio forces Popen to duplicate the host's standard handles
        # into its restricted inheritance list. On Windows, all-None stdio
        # with close_fds=True would not reliably inherit redirected pipes.
        target = subprocess.Popen(
            command,
            shell=shell,
            close_fds=True,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except Exception as exc:
        _send_status(
            status_fd,
            {
                "error": type(exc).__name__,
                "message": str(exc)[:256],
                "errno": getattr(exc, "errno", None),
            },
        )
        os.close(status_fd)
        return _HOST_FAILURE
    _send_status(status_fd, {"ok": True})
    os.close(status_fd)
    return target.wait()


def pipe_available(fd: int, api) -> int:
    """Poll the private startup pipe without a blocking reader thread."""
    import msvcrt

    available = _DWORD()
    if not api.PeekNamedPipe(
        msvcrt.get_osfhandle(fd), None, 0, None, ctypes.byref(available), None
    ):
        raise _job_error("PeekNamedPipe")
    return available.value


def main() -> None:
    import msvcrt

    api = _kernel32()
    status_fd = msvcrt.open_osfhandle(int(sys.argv[1]), os.O_WRONLY | os.O_BINARY)
    shell = sys.argv[2] == "shell"
    # JSON preserves both a raw shell string and every literal argv element,
    # including empty strings, quotes, metacharacters and trailing backslashes.
    command = json.loads(sys.argv[3])
    rc = _host(command, shell=shell, status_fd=status_fd, api=api)
    # sys.exit / CRT _exit can truncate or reject a native Windows DWORD status.
    # ExitProcess also closes the sole Job handle, reclaiming all descendants.
    api.ExitProcess(rc & 0xFFFFFFFF)


if __name__ == "__main__":
    main()
