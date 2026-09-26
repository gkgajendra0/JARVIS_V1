"""Trusted local-only CLI for secret enrollment, rotation and revocation."""

from __future__ import annotations

import argparse
import getpass
import json

from jarvis.engineering_substrate.contracts import SecretDescriptor
from jarvis.engineering_substrate.secrets.store import SecretStore


def _descriptor_json(descriptor: SecretDescriptor) -> str:
    return json.dumps(
        {
            "secret_id": descriptor.secret_id,
            "kind": descriptor.kind,
            "service": descriptor.service,
            "allowed_consumers": list(descriptor.allowed_consumers),
            "allowed_scopes": list(descriptor.allowed_scopes),
            "lifecycle_state": descriptor.lifecycle_state.value,
            "version": descriptor.version,
            "created_at_epoch": descriptor.created_at_epoch,
            "updated_at_epoch": descriptor.updated_at_epoch,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_secret_twice() -> bytes:
    first = getpass.getpass("Secret value: ")
    second = getpass.getpass("Confirm secret value: ")
    if not first:
        raise ValueError("secret value must not be empty")
    if first != second:
        raise ValueError("secret values do not match")
    return first.encode("utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis-secret",
        description=(
            "Manage JARVIS DPAPI-protected secrets locally. Secret values are read "
            "with no echo and are never accepted as command-line arguments."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    enroll = subparsers.add_parser("enroll", help="enroll one new secret")
    enroll.add_argument("secret_id")
    enroll.add_argument("--kind", required=True)
    enroll.add_argument("--service", required=True)
    enroll.add_argument(
        "--consumer",
        action="append",
        required=True,
        dest="consumers",
        help="registered consumer ID; repeat for multiple consumers",
    )
    enroll.add_argument(
        "--scope",
        action="append",
        required=True,
        dest="scopes",
        help="allowed scope; repeat for multiple scopes",
    )

    rotate = subparsers.add_parser("rotate", help="replace secret value")
    rotate.add_argument("secret_id")

    revoke = subparsers.add_parser("revoke", help="revoke secret")
    revoke.add_argument("secret_id")

    inspect = subparsers.add_parser("inspect", help="show non-secret metadata")
    inspect.add_argument("secret_id")

    subparsers.add_parser("list", help="list non-secret metadata")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    store: SecretStore | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    secret_store = store or SecretStore()

    if args.command == "enroll":
        value = _read_secret_twice()
        descriptor = secret_store.enroll(
            secret_id=args.secret_id,
            kind=args.kind,
            service=args.service,
            allowed_consumers=tuple(args.consumers),
            allowed_scopes=tuple(args.scopes),
            value=value,
        )
        print(_descriptor_json(descriptor))
        return 0

    if args.command == "rotate":
        value = _read_secret_twice()
        descriptor = secret_store.rotate(args.secret_id, value=value)
        print(_descriptor_json(descriptor))
        return 0

    if args.command == "revoke":
        descriptor = secret_store.revoke(args.secret_id)
        print(_descriptor_json(descriptor))
        return 0

    if args.command == "inspect":
        print(_descriptor_json(secret_store.verified_descriptor(args.secret_id)))
        return 0

    if args.command == "list":
        for descriptor in secret_store.list_descriptors():
            print(_descriptor_json(descriptor))
        return 0

    raise RuntimeError("unreachable secret CLI command")


if __name__ == "__main__":
    raise SystemExit(main())
