# Step 3B.13 — Native Sortformer real-machine benchmark

Status: **REAL-MACHINE FUNCTIONAL PASS — PRODUCTION SHADOW INTEGRATION IN PROGRESS**

Date: 2026-09-03

## Purpose

This benchmark answered one bounded question before production integration:

> Can NVIDIA's native Windows Sortformer path distinguish clean single-speaker speech from the already-known Scenario G overlap on the real JARVIS RTX 5060 Ti machine without creating unacceptable runtime contention?

Result: **YES — functional pass on the real JARVIS machine with normal Vision running.**

This acceptance does not by itself enable T2, actor authority, a CAM++ speaker threshold, or an authority-bearing overlap threshold.

## Pinned external/runtime boundary

NeMo-Speech.cpp source/installer revision researched for this gate:

```text
56b60d432f1731d6d5b28a4c5a31cbaf871daba1
```

Pinned runtime release:

```text
NeMo-Speech.cpp 0.1.0
windows/x86_64/cuda
```

The NVIDIA v0.1.0 release provides a prebuilt Windows CUDA archive plus published SHA-256 sidecar. The real machine used `-BinaryOnly`, so missing `nvcc` did not trigger an unnecessary source build or CUDA Toolkit installation.

The benchmark model is managed by JARVIS and pinned to:

```text
repository = nvidia/diar_streaming_sortformer_4spk-v2
revision   = 5240a64075176943f677d30fa2171c780229f341
file       = diar_streaming_sortformer_4spk-v2.q8_0.gguf
bytes      = 147075776
sha256     = 0679cfeb1ce356d0dea9470b31274f4bfc7eb927497d82005483770666da998a
license    = CC-BY-4.0
```

JARVIS verifies both exact byte count and SHA-256 before loading it.

## Real machine

Observed deployment machine/runtime:

```text
GPU    = NVIDIA GeForce RTX 5060 Ti, 8150 MiB visible VRAM
Driver = 596.49
CUDA driver compatibility reported by nvidia-smi = 13.2
NeMo-Speech.cpp = 0.1.0 native CUDA binary
Sortformer capacity = 4 speakers
Sortformer frame step = 0.080 s
```

The native runtime self-report showed:

```text
accelerator_available      = true
accelerator_compiled       = true
driver_runtime_compatible  = true
diarization                = true
backend_cuda               = true
```

`nvcc` was not installed and was not required because the accepted path used NVIDIA's prebuilt binary rather than a source build.

## Architecture under test

```text
Pocket3 microphone
      ↓
accepted LiveKit MediaDevices/WebRTC path
      ↓
canonical processed PCM in memory
      ↓
NativeSortformerDiarizer (ctypes -> nemo_speech_asr_c.dll)
      ↓
raw per-80-ms speaker probabilities
      ↓
JARVIS overlap interpreter
      ↓
SINGLE_SPEAKER / OVERLAP_DETECTED / SPEAKER_CHANGE /
AMBIGUOUS / INSUFFICIENT
```

The benchmark never opened a second microphone.

Normal JARVIS Vision/RF-DETR was enabled throughout so the result includes representative GPU contention.

## Accepted one-time runtime installation

The safe installation form used for the real gate was:

```powershell
$nemoCommit = "56b60d432f1731d6d5b28a4c5a31cbaf871daba1"
$installer = Join-Path $PWD "install-nemo-speech.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/NVIDIA/NeMo-Speech.cpp/$nemoCommit/scripts/install.ps1" `
  -OutFile $installer

powershell -ExecutionPolicy Bypass -File $installer `
  -Version 0.1.0 `
  -Backend cuda `
  -BinaryOnly
```

Using `-BinaryOnly` is intentional. It prevents silent fallback into a source build that would require `nvcc`, Visual Studio/C++, CMake, and Ninja.

Default install prefix:

```text
%LOCALAPPDATA%\Programs\NeMoSpeech
```

Accepted checks:

```text
nemo-speech --version -> nemo-speech 0.1.0
nemo_speech_asr_c.dll exists -> True
```

## Real A/B/G result

The guided benchmark ran three ~6 second captures through canonical LiveKit PCM with Vision active.

### A — OWNER only

```text
audio              = 5.99 s
RMS                = -20.3 dBFS
inference          = 363.9 ms
RTF                = 0.061
push median/p95/max= 2.1 / 55.4 / 228.5 ms
output frames      = 75
speech frames      = 61
overlap frames     = 0
peak active        = 1
overlap fraction   = 0.000
stable runs        = ((0, 61),)
state              = SINGLE_SPEAKER
```

A includes first-run/cold CUDA graph work; later captures were materially faster.

### B — external phone/TV speech only

