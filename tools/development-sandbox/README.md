# JARVIS Development Test Sandbox

This image is the approved execution boundary for background development tests.

Build it from the repository root:

```powershell
docker build -f tools/development-sandbox/Dockerfile -t jarvis-dev-tests:local .
```

Then configure the machine profile setting:

```text
JARVIS_DEV_TEST_DOCKER_IMAGE=jarvis-dev-tests:local
```

The Work Orchestrator does **not** install Docker, build this image, or fall back to
host execution automatically. If the image is not configured/available, development
work enters `WAITING_FOR_OWNER` before executing model-edited code.

Production execution uses a fixed Docker invocation with:

- network disabled;
- read-only worktree bind mount;
- read-only container root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- bounded PIDs, memory and CPU;
- writable temporary filesystem only under `/tmp`;
- fixed `python -m pytest` command surface.

The image contains test dependencies only. It does not grant push, merge, deployment,
package-installation or protected-main authority to the background worker.
