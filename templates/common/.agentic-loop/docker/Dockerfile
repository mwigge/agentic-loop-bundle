FROM node:22-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY quality-requirements.txt /tmp/agentic-loop-quality-requirements.txt
RUN python3 -m venv /opt/agentic-loop \
    && /opt/agentic-loop/bin/pip install --no-cache-dir \
       -r /tmp/agentic-loop-quality-requirements.txt

ENV PATH="/opt/agentic-loop/bin:${PATH}"

WORKDIR /workspace

# Extend this image with the repository's compiler, package manager, services,
# and dependency installation. The repository is mounted at runtime so each
# OpenSpec task slice is checked against the current working tree.
