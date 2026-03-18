FROM nvidia/cuda:12.2.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    git \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry

WORKDIR /app

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --all-extras

COPY deepiri_zepgpu/ ./deepiri_zepgpu/
COPY examples/ ./examples/

RUN pip install -e . && \
    mkdir -p /root/.zepgpu && \
    mkdir -p /root/.cache/zepgpu

ENV PYTHONPATH=/app:$PYTHONPATH
ENV ZEPGPU_HOME=/root/.zepgpu

EXPOSE 8000 8765

CMD ["python", "-m", "deepiri_zepgpu.cli", "serve"]
