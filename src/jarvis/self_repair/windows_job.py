"""Windows Job Object ownership for the supervised JARVIS runtime tree.

The supervisor keeps one job handle alive for each runtime child. On Windows,
children of a process in a job normally inherit that job. The job is configured with
KILL_ON_JOB_CLOSE so loss of the supervisor handle fails closed by terminating the
owned runtime processes.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class WindowsJobObjectError(RuntimeError):
    """Windows could not create, configure or operate the runtime job."""


class _JobApi(Protocol):
    def create_job(self) -> object: ...

    def set_kill_on_close(self, job: object) -> None: ...

    def contains_pid(self, job: object, pid: int) -> bool: ...

    def assign_pid(self, job: object, pid: int) -> None: ...

    def terminate_job(self, job: object, exit_code: int) -> None: ...

    def close_job(self, job: object) -> None: ...


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _CtypesJobApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsJobObjectError(
                "Windows Job Objects are available only on Windows"
            )

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32

        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE

        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL

        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL

        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE

        kernel32.AssignProcessToJobObject.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
        )
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

        kernel32.IsProcessInJob.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        )
        kernel32.IsProcessInJob.restype = wintypes.BOOL

        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL

        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

    @staticmethod
    def _raise_last_error(operation: str) -> None:
        error = ctypes.get_last_error()
        raise WindowsJobObjectError(f"{operation} failed with Win32 error {error}")

    def create_job(self) -> object:
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            self._raise_last_error("CreateJobObjectW")
        return handle

    def set_kill_on_close(self, job: object) -> None:
        info = _JobObjectExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self._kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            self._raise_last_error("SetInformationJobObject")

        verified = _JobObjectExtendedLimitInformation()
        returned_length = wintypes.DWORD()
        ok = self._kernel32.QueryInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(verified),
            ctypes.sizeof(verified),
            ctypes.byref(returned_length),
        )
        if not ok:
            self._raise_last_error("QueryInformationJobObject")
        if not (
            verified.BasicLimitInformation.LimitFlags
            & _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ):
            raise WindowsJobObjectError(
                "Windows Job Object did not retain KILL_ON_JOB_CLOSE"
            )

    def _open_process(self, pid: int) -> object:
        handle = self._kernel32.OpenProcess(
            _PROCESS_TERMINATE
            | _PROCESS_SET_QUOTA
            | _PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not handle:
            self._raise_last_error(f"OpenProcess({pid})")
        return handle

    def contains_pid(self, job: object, pid: int) -> bool:
        process = self._open_process(pid)
        try:
            result = wintypes.BOOL()
            ok = self._kernel32.IsProcessInJob(
                process,
                job,
                ctypes.byref(result),
            )
            if not ok:
                self._raise_last_error(f"IsProcessInJob({pid})")
            return bool(result.value)
        finally:
            self._kernel32.CloseHandle(process)

    def assign_pid(self, job: object, pid: int) -> None:
        process = self._open_process(pid)
        try:
            if not self._kernel32.AssignProcessToJobObject(job, process):
                self._raise_last_error(f"AssignProcessToJobObject({pid})")
        finally:
            self._kernel32.CloseHandle(process)

    def terminate_job(self, job: object, exit_code: int) -> None:
        if not self._kernel32.TerminateJobObject(job, exit_code):
            self._raise_last_error("TerminateJobObject")

    def close_job(self, job: object) -> None:
        if not self._kernel32.CloseHandle(job):
            self._raise_last_error("CloseHandle(job)")


class WindowsRuntimeJob:
    """Own one Windows Job Object for exactly one supervised runtime tree."""

    def __init__(self, *, api: _JobApi | None = None) -> None:
        resolved = api or _CtypesJobApi()
        job = resolved.create_job()
        try:
            resolved.set_kill_on_close(job)
        except Exception:
            resolved.close_job(job)
            raise
        self._api = resolved
        self._job: object | None = job

    @property
    def closed(self) -> bool:
        return self._job is None

    def assign_pid(self, pid: int) -> None:
        if pid <= 0:
            raise ValueError("pid must be positive")
        job = self._require_job()
        if not self._api.contains_pid(job, pid):
            self._api.assign_pid(job, pid)

    def terminate(self, *, exit_code: int = 1) -> None:
        if exit_code < 0:
            raise ValueError("exit_code must not be negative")
        self._api.terminate_job(self._require_job(), exit_code)

    def close(self) -> None:
        job = self._job
        if job is None:
            return
        self._job = None
        self._api.close_job(job)

    def _require_job(self) -> object:
        if self._job is None:
            raise WindowsJobObjectError("Windows runtime job is already closed")
        return self._job
