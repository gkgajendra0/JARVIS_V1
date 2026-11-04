"""Windows Hello consent prompt using only components Windows already trusts.

This replaces the separately compiled .NET helper. Smart App Control (and any
App Control policy) blocks a locally compiled, unsigned binary: it has no
trusted signature and no cloud reputation. This module runs in the signed
Python runtime Jarvis already uses and calls the same Windows API the .NET
helper called, through ``ctypes`` and Microsoft-signed system DLLs:

    combase.dll  RoGetActivationFactory(Windows.Security.Credentials.UI.UserConsentVerifier)
    IUserConsentVerifierStatics.CheckAvailabilityAsync
    IUserConsentVerifierInterop.RequestVerificationForWindowAsync(owner HWND, message)

The Windows Hello dialog, its biometrics/PIN checks and the result all come
from Windows (CredentialUIBroker). Nothing here can produce "verified" except
the operating system's ``UserConsentVerificationResult.Verified``.

It is run as a child process with the same JSON contract as the old helper:
one JSON request on stdin, one JSON response on stdout.

    {"message": "..."}           -> prompt; {"status": ..., "reason": ...}
    {"action": "availability"}   -> no prompt; reports whether Hello is usable
    {} (or anything invalid)     -> {"status": "error", "reason": "invalid_request"}, exit 2

It imports only the standard library, so it runs with ``python -I <file>``
(isolated: no PYTHONPATH, user site or current directory on the import path).
"""

from __future__ import annotations

import json
import sys
import time
import uuid

USER_CONSENT_VERIFIER = "Windows.Security.Credentials.UI.UserConsentVerifier"
IID_USER_CONSENT_VERIFIER_INTEROP = uuid.UUID("39e050c3-4e74-441a-8dc0-b81104df949c")
IID_USER_CONSENT_VERIFIER_STATICS = uuid.UUID("af4f3f91-564c-4ddc-b8b5-973447627c65")
IID_IASYNC_INFO = uuid.UUID("00000036-0000-0000-c000-000000000046")
_IASYNC_OPERATION = "9fc2b0bb-e446-44e2-aa61-9cab8f636af2"
_WINRT_PINTERFACE_NAMESPACE = uuid.UUID("11f47ad5-7b73-42c0-abae-878b1e16adee")


def async_operation_iid(enum_name: str) -> uuid.UUID:
    """IID of IAsyncOperation<enum> per the WinRT parameterized-interface rule."""

    signature = (
        f"pinterface({{{_IASYNC_OPERATION}}};"
        f"enum(Windows.Security.Credentials.UI.{enum_name};i4))"
    )
    return uuid.uuid5(_WINRT_PINTERFACE_NAMESPACE, signature)


IID_ASYNC_VERIFICATION_RESULT = async_operation_iid("UserConsentVerificationResult")
IID_ASYNC_AVAILABILITY = async_operation_iid("UserConsentVerifierAvailability")

# Vtable slots: IUnknown 0-2, IInspectable 3-5, then the interface's methods.
_STATICS_CHECK_AVAILABILITY = 6
_INTEROP_REQUEST_FOR_WINDOW = 6
_ASYNC_OPERATION_GET_RESULTS = 8
_ASYNC_INFO_GET_STATUS = 7
_ASYNC_INFO_GET_ERROR_CODE = 8
_ASYNC_INFO_CANCEL = 9

# UserConsentVerifierAvailability
_AVAILABILITY = {
    0: ("available", "available"),
    1: ("unavailable", "device_not_present"),
    2: ("not_configured", "not_configured_for_user"),
    3: ("unavailable", "disabled_by_policy"),
    4: ("unavailable", "device_busy"),
}
# UserConsentVerificationResult
_RESULT = {
    0: ("verified", "verified"),
    1: ("unavailable", "device_not_present"),
    2: ("not_configured", "not_configured_for_user"),
    3: ("unavailable", "disabled_by_policy"),
    4: ("unavailable", "device_busy"),
    5: ("retries_exhausted", "retries_exhausted"),
    6: ("canceled", "user_canceled"),
}


def availability_response(value: int) -> tuple[str, str]:
    return _AVAILABILITY.get(value, ("unavailable", "availability_unknown"))


def verification_response(value: int) -> tuple[str, str]:
    # Anything Windows did not report as Verified is never treated as verified.
    return _RESULT.get(value, ("failed", "verification_failed"))


class WinRtError(RuntimeError):
    def __init__(self, step: str, hresult: int) -> None:
        self.step = step
        self.hresult = hresult & 0xFFFFFFFF
        super().__init__(f"{step} failed: HRESULT 0x{self.hresult:08X}")

    @property
    def reason(self) -> str:
        return f"{self.step}_hresult_0x{self.hresult:08x}"


def parse_request(raw: str) -> dict | None:
    """The request, or None when it is not a valid request."""

    try:
        request = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(request, dict):
        return None
    if request.get("action") == "availability" and set(request) == {"action"}:
        return request
    message = request.get("message")
    if isinstance(message, str) and message.strip() and set(request) == {"message"}:
        return request
    return None


