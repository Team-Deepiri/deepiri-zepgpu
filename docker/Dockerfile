FROM nvidia/cuda:12.2.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV POETRY_VIRTUALENVS_CREATE=false

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    python3-pip \
    git \
    wget \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    update-alternatives --set python3 /usr/bin/python3.11 && \
    python3 --version

RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install poetry psycopg2-binary

WORKDIR /app

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false && \
    poetry install --no-root --no-interaction --all-extras

COPY . .

RUN groupadd -r zepgpu && \
    useradd -r -g zepgpu -d /app -s /bin/bash zepgpu && \
    mkdir -p /app/data /app/models && \
    chown -R zepgpu:zepgpu /app

USER zepgpu

EXPOSE 8000
EXPOSE 8765

CMD ["uvicorn", "deepiri_zepgpu.api.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
