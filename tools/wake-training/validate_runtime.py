"""Exercise the actual installed Jarvis predictor and full-window verifier."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort

from jarvis.voice.wakeword import (
    BoundedLiveKitWakeVerifier,
    OpenWakeWordStreamingPredictor,
)

path = Path(sys.argv[1]).resolve(strict=True)
options = ort.SessionOptions()
options.intra_op_num_threads = 1
session = ort.InferenceSession(
    str(path), sess_options=options, providers=["CPUExecutionProvider"]
)
assert session.get_inputs()[0].shape[1:] == [16, 96]
stream = OpenWakeWordStreamingPredictor(path)
for _ in range(40):
    scores = stream.predict(np.zeros(1280, np.int16))
    assert all(np.isfinite(list(scores.values())))
stream.reset()
verifier = BoundedLiveKitWakeVerifier(path)
score = verifier.predict(np.zeros(32000, np.int16))
assert all(np.isfinite(list(score.values())))
result = {
    "model": str(path),
    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "streaming": "passed",
    "exact_verifier": "passed",
    "silence_scores": score,
    "note": "Format smoke test only. Test real wake speech, room noise and playback before setting thresholds.",
}
path.with_suffix(".windows-validation.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
