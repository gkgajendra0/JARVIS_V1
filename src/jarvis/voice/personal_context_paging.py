"""Question-bound pages of personal context (personal memory slice 1, PR C).

A ``next_page`` token is an HMAC, under a secret that exists only inside one
per-turn personal-context session, over the question binding (session, turn),
the identity of the live read permit, the exact parsed requests, the offset,
the page number and the scope snapshot signature. It is therefore valid only
for the same question under the same live permit, and only while the
requested scopes are unchanged: a new turn (new session and secret), a lock,
revocation or expired lease (permit gone), and a correction or forget (new
signature) all void it. At most :data:`MAX_EXTRA_PAGES` further pages follow
the first; after that the release says ``more_remaining`` with the total.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

MAX_EXTRA_PAGES = 3
_TOKEN_LIMIT = 512


def _requests_digest(requests) -> str:
    payload = [(r.scope_key, r.target_quote) for r in requests]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _mac(secret, binding, permit_key, requests, offset, page, signature) -> str:
    message = json.dumps(
        [
            list(binding) if binding is not None else None,
            permit_key,
            _requests_digest(requests),
            offset,
            page,
            signature,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def issue_page_token(secret, binding, permit_key, requests, offset, page, signature):
    body = base64.urlsafe_b64encode(
        json.dumps([offset, page], separators=(",", ":")).encode()
    ).decode()
    mac = _mac(secret, binding, permit_key, requests, offset, page, signature)
    return f"{body}.{mac}"


def read_page_token(secret, binding, permit_key, requests, signature, token):
    """The (offset, page) a valid token names, or None. Never raises."""
    try:
        if type(token) is not str or not 0 < len(token) <= _TOKEN_LIMIT:
            return None
        body, mac = token.split(".", 1)
        offset, page = json.loads(base64.urlsafe_b64decode(body.encode()))
        if type(offset) is not int or type(page) is not int:
            return None
        if offset <= 0 or not 1 <= page <= MAX_EXTRA_PAGES:
            return None
        expected = _mac(secret, binding, permit_key, requests, offset, page, signature)
        if not hmac.compare_digest(expected, mac):
            return None
        return offset, page
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def paging_section(projection, *, page, token, omitted_scopes):
    """What the answer may claim about completeness, from the projection."""
    released_through = projection.offset + len(projection.facts)
    complete = projection.next_offset is None and not omitted_scopes
    per_scope = {
        scope: {
            "total": total,
            "released_through": through,
            "complete": through == total and scope not in omitted_scopes,
        }
        for scope, total, through in projection.scope_counts
    }
    section = {
        "total": projection.total,
        "this_page": {"from": projection.offset + 1, "to": released_through},
        "complete": complete,
        "scopes": per_scope,
    }
    if projection.next_offset is not None:
        if token is not None:
            section["next_page"] = token
        else:
            section["more_remaining"] = True
    if omitted_scopes:
        section["omitted_items"] = True
    if complete:
        rule = "Complete list for the requested categories."
    elif token is not None:
        rule = (
            f"Partial list: {projection.total} saved, items "
            f"{projection.offset + 1}-{released_through} released so far. Say the "
            f"list is partial (for example '{projection.total} saved; here are "
            f"{released_through}'). To continue, call read_personal_context_for_question "
            "again with the same requests and this page_token, or ask the owner to narrow."
        )
    elif projection.next_offset is not None:
        rule = (
            f"No more pages for this question: {projection.total} saved, "
            f"{released_through} released. Say more exist (total {projection.total}) "
            "and offer to continue in a follow-up question or to narrow; never "
            "present the released items as the whole list."
        )
    else:
        rule = "All items were released, but some were too large to include whole."
    if omitted_scopes:
        rule += (
            " Items marked omitted were too large to include in full: say their "
            "details were not included; never guess them."
        )
    section["list_rule"] = rule
    section["page"] = page
    return section