class _WinRt:
    """Minimal WinRT/COM access through ctypes and signed system DLLs."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        hresult = ctypes.c_long
        combase = ctypes.WinDLL("combase", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        self.GUID = GUID
        self._ro_initialize = combase.RoInitialize
        self._ro_initialize.argtypes = [ctypes.c_int]
        self._ro_initialize.restype = hresult
        self._ro_uninitialize = combase.RoUninitialize
        self._ro_uninitialize.argtypes = []
        self._ro_uninitialize.restype = None
        self._get_factory = combase.RoGetActivationFactory
        self._get_factory.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._get_factory.restype = hresult
        self._create_string = combase.WindowsCreateString
        self._create_string.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._create_string.restype = hresult
        self._delete_string = combase.WindowsDeleteString
        self._delete_string.argtypes = [ctypes.c_void_p]
        self._delete_string.restype = hresult
        self._initialized = False

        u = self.user32
        u.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        u.CreateWindowExW.restype = wintypes.HWND
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.DestroyWindow.restype = wintypes.BOOL
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.ShowWindow.restype = wintypes.BOOL
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.SetForegroundWindow.restype = wintypes.BOOL
        u.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND,
            wintypes.COLORREF,
            wintypes.BYTE,
            wintypes.DWORD,
        ]
        u.SetLayeredWindowAttributes.restype = wintypes.BOOL
        u.GetSystemMetrics.argtypes = [ctypes.c_int]
        u.GetSystemMetrics.restype = ctypes.c_int
        u.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        u.PeekMessageW.restype = wintypes.BOOL
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.TranslateMessage.restype = wintypes.BOOL
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.restype = ctypes.c_ssize_t

    # -- basics ------------------------------------------------------------------

    def guid(self, value: uuid.UUID):
        return self.GUID.from_buffer_copy(value.bytes_le)

    def check(self, step: str, hresult: int) -> None:
        if hresult < 0:
            raise WinRtError(step, hresult)

    def initialize(self) -> None:
        result = self._ro_initialize(0)  # RO_INIT_SINGLETHREADED, as [STAThread]
        if result in (0, 1):  # S_OK, S_FALSE
            self._initialized = True
        elif result & 0xFFFFFFFF != 0x80010106:  # RPC_E_CHANGED_MODE: keep going
            self.check("ro_initialize", result)

    def uninitialize(self) -> None:
        if self._initialized:
            self._ro_uninitialize()
            self._initialized = False

    def method(self, pointer, index: int, *argtypes):
        ctypes = self.ctypes
        vtable = ctypes.cast(
            pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        function = prototype(vtable[index])
        return lambda *args: function(pointer, *args)

    def release(self, pointer) -> None:
        if pointer:
            ctypes = self.ctypes
            vtable = ctypes.cast(
                pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            ).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(pointer)

    def query_interface(self, pointer, iid: uuid.UUID):
        ctypes = self.ctypes
        out = ctypes.c_void_p()
        query = self.method(
            pointer, 0, ctypes.POINTER(self.GUID), ctypes.POINTER(ctypes.c_void_p)
        )
        self.check(
            "query_interface", query(ctypes.byref(self.guid(iid)), ctypes.byref(out))
        )
        return out

    def hstring(self, text: str):
        ctypes = self.ctypes
        handle = ctypes.c_void_p()
        self.check(
            "create_string",
            self._create_string(
                text, len(text.encode("utf-16-le")) // 2, ctypes.byref(handle)
            ),
        )
        return handle

    def delete_hstring(self, handle) -> None:
        if handle:
            self._delete_string(handle)

    def factory(self, iid: uuid.UUID):
        ctypes = self.ctypes
        name = self.hstring(USER_CONSENT_VERIFIER)
        try:
            out = ctypes.c_void_p()
            self.check(
                "activation_factory",
                self._get_factory(
                    name, ctypes.byref(self.guid(iid)), ctypes.byref(out)
                ),
            )
            return out
        finally:
            self.delete_hstring(name)

    def pump(self) -> None:
        ctypes = self.ctypes
        message = self.wintypes.MSG()
        while self.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))

    def wait_for_enum(self, operation, *, deadline: float, pump: bool) -> int:
        """Wait for an IAsyncOperation<enum> and return its result."""

        ctypes = self.ctypes
        info = self.query_interface(operation, IID_IASYNC_INFO)
        try:
            get_status = self.method(
                info, _ASYNC_INFO_GET_STATUS, ctypes.POINTER(ctypes.c_int)
            )
            status = ctypes.c_int()
            while True:
                self.check("async_status", get_status(ctypes.byref(status)))
                if status.value != 0:  # Started
                    break
                if time.monotonic() > deadline:
                    self.method(info, _ASYNC_INFO_CANCEL)()
                    raise TimeoutError
                if pump:
                    self.pump()
                time.sleep(0.02)
            if status.value == 2:  # Canceled
                raise WinRtError("async_canceled", 0x800704C7)
            if status.value == 3:  # Error
                code = ctypes.c_long()
                self.method(
                    info, _ASYNC_INFO_GET_ERROR_CODE, ctypes.POINTER(ctypes.c_long)
                )(ctypes.byref(code))
                raise WinRtError("async_error", code.value)
            # -1 is no UserConsentVerificationResult: if Windows ever reported
            # success without writing a value, it maps to failed, never to
            # Verified (0).
            result = ctypes.c_int(-1)
            self.check(
                "async_results",
                self.method(
                    operation,
                    _ASYNC_OPERATION_GET_RESULTS,
                    ctypes.POINTER(ctypes.c_int),
                )(ctypes.byref(result)),
            )
            return int(result.value)
        finally:
            self.release(info)

    # -- owner window ------------------------------------------------------------

    def owner_window(self):
        """A 1x1, nearly transparent, top-most tool window to own the dialog."""

        u = self.user32
        ex_style = 0x00000080 | 0x00000008 | 0x00080000  # TOOLWINDOW|TOPMOST|LAYERED
        style = 0x80000000  # WS_POPUP
        x = max(u.GetSystemMetrics(0) // 2, 0)
        y = max(u.GetSystemMetrics(1) // 2, 0)
        hwnd = u.CreateWindowExW(
            ex_style, "STATIC", "JARVIS", style, x, y, 1, 1, None, None, None, None
        )
        if not hwnd:
            raise WinRtError("owner_window", 0x80070000 | self.ctypes.get_last_error())
        u.SetLayeredWindowAttributes(hwnd, 0, 3, 0x00000002)  # LWA_ALPHA
        u.ShowWindow(hwnd, 5)  # SW_SHOW
        u.SetForegroundWindow(hwnd)
        return hwnd

    def destroy_window(self, hwnd) -> None:
        if hwnd:
            self.user32.DestroyWindow(hwnd)
            self.pump()


def check_availability(winrt: _WinRt, *, deadline: float) -> int:
    ctypes = winrt.ctypes
    statics = winrt.factory(IID_USER_CONSENT_VERIFIER_STATICS)
    try:
        operation = ctypes.c_void_p()
        winrt.check(
            "check_availability",
            winrt.method(
                statics, _STATICS_CHECK_AVAILABILITY, ctypes.POINTER(ctypes.c_void_p)
            )(ctypes.byref(operation)),
        )
        try:
            return winrt.wait_for_enum(operation, deadline=deadline, pump=False)
        finally:
            winrt.release(operation)
    finally:
        winrt.release(statics)


def request_verification(winrt: _WinRt, hwnd, message: str, *, deadline: float) -> int:
    ctypes = winrt.ctypes
    interop = winrt.factory(IID_USER_CONSENT_VERIFIER_INTEROP)
    text = winrt.hstring(message)
    try:
        operation = ctypes.c_void_p()
        winrt.check(
            "request_verification",
            winrt.method(
                interop,
                _INTEROP_REQUEST_FOR_WINDOW,
                winrt.wintypes.HWND,
                ctypes.c_void_p,
                ctypes.POINTER(winrt.GUID),
                ctypes.POINTER(ctypes.c_void_p),
            )(
                hwnd,
                text,
                ctypes.byref(winrt.guid(IID_ASYNC_VERIFICATION_RESULT)),
                ctypes.byref(operation),
            ),
        )
        try:
            return winrt.wait_for_enum(operation, deadline=deadline, pump=True)
        finally:
            winrt.release(operation)
    finally:
        winrt.delete_hstring(text)
        winrt.release(interop)


def _set_dpi_awareness() -> None:
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32")
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))  # SYSTEM_AWARE
    except (AttributeError, OSError):
        pass


def run(request: dict, *, timeout_seconds: float = 300.0) -> tuple[str, str]:
    deadline = time.monotonic() + timeout_seconds
    winrt = _WinRt()
    winrt.initialize()
    try:
        availability = check_availability(winrt, deadline=deadline)
        if request.get("action") == "availability":
            return availability_response(availability)
        if availability != 0:
            return availability_response(availability)
        _set_dpi_awareness()
        hwnd = winrt.owner_window()
        try:
            return verification_response(
                request_verification(winrt, hwnd, request["message"], deadline=deadline)
            )
        finally:
            winrt.destroy_window(hwnd)
    finally:
        winrt.uninitialize()


def _write(stdout, status: str, reason: str, exit_code: int) -> int:
    stdout.write(json.dumps({"status": status, "reason": reason}))
    stdout.flush()
    return exit_code


def main(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for stream, errors in ((stdin, "strict"), (stdout, "strict")):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors=errors)
    try:
        raw = stdin.read()
    except UnicodeError:
        return _write(stdout, "error", "invalid_request", 2)
    request = parse_request(raw)
    if request is None:
        return _write(stdout, "error", "invalid_request", 2)
    if sys.platform != "win32":
        return _write(stdout, "unavailable", "not_windows", 0)
    try:
        status, reason = run(request)
    except TimeoutError:
        return _write(stdout, "error", "verification_timeout", 1)
    except WinRtError as exc:
        return _write(stdout, "error", exc.reason, 1)
    except Exception as exc:  # noqa: BLE001 - fail closed with a reason, never verified
        return _write(stdout, "error", type(exc).__name__, 1)
    return _write(stdout, status, reason, 0)


if __name__ == "__main__":
    raise SystemExit(main())
