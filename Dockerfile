FROM python:3.13-slim-bookworm

# Install BLAST+ and curl (for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ncbi-blast+ curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
# Install base + prod extras
RUN pip install --no-cache-dir -e ".[prod]"

COPY . .

# Non-root user for defence in depth
RUN useradd -m apiblast && \
    chown -R apiblast:apiblast /app
USER apiblast

# Default assumes Debian package BLAST location.
# Override BLAST_BIN_DIR to use a different installation.
ENV BLAST_BIN_DIR=/usr/bin \
    PYTHONUNBUFFERED=1
