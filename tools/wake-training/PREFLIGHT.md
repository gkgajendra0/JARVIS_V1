# Training preflight

Before starting the overnight workflow:

1. Preserve the existing trained model and choose distinct primary and backup directories. Check available disk space for datasets, generated audio, features and checkpoints.
2. Confirm Docker Desktop uses Linux containers and the container can access the NVIDIA GPU. The launcher checks Docker and runs `nvidia-smi`; the pipeline also performs a real CUDA calculation.
3. Acquire the exact upstream trainer revision using the README instructions. Keep the pinned dependency/configuration files with the recipe.
4. Run the supplied tiny end-to-end smoke and ONNX/runtime compatibility gates. Synthetic success establishes mechanics and format compatibility, not acoustic accuracy.
5. Verify the second-drive backup is writable and checksum-verified. A failed backup must fail the pipeline.
6. Keep the supervisor and Docker running. Its idle-sleep request cannot prevent shutdown, restart or power loss.

The runtime classifier contract is float32 `(batch,16,96)` input and `(batch,1)` scores. Use the pinned frontend models and validate against the actual target installation. Review final metrics and test real speech/background noise before deployment.

Hardware inventories, measured disk capacity, run receipts and trained-model hashes belong with private run logs and backups. No particular machine or completed training run is certified by this generic checklist.
