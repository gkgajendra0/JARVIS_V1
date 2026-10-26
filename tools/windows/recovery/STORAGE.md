# Persistent Windows storage

Copy these recovery scripts to `E:\Jarvis\Bootstrap` before using the restore launcher. Apply `Set-JarvisStorage.ps1` to configure the Jarvis process paths.

| Asset | Recipe location |
| --- | --- |
| App / virtual environment | `E:\Jarvis\App` |
| Base Python | `E:\Jarvis\Runtime\Python311` |
| Models | `E:\Jarvis\Models` |
| Download caches | `E:\Jarvis\Cache` |
| Process temporary files | `E:\Jarvis\Temp` |
| Machine configuration, identity and memory state | `E:\Jarvis\Data\LocalState` |
| Managed command-line tools | `E:\Jarvis\Data\LocalState\tools` |

The standard `%LOCALAPPDATA%\JARVIS` path can be a junction to persistent local state. A C: alias in logs does not by itself identify the physical storage drive. The scripts refuse to replace an unrelated existing directory; inspect it and preserve its contents before resolving conflicts.

For enrollment, use `Enroll-Owner.ps1`. For startup, use the app's `tools/windows/Restore-Jarvis.ps1 -Launch`. From a maintenance shell, initialize the same storage paths before invoking Python; if execution policy blocks dot-sourcing, launch the approved script through a process-scoped policy rather than changing machine-wide policy.

After Windows reinstall, restore the required Python environment, dependencies, GPU/audio/camera drivers, Windows Hello registration and API credentials. Keeping encrypted database files on E: alone does not recover Windows DPAPI keys. A tested separate key-recovery procedure or fresh enrollment is still required.

The training workflow supplies a second-drive backup recipe. These scripts do not establish a recurring backup of all personal data. Keep verified independent backups appropriate to the installed features.

Docker Desktop stores its VM disk independently of the training output directories. Inspect Settings > Resources > Advanced > Disk image location and use Docker's supported move action if needed. Never manually move or delete a mounted VM disk. See [official Docker WSL storage instructions](https://docs.docker.com/desktop/features/wsl/).
