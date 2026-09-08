# Step 4 Phase 4.5D — Final V2 Exact-SHA CI Gate

Status: **CI GATE PENDING**

Phase 4.5E remains blocked.

The final V2 owner acceptance must run only from an exact branch SHA that has all repository quality/security jobs green on that same SHA:

- Ruff format/lint;
- full pytest;
- Windows DPAPI smoke;
- Windows Hello helper contract.

The one-shot owner run must preserve either `PASS` or `FAIL_ACCEPTANCE` as final V2 evidence and must not overwrite/re-run the same V2 validation corpus to chase a pass.

This record exists to make the final owner-run SHA produce a normal CI workflow after the formatter-bot commit, whose SHA itself did not receive a Code Quality workflow run.
