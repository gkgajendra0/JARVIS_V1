from jarvis.vision.owner_reacquisition import ReacquisitionConfig


def test_owner_recenter_timing_defaults_are_deliberate() -> None:
    config = ReacquisitionConfig()

    assert config.recenter_after_loss_seconds == 1.0
    assert config.recenter_settle_seconds == 0.75
