"""Isolated LiveKit 0.2.1 pipeline with durable stages and disk checkpoints."""

import argparse
import hashlib
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

LOGGER = logging.getLogger(__name__)

ROOT = Path("/training")
BACKUP = Path("/backup")


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def copy_verified(source, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".copying")
    shutil.copy2(source, tmp)
    if source.suffix in (".onnx", ".pt"):
        assert digest(source) == digest(tmp), f"Backup checksum mismatch: {source}"
    tmp.replace(dest)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str) + "\n")
    tmp.replace(path)


def backup(include_audio=True):
    # Copy durable artifacts and metadata. Dataset backup runs after complete stages.
    for folder in ("logs", "state", "results"):
        source = ROOT / folder
        if not source.exists():
            continue
        for directory, dirs, files in os.walk(source):
            if not include_audio:
                dirs[:] = [
                    d
                    for d in dirs
                    if d
                    not in {
                        "positive_train",
                        "positive_test",
                        "negative_train",
                        "negative_test",
                        "background_train",
                        "background_test",
                    }
                ]
            for name in files:
                path = Path(directory) / name
                if path.suffix in (".tmp", ".partial", ".copying"):
                    continue
                dest = BACKUP / path.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() and dest.stat().st_size == path.stat().st_size:
                    # D: timestamps lose subsecond precision. Audio is immutable
                    # within a completed generation/augmentation stage.
                    tolerance = 2.0 if path.suffix == ".wav" else 0.0
                    if dest.stat().st_mtime + tolerance >= path.stat().st_mtime and (
                        path.suffix not in (".onnx", ".pt")
                        or digest(path) == digest(dest)
                    ):
                        continue
                copy_verified(path, dest)


