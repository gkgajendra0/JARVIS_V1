"""Fast synthetic-feature contract test. This does NOT create a usable wake model."""

import json

import numpy as np
import torch
from livekit.wakeword.config import load_config
from livekit.wakeword.export.onnx import run_export
from livekit.wakeword.training.trainer import run_train
from run_training import validate_onnx

torch.set_num_threads(2)
np.random.seed(7)
torch.manual_seed(7)
config = load_config("/workflow/jarvis.yaml")
config.model_name = "contract_fixture"
config.output_dir = "/training/preflight-only"
config.data_dir = "/training/preflight-only/no-real-datasets"
config.steps = 20
config.batch_n_per_class = {"positive": 8, "adversarial_negative": 8}
config.model_output_dir.mkdir(parents=True, exist_ok=True)
for split in ("train", "test"):
    for kind, mean in [("positive", 1), ("negative", -1)]:
        np.save(
            config.model_output_dir / f"{kind}_features_{split}.npy",
            (np.random.randn(32, 16, 96) + mean).astype(np.float32),
        )
run_train(config)
model = run_export(config)
result = validate_onnx(model)
result["purpose"] = (
    "Synthetic feature contract test ONLY. Never deploy this fixture model."
)
(config.model_output_dir / "contract-check.json").write_text(
    json.dumps(result, indent=2)
)
print("CONTRACT CHECK PASSED:", json.dumps(result))
