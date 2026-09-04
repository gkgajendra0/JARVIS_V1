# Step 4 — Windows stdout encoding note

## Status

Research harness operational note discovered on the real JARVIS Windows machine on 2026-09-04.

## Problem

Running the structured memory-extraction bake-off under Windows PowerShell with stdout redirected to a file failed only at the final JSON print with:

```text
UnicodeEncodeError: 'charmap' codec can't encode characters ...
```

The corpus contains Hindi text. On Windows, redirected stdout/pipes can use the active ANSI code page rather than UTF-8, which makes `ensure_ascii=False` JSON fail even though the API calls themselves completed.

## Safe invocation

Use Python UTF-8 mode for redirected benchmark output:

```powershell
.\.step4-extraction-venv\Scripts\python.exe -X utf8 tools\research\step4_memory_extraction_bakeoff.py --providers openai > .step4-openai-full.json
```

Before any paid rerun, verify UTF-8 redirection without API calls:

```powershell
.\.step4-extraction-venv\Scripts\python.exe -X utf8 -c "import sys; print(sys.stdout.encoding); print('हिंदी')" > .step4-utf8-test.txt
Get-Content -Encoding UTF8 .step4-utf8-test.txt
```

Expected output begins with `utf-8` and renders `हिंदी` correctly.

## Interpretation

The failed OpenAI full-corpus run reached the final `print(json.dumps(..., ensure_ascii=False))` call, so provider requests had already occurred. Because requests were made with `store=False` and the final JSON was never emitted, those in-memory results are not recoverable from the harness process. A rerun is required for reproducible benchmark evidence, but only after the zero-cost UTF-8 redirection check passes.

## References

- Python Windows UTF-8 mode: `-X utf8` / `PYTHONUTF8=1`
- Python `sys.stdout` encoding rules on Windows for redirected/non-console streams
