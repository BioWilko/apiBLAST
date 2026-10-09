FROM python:3.13-slim-bookworm

# MMseqs2 GPU build: AVX2, needs glibc >= 2.29 and, for GPU searches, NVIDIA
# driver >= 525.60.13.
ARG MMSEQS_VERSION=18-8cc5c
ARG MMSEQS_SHA256=83969dd5c7d4c32858c2fc9a4d1024c15e8fe5da768ce76e787ab0195ffd64e7

# curl for the MMseqs2 download
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/mmseqs.tar.gz \
      "https://github.com/soedinglab/MMseqs2/releases/download/${MMSEQS_VERSION}/mmseqs-linux-gpu.tar.gz" && \
    echo "${MMSEQS_SHA256}  /tmp/mmseqs.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/mmseqs.tar.gz -C /tmp && \
    install -m 0755 /tmp/mmseqs/bin/mmseqs /usr/local/bin/mmseqs && \
    rm -rf /tmp/mmseqs /tmp/mmseqs.tar.gz

WORKDIR /app

COPY pyproject.toml .
# Install base + prod extras
RUN pip install --no-cache-dir -e ".[prod]"

COPY . .

# Non-root user for defence in depth
RUN useradd -m apiblast && \
    chown -R apiblast:apiblast /app && \
    mkdir -p /data/results && \
    chown -R apiblast:apiblast /data
USER apiblast

ENV MMSEQS_BIN=/usr/local/bin/mmseqs \
    PYTHONUNBUFFERED=1
