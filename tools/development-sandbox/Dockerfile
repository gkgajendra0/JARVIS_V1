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

RUN python -m pip install --no-cache-dir \
    "https://files.pythonhosted.org/packages/8f/27/408c435cbed31fa3601ff32ef0499ff594cd898b483c9b4017e9df906de6/livekit_blingfire-1.1.0-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl" \
    && python -m pip install --no-cache-dir ".[dev,phase45d-acceptance,hands]" \
    && rm -rf /root/.cache/pip

WORKDIR /workspace
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
