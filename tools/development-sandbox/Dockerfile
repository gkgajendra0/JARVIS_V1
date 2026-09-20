FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        libgl1 \
        libglib2.0-0 \
        libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/jarvis-base
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir ".[dev,phase45d-acceptance,hands]" \
    && rm -rf /root/.cache/pip

WORKDIR /workspace
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
