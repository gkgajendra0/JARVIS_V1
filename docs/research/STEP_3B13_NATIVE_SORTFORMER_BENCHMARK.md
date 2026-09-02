# Step 3B.13 — Native Sortformer real-machine benchmark

Status: **READY FOR REAL JARVIS-MACHINE GATE — NOT PRODUCTION INTEGRATED**

Date: 2026-09-02

## Purpose

This benchmark answers one bounded question before any production integration:

> Can NVIDIA's native Windows Sortformer path distinguish clean single-speaker speech from the already-known Scenario G overlap on the real JARVIS RTX 5060 Ti machine without creating unacceptable runtime contention?

It does not enable T2, actor authority, a speaker threshold, or a production overlap threshold.

## Pinned external/runtime boundary

NeMo-Speech.cpp source revision researched for this gate:

```text
56b60d432f1731d6d5b28a4c5a31cbaf871daba1
```

The native installer downloads backend-matched release archives and verifies them against NVIDIA-published SHA-256 files. JARVIS does not execute or vendor NVIDIA's installer itself.

The benchmark model is managed by JARVIS and pinned to:

```text
repository = nvidia/diar_streaming_sortformer_4spk-v2
revision   = 5240a64075176943f677d30fa2171c780229f341
file       = diar_streaming_sortformer_4spk-v2.q8_0.gguf
bytes      = 147075776
sha256     = 0679cfeb1ce356d0dea9470b31274f4bfc7eb927497d82005483770666da998a
license    = CC-BY-4.0
```

The Hugging Face revision explicitly added the Q8 GGUF for local NeMo-Speech.cpp inference. JARVIS verifies both exact byte count and SHA-256 before loading it.

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

The benchmark never opens a second microphone.

Vision is enabled by default during the benchmark so GPU contention is representative of the accepted RF-DETR runtime.

## One-time NVIDIA runtime installation

Run from the JARVIS repository in PowerShell. Download the installer from the pinned NVIDIA commit rather than piping current `main` directly into PowerShell:

```powershell
$nemoCommit = "56b60d432f1731d6d5b28a4c5a31cbaf871daba1"
$installer = Join-Path $PWD "install-nemo-speech.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/NVIDIA/NeMo-Speech.cpp/$nemoCommit/scripts/install.ps1" `
  -OutFile $installer

# Inspect the downloaded script before execution if desired:
Get-Item $installer

powershell -ExecutionPolicy Bypass -File $installer -Backend cuda
```

Do **not** pass `-Source` for this first benchmark. The preferred path is NVIDIA's backend-matched prebuilt archive; the installer verifies the downloaded archive against its published SHA-256 sidecar.

Default install prefix on Windows:

```text
%LOCALAPPDATA%\Programs\NeMoSpeech
```

Verify the installed executable explicitly without relying on a newly refreshed PATH:

```powershell
& "$env:LOCALAPPDATA\Programs\NeMoSpeech\bin\nemo-speech.exe" --version
```

If the runtime installs elsewhere, set:

```powershell
$env:JARVIS_NEMO_SPEECH_DLL = "C:\path\to\nemo_speech_asr_c.dll"
```

## JARVIS branch/setup

```powershell
git fetch origin
git switch step3-final-identity-completion
git pull origin step3-final-identity-completion

python -m pip install -e ".[vision,overlap-benchmark]"
```

The first benchmark run downloads the pinned ~147 MB GGUF into JARVIS's managed local model directory and verifies its hash. No Hugging Face CLI or Python NeMo installation is required.

## Guided benchmark

Run:

```powershell
jarvis-overlap-benchmark
```

The harness asks for only three short captures:

### A — OWNER only

- TV/phone/other people silent;
- OWNER speaks naturally for the full capture.

Expected diagnostic state:

```text
SINGLE_SPEAKER
```

### B — other/TV speech only

- OWNER remains silent;
- play clear human speech from TV/phone, or use a real second person.

This is useful background evidence but is not itself a pass/fail identity test because diarization labels speakers generically rather than as GK/non-GK.

### G — overlap

- OWNER speaks naturally;
- TV/phone/another person speaks audibly at the same time for most of the capture.

Expected diagnostic state:

```text
OVERLAP_DETECTED
```

## Telemetry recorded

Derived console evidence only:

- model/runtime identity;
- exact model size + SHA;
- model load time;
- speaker capacity/frame step;
- captured duration/RMS/peak/clipping;
- inference time and real-time factor;
- per-push median/p95/max latency;
- process GPU memory before/after;
- process RSS before/after;
- frame/speech/overlap counts;
- longest overlap run;
- stable speaker runs;
- final diagnostic state.

Raw audio is not persisted.

## First functional gate

The harness prints:

```text
STEP_3B13_NATIVE_SORTFORMER_BENCHMARK = FUNCTIONAL_PASS
```

only if:

```text
A -> SINGLE_SPEAKER
G -> OVERLAP_DETECTED
```

Even a functional pass does not automatically promote the model to production. Human review also considers:

- RTF / evidence delay;
- VRAM/RSS;
- RF-DETR contention;
- stability;
- whether the machine still feels responsive.

If v2 fails this gate, do not weaken the gate. Reconsider Sortformer v2.1 through another deployment path or the pyannote/diart alternatives documented in `STEP_3_FINAL_IDENTITY_SECURITY_RESEARCH.md`.

## Upstream references

- NeMo-Speech.cpp installation: `https://github.com/NVIDIA/NeMo-Speech.cpp/blob/56b60d432f1731d6d5b28a4c5a31cbaf871daba1/docs/install.md`
- NeMo-Speech.cpp diarization C ABI: `https://github.com/NVIDIA/NeMo-Speech.cpp/blob/56b60d432f1731d6d5b28a4c5a31cbaf871daba1/include/nemo_speech/diar.h`
- Sortformer v2: `https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2`
- Q8 GGUF addition: `https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2/commit/5240a64075176943f677d30fa2171c780229f341`
