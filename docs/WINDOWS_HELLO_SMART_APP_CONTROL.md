# Windows Hello under Smart App Control, and OPA startup failures

## 1. Root cause: the Hello helper is a locally compiled, unsigned binary

Evidence:
- **On your PC:** Smart App Control is enforced (`VerifiedAndReputableDesktop`,
  policy `0283ac0f-…`). Code Integrity events 3033/3077 name
  `Jarvis.WindowsHelloVerifier.dll`, error `0x800711C7`
  (`ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION`).
- **Installed helper files** (`E:\Jarvis\Data\LocalState\tools\windows-hello`,
  published by `jarvis-setup` on 2026-10-04):
  - `Jarvis.WindowsHelloVerifier.exe` and `.dll`: **no Authenticode
    signature**;
  - the .NET runtime files beside them: signed by Microsoft.
- **The helper was built on your PC**, so its hashes exist nowhere else.

How Smart App Control decides:
- It checks **every** image the loader maps, DLLs included, not only the
  started program.
- It allows a file in two cases:
  - Microsoft's cloud service (the Intelligent Security Graph) knows the file
    as good;
  - otherwise, the file has a valid signature chaining to Microsoft's Trusted
    Root Program. Certificates you trust locally (`certmgr`, Group Policy) do
    not count.
- Unsigned files the cloud cannot vouch for are blocked.
- There is no per-app exception.

A one-off local build can satisfy neither condition. The helper worked
before October 28 and is blocked now. The usual cause is Smart App Control
leaving Evaluation mode for On, which Windows does automatically. Nothing in
Jarvis changed the helper.

## 2. Options

