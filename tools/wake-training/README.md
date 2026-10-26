# Reproducible wake-word training

This recipe uses LiveKit WakeWord v0.2.1 at source revision `1ec7f680df30ff4ca0ebae6b5983441e94b10980`. Read `PREFLIGHT.md` before starting a GPU workload. Choose your own absolute primary-output and independent-backup directories through the launcher's `-TrainingRoot` and `-BackupRoot` parameters; do not reuse another run's configuration or outputs.

The Dockerfile requires upstream source in a sibling `trainer` directory. From this recipe directory, acquire the pinned source without replacing an existing checkout:

```powershell
$trainer = Join-Path $PWD 'trainer'
if (Test-Path -LiteralPath $trainer) { throw 'Inspect and preserve the existing trainer checkout first.' }
git clone --no-checkout https://github.com/livekit/livekit-wakeword.git $trainer
if ($LASTEXITCODE -ne 0) { throw 'Trainer clone failed.' }
git -C $trainer checkout --detach 1ec7f680df30ff4ca0ebae6b5983441e94b10980
if ($LASTEXITCODE -ne 0) { throw 'Pinned checkout failed.' }
if ((git -C $trainer rev-parse HEAD) -ne '1ec7f680df30ff4ca0ebae6b5983441e94b10980') { throw 'Trainer revision mismatch.' }
```

The launcher builds the pinned CUDA/PyTorch image, checks GPU access, runs an end-to-end smoke test and starts training only after that gate passes. Keep Docker and the supervisor running. Read the YAML and launcher parameters before starting; training downloads substantial data and has no guaranteed completion time.

Inspect `logs/pipeline.log`, Docker logs and `state/status.json` under your selected output root. The launcher records the container name. Do not start a second run while the original container is active. To resume after a failure, stop the old container and rerun the same launcher/configuration with `-SkipBuild`. Completed stages may be reused. An interrupted training stage restarts from saved features; checkpoints do not implement exact optimizer/RNG resume.

Checkpoints and completed artifacts are copied to the selected backup directory; logs are copied periodically. Model/checkpoint copies use SHA256 verification, and backup failures fail the pipeline. Keep source/configuration and dependency receipts with each run. Raw datasets can be downloaded again under their upstream licenses. The workflow retains containers and logs for diagnosis.

After completion, validate the ONNX with `validate_runtime.py` against the target Jarvis installation and compare model hashes in the primary and backup locations. The contract is float32 `(batch,16,96)` input and `(batch,1)` scores. Format compatibility does not establish acoustic accuracy: inspect metrics and test speech, microphone distance, background noise and assistant playback before deployment. The workflow does not activate the model or change runtime thresholds.

Machine-specific inventories, paths, completed-run receipts and trained-model hashes belong in private run logs/backups.

References: [LiveKit WakeWord v0.2.1](https://github.com/livekit/livekit-wakeword/tree/v0.2.1), [OpenWakeWord](https://github.com/dscripka/openWakeWord).
