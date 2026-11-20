# Personal memory paging: bounded first-release design (slice 1)

Status: first-release choice for personal memory slice 1 (PR C). It is not a
general scaling design. Revisit it before any category is expected to hold
more than a few hundred facts.

## What the release does

- **A question read loads the current facts of the requested scopes only**
  (for example `owned_item.vehicle`), in one read transaction. The projection
  then sorts them and cuts one page: at most 8 items or 3,000 bytes.
- **The page token's scope signature covers the whole loaded scope.** That is
  why the whole scope is loaded: a forget or correction anywhere in the scope
  must void the remaining pages, not only a change inside the visible page.
- **The learning catalog** reads all current standard facts (the existing
  scoped reader), keeps only the proposed categories, and narrows a category
  over 32 facts per proposal (`learning_catalog_page.py`).

## Limits

- **Hard ceiling:** 2,000 current standard owner facts per read
  (`SCOPED_READ_CEILING`). Beyond it, the read fails explicitly
  (`learning_scope_too_large`). The answer then says the lookup is
  unavailable; a list is never silently shortened. Learning for that turn
  fails closed in the same way.
- **Per question:** the first page plus at most 3 extra pages (32 items),
  then `more_remaining` with the total.
- **Cost grows linearly** with the facts in the requested scopes (page read)
  and with all current standard facts (learning catalog). Each page re-reads
  the scope.

## Measured (offline, fictional data, this development container, 2 vCPU)

These are the sizes measured, not a claim of unlimited scaling.

| Facts in scope | Page read (snapshot + projection), median / max | Learning catalog read, median | Peak Python allocation during a page read* |
|---|---|---|---|
| 500 | 34 / 35 ms | 9 ms | ≈2.5 MiB |
| 1,000 | 60 / 68 ms | 20 ms | ≈4.4 MiB |
| 2,000 (ceiling) | 106 / 130 ms | 28 ms | ≈9.1 MiB |

\*Peak allocation was measured with `tracemalloc` in a separate run (that run's
times are inflated by tracing and are not reported). The Windows PC and
SQLCipher decryption add their own overhead, which has not been measured here.
The real-database rehearsal and acceptance runs will record actual timings.

## When to replace it

Before any one scope routinely exceeds a few hundred facts, or the 2,000-row
ceiling is approached, replace this with an indexed design:
- SQL `COUNT` plus an ordered page by a stored sort key;
- a per-scope change counter instead of a whole-scope signature;
- a learning catalog query filtered by category in SQL.

That is a separate, owner-approved change.
