# JARVIS Runtime Performance Optimization — Research and Baseline Protocol

Date: 2026-09-11
Status: Phase OPT-0 measurement harness implemented; production behavior unchanged

## Problem

The owner PC can reach very high CPU utilization while `jarvis-voice` is running even when aggregate GPU utilization remains low. The optimization objective is not to maximize GPU percentage. The objective is to recover CPU/system headroom while preserving wake word, full-duplex audio/AEC, vision, owner identity, passive liveness, tracking, active-speaker validation, and conversation responsiveness.

## Research-first decision

Do not tune production behavior before measuring the current runtime.

The first pass uses:

- `psutil` for repeatable process CPU, system CPU, RSS/VMS, thread count, child-process count, and Windows handle count.
- `nvidia-smi` when available for device GPU utilization and VRAM usage.
- `py-spy` as an external low-overhead sampling profiler when function/native-extension attribution is needed after the baseline.

`psutil.Process.cpu_percent()` can exceed 100% on a multicore system. To compare with Windows Task Manager, divide the process value by the logical CPU count. The harness therefore records both values.

Sources:

- https://psutil.io/faq/
- https://psutil.io/api/
- https://github.com/benfred/py-spy
- https://github.com/benfred/py-spy/releases

As of this research pass, py-spy 0.4.2 is the current release and supports current CPython versions plus native-extension profiling on x86-64 Windows.

## Repository findings that motivated the baseline

These are hypotheses to validate, not optimization changes approved yet:

1. Production assembly currently enables the OpenCV vision preview by default when vision is enabled. Preview copies/draws full frames and calls OpenCV GUI functions.
2. The camera capture loop is not explicitly FPS-governed and publishes every camera frame.
3. Heavy perception runs RF-DETR, tracking, head detection, and framing whenever the vision runtime consumes a frame.
4. Owner-context analysis can run every 0.10 seconds and includes face detection/recognition plus the MiniFAS passive-liveness ensemble.
5. MiniFAS ONNX sessions are explicitly CPU execution sessions.
6. ONNX Runtime CPU sessions currently do not impose a JARVIS-specific thread budget or disable worker spinning.
7. Standard PyPI OpenCV wheels are CPU builds; simply selecting an OpenCV DNN backend does not provide CUDA execution.
8. RF-DETR is configured for CUDA, but its inference preparation currently uses `compile=False`.
9. Camera frame rate and expensive perception rate do not need to be identical. LR-ASD can retain frequent visual samples while expensive object/head/identity inference runs at a lower controlled cadence.

These findings define the likely optimization order, but none should be changed before OPT-0 is captured.

## OPT-0 baseline harness

CLI:

```powershell
jarvis-runtime-profile
```

Default output:

```text
artifacts/performance/baseline-owner-pc.json
```

The output directory is intentionally ignored by Git. Baseline files are owner-machine evidence, not repository source.

### Guided phases

The profiler waits for Enter before every phase so the owner can make the scenario repeatable.

1. `idle_background` — 20 seconds. Stay silent and, if practical, stay outside camera view.
2. `owner_visible_idle` — 20 seconds. Sit normally in camera view and remain silent.
3. `conversation` — 30 seconds. Use the wake word and have a short normal conversation.
4. `post_conversation_idle` — 20 seconds. Remain visible and silent after the conversation.

The same protocol must be reused after every optimization pass.

### Captured metrics

Per sample:

- raw process CPU percentage
- Task-Manager-equivalent process CPU percentage
- system CPU percentage
- RSS and VMS memory
- process thread count
- child process count
- Windows handle count when available
- NVIDIA device GPU utilization when available
- NVIDIA device VRAM used/total when available
- phase and UTC timestamp

The JSON also records:

- Python/platform information
- logical/physical CPU count
- target PID/name/command line
- Git HEAD, branch, and dirty state when run inside the repository
- mean/median/p95/max summaries overall and by phase

## Optional attribution after OPT-0

If the baseline confirms CPU pressure, use py-spy externally rather than embedding a profiler in JARVIS:

```powershell
python -m pip install py-spy==0.4.2
py-spy record --native --nonblocking --pid <JARVIS_PID> --duration 30 --output artifacts/performance/jarvis-native.svg
```

This keeps sampling overhead outside the target process. Run the capture during the specific phase that is expensive instead of recording an unnecessarily long mixed workload.

## Optimization order after the baseline

### OPT-1 — low-risk scheduling/thread controls

Candidate changes, one at a time with before/after evidence:

1. Make production vision preview opt-in rather than default-on.
2. Introduce a heavy-perception cadence target, initially around 10 FPS, while leaving camera capture available at the rate needed by LR-ASD.
3. Adjust OC-SORT frame-rate/lost-track configuration to preserve time semantics when perception FPS changes.
4. Add a small OpenCV thread budget and benchmark 1 vs 2 threads.
5. Add ONNX Runtime session options for the tiny MiniFAS models: benchmark intra-op 1 vs 2 and disable worker spinning.

### OPT-2 — adaptive identity/liveness cadence

Use faster sampling during acquisition/uncertainty and a slower maintenance cadence after stable owner+liveness evidence. The current temporal windows permit a maintenance cadence near 4 Hz while remaining below the existing maximum observation gap, but acceptance testing must validate this before approval.

### OPT-3 — accelerator/inference-path benchmark

Only after OPT-1/2:

1. Benchmark MiniFAS on `onnxruntime-gpu` versus tightly-threaded CPU execution. Tiny 80x80 models may not benefit from GPU copies, so measure rather than assume.
2. Benchmark RF-DETR `compile=True` at the production resolution.
3. Consider TensorRT/inference-models only if remaining latency/CPU pressure justifies the extra deployment complexity.

## Acceptance invariants

An optimization is rejected if it obtains lower CPU by degrading any of these behaviors:

- wake-word reliability
- full-duplex audio/AEC stability
- no new audio drop/overflow regressions
- owner identity semantics
- passive-liveness semantics
- active-speaker/LR-ASD semantics
- person/head tracking stability
- PTZ/follow behavior
- conversation responsiveness

## Performance target

Do not hard-code a final target until the real OPT-0 baseline exists. The working owner-PC objective is to make normal vision-enabled idle operation leave substantial desktop headroom, with roughly 30–40% total system CPU or lower as an initial target if acceptance behavior remains intact.

## Gate to OPT-1

OPT-1 does not begin until:

- the baseline JSON exists from the owner PC;
- the four guided phases were completed correctly;
- the report contains CPU/RAM/thread data and GPU data when `nvidia-smi` is available;
- the expensive phase(s) are identified from evidence;
- optional py-spy attribution is captured if process-level metrics alone are insufficient.
