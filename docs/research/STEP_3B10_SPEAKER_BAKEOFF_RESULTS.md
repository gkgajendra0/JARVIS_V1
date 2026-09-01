# Step 3B.10 Speaker Embedding Bake-off Results

Status: **REAL-MACHINE BAKE-OFF COMPLETE — CAM++ SELECTED AS PROVISIONAL SHADOW PROVIDER**

Date: 2026-08-31

## Scope

This result records the first real JARVIS speaker-embedding bake-off on the accepted canonical Windows microphone route:

```text
Voicemeeter / physical microphone
        ↓
LiveKit MediaDevices
        ↓
AEC + noise suppression + high-pass + AGC
        ↓
canonical 48 kHz mono JARVIS PCM
        ↓
model-owned sherpa-onnx frontend
        ↓
speaker embedding
```

No raw audio, speaker embedding, voiceprint, or biometric template was persisted by the benchmark. No deployment similarity threshold was selected.

## Models tested

| Candidate | Embedding dimension | Model size | Real ~3 s latency |
| --- | ---: | ---: | ---: |
| 3D-Speaker CAM++ zh/en advanced | 192 | 27.0 MiB | ~54 ms median |
| 3D-Speaker ERes2NetV2 | 192 | 68.1 MiB | ~319 ms median |
| NVIDIA TitaNet-Large | 192 | 96.7 MiB | ~143 ms median |

The exact CAM++ artifact used in the accepted run was:

- filename: `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`
- size: `28,281,164` bytes
- SHA-256: `aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2`

## Real observed score distributions

The benchmark used five natural OWNER reference regions and then scored natural Hinglish, quiet, short-duration, far-field and TV speech regions against the in-memory reference prototype set.

### CAM++

| Scenario | n | min | median | max |
| --- | ---: | ---: | ---: | ---: |
| OWNER Hinglish, 3 s | 3 | 0.7354 | 0.7416 | 0.7579 |
| OWNER far, 3 s | 3 | 0.6287 | 0.6384 | 0.6435 |
| OWNER short, 2 s | 3 | 0.7087 | 0.7225 | 0.7611 |
| OWNER short, 1 s | 3 | 0.2282 | 0.5448 | 0.5554 |
| OWNER short, 0.5 s | 3 | 0.1641 | 0.2541 | 0.4327 |
| TV speech, 3 s | 3 | 0.1847 | 0.3644 | 0.3943 |

### ERes2NetV2

| Scenario | n | min | median | max |
| --- | ---: | ---: | ---: | ---: |
| OWNER Hinglish, 3 s | 3 | 0.7622 | 0.7764 | 0.7879 |
| OWNER far, 3 s | 3 | 0.6596 | 0.6721 | 0.6926 |
| OWNER short, 2 s | 3 | 0.7085 | 0.7378 | 0.7923 |
| OWNER short, 1 s | 3 | 0.1601 | 0.5254 | 0.6827 |
| OWNER short, 0.5 s | 3 | 0.1584 | 0.2016 | 0.6328 |
| TV speech, 3 s | 3 | 0.1788 | 0.2898 | 0.3052 |

### TitaNet-Large

| Scenario | n | min | median | max |
| --- | ---: | ---: | ---: | ---: |
| OWNER Hinglish, 3 s | 3 | 0.6909 | 0.7104 | 0.7348 |
| OWNER far, 3 s | 3 | 0.3770 | 0.4091 | 0.4866 |
| OWNER short, 2 s | 3 | 0.5325 | 0.5504 | 0.6439 |
| TV speech, 3 s | 3 | 0.0484 | 0.0637 | 0.1536 |

## Quality-gate finding

Several deliberately quiet/short captures were effectively silence or contained too little useful speech:

- OWNER quiet: `-68.6 dBFS` RMS;
- OWNER quiet: `-49.1 dBFS` RMS;
- OWNER short 0.5 s: `-75.1 dBFS` RMS;
- OWNER short 1 s: `-52.8 dBFS` RMS.

All three embedding models still returned vectors for those regions. Therefore embedding readiness is not equivalent to usable identity evidence.

Accepted implementation rule:

```text
bad / too-short / near-silent / clipped audio
        ↓
INSUFFICIENT
```

It must never become `UNKNOWN_SPEAKER` merely because similarity is low.

The first shadow-mode quality defaults are deliberately conservative and are not identity thresholds:

- minimum segment duration: `1.5 s`;
- minimum RMS: `-45 dBFS`;
- maximum clipping ratio: `0.5%`.

These defaults may be tightened from passive real-use observations without changing authority semantics.

## Candidate decision

### CAM++ — PROVISIONAL SHADOW PROVIDER

CAM++ is selected for the next implementation slice because:

- real JARVIS ~3 s latency is only ~54 ms;
- healthy 2 s OWNER regions remained `0.7087–0.7611`;
- natural Hinglish OWNER regions remained `0.7354–0.7579`;
- far-field OWNER regions remained `0.6287–0.6435`;
- observed TV regions remained at or below `0.3943`;
- its deployment/runtime footprint is materially smaller than the alternatives.

This is a **provisional shadow-mode selection**, not an accepted authentication threshold.

### ERes2NetV2 — RETAIN AS FALLBACK CHALLENGER

ERes2NetV2 showed the cleanest observed TV-vs-healthy-OWNER score separation, but cost roughly six times CAM++ latency on the same route. It remains a fallback challenger if passive real-use observations show CAM++ ambiguity that the slower model materially resolves.

### TitaNet-Large — DROP FROM FIRST DEPLOYMENT PATH

TitaNet degraded substantially on far-field and short speech relative to the other candidates while also being slower and larger than CAM++. It remains a research reference only.

## Implementation direction

Do not continue requiring scripted manual benchmark sessions for ordinary development.

The next path is passive shadow learning during normal JARVIS conversation:

```text
normal JARVIS user turn
        ↓
canonical processed PCM
        ↓
quality gate
        ↓
CAM++ embedding
        ↓
separate trusted OWNER context available?
   ├── no  → score only if trusted prototypes already exist; never self-enroll
   └── yes → admit bounded session-only OWNER shadow prototype
        ↓
max-prototype similarity observation
        ↓
shadow telemetry / calibration only
```

Important constraints:

- the speaker model may never bootstrap itself from its own similarity score;
- session shadow prototypes are memory-only and cleared at session end;
- persistent voice-template enrollment/adaptation requires a strongly verified OWNER context and explicit profile-versioning rules;
- raw audio retention remains off;
- no speaker similarity threshold grants `MATCH`/`NO_MATCH` yet;
- typed `SPEAKER_MATCH` evidence remains `INSUFFICIENT` during shadow calibration;
- speaker identity alone never grants T2/T3 or action authority.

## Remaining acceptance gap

The manual bake-off did not include a controlled direct non-owner human, OWNER replay, or overlapping-speaker set. Rather than impose another large scripted recording ceremony, these conditions should be accumulated opportunistically in shadow mode and supplemented by a small targeted acceptance test only if needed before threshold promotion.

CAM++ therefore advances to passive shadow implementation, not production authority.
