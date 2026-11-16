# Isolated execution image for generated code. Build: docker build -f runner/Dockerfile -t freshcode-runner:latest runner
FROM python:3.15-slim
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pytest==8.3.5
RUN useradd --uid 65534 --no-create-home --shell /usr/sbin/nologin runner 2>/dev/null || true
WORKDIR /work
USER 65534:65534
