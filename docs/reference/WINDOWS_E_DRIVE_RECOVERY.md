# E-drive Windows recovery sources

The repository now preserves the source recipes used to recover the Windows installation:

- `tools/windows/Restore-Jarvis.ps1`: working local launcher, including PowerShell quoting and saved-key loading fixes, combined with the original online recovery work.
- `tools/windows/recovery/`: the storage/cache bootstrap, owner enrollment wrapper, pinned WinApp installer, verification and storage notes.
- `tools/wake-training/`: pinned Docker/CUDA wake-word training recipe, supervisor, runtime validation and training notes.

Before using the restore launcher after a fresh clone, copy the files in `tools/windows/recovery/` to `E:\Jarvis\Bootstrap`, then follow `STORAGE.md` and the existing setup instructions. The launcher expects the bootstrap at that persistent location. Copy `tools/wake-training/` to `E:\Jarvis\WakeTraining\workflow` before following its README; running the training supervisor starts a substantial GPU workload.

These are source backups, not a replacement for the E:/D: model and data backups. Trained ONNX files, downloaded weights/datasets, virtual environments, API keys, machine profiles and encrypted personal/identity databases remain outside Git. Windows DPAPI state can require separate recovery or reenrollment after a reinstall.

Automatic Gemini fallback is enabled on the owner's machine with the explicit persisted settings `JARVIS_GEMINI_PAID_FALLBACK_ENABLED=true` and `JARVIS_GEMINI_PAID_BUDGET_ENABLED=false`. Repository defaults retain spending enforcement for other installations. Historical budget records are preserved and do not block this opted-in mode.

The online UI is included as source with its existing opt-in controls. Merging it does not enable a new UI server or expose microphone/camera/personal data.