```text
audio              = 5.99 s
RMS                = -26.5 dBFS
inference          = 135.4 ms
RTF                = 0.023
push median/p95/max= 1.8 / 27.0 / 27.9 ms
output frames      = 75
speech frames      = 75
overlap frames     = 0
peak active        = 1
overlap fraction   = 0.000
stable runs        = ((0, 75),)
state              = SINGLE_SPEAKER
```

This is expected: diarization identifies speaker structure, not OWNER identity.

### G — OWNER + external speech overlap

```text
audio              = 5.99 s
RMS                = -18.7 dBFS
inference          = 148.0 ms
RTF                = 0.025
push median/p95/max= 1.9 / 27.0 / 38.4 ms
output frames      = 75
speech frames      = 67
overlap frames     = 14
longest overlap run= 6 frames (~480 ms)
peak active        = 2
overlap fraction   = 0.209
stable runs        = ((0, 7), (1, 5), (0, 14), (1, 16), (0, 10))
state              = OVERLAP_DETECTED
reason             = concurrent_speaker_activity
```

This closes the exact signal gap exposed by the previous LR-ASD Scenario G run:

```text
LR-ASD: visible OWNER is speaking     -> may be YES
CAM++: audio sounds like OWNER        -> may be YES
Sortformer: another speaker overlaps  -> YES

therefore spoken actor evidence       -> AMBIGUOUS / fail closed
```

The final actor-composition rule is not enabled yet; this benchmark proves the missing concurrent-speaker signal is available.

## Functional acceptance

The harness printed:

```text
A clean single-speaker = True
G overlap detected = True
threshold_promoted = False
authority_effect = False
raw_audio_saved = False
STEP_3B13_NATIVE_SORTFORMER_BENCHMARK = FUNCTIONAL_PASS
```

**3B.13 native signal gate: ACCEPTED.**

## Performance interpretation

The warm real-machine captures ran at approximately `RTF 0.023–0.025`, far below real time. Push p95 was about `27 ms` after warm-up. RF-DETR Vision remained active throughout and the benchmark completed normally.

The current `nvidia-smi --query-compute-apps=pid,used_memory` telemetry returned `0.0 MiB` for the Python process even though the native runtime explicitly selected `CUDA0`. Under the current Windows/WDDM + native-DLL path that per-process counter is therefore treated as **not reliable**, not as proof of zero GPU memory use. RSS rose during the combined benchmark process and reached roughly 2.6 GiB, but that includes Vision/model/runtime state and is not attributed solely to Sortformer.

The accepted performance evidence is therefore:

- native runtime explicitly selected RTX 5060 Ti CUDA backend;
- driver/runtime compatibility passed;
- Vision and Sortformer coexisted successfully;
- warm RTF ~0.025;
- warm push p95 ~27 ms;
- no observed benchmark instability.

A normal-conversation shadow run is still required to judge perceived UX before any evidence can influence trust.

## Production shadow integration rule

After this pass, Sortformer may be integrated only as a background observer over full committed canonical PCM:

- no second microphone;
- no blocking conversation path;
- model stays warm;
- scoring failures never break normal conversation;
- `SINGLE_SPEAKER`, `OVERLAP_DETECTED`, `SPEAKER_CHANGE`, `AMBIGUOUS`, `INSUFFICIENT` remain diagnostic evidence;
- no overlap threshold becomes authority merely because this benchmark used `0.5`;
- T2 and spoken approval remain disabled until identity-session composition and attack/degraded tests are complete.

## Next acceptance gate

Run ordinary `jarvis-voice` with Sortformer shadow integrated and verify:

1. startup remains clean;
2. normal single-speaker OWNER turns report `single_speaker`;
3. a deliberate OWNER + phone/TV overlap turn reports `overlap_detected`;
4. CAM++ and LR-ASD still run normally;
5. responses remain subjectively realtime;
6. no observer exception affects conversation.

After that gate, proceed to live non-OWNER CAM++ calibration and anti-spoof bake-off rather than promoting authority prematurely.

## Upstream references

- NeMo-Speech.cpp installation: `https://github.com/NVIDIA/NeMo-Speech.cpp/blob/56b60d432f1731d6d5b28a4c5a31cbaf871daba1/docs/install.md`
- NeMo-Speech.cpp diarization C ABI: `https://github.com/NVIDIA/NeMo-Speech.cpp/blob/56b60d432f1731d6d5b28a4c5a31cbaf871daba1/include/nemo_speech/diar.h`
- NeMo-Speech.cpp v0.1.0 release: `https://github.com/NVIDIA/NeMo-Speech.cpp/releases/tag/v0.1.0`
- Sortformer v2: `https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2`
- Q8 GGUF addition: `https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2/commit/5240a64075176943f677d30fa2171c780229f341`
