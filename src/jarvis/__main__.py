"""Command-line entrypoint for ``python -m jarvis``."""

from jarvis.app import JarvisApp
from jarvis.config import JarvisConfig
from jarvis.logging_config import configure_logging


def main() -> int:
    config = JarvisConfig.from_environment()
    configure_logging(config.log_level)
    app = JarvisApp()
    app.start()
    app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
