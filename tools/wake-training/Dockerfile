FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime@sha256:c16f4c749e2d9e96878875cdf6cc45cddda1d1a36fddd371dd6f2360f1b6e2a2
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 HF_HUB_DISABLE_XET=1 HF_HOME=/training/cache/huggingface
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng libsndfile1 ffmpeg git build-essential && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
COPY trainer /opt/trainer
COPY constraints.txt /opt/constraints.txt
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.2.1 python -m pip install --no-cache-dir -c /opt/constraints.txt '/opt/trainer[train,eval,export]' openwakeword==0.6.0 && python -m pip check && python -m pip freeze > /opt/requirements-resolved.txt
WORKDIR /training
CMD ["python", "-u", "/workflow/run_training.py"]
