from __future__ import annotations

import pytest

from jarvis.sensors.gstreamer_probe import (
    TimedBuffer,
    _mmdevice_id_from_pnp_instance,
    _parse_gst_time,
    parse_identity_line,
    summarize_timing,
)


def test_parse_gst_time() -> None:
    assert _parse_gst_time("0:00:01.250000000") == pytest.approx(1.25)
    assert _parse_gst_time("1:02:03.500") == pytest.approx(3723.5)
    assert _parse_gst_time("none") is None


def test_parse_identity_line_extracts_pts_and_duration() -> None:
    line = (
        "/GstPipeline:pipeline0/GstIdentity:vprobe: last-message = "
        "chain   ******* (vprobe:sink) (1382400 bytes, dts: none, "
        "pts: 0:00:02.500000000, duration: 0:00:00.033333333, "
        "offset: 0, offset_end: -1, flags: 00000000)"
    )

    parsed = parse_identity_line(line)

    assert parsed is not None
    name, buffer = parsed
    assert name == "vprobe"
    assert buffer.pts_seconds == pytest.approx(2.5)
    assert buffer.duration_seconds == pytest.approx(0.033333333)


def test_summarize_timing_reports_continuity() -> None:
    buffers = [
        TimedBuffer(0.000, 0.010),
        TimedBuffer(0.010, 0.010),
        TimedBuffer(0.020, 0.010),
    ]

    stats = summarize_timing(buffers)

    assert stats.buffers == 3
    assert stats.span_ms == pytest.approx(20.0)
    assert stats.median_period_ms == pytest.approx(10.0)
    assert stats.max_positive_gap_ms == pytest.approx(0.0)
    assert stats.max_timestamp_error_ms == pytest.approx(0.0)
    assert stats.monotonic is True


def test_summarize_timing_exposes_gap_without_declaring_policy() -> None:
    buffers = [
        TimedBuffer(0.000, 0.010),
        TimedBuffer(0.014, 0.010),
        TimedBuffer(0.024, 0.010),
    ]

    stats = summarize_timing(buffers)

    assert stats.max_positive_gap_ms == pytest.approx(4.0)
    assert stats.max_timestamp_error_ms == pytest.approx(4.0)
    assert stats.monotonic is True


def test_mmdevice_id_keeps_endpoint_id_opaque() -> None:
    endpoint = "{0.0.1.00000000}.{2789c851-7a26-4474-bdd7-c82256ca1fa6}"
    pnp_id = f"SWD\\MMDEVAPI\\{endpoint}"

    assert _mmdevice_id_from_pnp_instance(pnp_id) == endpoint


def test_mmdevice_id_rejects_non_mmdevice_node() -> None:
    with pytest.raises(ValueError, match="MMDevice"):
        _mmdevice_id_from_pnp_instance("USB\\VID_2CA3&PID_0023")
