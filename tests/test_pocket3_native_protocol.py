import struct

import pytest

from jarvis.vision.pocket3_native import (
    _a5_active,
    _decode_subject_box,
    _handshake_payload,
    _transport_header,
)


def test_a5_accepts_hardware_observed_active_variant() -> None:
    assert _a5_active(bytes.fromhex("00 01 01 00")) is True


def test_a5_accepts_older_documented_active_variant() -> None:
    assert _a5_active(bytes.fromhex("00 01 00 00")) is True


def test_a5_idle_variant_is_inactive() -> None:
    assert _a5_active(bytes.fromhex("00 00 00 00")) is False


def test_a5_rejects_unknown_or_error_shapes() -> None:
    assert _a5_active(b"\xe0") is None
    assert _a5_active(bytes.fromhex("00 02 00 00")) is None


def test_subject_push_decodes_center_and_size_at_offset_seven() -> None:
    payload = bytes(7) + struct.pack("<ffff", 0.60, 0.40, 0.20, 0.30)
    subject = _decode_subject_box(payload, observed_at=12.5)
    assert subject is not None
    assert subject.observed_at == 12.5
    assert subject.bounds.left == pytest.approx(0.50)
    assert subject.bounds.right == pytest.approx(0.70)
    assert subject.bounds.top == pytest.approx(0.25)
    assert subject.bounds.bottom == pytest.approx(0.55)


def test_handshake_payload_embeds_little_endian_base_sequence() -> None:
    payload = _handshake_payload(0x8BF0)
    assert len(payload) == 40
    assert payload[:2] == bytes.fromhex("f0 8b")


def test_transport_header_has_valid_xor_and_declared_length() -> None:
    header = _transport_header(0x00, 40, 0x65CA, 0)
    assert len(header) == 8
    declared = int.from_bytes(header[:2], "little") & 0x3FFF
    assert declared == 48
    checksum = 0
    for byte in header[:7]:
        checksum ^= byte
    assert header[7] == checksum