def validate_onnx(path):
    import numpy as np
    import onnx
    import onnxruntime as ort
    from livekit.wakeword.resources import get_embedding_model_path, get_mel_model_path
    from openwakeword.model import Model

    onnx.checker.check_model(onnx.load(str(path)))
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inp = session.get_inputs()[0]
    assert inp.shape[1:] == [16, 96], inp.shape
    scores = session.run(None, {inp.name: np.zeros((1, 16, 96), np.float32)})[0]
    assert (
        scores.shape == (1, 1)
        and np.isfinite(scores).all()
        and ((scores >= 0) & (scores <= 1)).all()
    )
    streaming = Model(
        wakeword_models=[str(path)],
        inference_framework="onnx",
        ncpu=1,
        melspec_model_path=str(get_mel_model_path()),
        embedding_model_path=str(get_embedding_model_path()),
    )
    for _ in range(30):
        result = streaming.predict(np.zeros(1280, np.int16))
        assert np.isfinite(list(result.values())).all()
    return {
        "input_shape": inp.shape,
        "output_shape": list(scores.shape),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "openwakeword_0_6_streaming_smoke": "passed",
        "quality": "requires real microphone/room evaluation",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(ROOT / "logs/pipeline.log"),
        ],
    )
    import numpy as np
    import torch

    # LiveKit 0.2.1's DET evaluator uses the NumPy 2 spelling. Keep the
    # numerically equivalent NumPy 1.26 implementation for audio dependencies.
    if not hasattr(np, "trapezoid"):
        np.trapezoid = np.trapz
    from livekit.wakeword.config import load_config
    from livekit.wakeword.training.trainer import WakeWordTrainer as Trainer

    config = load_config("/workflow/jarvis.yaml")
    if args.smoke:
        config.n_samples = 32
        config.n_samples_val = 16
        config.n_background_samples = 16
        config.n_background_samples_val = 16
        config.steps = 20
        config.augmentation.rounds = 1
        config.output_dir = "/training/smoke-results"
        config.batch_n_per_class = {
            "positive": 8,
            "adversarial_negative": 8,
            "ACAV100M_sample": 0,
            "background_noise": 8,
        }
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    torch.set_num_threads(4)
    assert torch.cuda.is_available(), "CUDA is required; refusing silent CPU training"
    # Exercise a CUDA kernel; detecting a GPU alone does not establish architecture support.
    x = torch.randn(256, 256, device="cuda")
    (x @ x).sum().item()
    torch.cuda.synchronize()
    info = {
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "capability": torch.cuda.get_device_capability(0),
        "python": sys.version,
        "seed": 42,
        "smoke": args.smoke,
        "trainer_commit": "1ec7f680df30ff4ca0ebae6b5983441e94b10980",
    }
    LOGGER.info("CUDA preflight passed: %s", info)
    assert shutil.disk_usage(ROOT).free > 40 * 1024**3, (
        "Insufficient free training storage"
    )
    assert shutil.disk_usage(BACKUP).free > 25 * 1024**3, (
        "Insufficient free backup storage"
    )
    atomic_json(BACKUP / "backup-preflight.json", info)
    config.model_output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(config.model_output_dir / "preflight.json", info)
    atomic_json(
        config.model_output_dir / "resolved-config.json", config.model_dump(mode="json")
    )
    shutil.copy2(
        "/opt/requirements-resolved.txt", ROOT / "logs/requirements-resolved.txt"
    )
    # Store every validation checkpoint on disk, rather than only in upstream RAM.
    original_save = Trainer._save_checkpoint

    def save_checkpoint(self, step, phase, metrics):
        original_save(self, step, phase, metrics)
        dest = (
            self.config.model_output_dir
            / "checkpoints"
            / f"phase-{phase}-step-{step}.pt"
        )
        dest.parent.mkdir(exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        torch.save(
            {
                "state_dict": {
                    k: v.detach().cpu() for k, v in self.model.state_dict().items()
                },
                "phase": phase,
                "step": step,
                "metrics": metrics,
                "config": self.config.model_dump(mode="json"),
            },
            tmp,
        )
        tmp.replace(dest)
        # Keep the tiny checkpoints in the second drive immediately.
        target = BACKUP / dest.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        copy_verified(dest, target)

    Trainer._save_checkpoint = save_checkpoint
    state = ROOT / ("smoke-state" if args.smoke else "state")
    state.mkdir(exist_ok=True)
    signature = hashlib.sha256(Path("/workflow/jarvis.yaml").read_bytes()).hexdigest()
    signature_path = state / "config-sha256.txt"
    if signature_path.exists():
        assert signature_path.read_text().strip() == signature, (
            "Configuration changed: use a new run directory"
        )
    else:
        signature_path.write_text(signature + "\n")

    def stage(name, action, check=None):
        marker = state / f"{name}.done.json"
        if marker.exists():
            if check:
                check()
            LOGGER.info("Reusing completed stage %s", name)
            return
        atomic_json(
            state / "status.json",
            {"stage": name, "status": "running", "time": time.time()},
        )
        LOGGER.info("BEGIN %s", name)
        action()
        if check:
            check()
        atomic_json(marker, {"stage": name, "completed": time.time()})
        backup(include_audio=not args.smoke and name in ("02-generate", "03-augment"))
        LOGGER.info("COMPLETE %s (backup synchronized)", name)

    def check_data():
        feature_names = ["validation_set_features.npy"]
        if not args.smoke:
            feature_names.append("openwakeword_features_ACAV100M_2000_hrs_16bit.npy")
        required = [
            config.piper_checkpoint_path,
            config.piper_checkpoint_path.with_suffix(".json"),
        ]
        required.extend(config.data_path / "features" / name for name in feature_names)
        for p in required:
            assert p.is_file() and p.stat().st_size > 0, (
                f"Missing training resource: {p}"
            )
        for directory in ("backgrounds", "rirs"):
            assert any((config.data_path / directory).rglob("*.wav")), (
                f"No {directory} WAV files; setup did not finish"
            )
        for name in feature_names:
            features = np.load(config.data_path / "features" / name, mmap_mode="r")
            assert features.shape[-1] == 96 and features.size > 0, features.shape

    from livekit.wakeword.data.augment import run_augment
    from livekit.wakeword.data.features import run_extraction
    from livekit.wakeword.data.generate import run_generate
    from livekit.wakeword.eval.evaluate import run_eval
    from livekit.wakeword.export.onnx import run_export
    from livekit.wakeword.training.trainer import run_train

    def setup_data():
        for attempt in range(1, 4):
            try:
                command = [
                    "livekit-wakeword",
                    "setup",
                    "--config",
                    "/workflow/jarvis.yaml",
                ]
                if args.smoke:
                    command.append("--skip-acav")
                subprocess.run(command, check=True)
                check_data()
                return
            except Exception:
                LOGGER.exception("Data setup attempt %d/3 failed", attempt)
                if attempt == 3:
                    raise
                time.sleep(30 * attempt)

    stage("01-data", setup_data, check_data)
    stage("02-generate", lambda: run_generate(config))
    stage("03-augment", lambda: run_augment(config))

    def check_features():
        for split in (
            "positive_features_train",
            "negative_features_train",
            "positive_features_test",
            "negative_features_test",
        ):
            f = np.load(config.model_output_dir / f"{split}.npy", mmap_mode="r")
            assert (
                f.shape[0] > 0 and f.shape[1:] == (16, 96) and np.isfinite(f).all()
            ), (split, f.shape)

    stage("04-features", lambda: run_extraction(config), check_features)
    stage("05-train", lambda: run_train(config))
    path = config.model_output_dir / "jarvis.onnx"
    stage(
        "06-export",
        lambda: run_export(config),
        lambda: atomic_json(
            config.model_output_dir / "compatibility.json", validate_onnx(path)
        ),
    )
    stage("07-evaluate", lambda: run_eval(config, path))
    atomic_json(
        state / "status.json",
        {"status": "complete", "model": str(path), "time": time.time()},
    )
    backup(include_audio=False)
    LOGGER.info("SUCCESS: %s; evaluate on the real microphone before deployment.", path)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        LOGGER.exception("TRAINING FAILED")
        atomic_json(
            ROOT / "logs/failure.json",
            {
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "time": time.time(),
            },
        )
        atomic_json(
            ROOT
            / ("smoke-state" if "--smoke" in sys.argv else "state")
            / "status.json",
            {"status": "failed", "error": repr(exc), "time": time.time()},
        )
        try:
            backup(include_audio=False)
        except Exception:
            LOGGER.exception("Failure backup also failed")
        raise
