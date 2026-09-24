"""Production entry point for the local-only JARVIS runtime supervisor."""

from jarvis.dev_supervisor import runtime_supervisor_main


def main() -> int:
    return runtime_supervisor_main()


if __name__ == "__main__":
    raise SystemExit(main())