| Option | Result |
| --- | --- |
| Turn Smart App Control off | Rejected: weakens the whole PC (and your instruction) |
| Self-signed certificate / local root | Not accepted by Smart App Control |
| Azure Artifact Signing (~$9.99/month) | Public trust for individuals is limited to the USA and Canada: not available to you |
| OV code-signing certificate | $150–300/year plus a hardware token (required since 2023). Every rebuild must be signed. It works, but it is a recurring cost and a key to guard |
| Rewrite the helper in PowerShell (WinRT from PowerShell) | The window-owner interop call needs `Add-Type` (compiled C# at run time). Under App Control policies, script behaviour is uncertain |
| Third-party Python WinRT packages | Adds native modules whose admission depends on cloud reputation: the same fragility |
| **Run the same API from the signed Python runtime (chosen)** | No new binary at all. Zero cost |

## 3. The solution: built-in Windows Hello consent

`src/jarvis/authority/windows_hello_consent.py` replaces the .NET helper.
It is run as a child process: `python -I <that file>`.

**What it calls.** The same Windows API as before, through `ctypes` and
Microsoft-signed system DLLs (`combase.dll`, `user32.dll`):
1. `UserConsentVerifier.CheckAvailabilityAsync`;
2. `IUserConsentVerifierInterop.RequestVerificationForWindowAsync` on a 1×1,
   nearly transparent, top-most owner window, as the .NET helper did.

**What loads.** Your Python 3.11 runtime (`E:\Jarvis\Runtime\Python311`):
`python.exe`, `python311.dll`, `_ctypes.pyd` and `libffi-8.dll` are all
signed by the Python Software Foundation (checked on your PC). Jarvis
already loads them; the DPAPI memory key uses `ctypes` in the same way, and
the fresh memory initialization passed on your PC under Smart App Control.

**Security is unchanged or stronger:**
- The prompt, biometric/PIN check and result are Windows'
  (CredentialUIBroker). Only Windows' `Verified` maps to verified; every
  other value, error, timeout or exception is not verified.
- The JSON contract, verifier id, 60-second timeout, proposal binding and
  every fail-closed path are unchanged.
- **The trust chain is smaller.** Before, a user-writable `.exe` under
  `LocalState\tools` decided "verified"; anyone able to replace it could
  forge approvals. Now the decision code is Jarvis's own source, run by the
  signed interpreter.
- `-I` isolated mode ignores `PYTHONPATH`, the user site and the current
  directory. The module imports only the standard library.
- **Smart App Control stays on and unchanged.**

**Configuration:**
- `machine.json` is not changed. `JARVIS_WINDOWS_HELLO_HELPER` stays valid;
  the preflight notes that it is no longer used.
- `jarvis-setup` no longer needs the .NET SDK.
- Encrypted memory and every other setting are untouched.

**Removed:**
- the C# project;
- the .NET build and publish in CI. The `windows-hello-helper` CI job now
  checks the four interface IDs against the Windows SDK headers and runs the
  real WinRT calls on Windows.

## 4. OPA: the intermittent startup probe failure (separate cause)

**Facts:**
- `opa.exe` 1.21.4 is the official release. It is 64 MB and has **no
  Authenticode signature** (checked on your PC).
- Under Smart App Control it runs only because the cloud service knows its
  hash, which is why it "runs successfully when tested directly".
- Startup gave `opa version` **5 seconds** in total.
- The probe reported only "OPA version probe failed": a timeout and a policy
  refusal produced the same message.

**Likely causes** (both intermittent, both fit the evidence):
1. **Cold start.** On a first launch, or when the cached verdict has expired,
   Windows hashes the 64 MB file and asks the cloud before running it.
   Defender also scans it, while Jarvis is loading models at startup. More
   than 5 seconds is plausible.
2. **Transient reputation lookup failure.** If the cloud cannot be reached in
   time, Smart App Control refuses the launch (WinError 4551) for that
   attempt.

**Fix in this PR** (it does not change what runs or how it is checked):
- 30 seconds for the probe and for the OPA server start;
- one retry of the probe after 2 seconds;
- a precise cause: `no response within 30 s`, `blocked by Windows code
  integrity policy … (WinError 4551)`, or the exit code;
- a slow start is still a pass, shown in the preflight as `(slow start: N s)`.

**To find out which cause you hit (read-only, PowerShell):**

```powershell
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational'; Id=3033,3076,3077} |
  Where-Object Message -match 'opa\.exe' | Select-Object -First 10 TimeCreated, Id
```

- **No rows:** the failures were cold-start timeouts. The longer timeout and
  the retry fix them.
- **Rows at the failure times:** reputation lookups failed. The retry covers
  transient cases. If blocks persist (for example, when the PC is offline at
  startup), the permanent options are the same as for any unsigned tool: a
  signed OPA build, or an OV certificate to sign it yourself. OPA does not
  publish signed Windows binaries today.

## 5. Deployment (after your approval to merge)

Merging changes nothing on the PC. Then:

```powershell
# 1. Update the code (App is on main 62af793f, so this is a fast-forward)
git -C E:\Jarvis\App status --porcelain              # must print nothing
git -C E:\Jarvis\App fetch origin main
git -C E:\Jarvis\App merge --ff-only origin/main

# 2. Hello without a prompt: must print "available"
$py = 'E:\Jarvis\App\.venv\Scripts\python.exe'
$hello = 'E:\Jarvis\App\src\jarvis\authority\windows_hello_consent.py'
'{"action": "availability"}' | & $py -I $hello

# 3. One real Hello prompt: approve it; must print "verified"
'{"message": "JARVIS Windows Hello check"}' | & $py -I $hello

# 4. Startup preflight, then a normal start
& E:\Jarvis\Bootstrap\Start-Jarvis.ps1 -CheckOnly
& E:\Jarvis\Bootstrap\Start-Jarvis.ps1
```

Pass when:
- step 2 prints `{"status": "available", ...}`;
- step 3 shows the Windows Hello dialog and prints `verified`; cancelling
  prints `canceled`;
- the preflight shows `Windows Hello helper: passed` (built-in) and `OPA
  policy engine: passed`;
- Jarvis starts with the usual Hello approval;
- no new Code Integrity 3033/3077 events appear for Jarvis files.

**Optional cleanup:** the old `E:\Jarvis\Data\LocalState\tools\windows-hello`
folder is no longer used. You may delete it.

**Rollback:** `git -C E:\Jarvis\App checkout -B main 62af793f`. Note that the
old helper stays blocked by Smart App Control, so rollback restores the
current failure, not a working Hello.
