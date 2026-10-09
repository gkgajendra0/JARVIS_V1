"""Adversarial policy and lifecycle tests for Windows native AEP discovery."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from jarvis.goal_intelligence.runtime import build_gicc_apply_runtime
from jarvis.goal_intelligence.windows_aep import (
    ReviewedAepScopeV1,
    WindowsAepIdentityBackend,
    _candidate_from_device,
    _normalize_protocol,
)

_UPNP = "0e261de4-12f0-46e6-91ba-428607ccef64"


def _scope(**changes) -> ReviewedAepScopeV1:
    defaults = {
        "protocol": "upnp",
        "approved_address_ranges": ("192.168.1.0/24",),
        "consent_record_id": "approval-fixture",
        "all_local_interfaces_authorized": True,
        "timeout_seconds": 0.25,
        "max_results": 2,
    }
    defaults.update(changes)
    return ReviewedAepScopeV1(**defaults)


def _device(
    *,
    endpoint_id="endpoint-1",
    address="192.168.1.10",
    protocol=_UPNP,
    present=True,
    manufacturer="Example Media",
    model="Example 4K",
    category="Media Device",
):
    return SimpleNamespace(
        id=endpoint_id,
        name="Family Television",
        properties={
            "System.Devices.Aep.DeviceAddress": address,
            "System.Devices.Aep.IsPresent": present,
            "System.Devices.Aep.ProtocolId": "{" + protocol + "}",
            "System.Devices.Aep.Manufacturer": manufacturer,
            "System.Devices.Aep.ModelName": model,
            "System.Devices.Aep.Category": category,
        },
    )


class FakeWatcher:
    def __init__(self, rows=(), *, removed=(), completed=True):
        self.rows = rows
        self.removed = removed
        self.complete = completed
        self.callbacks = {}
        self.started = 0
        self.stopped = 0
        self.unsubscribed = []

    def add_added(self, fn):
        self.callbacks["added"] = fn
        return "added"

    def add_removed(self, fn):
        self.callbacks["removed"] = fn
        return "removed"

    def add_enumeration_completed(self, fn):
        self.callbacks["enumeration_completed"] = fn
        return "enumeration_completed"

    def remove_added(self, token):
        self.unsubscribed.append(token)

    def remove_removed(self, token):
        self.unsubscribed.append(token)

    def remove_enumeration_completed(self, token):
        self.unsubscribed.append(token)

    def start(self):
        self.started += 1
        for row in self.rows:
            self.callbacks["added"](self, row)
        for endpoint_id in self.removed:
            self.callbacks["removed"](self, SimpleNamespace(id=endpoint_id))
        if self.complete:
            self.callbacks["enumeration_completed"](self, None)

    def stop(self):
        self.stopped += 1


def _backend(watcher, *, approved=True, auth_calls=None):
    def check(scope):
        if auth_calls is not None:
            auth_calls.append(scope)
        return approved

    return WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=check,
        watcher_factory=lambda _: watcher,
        clock=lambda: 1_000,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"protocol": "all"},
        {"all_local_interfaces_authorized": False},
        {"approved_address_ranges": ()},
        {"approved_address_ranges": ("0.0.0.0/0",)},
        {"approved_address_ranges": ("192.168.0.0/16",)},
        {"approved_address_ranges": ("8.8.8.0/24",)},
        {"approved_address_ranges": ("192.168.1.0/24", "8.8.8.0/24")},
        {"approved_address_ranges": ("::1/128",)},
        {"timeout_seconds": 5.0},
        {"max_results": 50},
        {"consent_record_id": ""},
    ],
)
def test_unreviewed_or_unbounded_scope_rejected(changes) -> None:
    with pytest.raises(ValueError):
        _scope(**changes)


def test_absent_authority_never_constructs_watcher() -> None:
    def forbidden(_):
        raise AssertionError("unauthorized WinRT watcher must not exist")

    no_checker = WindowsAepIdentityBackend(platform="win32", watcher_factory=forbidden)
    assert no_checker.observe(_scope()) == ()
    refused = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=lambda _: False,
        watcher_factory=forbidden,
    )
    assert refused.observe(_scope()) == ()


def test_nonwindows_backend_never_constructs_watcher() -> None:
    def forbidden(_):
        raise AssertionError("non-Windows watcher must not exist")

    backend = WindowsAepIdentityBackend(
        platform="linux",
        is_authorized=lambda _: True,
        watcher_factory=forbidden,
    )
    assert backend.observe(_scope()) == ()


def test_approved_aep_scan_returns_only_fresh_bounded_unverified_metadata() -> None:
    watcher = FakeWatcher(
        rows=(
            _device(),
            _device(endpoint_id="missing-tv", present=False),
            _device(endpoint_id="outside-subnet", address="192.168.2.20"),
            _device(endpoint_id="public-ip", address="8.8.8.8"),
            _device(
                endpoint_id="other-protocol",
                protocol="782232aa-a2f9-4993-971b-aedc551346b0",
            ),
            _device(),  # identical repeated Added notification is harmless
        )
    )
    calls = []
    backend = _backend(watcher, auth_calls=calls)
    rows = backend.observe(_scope())
    assert calls == [_scope()]
    assert len(rows) == 1
    assert rows[0].address == "192.168.1.10"
    assert rows[0].manufacturer == "Example Media"
    assert rows[0].model == "Example 4K"
    assert rows[0].category == "Media Device"
    assert "vendor=example_media:model=example_4k" in rows[0].evidence_ref
    assert "category=media_device:at=000000001000:" in rows[0].evidence_ref
    assert rows[0].observed_at_epoch == 1_000
    assert rows[0].evidence_ref.startswith("windows_aep_unverified:")
    assert watcher.started == watcher.stopped == 1
    assert set(watcher.unsubscribed) == {
        "added",
        "removed",
        "enumeration_completed",
    }


def test_removed_device_excluded_before_snapshot() -> None:
    watcher = FakeWatcher(rows=(_device(),), removed=("endpoint-1",))
    assert _backend(watcher).observe(_scope()) == ()


def test_duplicate_conflicting_identity_fails_closed_and_stops() -> None:
    watcher = FakeWatcher(rows=(_device(), _device(manufacturer="a conflicting label")))
    assert _backend(watcher).observe(_scope()) == ()
    assert watcher.stopped == 1


def test_result_overflow_fails_closed_not_arbitrarily_first_n() -> None:
    watcher = FakeWatcher(
        rows=tuple(_device(endpoint_id=f"endpoint-{i}") for i in range(3))
    )
    assert _backend(watcher).observe(_scope()) == ()
    assert watcher.stopped == 1


def test_never_accept_partial_scan_on_timeout() -> None:
    watcher = FakeWatcher(rows=(_device(),), completed=False)
    assert _backend(watcher).observe(_scope()) == ()
    assert watcher.stopped == 1


def test_missing_presence_and_invalid_address_never_confirms_device() -> None:
    assert _candidate_from_device(_device(present="true"), _scope(), 1_000) is None
    assert (
        _candidate_from_device(_device(address="169.254.0.5"), _scope(), 1_000) is None
    )
    assert _normalize_protocol("not-a-uuid") is None


def test_authority_checker_failure_is_denial() -> None:
    def denied(_):
        raise RuntimeError("permission service unavailable")

    watcher = FakeWatcher(rows=(_device(),))
    backend = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=denied,
        watcher_factory=lambda _: watcher,
    )
    assert backend.observe(_scope()) == ()
    assert watcher.started == 0


@pytest.mark.skipif(sys.platform != "win32", reason="WinRT projection on Windows")
def test_windows_winrt_aep_projection_contract_without_starting_discovery() -> None:
    from winrt.windows.devices.enumeration import (
        DeviceInformation,
        DeviceInformationKind,
    )

    assert callable(
        DeviceInformation.create_watcher_with_kind_aqs_filter_and_additional_properties
    )
    assert DeviceInformationKind.ASSOCIATION_ENDPOINT is not None


def test_runtime_rejects_unapproved_active_aep_scans_before_store_access() -> None:
    """Optional network enumeration cannot be enabled by config alone."""

    runtime = SimpleNamespace(
        capability_acquisition=object(),
        changes=object(),
    )
    capability_context = SimpleNamespace(current=lambda: None)
    with pytest.raises(ValueError, match="independent owner-consent"):
        build_gicc_apply_runtime(
            config=object(),
            capability_runtime=object(),
            work_runtime=runtime,
            capability_context=capability_context,
            approved_aep_scopes=(_scope(),),
        )


def test_runtime_rejects_duplicate_protocol_scopes_before_store_access() -> None:
    runtime = SimpleNamespace(
        capability_acquisition=object(),
        changes=object(),
    )
    with pytest.raises(ValueError, match="distinct reviewed protocol scopes"):
        build_gicc_apply_runtime(
            config=object(),
            capability_runtime=object(),
            work_runtime=runtime,
            capability_context=SimpleNamespace(current=lambda: None),
            approved_aep_scopes=(_scope(), _scope()),
            trusted_aep_consent_validator=lambda _: True,
        )


def test_untrusted_aep_labels_are_sanitized_for_protected_evidence() -> None:
    row = _candidate_from_device(
        _device(
            manufacturer='Vendor:"ignore-all-rules\\n"',
            model="55<do-not-execute>{tokens}",
        ),
        _scope(),
        1_000,
    )
    assert row is not None
    assert "\\n" not in row.evidence_ref
    assert "<" not in row.evidence_ref
    assert "{" not in row.evidence_ref
    assert "vendor=vendor_ignore_all_rules:" in row.evidence_ref
