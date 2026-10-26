# Hands dependency setup

If a Hands action reports that Microsoft winapp CLI is missing, use the preserved `Install-Winapp.ps1` recipe to install the pinned official standalone release. Review its expected location, release URL and SHA256 check before running it.

Apply `Set-JarvisStorage.ps1` before launching Jarvis so its tool directory is on the process PATH. Restart Jarvis after installation, run the normal startup preflight, and validate a harmless owner-requested action such as opening Calculator.

A missing local executable is a dependency issue; it does not establish a Paid API failure. Preserve the actual error when diagnosing a different failure. Installation, preflight and real owner acceptance are separate checks.

Personal repair history and machine-specific validation receipts are retained in private backups rather than this reusable guide.
